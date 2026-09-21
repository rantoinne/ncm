"""Minimal MCP-style tool server exposing NCM query/map/blast-radius."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from brain.api.main import _ingest_bundle, get_store, set_store
from brain.graph.store import InMemoryGraphStore, create_store
from brain.logging_config import setup_logging
from brain.reasoning.engine import Reasoner


TOOLS = [
    {
        "name": "ncm_query",
        "description": "Ask an architectural question over the indexed NCM graph",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "repo_id": {"type": "string"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "ncm_repo_map",
        "description": "Return repository map (files/modules) for a repo_id",
        "inputSchema": {
            "type": "object",
            "properties": {"repo_id": {"type": "string"}},
            "required": ["repo_id"],
        },
    },
    {
        "name": "ncm_blast_radius",
        "description": "Compute blast radius for a node id or path",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["node_id"],
        },
    },
]


def _ensure_store(data_dir: str = "./data", memory: bool = True) -> None:
    if memory:
        s = InMemoryGraphStore()
        s.connect()
        set_store(s)
    else:
        set_store(create_store(prefer_neo4j=True))
    if os.path.isdir(data_dir) and (os.path.exists(os.path.join(data_dir, "manifest.json"))):
        _ingest_bundle(data_dir, merge=False)


def handle_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    if name == "ncm_query":
        rid = arguments.get("repo_id") or os.getenv("NCM_REPO_ID", "")
        return Reasoner(store, repo_id=rid).answer(arguments["q"], repo_id=rid or None).to_dict()
    if name == "ncm_repo_map":
        return store.get_repo_map(arguments["repo_id"])
    if name == "ncm_blast_radius":
        return store.blast_radius(arguments["node_id"], max_depth=int(arguments.get("max_depth") or 3))
    return {"error": f"unknown tool {name}"}


def main() -> None:
    """
    Simple line-oriented JSON protocol for agents:

      {"tool":"ncm_query","arguments":{"q":"Where does persistence live?"}}
    """
    setup_logging()
    data_dir = os.getenv("NCM_DATA_DIR", "./data")
    memory = os.getenv("NCM_MEMORY", "1") != "0"
    _ensure_store(data_dir=data_dir, memory=memory)
    print(json.dumps({"ok": True, "tools": [t["name"] for t in TOOLS]}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            out = handle_tool(req.get("tool") or req.get("name") or "", req.get("arguments") or {})
            print(json.dumps({"result": out}), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)


if __name__ == "__main__":
    main()
