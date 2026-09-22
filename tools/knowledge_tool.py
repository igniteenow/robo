"""Knowledge-base tools: attach any file, then ask about it.
Copyright (c) 2026 Ignitee Now.

Four tools in the ``knowledge`` toolset. ``knowledge_add`` indexes a file or
pasted text of any size; ``knowledge_search`` returns the passages that answer
a question; ``knowledge_list`` and ``knowledge_remove`` manage what is stored.
Retrieval is local (SQLite FTS5) and works offline. See
``robo_cli/knowledge_store.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

_store = None


def _get_store():
    global _store
    if _store is None:
        from robo_cli.knowledge_store import KnowledgeStore

        _store = KnowledgeStore()
    return _store


def _reset_store() -> None:  # tests
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = None


def knowledge_add(path: str = "", text: str = "", title: str = "", tags: str = "", source: str = "") -> str:
    from robo_cli.knowledge_store import KnowledgeError, to_json

    try:
        store = _get_store()
        if path:
            doc = store.add_file(path, title=title or None, tags=tags)
        elif text:
            doc = store.add_text(text, source=source or (title or f"note-{abs(hash(text)) % 10**8}"), title=title or None, tags=tags)
        else:
            return json.dumps({"error": "Give either a file path or text to index."})
        return json.dumps({"indexed": to_json(doc), "hint": "Ask about it with knowledge_search; large files are read in parts."})
    except KnowledgeError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("knowledge_add failed")
        return json.dumps({"error": f"Could not index: {exc}"})


def knowledge_search(query: str = "", limit: int = 5, source: str = "") -> str:
    try:
        store = _get_store()
        if not (query or "").strip():
            return json.dumps({"error": "Give a question or keywords to search for."})
        hits = store.search(query, limit=limit, source=source or None)
        if not hits:
            stats = store.stats()
            if stats["documents"] == 0:
                return json.dumps({"results": [], "note": "The knowledge base is empty. Index a file with knowledge_add first."})
            return json.dumps({"results": [], "note": "No passage matched. Try other words, or knowledge_list to see what is indexed."})
        return json.dumps({"results": [
            {"document": h.title, "source": h.document, "part": h.ordinal + 1, "text": h.text} for h in hits
        ]}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("knowledge_search failed")
        return json.dumps({"error": f"Search failed: {exc}"})


def knowledge_list() -> str:
    from robo_cli.knowledge_store import to_json

    try:
        store = _get_store()
        return json.dumps({"documents": [to_json(d) for d in store.documents()], "stats": store.stats()}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"Could not list: {exc}"})


def knowledge_remove(source: str = "") -> str:
    try:
        if not source:
            return json.dumps({"error": "Give the source path or name to remove (see knowledge_list)."})
        removed = _get_store().remove(source)
        return json.dumps({"removed": removed, "source": source})
    except Exception as exc:
        return json.dumps({"error": f"Could not remove: {exc}"})


KNOWLEDGE_ADD_SCHEMA = {
    "name": "knowledge_add",
    "description": (
        "Index a document into the local knowledge base so it can be searched. Works for files of any size "
        "(text, code, markdown, CSV, JSON, HTML, PDF, DOCX, PPTX, XLSX) or for pasted text. Use this when the "
        "user attaches or names a file that is too large to read in one go, or that they will ask about later. "
        "Re-adding an unchanged file is free."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to index."},
            "text": {"type": "string", "description": "Text to index instead of a file."},
            "title": {"type": "string", "description": "Optional display name."},
            "tags": {"type": "string", "description": "Optional comma-separated tags."},
            "source": {"type": "string", "description": "Optional identifier for pasted text (defaults to the title)."},
        },
    },
}

KNOWLEDGE_SEARCH_SCHEMA = {
    "name": "knowledge_search",
    "description": (
        "Search the local knowledge base and get back the passages most relevant to a question. "
        "Use it to answer questions about attached documents instead of reading whole files. "
        "Returns document name, part number and the passage text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question, or keywords."},
            "limit": {"type": "integer", "description": "How many passages to return (default 5, max 50)."},
            "source": {"type": "string", "description": "Restrict to one document (its source path or name)."},
        },
        "required": ["query"],
    },
}

KNOWLEDGE_LIST_SCHEMA = {
    "name": "knowledge_list",
    "description": "List the documents in the local knowledge base with their size and part count.",
    "parameters": {"type": "object", "properties": {}},
}

KNOWLEDGE_REMOVE_SCHEMA = {
    "name": "knowledge_remove",
    "description": "Remove a document from the knowledge base by its source path or name.",
    "parameters": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]},
}

registry.register(
    name="knowledge_add", toolset="knowledge", schema=KNOWLEDGE_ADD_SCHEMA,
    handler=lambda args, **kw: knowledge_add(
        path=args.get("path", ""), text=args.get("text", ""), title=args.get("title", ""),
        tags=args.get("tags", ""), source=args.get("source", ""),
    ),
    description="Index a file or text of any size into the knowledge base",
)
registry.register(
    name="knowledge_search", toolset="knowledge", schema=KNOWLEDGE_SEARCH_SCHEMA,
    handler=lambda args, **kw: knowledge_search(query=args.get("query", ""), limit=args.get("limit", 5), source=args.get("source", "")),
    description="Find the passages in the knowledge base that answer a question",
)
registry.register(
    name="knowledge_list", toolset="knowledge", schema=KNOWLEDGE_LIST_SCHEMA,
    handler=lambda args, **kw: knowledge_list(), description="List indexed documents",
)
registry.register(
    name="knowledge_remove", toolset="knowledge", schema=KNOWLEDGE_REMOVE_SCHEMA,
    handler=lambda args, **kw: knowledge_remove(source=args.get("source", "")), description="Remove an indexed document",
)
