"""Robo's knowledge base: attach a file of any size, then ask about it.
Copyright (c) 2026 Ignitee Now.

Documents are split into overlapping chunks and indexed in SQLite's built-in
full-text engine (FTS5, BM25 ranking). Nothing is sent anywhere, nothing is
downloaded, and there is no new dependency: it works offline on every OS Robo
runs on, and it works the same from the TUI, the desktop app, the dashboard and
the iPhone app because they all reach the same store through the gateway.

Any size: files are read in blocks and indexed chunk by chunk inside a single
transaction, so a 2 GB log takes time but never takes memory. The agent then
asks for the parts that matter (``knowledge_search``) instead of trying to read
the whole thing into its context window, which is how large files become
usable at all.

Formats: plain text of any kind (txt, md, code, json, csv, yaml, logs, html),
PDF (``pypdf``, page by page), Word (``python-docx``), Excel (``openpyxl``),
and PowerPoint (read straight from the zip, no library). Images are refused
with a pointer to the vision tools.

Layout: ``<robo home>/knowledge/knowledge.db``.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1200      # about 300 tokens: enough context, small enough to rank well
CHUNK_OVERLAP = 160     # a sentence or two, so a fact split across chunks is still found
READ_BLOCK = 64 * 1024
DEFAULT_LIMIT = 5
MAX_SNIPPET_CHARS = 700

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".kt", ".swift", ".go", ".rs", ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs",
    ".sh", ".ps1", ".bat", ".sql", ".r", ".m", ".scala", ".lua", ".pl", ".env", ".tex", ".org",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".svg", ".tiff"}
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")
_TOKEN = re.compile(r"[\w'’-]{2,}", re.UNICODE)


class KnowledgeError(Exception):
    """A document could not be indexed. The message says what to do."""


@dataclass
class Document:
    id: int
    source: str
    title: str
    kind: str
    size: int
    chunks: int
    added_at: float
    tags: str = ""


@dataclass
class Hit:
    document: str
    title: str
    ordinal: int
    score: float
    text: str


# ----------------------------------------------------------------------------- text
def normalise(text: str) -> str:
    text = text.replace("\x00", "")
    text = _WS.sub(" ", text)
    return _BLANKS.sub("\n\n", text).strip()


def chunk_stream(blocks: Iterable[str], size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> Iterator[str]:
    """Turn a stream of text blocks into overlapping chunks, breaking at a
    paragraph, sentence or word boundary when one is near the target size.
    Holds at most a few chunks' worth of text in memory at any time."""
    overlap = max(0, min(overlap, size // 2))
    buffer = ""
    for block in blocks:
        buffer += block
        while len(buffer) >= size + overlap:
            cut = _cut_point(buffer, size)
            piece = buffer[:cut].strip()
            if piece:
                yield piece
            buffer = buffer[max(cut - overlap, 1):]
    tail = buffer.strip()
    if tail:
        yield tail


def _cut_point(text: str, size: int) -> int:
    window = text[: size + 1]
    for pattern in ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "):
        at = window.rfind(pattern, size // 2, size)
        if at != -1:
            return at + len(pattern)
    return size


# ------------------------------------------------------------------------ extractors
def _text_blocks(path: Path) -> Iterator[str]:
    strip_html = path.suffix.lower() in (".html", ".htm", ".xml")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        while True:
            block = handle.read(READ_BLOCK)
            if not block:
                break
            if strip_html:
                block = html.unescape(_TAG.sub(" ", block))
            yield normalise(block) + "\n"


def _pdf_blocks(path: Path) -> Iterator[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared, but be clear if missing
        raise KnowledgeError("PDF support needs the 'pypdf' package: uv pip install pypdf") from exc
    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # a damaged page should not lose the whole document
            logger.debug("knowledge: page %s of %s unreadable: %s", number, path, exc)
            continue
        text = normalise(text)
        if text:
            yield f"[page {number}]\n{text}\n\n"


def _docx_blocks(path: Path) -> Iterator[str]:
    try:
        import docx  # python-docx
    except ImportError:
        yield from _office_xml_blocks(path, "word/document.xml")
        return
    document = docx.Document(str(path))
    for paragraph in document.paragraphs:
        text = normalise(paragraph.text)
        if text:
            yield text + "\n"
    for table in document.tables:
        for row in table.rows:
            cells = [normalise(c.text) for c in row.cells]
            if any(cells):
                yield " | ".join(cells) + "\n"
        yield "\n"


def _pptx_blocks(path: Path) -> Iterator[str]:
    with zipfile.ZipFile(path) as archive:
        slides = sorted(
            (n for n in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        for number, name in enumerate(slides, 1):
            xml = archive.read(name).decode("utf-8", errors="replace")
            runs = re.findall(r"<a:t[^>]*>(.*?)</a:t>", xml, re.S)
            text = normalise(html.unescape(" ".join(runs)))
            if text:
                yield f"[slide {number}]\n{text}\n\n"


def _office_xml_blocks(path: Path, member: str) -> Iterator[str]:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read(member).decode("utf-8", errors="replace")
    paragraphs = re.split(r"</w:p>", xml)
    for paragraph in paragraphs:
        runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, re.S)
        text = normalise(html.unescape("".join(runs)))
        if text:
            yield text + "\n"


def _xlsx_blocks(path: Path) -> Iterator[str]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise KnowledgeError("Excel support needs the 'openpyxl' package, or save the sheet as CSV.") from exc
    workbook = load_workbook(str(path), read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        yield f"[sheet {sheet.title}]\n"
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(cells):
                yield " | ".join(cells).rstrip(" |") + "\n"
        yield "\n"


EXTRACTORS: dict[str, Callable[[Path], Iterator[str]]] = {
    ".pdf": _pdf_blocks, ".docx": _docx_blocks, ".pptx": _pptx_blocks, ".xlsx": _xlsx_blocks, ".xlsm": _xlsx_blocks,
}


def blocks_for(path: Path) -> tuple[str, Iterator[str]]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        raise KnowledgeError(f"{path.name} is an image. Use the vision tools to look at images; the knowledge base holds text.")
    if suffix in EXTRACTORS:
        return suffix.lstrip("."), EXTRACTORS[suffix](path)
    if suffix in TEXT_SUFFIXES or suffix == "" or _looks_like_text(path):
        return (suffix.lstrip(".") or "text"), _text_blocks(path)
    raise KnowledgeError(
        f"{path.name}: unsupported type '{suffix}'. Supported: text/code/markdown/CSV/JSON/HTML, PDF, DOCX, PPTX, XLSX."
    )


def _looks_like_text(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError:
        return False
    if not sample or b"\x00" in sample:
        return False
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13) or b >= 128)
    return printable / len(sample) > 0.9


# ------------------------------------------------------------------------------ store
def default_db_path() -> Path:
    from robo_constants import get_robo_home

    return get_robo_home() / "knowledge" / "knowledge.db"


_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ers", "ed", "es", "er", "ly", "s")


def _stems(token: str) -> List[str]:
    """The token, plus a shortened form with a common English suffix removed,
    so a prefix search for 'releasing' also finds 'release' and 'released'.
    Cheaper and more predictable than a stemming tokenizer, which breaks
    prefix matching (FTS5 stems the query too)."""
    forms = [token]
    low = token.lower()
    for suffix in _SUFFIXES:
        if low.endswith(suffix) and len(low) - len(suffix) >= 4:
            forms.append(low[: -len(suffix)])
            break
    return forms


def fts_query(text: str) -> str:
    """Turn a natural-language question into a safe FTS5 query: quoted terms,
    OR-ed so partial matches still rank, prefix-matched so 'deploy' finds
    'deployments'. Nothing the user types can reach the FTS parser unquoted."""
    terms = []
    for token in _TOKEN.findall(text or ""):
        cleaned = token.replace('"', "").strip("'’-")
        if len(cleaned) >= 2:
            terms.extend(f'"{form}"*' for form in _stems(cleaned))
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return " OR ".join(seen[:32])


class KnowledgeStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.path = Path(db_path) if db_path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                chunks INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                added_at REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                content, doc_id UNINDEXED, ordinal UNINDEXED,
                tokenize = 'unicode61'
            );
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # -- adding ---------------------------------------------------------------
    def add_file(self, path: str | os.PathLike, *, title: Optional[str] = None, tags: str = "") -> Document:
        """Index a file. Re-adding an unchanged file is a no-op; a changed file
        replaces its previous chunks."""
        file = Path(path).expanduser()
        if not file.is_file():
            raise KnowledgeError(f"{file}: no such file.")
        digest = _sha256(file)
        existing = self.get(str(file.resolve()))
        if existing and existing_sha(self._db, existing.id) == digest:
            return existing
        kind, blocks = blocks_for(file)
        return self._index(str(file.resolve()), title or file.name, kind, file.stat().st_size, digest, tags, blocks)

    def add_text(self, text: str, *, source: str, title: Optional[str] = None, tags: str = "") -> Document:
        """Index text that did not come from a file (pasted notes, a web page)."""
        text = text or ""
        if not text.strip():
            raise KnowledgeError("Nothing to index: the text is empty.")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.get(source)
        if existing and existing_sha(self._db, existing.id) == digest:
            return existing
        blocks = (normalise(text[i:i + READ_BLOCK]) + "\n" for i in range(0, len(text), READ_BLOCK))
        return self._index(source, title or source, "text", len(text.encode("utf-8")), digest, tags, blocks)

    def _index(self, source: str, title: str, kind: str, size: int, sha: str, tags: str, blocks: Iterable[str]) -> Document:
        db = self._db
        try:
            db.execute("BEGIN")
            row = db.execute("SELECT id FROM documents WHERE source = ?", (source,)).fetchone()
            if row:
                db.execute("DELETE FROM chunks WHERE doc_id = ?", (row[0],))
                db.execute("DELETE FROM documents WHERE id = ?", (row[0],))
            cursor = db.execute(
                "INSERT INTO documents (source, title, kind, size, chunks, sha256, tags, added_at) VALUES (?,?,?,?,0,?,?,?)",
                (source, title, kind, size, sha, tags or "", time.time()),
            )
            doc_id = cursor.lastrowid
            count = 0
            batch: List[tuple] = []
            for ordinal, chunk in enumerate(chunk_stream(blocks)):
                batch.append((chunk, doc_id, ordinal))
                count += 1
                if len(batch) >= 500:
                    db.executemany("INSERT INTO chunks (content, doc_id, ordinal) VALUES (?,?,?)", batch)
                    batch.clear()
            if batch:
                db.executemany("INSERT INTO chunks (content, doc_id, ordinal) VALUES (?,?,?)", batch)
            if count == 0:
                db.execute("ROLLBACK")
                raise KnowledgeError(f"{title}: no readable text was found in it.")
            db.execute("UPDATE documents SET chunks = ? WHERE id = ?", (count, doc_id))
            db.execute("COMMIT")
        except KnowledgeError:
            raise
        except Exception:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return self.get(source)  # type: ignore[return-value]

    # -- reading ---------------------------------------------------------------
    def get(self, source: str) -> Optional[Document]:
        row = self._db.execute(
            "SELECT id, source, title, kind, size, chunks, added_at, tags FROM documents WHERE source = ?", (source,)
        ).fetchone()
        return Document(*row) if row else None

    def documents(self) -> List[Document]:
        rows = self._db.execute(
            "SELECT id, source, title, kind, size, chunks, added_at, tags FROM documents ORDER BY added_at DESC"
        ).fetchall()
        return [Document(*r) for r in rows]

    def remove(self, source: str) -> bool:
        doc = self.get(source)
        if not doc:
            return False
        with self._db:
            self._db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc.id,))
            self._db.execute("DELETE FROM documents WHERE id = ?", (doc.id,))
        return True

    def stats(self) -> dict:
        docs, chunks, size = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunks),0), COALESCE(SUM(size),0) FROM documents"
        ).fetchone()
        return {"documents": docs, "chunks": chunks, "bytes": size, "path": str(self.path)}

    def search(self, query: str, *, limit: int = DEFAULT_LIMIT, source: Optional[str] = None) -> List[Hit]:
        match = fts_query(query)
        if not match:
            return []
        # FTS5 MATCH cannot be combined with a JOIN on the same table name, so
        # rank inside the FTS table first, then look each document up.
        sql = "SELECT doc_id, ordinal, bm25(chunks) AS score, content FROM chunks WHERE chunks MATCH ?"
        params: list = [match]
        if source:
            doc = self.get(source)
            if doc is None:
                return []
            sql += " AND doc_id = ?"
            params.append(doc.id)
        sql += " ORDER BY score LIMIT ?"
        params.append(max(1, min(int(limit or DEFAULT_LIMIT), 50)))
        try:
            rows = self._db.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:  # a query FTS5 still rejects: report empty, never crash a turn
            logger.debug("knowledge: query rejected (%s): %r", exc, match)
            return []
        titles: dict = {}
        hits: List[Hit] = []
        for doc_id, ordinal, score, content in rows:
            if doc_id not in titles:
                row = self._db.execute("SELECT source, title FROM documents WHERE id = ?", (doc_id,)).fetchone()
                titles[doc_id] = row or ("", "")
            src, title = titles[doc_id]
            hits.append(Hit(document=src, title=title, ordinal=int(ordinal), score=float(score), text=content))
        return hits

    def recall(self, query: str, *, limit: int = 3, max_chars: int = 2400) -> str:
        """A compact block of the most relevant passages, for a prompt."""
        hits = self.search(query, limit=limit)
        if not hits:
            return ""
        lines = ["Relevant passages from the knowledge base:"]
        used = len(lines[0])
        for hit in hits:
            text = hit.text if len(hit.text) <= MAX_SNIPPET_CHARS else hit.text[:MAX_SNIPPET_CHARS].rstrip() + "…"
            entry = f"\n[{hit.title} · part {hit.ordinal + 1}]\n{text}"
            if used + len(entry) > max_chars:
                break
            lines.append(entry)
            used += len(entry)
        return "\n".join(lines) if len(lines) > 1 else ""


def existing_sha(db: sqlite3.Connection, doc_id: int) -> str:
    row = db.execute("SELECT sha256 FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return row[0] if row else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def to_json(document: Document) -> dict:
    return {
        "source": document.source, "title": document.title, "kind": document.kind,
        "size": format_size(document.size), "chunks": document.chunks,
        "added_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(document.added_at)), "tags": document.tags,
    }


__all__ = ["KnowledgeStore", "KnowledgeError", "Document", "Hit", "chunk_stream", "fts_query", "default_db_path", "to_json"]
