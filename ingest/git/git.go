package git

import (
	"bufio"
	"bytes"
	"fmt"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Commit is a git commit summary.
type Commit struct {
	SHA     string    `json:"sha"`
	Message string    `json:"message"`
	Author  string    `json:"author"`
	Email   string    `json:"email"`
	Date    time.Time `json:"date"`
}

// FileStats holds per-file history metrics.
type FileStats struct {
	Path        string         `json:"path"`
	CommitCount int            `json:"commit_count"`
	Authors     map[string]int `json:"authors"`
	Churn       int            `json:"churn"`
	Owner       string         `json:"owner"`
}

// Rename records a detected rename.
type Rename struct {
	From string `json:"from"`
	To   string `json:"to"`
	SHA  string `json:"sha,omitempty"`
}

// Hotspot is a frequently changed file.
type Hotspot struct {
	Path        string `json:"path"`
	CommitCount int    `json:"commit_count"`
}

// EdgeHint is relationship data derived from git (pipeline may materialize as graph edges).
type EdgeHint struct {
	Type       string   `json:"type"` // INTRODUCED_IN, MODIFIED_BY, RENAMED_TO, OWNS
	From       string   `json:"from"`
	To         string   `json:"to"`
	Confidence float64  `json:"confidence"`
	Evidence   []string `json:"evidence,omitempty"`
}

// GitArtifact is the JSON-serializable git history summary.
type GitArtifact struct {
	RepoRoot  string               `json:"repo_root"`
	HEAD      string               `json:"head"`
	Commits   []Commit             `json:"commits"`
	Files     map[string]FileStats `json:"files"`
	Renames   []Rename             `json:"renames"`
	Hotspots  []Hotspot            `json:"hotspots"`
	EdgeHints []EdgeHint           `json:"edge_hints"`
}

// Collect gathers git history for repoRoot. Must be run inside a git repository.
func Collect(repoRoot string) (*GitArtifact, error) {
	abs, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	if err := requireGitRepo(abs); err != nil {
		return nil, err
	}

	head, err := gitOutput(abs, "rev-parse", "HEAD")
	if err != nil {
		return nil, fmt.Errorf("rev-parse HEAD: %w", err)
	}

	commits, err := collectCommits(abs)
	if err != nil {
		return nil, err
	}

	files, err := collectFileStats(abs)
	if err != nil {
		return nil, err
	}

	renames, err := collectRenames(abs)
	if err != nil {
		return nil, err
	}

	introduced, err := collectIntroduced(abs)
	if err != nil {
		return nil, err
	}

	hotspots := buildHotspots(files, 20)
	hints := buildEdgeHints(files, renames, introduced)

	return &GitArtifact{
		RepoRoot:  abs,
		HEAD:      strings.TrimSpace(head),
		Commits:   commits,
		Files:     files,
		Renames:   renames,
		Hotspots:  hotspots,
		EdgeHints: hints,
	}, nil
}

// ChangedFilesSince returns paths changed between sinceSHA and HEAD.
func ChangedFilesSince(repoRoot, sinceSHA string) ([]string, error) {
	abs, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	if err := requireGitRepo(abs); err != nil {
		return nil, err
	}
	out, err := gitOutput(abs, "diff", "--name-only", sinceSHA, "HEAD")
	if err != nil {
		return nil, err
	}
	var files []string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			files = append(files, filepath.ToSlash(line))
		}
	}
	return files, nil
}

// HEADSHA returns the current HEAD commit sha.
func HEADSHA(repoRoot string) (string, error) {
	out, err := gitOutput(repoRoot, "rev-parse", "HEAD")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

func requireGitRepo(dir string) error {
	out, err := gitOutput(dir, "rev-parse", "--is-inside-work-tree")
	if err != nil || strings.TrimSpace(out) != "true" {
		return fmt.Errorf("%s is not inside a git repository", dir)
	}
	return nil
}

func gitOutput(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("git %s: %w (%s)", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return stdout.String(), nil
}

func collectCommits(dir string) ([]Commit, error) {
	out, err := gitOutput(dir, "log", "--pretty=format:%H%x00%an%x00%ae%x00%aI%x00%s", "--no-merges")
	if err != nil {
		return nil, err
	}
	var commits []Commit
	scanner := bufio.NewScanner(strings.NewReader(out))
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)
	for scanner.Scan() {
		parts := strings.SplitN(scanner.Text(), "\x00", 5)
		if len(parts) < 5 {
			continue
		}
		t, _ := time.Parse(time.RFC3339, parts[3])
		commits = append(commits, Commit{
			SHA:     parts[0],
			Author:  parts[1],
			Email:   parts[2],
			Date:    t,
			Message: parts[4],
		})
	}
	return commits, scanner.Err()
}

func collectFileStats(dir string) (map[string]FileStats, error) {
	out, err := gitOutput(dir, "log", "--pretty=format:COMMIT %H %an", "--numstat", "--no-merges")
	if err != nil {
		return nil, err
	}

	files := make(map[string]FileStats)
	var curAuthor string

	scanner := bufio.NewScanner(strings.NewReader(out))
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "COMMIT ") {
			rest := strings.TrimPrefix(line, "COMMIT ")
			sp := strings.SplitN(rest, " ", 2)
			if len(sp) > 1 {
				curAuthor = sp[1]
			} else {
				curAuthor = ""
			}
			continue
		}
		line = strings.TrimSpace(line)
		if line == "" || curAuthor == "" {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		ins, _ := strconv.Atoi(fields[0])
		del, _ := strconv.Atoi(fields[1])
		fpath := filepath.ToSlash(strings.Join(fields[2:], " "))
		if strings.Contains(fpath, "=>") {
			parts := strings.Split(fpath, "=>")
			fpath = strings.TrimSpace(parts[len(parts)-1])
			fpath = strings.Trim(fpath, "{} ")
		}
		st := files[fpath]
		st.Path = fpath
		st.CommitCount++
		if st.Authors == nil {
			st.Authors = make(map[string]int)
		}
		st.Authors[curAuthor]++
		st.Churn += ins + del
		files[fpath] = st
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	for p, st := range files {
		st.Owner = topAuthor(st.Authors)
		files[p] = st
	}
	return files, nil
}

func collectRenames(dir string) ([]Rename, error) {
	out, err := gitOutput(dir, "log", "--diff-filter=R", "--summary", "--pretty=format:COMMIT %H", "-M")
	if err != nil {
		return nil, err
	}
	var renames []Rename
	var curSHA string
	scanner := bufio.NewScanner(strings.NewReader(out))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "COMMIT ") {
			curSHA = strings.TrimPrefix(line, "COMMIT ")
			continue
		}
		if !strings.HasPrefix(line, "rename ") {
			continue
		}
		body := strings.TrimPrefix(line, "rename ")
		if idx := strings.LastIndex(body, " ("); idx >= 0 {
			body = body[:idx]
		}
		from, to, ok := parseRename(body)
		if !ok {
			continue
		}
		renames = append(renames, Rename{From: from, To: to, SHA: curSHA})
	}
	return renames, scanner.Err()
}

func parseRename(body string) (from, to string, ok bool) {
	body = strings.TrimSpace(body)
	if i := strings.Index(body, " => "); i >= 0 {
		left := strings.TrimSpace(body[:i])
		right := strings.TrimSpace(body[i+4:])
		return filepath.ToSlash(left), filepath.ToSlash(right), true
	}
	return "", "", false
}

func topAuthor(authors map[string]int) string {
	best := ""
	bestN := -1
	for a, n := range authors {
		if n > bestN || (n == bestN && a < best) {
			best = a
			bestN = n
		}
	}
	return best
}

func buildHotspots(files map[string]FileStats, n int) []Hotspot {
	list := make([]Hotspot, 0, len(files))
	for _, st := range files {
		list = append(list, Hotspot{Path: st.Path, CommitCount: st.CommitCount})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].CommitCount == list[j].CommitCount {
			return list[i].Path < list[j].Path
		}
		return list[i].CommitCount > list[j].CommitCount
	})
	if n > 0 && len(list) > n {
		list = list[:n]
	}
	return list
}

func collectIntroduced(dir string) (map[string]string, error) {
	// Oldest-first: first commit that added each path.
	out, err := gitOutput(dir, "log", "--diff-filter=A", "--pretty=format:COMMIT %H", "--name-only", "--reverse", "--no-merges")
	if err != nil {
		return nil, err
	}
	introduced := make(map[string]string)
	var curSHA string
	scanner := bufio.NewScanner(strings.NewReader(out))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "COMMIT ") {
			curSHA = strings.TrimPrefix(line, "COMMIT ")
			continue
		}
		path := filepath.ToSlash(line)
		if _, ok := introduced[path]; !ok && curSHA != "" {
			introduced[path] = curSHA
		}
	}
	return introduced, scanner.Err()
}

func buildEdgeHints(files map[string]FileStats, renames []Rename, introduced map[string]string) []EdgeHint {
	var hints []EdgeHint
	for path, st := range files {
		if st.Owner != "" {
			hints = append(hints, EdgeHint{
				Type:       "OWNS",
				From:       st.Owner,
				To:         path,
				Confidence: 0.8,
				Evidence:   []string{fmt.Sprintf("%d commits by owner", st.Authors[st.Owner])},
			})
		}
		for author, n := range st.Authors {
			hints = append(hints, EdgeHint{
				Type:       "MODIFIED_BY",
				From:       path,
				To:         author,
				Confidence: 0.7,
				Evidence:   []string{fmt.Sprintf("%d commits", n)},
			})
		}
	}
	for path, sha := range introduced {
		hints = append(hints, EdgeHint{
			Type:       "INTRODUCED_IN",
			From:       path,
			To:         sha,
			Confidence: 0.9,
			Evidence:   []string{"git log --diff-filter=A"},
		})
	}
	for _, r := range renames {
		hints = append(hints, EdgeHint{
			Type:       "RENAMED_TO",
			From:       r.From,
			To:         r.To,
			Confidence: 0.95,
			Evidence:   []string{r.SHA},
		})
	}
	sort.Slice(hints, func(i, j int) bool {
		if hints[i].Type == hints[j].Type {
			return hints[i].From+hints[i].To < hints[j].From+hints[j].To
		}
		return hints[i].Type < hints[j].Type
	})
	return hints
}
