package parser

// Symbol is a named code entity extracted from a source file.
type Symbol struct {
	ID         string   `json:"id"`
	Name       string   `json:"name"`
	Kind       string   `json:"kind"` // function, method, struct, interface, class, type
	Signature  string   `json:"signature,omitempty"`
	StartLine  uint32   `json:"start_line"`
	EndLine    uint32   `json:"end_line"`
	Calls      []string `json:"calls,omitempty"`
	Extends    []string `json:"extends,omitempty"`
	Implements []string `json:"implements,omitempty"`
}

// FileArtifact is the normalized per-file parse output.
type FileArtifact struct {
	Path      string   `json:"path"`
	RelPath   string   `json:"rel_path"`
	Language  string   `json:"language"`
	Package   string   `json:"package,omitempty"`
	Imports   []string `json:"imports,omitempty"`
	Symbols   []Symbol `json:"symbols,omitempty"`
	Comments  []string `json:"comments,omitempty"`
	Hash      string   `json:"hash,omitempty"`
	RepoID    string   `json:"repo_id,omitempty"`
	CommitSHA string   `json:"commit_sha,omitempty"`
}
