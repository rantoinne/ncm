"""Neo4j and in-memory graph stores for NCM."""

from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Any, Protocol, runtime_checkable

from dotenv import load_dotenv

load_dotenv()


@runtime_checkable
class GraphStore(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def clear_repo(self, repo_id: str) -> None: ...
    def ingest_nodes(self, nodes: list[dict[str, Any]], repo_id: str = "") -> int: ...
    def ingest_edges(self, edges: list[dict[str, Any]], repo_id: str = "") -> int: ...
    def neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]: ...
    def shortest_path(self, from_id: str, to_id: str) -> list[dict[str, Any]]: ...
    def upstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]: ...
    def downstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]: ...
    def blast_radius(self, node_id: str, max_depth: int = 3) -> dict[str, Any]: ...
    def get_repo_map(self, repo_id: str) -> dict[str, Any]: ...
    def files_by_concept(self, concept: str, repo_id: str = "") -> list[dict[str, Any]]: ...
    def ownership_for_path(self, path: str, repo_id: str = "") -> list[dict[str, Any]]: ...
    def hotspots(self, repo_id: str = "", limit: int = 10) -> list[dict[str, Any]]: ...


def _node_dict(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "type": node.get("type", "Unknown"),
        "label": node.get("label", node["id"]),
        "props": dict(node.get("props") or {}),
    }


def _edge_dict(edge: dict[str, Any]) -> dict[str, Any]:
    from_id = edge.get("from_id") or edge.get("from") or edge.get("fromId")
    return {
        "id": edge.get("id") or f"{from_id}->{edge.get('to')}:{edge.get('type')}",
        "type": edge.get("type", "RELATED"),
        "from": from_id,
        "to": edge.get("to"),
        "confidence": float(edge.get("confidence", 1.0)),
        "evidence": list(edge.get("evidence") or []),
    }


DEP_EDGE_TYPES = frozenset(
    {"DEPENDS_ON", "IMPORTS", "CALLS", "IMPLEMENTS", "EXTENDS", "TESTS"}
)


class InMemoryGraphStore:
    """Dict-based graph store for tests and local use without Neo4j."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._in: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._repo_nodes: dict[str, set[str]] = defaultdict(set)
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def clear_repo(self, repo_id: str) -> None:
        node_ids = set(self._repo_nodes.get(repo_id, set()))
        # Also remove by props.repo_id
        for nid, node in list(self.nodes.items()):
            if node.get("props", {}).get("repo_id") == repo_id:
                node_ids.add(nid)
        for nid in node_ids:
            self.nodes.pop(nid, None)
            self._out.pop(nid, None)
            self._in.pop(nid, None)
        self.edges = [
            e
            for e in self.edges
            if e["from"] not in node_ids and e["to"] not in node_ids
            and e.get("props", {}).get("repo_id") != repo_id
        ]
        # Rebuild adjacency for remaining edges
        self._out.clear()
        self._in.clear()
        for e in self.edges:
            self._out[e["from"]].append(e)
            self._in[e["to"]].append(e)
        self._repo_nodes.pop(repo_id, None)

    def ingest_nodes(self, nodes: list[dict[str, Any]], repo_id: str = "") -> int:
        count = 0
        for raw in nodes:
            node = _node_dict(raw)
            if repo_id:
                node["props"]["repo_id"] = repo_id
                self._repo_nodes[repo_id].add(node["id"])
            elif node["props"].get("repo_id"):
                self._repo_nodes[str(node["props"]["repo_id"])].add(node["id"])
            self.nodes[node["id"]] = node
            count += 1
        return count

    def ingest_edges(self, edges: list[dict[str, Any]], repo_id: str = "") -> int:
        count = 0
        for raw in edges:
            edge = _edge_dict(raw)
            if not edge["from"] or not edge["to"]:
                continue
            if repo_id:
                edge["repo_id"] = repo_id
            self.edges.append(edge)
            self._out[edge["from"]].append(edge)
            self._in[edge["to"]].append(edge)
            count += 1
        return count

    def neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        if node_id not in self.nodes:
            return []
        seen: set[str] = {node_id}
        frontier = {node_id}
        result: list[dict[str, Any]] = []
        for _ in range(max(1, depth)):
            nxt: set[str] = set()
            for nid in frontier:
                for e in self._out.get(nid, []) + self._in.get(nid, []):
                    other = e["to"] if e["from"] == nid else e["from"]
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.add(other)
                    if other in self.nodes:
                        result.append(dict(self.nodes[other]))
            frontier = nxt
            if not frontier:
                break
        return result

    def shortest_path(self, from_id: str, to_id: str) -> list[dict[str, Any]]:
        if from_id not in self.nodes or to_id not in self.nodes:
            return []
        if from_id == to_id:
            return [dict(self.nodes[from_id])]
        queue: deque[str] = deque([from_id])
        prev: dict[str, str | None] = {from_id: None}
        found = False
        while queue:
            cur = queue.popleft()
            for e in self._out.get(cur, []) + self._in.get(cur, []):
                other = e["to"] if e["from"] == cur else e["from"]
                if other in prev:
                    continue
                prev[other] = cur
                if other == to_id:
                    found = True
                    queue.clear()
                    break
                queue.append(other)
        if not found:
            return []
        path_ids: list[str] = []
        cur_id: str | None = to_id
        while cur_id is not None:
            path_ids.append(cur_id)
            cur_id = prev[cur_id]
        path_ids.reverse()
        return [dict(self.nodes[i]) for i in path_ids if i in self.nodes]

    def _traverse(
        self,
        node_id: str,
        max_depth: int,
        *,
        forward: bool,
        edge_types: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        edge_types = edge_types or DEP_EDGE_TYPES
        if node_id not in self.nodes:
            return []
        seen: set[str] = {node_id}
        frontier = {node_id}
        result: list[dict[str, Any]] = []
        for _ in range(max(1, max_depth)):
            nxt: set[str] = set()
            for nid in frontier:
                edges = self._out.get(nid, []) if forward else self._in.get(nid, [])
                for e in edges:
                    if e["type"] not in edge_types:
                        continue
                    other = e["to"] if forward else e["from"]
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.add(other)
                    if other in self.nodes:
                        item = dict(self.nodes[other])
                        item["via"] = e["type"]
                        result.append(item)
            frontier = nxt
            if not frontier:
                break
        return result

    def upstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        """Nodes that this node depends on (outgoing DEPENDS_ON/IMPORTS/CALLS)."""
        return self._traverse(node_id, max_depth, forward=True)

    def downstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        """Nodes that depend on this node (incoming edges)."""
        return self._traverse(node_id, max_depth, forward=False)

    def blast_radius(self, node_id: str, max_depth: int = 3) -> dict[str, Any]:
        affected = self.downstream_deps(node_id, max_depth=max_depth)
        by_type: dict[str, int] = defaultdict(int)
        for n in affected:
            by_type[n.get("type", "Unknown")] += 1
        return {
            "center": node_id,
            "affected_count": len(affected),
            "affected": affected,
            "by_type": dict(by_type),
            "max_depth": max_depth,
        }

    def get_repo_map(self, repo_id: str) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        modules: list[dict[str, Any]] = []
        concepts: list[dict[str, Any]] = []
        functions = 0
        for node in self.nodes.values():
            props = node.get("props") or {}
            if props.get("repo_id") and props.get("repo_id") != repo_id:
                continue
            # If repo filter set on store, prefer matching; allow unscoped nodes
            if repo_id and props.get("repo_id") and props["repo_id"] != repo_id:
                continue
            ntype = node.get("type", "")
            if ntype == "File":
                files.append({"id": node["id"], "label": node.get("label"), "path": props.get("path", node.get("label"))})
            elif ntype in {"Module", "Package"}:
                modules.append({"id": node["id"], "label": node.get("label")})
            elif ntype == "Concept":
                concepts.append({"id": node["id"], "label": node.get("label")})
            elif ntype in {"Function", "Method", "Struct", "Interface", "Class"}:
                functions += 1
        return {
            "repo_id": repo_id,
            "file_count": len(files),
            "module_count": len(modules),
            "function_count": functions,
            "concept_count": len(concepts),
            "files": files[:200],
            "modules": modules,
            "concepts": concepts,
            "edge_count": len(self.edges),
            "node_count": len(self.nodes),
        }

    def files_by_concept(self, concept: str, repo_id: str = "") -> list[dict[str, Any]]:
        concept_l = concept.lower()
        concept_ids = {
            nid
            for nid, n in self.nodes.items()
            if n.get("type") == "Concept"
            and (
                n.get("label", "").lower() == concept_l
                or nid.lower().endswith(":" + concept_l)
                or nid.lower() == concept_l
            )
        }
        # Also match concept nodes by props.name
        for nid, n in self.nodes.items():
            if n.get("type") == "Concept":
                name = (n.get("props") or {}).get("name", "")
                if str(name).lower() == concept_l:
                    concept_ids.add(nid)

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for e in self.edges:
            if e["type"] != "TAGGED_AS":
                continue
            if e["to"] not in concept_ids and e["to"].lower() != concept_l:
                # allow tagging to concept label id
                to_node = self.nodes.get(e["to"])
                if not to_node or to_node.get("label", "").lower() != concept_l:
                    if e["to"].lower().split(":")[-1] != concept_l:
                        continue
            src = self.nodes.get(e["from"])
            if not src:
                continue
            if repo_id and (src.get("props") or {}).get("repo_id") not in ("", repo_id, None):
                if (src.get("props") or {}).get("repo_id") != repo_id:
                    continue
            # Walk up to File if symbol
            file_node = src
            if src.get("type") != "File":
                path = (src.get("props") or {}).get("path") or (src.get("props") or {}).get("file_path")
                if path:
                    for n in self.nodes.values():
                        if n.get("type") == "File" and (
                            n.get("label") == path or (n.get("props") or {}).get("path") == path
                        ):
                            file_node = n
                            break
            fid = file_node["id"]
            if fid in seen:
                continue
            seen.add(fid)
            results.append(
                {
                    "id": file_node["id"],
                    "label": file_node.get("label"),
                    "type": file_node.get("type"),
                    "confidence": e.get("confidence", 1.0),
                    "evidence": e.get("evidence", []),
                    "tagged_node": src["id"],
                }
            )
        results.sort(key=lambda x: (-float(x.get("confidence", 0)), str(x.get("label", ""))))
        return results

    def ownership_for_path(self, path: str, repo_id: str = "") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(path_v: str, owner: str, confidence: float, evidence: list[str]) -> None:
            key = (path_v, owner)
            if key in seen:
                return
            seen.add(key)
            results.append(
                {
                    "path": path_v,
                    "owner": owner,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )

        for e in self.edges:
            if e["type"] != "OWNS":
                continue
            owner_node = self.nodes.get(e["from"])
            file_node = self.nodes.get(e["to"])
            if file_node and file_node.get("type") not in {"File", "Module", "Package"}:
                file_node, owner_node = owner_node, file_node
            path_props = ((file_node or {}).get("props") or {})
            fpath = path_props.get("path") or (file_node or {}).get("label", "")
            if path not in str(fpath) and str(fpath) not in path and e["to"] != path and e["from"] != path:
                if path not in (e["to"], e["from"]):
                    continue
            owner_label = (owner_node or {}).get("label") or e["from"]
            if repo_id and path_props.get("repo_id") and path_props["repo_id"] != repo_id:
                continue
            add(str(fpath or path), str(owner_label), float(e.get("confidence", 0.0)), list(e.get("evidence") or []))

        for node in self.nodes.values():
            props = node.get("props") or {}
            npath = props.get("path") or node.get("label", "")
            if path not in str(npath) and str(npath) != path:
                continue
            if "owner" in props:
                add(
                    str(npath),
                    str(props["owner"]),
                    float(props.get("ownership_confidence", 0.5)),
                    ["node_props"],
                )
        results.sort(key=lambda x: -float(x.get("confidence", 0)))
        return results

    def hotspots(self, repo_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for node in self.nodes.values():
            if node.get("type") != "File":
                continue
            props = node.get("props") or {}
            if repo_id and props.get("repo_id") and props["repo_id"] != repo_id:
                continue
            churn = float(props.get("churn", props.get("commits", 0)) or 0)
            commits = int(props.get("commits", 0) or 0)
            score = churn if churn else float(commits)
            if score <= 0:
                continue
            scored.append(
                {
                    "id": node["id"],
                    "path": props.get("path", node.get("label")),
                    "label": node.get("label"),
                    "churn": churn,
                    "commits": commits,
                    "score": score,
                }
            )
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]


class Neo4jGraphStore:
    """Neo4j-backed graph store using the official driver."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "ncmpassword")
        self._driver: Any = None

    def connect(self) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._driver.verify_connectivity()
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT ncm_node_id IF NOT EXISTS "
                "FOR (n:NCMNode) REQUIRE n.id IS UNIQUE"
            )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _session(self) -> Any:
        if self._driver is None:
            raise RuntimeError("Neo4jGraphStore is not connected; call connect() first")
        return self._driver.session()

    def clear_repo(self, repo_id: str) -> None:
        with self._session() as session:
            session.run(
                """
                MATCH (n:NCMNode {repo_id: $repo_id})
                DETACH DELETE n
                """,
                repo_id=repo_id,
            )

    def ingest_nodes(self, nodes: list[dict[str, Any]], repo_id: str = "") -> int:
        count = 0
        with self._session() as session:
            for raw in nodes:
                node = _node_dict(raw)
                rid = repo_id or (node["props"].get("repo_id") or "")
                props = {
                    **node["props"],
                    "id": node["id"],
                    "label": node["label"],
                    "type": node["type"],
                }
                if rid:
                    props["repo_id"] = rid
                # Flatten JSON-serializable props only
                flat = {
                    k: v
                    for k, v in props.items()
                    if isinstance(v, (str, int, float, bool, list, type(None)))
                }
                session.run(
                    """
                    MERGE (n:NCMNode {id: $id})
                    SET n += $props
                    """,
                    id=node["id"],
                    props=flat,
                )
                count += 1
        return count

    def ingest_edges(self, edges: list[dict[str, Any]], repo_id: str = "") -> int:
        count = 0
        with self._session() as session:
            for raw in edges:
                edge = _edge_dict(raw)
                if not edge["from"] or not edge["to"]:
                    continue
                # Ensure endpoints exist
                session.run(
                    "MERGE (a:NCMNode {id: $id})",
                    id=edge["from"],
                )
                session.run(
                    "MERGE (b:NCMNode {id: $id})",
                    id=edge["to"],
                )
                rel_type = "".join(c if c.isalnum() or c == "_" else "_" for c in edge["type"]).upper()
                if not rel_type:
                    rel_type = "RELATED"
                cypher = f"""
                    MATCH (a:NCMNode {{id: $from_id}})
                    MATCH (b:NCMNode {{id: $to_id}})
                    MERGE (a)-[r:{rel_type} {{id: $eid}}]->(b)
                    SET r.confidence = $confidence,
                        r.evidence = $evidence,
                        r.repo_id = $repo_id
                """
                session.run(
                    cypher,
                    from_id=edge["from"],
                    to_id=edge["to"],
                    eid=edge["id"],
                    confidence=edge["confidence"],
                    evidence=edge["evidence"],
                    repo_id=repo_id,
                )
                count += 1
        return count

    def neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        depth = max(1, min(depth, 5))
        with self._session() as session:
            result = session.run(
                f"""
                MATCH (s:NCMNode {{id: $id}})-[*1..{depth}]-(n:NCMNode)
                RETURN DISTINCT n.id AS id, n.type AS type, n.label AS label, n AS props
                """,
                id=node_id,
            )
            return [_record_to_node(r) for r in result]

    def shortest_path(self, from_id: str, to_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (a:NCMNode {id: $from_id}), (b:NCMNode {id: $to_id})
                MATCH p = shortestPath((a)-[*..12]-(b))
                RETURN nodes(p) AS nodes
                LIMIT 1
                """,
                from_id=from_id,
                to_id=to_id,
            )
            record = result.single()
            if not record:
                return []
            nodes = record["nodes"] or []
            out: list[dict[str, Any]] = []
            for n in nodes:
                out.append(
                    {
                        "id": n.get("id"),
                        "type": n.get("type"),
                        "label": n.get("label"),
                        "props": {k: v for k, v in dict(n).items() if k not in {"id", "type", "label"}},
                    }
                )
            return out

    def upstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        max_depth = max(1, min(max_depth, 8))
        with self._session() as session:
            result = session.run(
                f"""
                MATCH (s:NCMNode {{id: $id}})-[:DEPENDS_ON|IMPORTS|CALLS|CONTAINS*1..{max_depth}]->(n:NCMNode)
                RETURN DISTINCT n.id AS id, n.type AS type, n.label AS label, n AS props
                """,
                id=node_id,
            )
            return [_record_to_node(r) for r in result]

    def downstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        max_depth = max(1, min(max_depth, 8))
        with self._session() as session:
            result = session.run(
                f"""
                MATCH (s:NCMNode {{id: $id}})<-[:DEPENDS_ON|IMPORTS|CALLS|CONTAINS*1..{max_depth}]-(n:NCMNode)
                RETURN DISTINCT n.id AS id, n.type AS type, n.label AS label, n AS props
                """,
                id=node_id,
            )
            return [_record_to_node(r) for r in result]

    def blast_radius(self, node_id: str, max_depth: int = 3) -> dict[str, Any]:
        affected = self.downstream_deps(node_id, max_depth=max_depth)
        by_type: dict[str, int] = defaultdict(int)
        for n in affected:
            by_type[str(n.get("type") or "Unknown")] += 1
        return {
            "center": node_id,
            "affected_count": len(affected),
            "affected": affected,
            "by_type": dict(by_type),
            "max_depth": max_depth,
        }

    def get_repo_map(self, repo_id: str) -> dict[str, Any]:
        with self._session() as session:
            files = [
                {"id": r["id"], "label": r["label"], "path": r["path"]}
                for r in session.run(
                    """
                    MATCH (n:NCMNode {repo_id: $repo_id})
                    WHERE n.type = 'File'
                    RETURN n.id AS id, n.label AS label, coalesce(n.path, n.label) AS path
                    LIMIT 200
                    """,
                    repo_id=repo_id,
                )
            ]
            modules = [
                {"id": r["id"], "label": r["label"]}
                for r in session.run(
                    """
                    MATCH (n:NCMNode {repo_id: $repo_id})
                    WHERE n.type IN ['Module', 'Package']
                    RETURN n.id AS id, n.label AS label
                    """,
                    repo_id=repo_id,
                )
            ]
            concepts = [
                {"id": r["id"], "label": r["label"]}
                for r in session.run(
                    """
                    MATCH (n:NCMNode)
                    WHERE n.type = 'Concept' AND (n.repo_id = $repo_id OR n.repo_id IS NULL)
                    RETURN n.id AS id, n.label AS label
                    """,
                    repo_id=repo_id,
                )
            ]
            counts = session.run(
                """
                MATCH (n:NCMNode {repo_id: $repo_id})
                RETURN count(n) AS nodes,
                       sum(CASE WHEN n.type IN ['Function','Method','Struct','Interface','Class'] THEN 1 ELSE 0 END) AS functions
                """,
                repo_id=repo_id,
            ).single()
            edge_count = session.run(
                """
                MATCH (a:NCMNode {repo_id: $repo_id})-[r]->(b:NCMNode)
                RETURN count(r) AS edges
                """,
                repo_id=repo_id,
            ).single()
            return {
                "repo_id": repo_id,
                "file_count": len(files),
                "module_count": len(modules),
                "function_count": int((counts or {}).get("functions") or 0),
                "concept_count": len(concepts),
                "files": files,
                "modules": modules,
                "concepts": concepts,
                "edge_count": int((edge_count or {}).get("edges") or 0),
                "node_count": int((counts or {}).get("nodes") or 0),
            }

    def files_by_concept(self, concept: str, repo_id: str = "") -> list[dict[str, Any]]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (c:NCMNode)
                WHERE c.type = 'Concept' AND (
                    toLower(c.label) = toLower($concept)
                    OR toLower(c.name) = toLower($concept)
                    OR toLower(c.id) ENDS WITH ':' + toLower($concept)
                )
                MATCH (n:NCMNode)-[r:TAGGED_AS]->(c)
                WHERE $repo_id = '' OR n.repo_id = $repo_id OR n.repo_id IS NULL
                OPTIONAL MATCH (f:NCMNode {type: 'File'})
                WHERE f.path = n.path OR f.path = n.file_path OR f.id = n.id
                RETURN coalesce(f.id, n.id) AS id,
                       coalesce(f.label, n.label) AS label,
                       coalesce(f.type, n.type) AS type,
                       r.confidence AS confidence,
                       r.evidence AS evidence,
                       n.id AS tagged_node
                ORDER BY confidence DESC
                """,
                concept=concept,
                repo_id=repo_id or "",
            )
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for r in result:
                nid = r["id"]
                if nid in seen:
                    continue
                seen.add(nid)
                out.append(
                    {
                        "id": nid,
                        "label": r["label"],
                        "type": r["type"],
                        "confidence": r["confidence"] or 0.0,
                        "evidence": list(r["evidence"] or []),
                        "tagged_node": r["tagged_node"],
                    }
                )
            return out

    def ownership_for_path(self, path: str, repo_id: str = "") -> list[dict[str, Any]]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (a:NCMNode)-[r:OWNS]->(f:NCMNode)
                WHERE f.path CONTAINS $path OR f.label CONTAINS $path OR f.id CONTAINS $path
                  AND ($repo_id = '' OR f.repo_id = $repo_id OR f.repo_id IS NULL)
                RETURN coalesce(f.path, f.label) AS path,
                       coalesce(a.label, a.id) AS owner,
                       r.confidence AS confidence,
                       r.evidence AS evidence
                ORDER BY confidence DESC
                """,
                path=path,
                repo_id=repo_id or "",
            )
            return [
                {
                    "path": r["path"],
                    "owner": r["owner"],
                    "confidence": r["confidence"] or 0.0,
                    "evidence": list(r["evidence"] or []),
                }
                for r in result
            ]

    def hotspots(self, repo_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (n:NCMNode)
                WHERE n.type = 'File'
                  AND ($repo_id = '' OR n.repo_id = $repo_id OR n.repo_id IS NULL)
                  AND (n.churn IS NOT NULL OR n.commits IS NOT NULL)
                RETURN n.id AS id,
                       coalesce(n.path, n.label) AS path,
                       n.label AS label,
                       coalesce(n.churn, 0) AS churn,
                       coalesce(n.commits, 0) AS commits,
                       coalesce(n.churn, n.commits, 0) AS score
                ORDER BY score DESC
                LIMIT $limit
                """,
                repo_id=repo_id or "",
                limit=limit,
            )
            return [
                {
                    "id": r["id"],
                    "path": r["path"],
                    "label": r["label"],
                    "churn": float(r["churn"] or 0),
                    "commits": int(r["commits"] or 0),
                    "score": float(r["score"] or 0),
                }
                for r in result
            ]


def _record_to_node(r: Any) -> dict[str, Any]:
    props_node = r.get("props")
    extra: dict[str, Any] = {}
    if props_node is not None:
        try:
            extra = {k: v for k, v in dict(props_node).items() if k not in {"id", "type", "label"}}
        except Exception:
            extra = {}
    return {
        "id": r.get("id"),
        "type": r.get("type"),
        "label": r.get("label"),
        "props": extra,
    }


def create_store(*, prefer_neo4j: bool = True) -> InMemoryGraphStore | Neo4jGraphStore:
    """Create a store: Neo4j if NEO4J_URI is set and connection works, else in-memory."""
    from brain.logging_config import get_logger

    log = get_logger("ncm.graph")
    uri = os.getenv("NEO4J_URI")
    if prefer_neo4j and uri:
        store = Neo4jGraphStore(uri=uri)
        try:
            store.connect()
            log.info("connected to Neo4j uri=%s", uri)
            return store
        except Exception as exc:
            log.warning("Neo4j unavailable (%s); falling back to in-memory store", exc)
            try:
                store.close()
            except Exception:
                pass
    else:
        log.debug("NEO4J_URI not set or prefer_neo4j=False; using in-memory store")
    mem = InMemoryGraphStore()
    mem.connect()
    log.info("using in-memory graph store")
    return mem
