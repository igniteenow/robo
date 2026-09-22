"""Tests for the knowledge base. Copyright (c) 2026 Ignitee Now."""

import json
import zipfile

import pytest

from robo_cli import knowledge_store as ks
from robo_cli.knowledge_store import KnowledgeError, KnowledgeStore, chunk_stream, fts_query


@pytest.fixture
def store(tmp_path):
    s = KnowledgeStore(tmp_path / "kb" / "knowledge.db")
    yield s
    s.close()


class TestChunking:
    def test_covers_everything_with_overlap(self):
        text = " ".join(f"word{i}" for i in range(3000))
        chunks = list(chunk_stream([text], size=500, overlap=60))
        assert len(chunks) > 20
        assert all(len(c) <= 620 for c in chunks)
        joined = " ".join(chunks)
        for i in (0, 1499, 2999):
            assert f"word{i}" in joined
        # consecutive chunks share words (the overlap)
        assert set(chunks[0].split()) & set(chunks[1].split())

    def test_prefers_paragraph_and_sentence_boundaries(self):
        text = ("First paragraph sentence one. Sentence two.\n\n" * 40)
        chunks = list(chunk_stream([text], size=300, overlap=40))
        assert all(c.endswith((".", "two.")) or len(c) < 300 for c in chunks[:-1])

    def test_streams_across_block_boundaries(self):
        blocks = ["abc " * 100 for _ in range(50)]  # 20 KB in 50 blocks
        assert sum(len(c) for c in chunk_stream(blocks, size=400, overlap=50)) >= 20_000

    def test_empty_input(self):
        assert list(chunk_stream([])) == [] and list(chunk_stream(["   \n  "])) == []


class TestQuerySafety:
    @pytest.mark.parametrize("hostile", ['"; DROP TABLE documents; --', "NOT OR AND (", 'a" OR "b', "*", "col:value", "((("])
    def test_hostile_queries_never_raise(self, store, hostile):
        store.add_text("plain content here", source="s")
        assert isinstance(store.search(hostile), list)

    def test_natural_language_becomes_prefix_terms(self):
        assert fts_query("How do I deploy the gateway?") == '"How"* OR "do"* OR "deploy"* OR "the"* OR "gateway"*'
        assert fts_query("releasing") == '"releasing"* OR "releas"*'
        assert fts_query("") == "" and fts_query("? ! .") == ""
        assert fts_query("x " * 100).count(" OR ") <= 31


class TestIndexAndSearch:
    def test_text_round_trip(self, store):
        doc = store.add_text("The gateway listens on port 8642 by default. Change it with gateway.port.", source="notes", title="Notes")
        assert doc.chunks == 1 and doc.kind == "text"
        hits = store.search("which port does the gateway use")
        assert hits and hits[0].title == "Notes" and "8642" in hits[0].text

    def test_stemming_and_prefixes(self, store):
        store.add_text("Deployments happen nightly from the release branch.", source="a")
        assert len(store.search("deploy")) == 1  # prefix: deploy -> Deployments
        assert store.search("releasing")  # suffix stripping: releasing -> releas* -> release

    def test_unchanged_file_is_not_reindexed_and_changed_file_is(self, store, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("alpha beta gamma", encoding="utf-8")
        first = store.add_file(f)
        again = store.add_file(f)
        assert again.id == first.id
        f.write_text("delta epsilon", encoding="utf-8")
        third = store.add_file(f)
        assert third.chunks >= 1 and store.stats()["documents"] == 1
        assert store.search("alpha") == [] and store.search("epsilon")

    def test_large_file_streams_and_is_searchable(self, store, tmp_path):
        big = tmp_path / "big.log"
        with big.open("w", encoding="utf-8") as handle:
            for i in range(120_000):
                handle.write(f"2026-09-22 line {i} service=api status=ok latency={i % 97}ms\n")
            handle.write("2026-09-22 line FINAL service=billing status=FAILED reason=card_declined_XK9\n")
        assert big.stat().st_size > 6_000_000  # ~7 MB
        doc = store.add_file(big)
        assert doc.chunks > 4000 and doc.size == big.stat().st_size
        hits = store.search("card declined XK9")
        assert hits and "card_declined_XK9" in hits[0].text
        assert store.search("billing FAILED", source=str(big.resolve()))

    def test_search_limit_and_source_filter(self, store):
        for i in range(8):
            store.add_text(f"topic shared across documents number {i}", source=f"doc{i}")
        assert len(store.search("shared topic", limit=3)) == 3
        assert len(store.search("shared topic", limit=0)) == 5  # 0 means the default
        only = store.search("shared topic", source="doc5")
        assert len(only) == 1 and only[0].document == "doc5"

    def test_list_remove_stats(self, store):
        store.add_text("one", source="x", title="X", tags="t1")
        store.add_text("two", source="y")
        assert [d.source for d in store.documents()] == ["y", "x"]
        assert store.remove("x") is True and store.remove("x") is False
        assert store.stats()["documents"] == 1 and store.stats()["chunks"] == 1

    def test_recall_block_is_bounded_and_empty_when_irrelevant(self, store):
        store.add_text("The office wifi password is stored in the vault under IT.", source="wifi", title="IT notes")
        block = store.recall("wifi password")
        assert block.startswith("Relevant passages") and "[IT notes · part 1]" in block
        assert store.recall("zzzz qqqq") == ""
        assert len(store.recall("wifi", max_chars=80)) <= 80 or store.recall("wifi", max_chars=80) == ""

    def test_empty_document_is_rejected_cleanly(self, store, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("   \n\n", encoding="utf-8")
        with pytest.raises(KnowledgeError):
            store.add_file(f)
        assert store.stats()["documents"] == 0  # the failed insert was rolled back

    def test_images_and_unknown_binaries_are_refused_with_a_hint(self, store, tmp_path):
        img = tmp_path / "shot.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        with pytest.raises(KnowledgeError, match="vision"):
            store.add_file(img)
        blob = tmp_path / "thing.bin"
        blob.write_bytes(bytes(range(256)) * 32)
        with pytest.raises(KnowledgeError, match="unsupported"):
            store.add_file(blob)

    def test_missing_file(self, store, tmp_path):
        with pytest.raises(KnowledgeError, match="no such file"):
            store.add_file(tmp_path / "nope.txt")

    def test_html_is_stripped(self, store, tmp_path):
        f = tmp_path / "page.html"
        f.write_text("<html><body><h1>Refund &amp; returns</h1><p>Refunds take 5 days.</p></body></html>", encoding="utf-8")
        store.add_file(f)
        hit = store.search("refunds days")[0]
        assert "<p>" not in hit.text and "Refund & returns" in hit.text


class TestOfficeAndPdf:
    def test_pptx_without_any_library(self, store, tmp_path):
        f = tmp_path / "deck.pptx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("ppt/slides/slide2.xml", '<p:sld><a:t>Second slide: roadmap Q4</a:t></p:sld>')
            z.writestr("ppt/slides/slide1.xml", '<p:sld><a:t>Welcome to</a:t><a:t>Robo</a:t></p:sld>')
        doc = store.add_file(f)
        assert doc.kind == "pptx"
        assert "[slide 1]" in store.search("Welcome Robo")[0].text
        assert "[slide 2]" in store.search("roadmap")[0].text

    def test_docx(self, store, tmp_path):
        docx = pytest.importorskip("docx")
        f = tmp_path / "memo.docx"
        d = docx.Document()
        d.add_paragraph("Vendor contract renews on 1 March 2027.")
        t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Penalty", "2 percent"
        d.save(str(f))
        store.add_file(f)
        assert "2027" in store.search("when does the vendor contract renew")[0].text
        assert "Penalty | 2 percent" in store.search("penalty")[0].text

    def test_xlsx(self, store, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        f = tmp_path / "sales.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Q3"
        ws.append(["Region", "Revenue"])
        ws.append(["EMEA", 120500])
        wb.save(str(f))
        store.add_file(f)
        hit = store.search("EMEA revenue")[0]
        assert "[sheet Q3]" in hit.text and "120500" in hit.text

    def test_pdf(self, store, tmp_path):
        pypdf = pytest.importorskip("pypdf")
        reportlab = pytest.importorskip("reportlab")  # authors a PDF with real text
        from reportlab.pdfgen import canvas

        f = tmp_path / "doc.pdf"
        c = canvas.Canvas(str(f))
        c.drawString(72, 720, "Robo indexes PDF pages")
        c.showPage()
        c.drawString(72, 720, "Second page mentions the warranty period of 24 months")
        c.save()
        doc = store.add_file(f)
        assert doc.kind == "pdf"
        assert "[page 1]" in store.search("indexes PDF pages")[0].text
        assert "[page 2]" in store.search("warranty period")[0].text


@pytest.fixture(autouse=True)
def isolated_knowledge_base(tmp_path, monkeypatch):
    import tools.knowledge_tool as kt

    monkeypatch.setattr(ks, "default_db_path", lambda: tmp_path / "kb.db")
    kt._reset_store()
    yield
    kt._reset_store()


class TestTools:
    def test_add_search_list_remove_round_trip(self, tmp_path):
        import tools.knowledge_tool as kt

        f = tmp_path / "policy.md"
        f.write_text("Expenses over 500 euros need director approval.", encoding="utf-8")
        added = json.loads(kt.knowledge_add(path=str(f)))
        assert added["indexed"]["title"] == "policy.md"
        found = json.loads(kt.knowledge_search(query="who approves big expenses"))
        assert found["results"][0]["document"] == "policy.md" and "director" in found["results"][0]["text"]
        listed = json.loads(kt.knowledge_list())
        assert listed["stats"]["documents"] == 1
        assert json.loads(kt.knowledge_remove(source=str(f.resolve())))["removed"] is True
        assert json.loads(kt.knowledge_search(query="expenses"))["results"] == []

    def test_text_and_error_paths_return_json_never_raise(self):
        import tools.knowledge_tool as kt

        assert "error" in json.loads(kt.knowledge_add())
        assert "indexed" in json.loads(kt.knowledge_add(text="pasted note about the Q4 offsite in Lisbon", title="offsite"))
        assert "Lisbon" in json.loads(kt.knowledge_search(query="where is the offsite"))["results"][0]["text"]
        assert "error" in json.loads(kt.knowledge_search(query=""))
        assert "error" in json.loads(kt.knowledge_add(path="/definitely/not/here.txt"))
        assert "error" in json.loads(kt.knowledge_remove())

    def test_tools_are_registered_in_the_knowledge_toolset(self):
        import tools.knowledge_tool  # noqa: F401  (registers on import)
        from tools.registry import registry

        names = {"knowledge_add", "knowledge_search", "knowledge_list", "knowledge_remove"}
        assert names <= set(registry.get_toolset_tools("knowledge")) if hasattr(registry, "get_toolset_tools") else True
        from toolsets import TOOLSETS

        assert set(TOOLSETS["knowledge"]["tools"]) == names
