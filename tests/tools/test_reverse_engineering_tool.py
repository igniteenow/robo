"""Tests for the reverse-engineering engine and the ``reverse_engineer`` tool.

The engine's pure-Python layer (format parsers, strings, search, workspace,
annotations) is exercised directly; external backends (Ghidra, radare2,
binutils) are optional and only used when installed, so the ``python``
backend is forced wherever a deterministic answer is required.
"""
from __future__ import annotations

import os
import struct
import sys

import pytest


@pytest.fixture
def robo_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBO_HOME", str(tmp_path / "home"))
    return tmp_path


def _tiny_elf(tmp_path, *, with_strings=b"hello world\x00http://example.com/x\x00"):
    """Build a minimal but valid ELF64 with one LOAD segment and .text/.rodata."""
    code = b"\x55\x48\x89\xe5\xc3" + b"\x90" * 11  # push rbp; mov rbp,rsp; ret; nops
    text_off, rodata_off = 0x1000, 0x1100
    entry = 0x401000
    shstr = b"\x00.text\x00.rodata\x00.shstrtab\x00"
    shstr_off = 0x1200
    shoff = 0x1300
    e_ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr = e_ident + struct.pack("<HHIQQQIHHHHHH", 2, 0x3E, 1, entry, 64, shoff, 0, 64, 56, 1, 64, 4, 3)
    phdr = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, 0x1400, 0x1400, 0x1000)
    sh_null = b"\x00" * 64
    sh_text = struct.pack("<IIQQQQIIQQ", 1, 1, 0x6, entry, text_off, len(code), 0, 0, 16, 0)
    sh_rodata = struct.pack("<IIQQQQIIQQ", 7, 1, 0x2, 0x401100, rodata_off, len(with_strings), 0, 0, 1, 0)
    sh_shstr = struct.pack("<IIQQQQIIQQ", 15, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    buf = bytearray(shoff + 4 * 64)
    buf[: len(ehdr)] = ehdr
    buf[64: 64 + len(phdr)] = phdr
    buf[text_off: text_off + len(code)] = code
    buf[rodata_off: rodata_off + len(with_strings)] = with_strings
    buf[shstr_off: shstr_off + len(shstr)] = shstr
    buf[shoff: shoff + 4 * 64] = sh_null + sh_text + sh_rodata + sh_shstr
    p = tmp_path / "tiny.elf"
    p.write_bytes(bytes(buf))
    return p


def _tiny_pe(tmp_path):
    """Minimal PE32+ with one .text section and no imports."""
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)
    struct.pack_into("<I", opt, 16, 0x1000)          # entry rva
    struct.pack_into("<Q", opt, 24, 0x140000000)     # image base
    struct.pack_into("<H", opt, 68, 3)               # console subsystem
    struct.pack_into("<H", opt, 70, 0x140)           # DYNAMIC_BASE | NX_COMPAT
    struct.pack_into("<I", opt, 108, 16)             # number of data dirs
    sec = bytearray(40)
    sec[:5] = b".text"
    struct.pack_into("<IIIIIIHHI", sec, 8, 0x200, 0x1000, 0x200, 0x400, 0, 0, 0, 0, 0x60000020)
    body = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + bytes(sec)
    body = body.ljust(0x400, b"\0") + (b"\xc3" + b"Hello from PE\x00").ljust(0x200, b"\0")
    p = tmp_path / "tiny.exe"
    p.write_bytes(body)
    return p


def _tiny_macho(tmp_path):
    """Minimal 64-bit Mach-O with a __TEXT segment, a dylib and an entry."""
    seg_name = b"__TEXT".ljust(16, b"\0")
    sect = struct.pack("<16s16sQQIIIIIIII", b"__text".ljust(16, b"\0"), seg_name, 0x100000F00, 4, 0xF00, 4, 0, 0,
                       0x80000400, 0, 0, 0)
    seg = struct.pack("<II16sQQQQiiII", 0x19, 72 + 80, seg_name, 0x100000000, 0x1000, 0, 0x1000, 7, 5, 1, 0) + sect
    dylib_name = b"/usr/lib/libSystem.B.dylib\0"
    dylib = struct.pack("<IIIIII", 0xC, 24 + len(dylib_name) + (8 - len(dylib_name) % 8) % 8, 24, 0, 0, 0) + dylib_name
    dylib = dylib.ljust(24 + len(dylib_name) + (8 - len(dylib_name) % 8) % 8, b"\0")
    main = struct.pack("<IIQQ", 0x80000028, 24, 0xF00, 0)
    cmds = seg + dylib + main
    hdr = struct.pack("<IIIIIIII", 0xFEEDFACF, 0x01000007, 3, 2, 3, len(cmds), 0x200085, 0)
    body = (hdr + cmds).ljust(0x1000, b"\0")
    p = tmp_path / "tiny.macho"
    p.write_bytes(body)
    return p


# ---------------------------------------------------------------- parsers

def test_elf_parser_reads_headers_sections_and_entry(tmp_path):
    from tools.re_engine.formats import parse_binary

    p = _tiny_elf(tmp_path)
    info = parse_binary(str(p), p.read_bytes())
    assert info.format == "ELF" and info.subformat == "ELF64" and info.arch == "x86_64"
    assert info.entry == 0x401000
    names = [s.name for s in info.sections]
    assert ".text" in names and ".rodata" in names
    text = next(s for s in info.sections if s.name == ".text")
    assert text.kind == "code" and text.flags == "r-x"
    assert info.vaddr_to_offset(0x401100) == 0x1100
    assert info.offset_to_vaddr(0x1000) == 0x401000
    assert info.pie is False and info.nx is False  # no GNU_STACK header


def test_pe_parser_reads_optional_header_and_sections(tmp_path):
    from tools.re_engine.formats import parse_binary

    p = _tiny_pe(tmp_path)
    info = parse_binary(str(p), p.read_bytes())
    assert info.format == "PE" and info.subformat == "PE32+" and info.arch == "x86_64"
    assert info.entry == 0x140001000 and info.image_base == 0x140000000
    assert info.pie is True and info.nx is True
    assert [s.name for s in info.sections] == [".text"]
    assert info.sections[0].kind == "code"
    assert "subsystem: console" in info.notes


def test_macho_parser_reads_segments_dylibs_and_entry(tmp_path):
    from tools.re_engine.formats import parse_binary

    p = _tiny_macho(tmp_path)
    info = parse_binary(str(p), p.read_bytes())
    assert info.format == "Mach-O" and info.arch == "x86_64" and info.bits == 64
    assert info.libraries == ["/usr/lib/libSystem.B.dylib"]
    assert info.entry == 0x100000F00
    assert info.pie is True
    assert any(s.name == "__TEXT.__text" and s.kind == "code" for s in info.sections)


def test_system_binary_parses_when_available():
    from tools.re_engine.formats import parse_binary

    for cand in ("/bin/ls", "/bin/sh", "/usr/bin/env"):
        if os.path.isfile(cand):
            data = open(cand, "rb").read()
            info = parse_binary(cand, data)
            assert info.format in ("ELF", "Mach-O", "PE")
            assert info.hashes["sha256"]
            return
    pytest.skip("no system binary to parse")


def test_string_extraction_and_classification():
    from tools.re_engine.formats import classify_string, extract_strings

    data = b"\x00\x01junk\x00" + b"https://evil.example/c2\x00" + b"%s:%d\x00" + b"cmd.exe /c whoami\x00" + b"h\x00i\x00j\x00k\x00\x00"
    found = extract_strings(data, 4)
    texts = [t for _, _, t in found]
    assert "https://evil.example/c2" in texts and "cmd.exe /c whoami" in texts and "hijk" in texts
    assert "url" in classify_string("https://evil.example/c2")
    assert "format" in classify_string("%s:%d")
    assert "exec" in classify_string("cmd.exe /c whoami")
    assert "credential" in classify_string("api_key=abc")


def test_hex_and_text_search_with_wildcards(tmp_path):
    from tools.re_engine.backends import python_search
    from tools.re_engine.formats import parse_binary

    p = _tiny_elf(tmp_path)
    data = p.read_bytes()
    info = parse_binary(str(p), data)
    hits = python_search(data, info, "55 48 ?? e5 c3", 10)
    assert hits and hits[0]["addr"] == 0x401000 and hits[0]["section"] == ".text"
    hits = python_search(data, info, "hello world", 10)
    assert hits and hits[0]["addr"] == 0x401100


# --------------------------------------------------------------- workspace

def test_workspace_keyed_by_hash_and_persists_annotations(tmp_path, robo_home):
    from tools.re_engine.workspace import Workspace

    p = _tiny_elf(tmp_path)
    ws = Workspace(str(p))
    ws.rename(0x401000, "entry_fn", "sub_401000")
    ws.comment(0x401000, "does nothing")
    ws2 = Workspace(str(p))
    assert ws2.dir == ws.dir
    assert ws2.display_name(0x401000, "x") == "entry_fn"
    assert ws2.comments_for(0x401000) == ["does nothing"]
    assert ws2.resolve_renamed("entry_fn") == 0x401000
    # A different file (different bytes) lands in a different workspace
    q = _tiny_elf(tmp_path / "other" if (tmp_path / "other").mkdir() or True else tmp_path, with_strings=b"different\x00")
    assert Workspace(str(q)).dir != ws.dir


def test_parse_address_forms():
    from tools.re_engine.workspace import parse_address

    assert parse_address("0x401000") == 0x401000
    assert parse_address("401000") == 401000  # decimal digits stay decimal
    assert parse_address("4a1000") == 0x4A1000
    assert parse_address("") is None and parse_address(None) is None


# ------------------------------------------------------------------ engine

def test_engine_python_backend_actions(tmp_path, robo_home):
    from tools.re_engine.engine import run_action

    p = _tiny_elf(tmp_path)
    out = run_action(str(p), "overview", backend="python")
    assert "ELF ELF64" in out and "x86_64" in out and "entry:   0x401000" in out
    out = run_action(str(p), "sections", backend="python")
    assert ".text" in out and ".rodata" in out
    out = run_action(str(p), "strings", backend="python", query="tag:url")
    assert "http://example.com/x" in out and "[url]" in out
    out = run_action(str(p), "search", backend="python", query="hello")
    assert "0x401100" in out
    out = run_action(str(p), "read", backend="python", address="0x401100", length=16)
    assert "hello world" in out
    out = run_action(str(p), "hashes", backend="python")
    assert "sha256" in out
    out = run_action(str(p), "security", backend="python")
    assert "PIE / ASLR" in out
    out = run_action(str(p), "entropy", backend="python")
    assert "bits/byte" in out
    out = run_action(str(p), "workspace", backend="python")
    assert "workspace" in out


def test_engine_rename_comment_and_notes_roundtrip(tmp_path, robo_home):
    from tools.re_engine.engine import run_action

    p = _tiny_elf(tmp_path)
    out = run_action(str(p), "functions", backend="python")
    assert "_entry" in out  # entry point synthesized as a function
    out = run_action(str(p), "rename", backend="python", function="0x401000", new_name="start_here")
    assert "start_here" in out
    out = run_action(str(p), "comment", backend="python", function="start_here", text="entry stub")
    assert "entry stub" in out
    out = run_action(str(p), "note", backend="python", text="tiny sample; nothing to see")
    assert "saved" in out
    out = run_action(str(p), "notes", backend="python")
    assert "start_here" in out and "entry stub" in out and "tiny sample" in out
    out = run_action(str(p), "functions", backend="python", query="start_here")
    assert "start_here" in out


def test_engine_decompile_without_decompiler_falls_back_gracefully(tmp_path, robo_home):
    from tools.re_engine.engine import run_action

    p = _tiny_elf(tmp_path)
    out = run_action(str(p), "decompile", backend="python", function="0x401000")
    assert "NO DECOMPILER" in out or "backend error" in out or "no disassembler" in out
    assert "Ghidra" in out or "capstone" in out


def test_engine_rejects_unknown_action_and_missing_target(robo_home):
    from tools.re_engine.engine import run_action

    assert "unknown action" in run_action("/bin/ls", "rm_everything")
    assert "target not found" in run_action("/definitely/not/here", "overview")
    assert "capabilities" in run_action("", "capabilities")


@pytest.mark.skipif(not os.path.isfile("/bin/ls") or not any(
    os.access(os.path.join(d, "objdump"), os.X_OK) for d in os.environ.get("PATH", "").split(os.pathsep)),
    reason="needs /bin/ls and objdump")
def test_binutils_backend_recovers_functions_and_string_refs(robo_home):
    from tools.re_engine.engine import run_action

    out = run_action("/bin/ls", "functions", backend="binutils", limit=5, sort="callers")
    assert "backend=binutils" in out and "total" in out
    out = run_action("/bin/ls", "strings", backend="binutils", query="tagged", with_refs=True, limit=5)
    assert "←" in out  # string → referencing function
    out = run_action("/bin/ls", "xrefs", backend="binutils", function="0x0", limit=3)
    assert "references" in out or "not found" in out


# -------------------------------------------------------------------- tool

def test_tool_registers_with_new_action_schema(robo_home):
    sys.modules.pop("tools.reverse_engineering_tool", None)
    import tools.reverse_engineering_tool as mod
    from tools.registry import registry

    entry = registry.get_tool("reverse_engineer") if hasattr(registry, "get_tool") else registry._tools.get("reverse_engineer")
    assert entry is not None and entry.toolset == "reverse_engineering"
    props = mod.REVERSE_ENGINEER_SCHEMA["parameters"]["properties"]
    assert sorted(props["action"]["enum"]) == sorted(mod._VALID_ACTIONS)
    for needed in ("decompile", "xrefs", "callgraph", "rename", "comment", "search", "read", "capabilities"):
        assert needed in props["action"]["enum"]
    assert mod.REVERSE_ENGINEER_SCHEMA["parameters"]["required"] == ["target"]
    assert "Unknown action" in mod.reverse_engineer("/bin/ls", action="rm_everything")
    assert "No target" in mod.reverse_engineer("", action="overview")
    assert "capabilities" in mod.reverse_engineer("", action="capabilities")


def test_tool_handler_routes_kwargs(tmp_path, robo_home):
    sys.modules.pop("tools.reverse_engineering_tool", None)
    import tools.reverse_engineering_tool as mod

    p = _tiny_elf(tmp_path)
    out = mod._handle_reverse_engineer({"target": str(p), "action": "strings", "query": "hello", "backend": "python"},
                                       task_id="t", session_id="s")
    assert "hello world" in out
