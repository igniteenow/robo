"""Pure-Python binary format parsing for the reverse-engineering engine.

Parses ELF (32/64, either endianness), PE/PE32+ and Mach-O (thin and fat)
well enough to answer the structural questions an analyst asks first, with no
third-party dependencies: what is this, what architecture, where is the entry
point, what sections/segments exist, which symbols are defined, what does it
import/export, which strings does it contain and where do they live, and is
any region packed or encrypted (entropy). Everything here is read-only and
bounded; malformed inputs degrade to partial results rather than exceptions.

The dataclasses returned are plain enough to serialize as JSON and to be
enriched by a real backend (Ghidra / radare2) when one is available.
"""
from __future__ import annotations

import hashlib
import math
import re
import struct
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Section:
    name: str
    offset: int          # file offset
    size: int            # size in file (0 for NOBITS)
    vaddr: int           # virtual address (0 if not mapped)
    vsize: int           # size in memory
    flags: str           # human-readable flags, e.g. "r-x", "rw-", "code"
    kind: str = ""       # "code" | "data" | "rodata" | "bss" | "debug" | ""
    entropy: float = 0.0

    def contains_vaddr(self, addr: int) -> bool:
        return self.vaddr and self.vaddr <= addr < self.vaddr + max(self.vsize, self.size)

    def contains_offset(self, off: int) -> bool:
        return self.offset <= off < self.offset + self.size


@dataclass
class Symbol:
    name: str
    addr: int
    size: int = 0
    kind: str = ""       # "func" | "object" | "section" | "file" | ""
    bind: str = ""       # "global" | "local" | "weak" | ""
    section: str = ""
    defined: bool = True


@dataclass
class Import:
    name: str
    library: str = ""
    addr: int = 0        # IAT / GOT slot address when known


@dataclass
class Export:
    name: str
    addr: int
    ordinal: int = 0


@dataclass
class BinaryInfo:
    path: str
    size: int
    format: str = "unknown"       # "ELF" | "PE" | "Mach-O" | "raw" | ...
    subformat: str = ""           # "ELF64", "PE32+", "Mach-O 64-bit", "Fat"
    arch: str = "unknown"         # "x86", "x86_64", "arm", "aarch64", ...
    bits: int = 0
    endian: str = ""              # "little" | "big"
    os: str = ""                  # "linux" | "windows" | "macos" | ...
    file_type: str = ""           # "executable" | "shared library" | "object" | "core"
    entry: int = 0
    image_base: int = 0
    pie: Optional[bool] = None
    nx: Optional[bool] = None
    relro: Optional[str] = None   # "none" | "partial" | "full"
    canary: Optional[bool] = None
    stripped: Optional[bool] = None
    static: Optional[bool] = None
    interpreter: str = ""
    libraries: List[str] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    segments: List[Section] = field(default_factory=list)
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[Import] = field(default_factory=list)
    exports: List[Export] = field(default_factory=list)
    hashes: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Fat Mach-O members / other embedded slices: (arch, offset, size)
    members: List[Tuple[str, int, int]] = field(default_factory=list)
    # End of the last structure the parser knows about (section header table,
    # symbol tables, …) so the overlay heuristic doesn't flag metadata tails.
    parsed_end: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def section_for_vaddr(self, addr: int) -> Optional[Section]:
        for s in self.sections:
            if s.contains_vaddr(addr):
                return s
        return None

    def section_for_offset(self, off: int) -> Optional[Section]:
        for s in self.sections:
            if s.size and s.contains_offset(off):
                return s
        return None

    def _mapped_regions(self) -> List["Section"]:
        """Loadable regions in lookup order (LOAD segments first, then sections).

        A PIE's first LOAD segment legitimately starts at vaddr 0, so "mapped"
        is decided by size, never by a non-zero address.
        """
        segs = [s for s in self.segments if s.name in ("LOAD", "__TEXT", "__DATA", "__DATA_CONST", "__LINKEDIT")
                or (self.format == "PE") or s.name.startswith("__")]
        if not segs:
            segs = [s for s in self.segments if s.size]
        return segs + [s for s in self.sections if s.size]

    def vaddr_to_offset(self, addr: int) -> Optional[int]:
        for s in self._mapped_regions():
            span = max(s.vsize, s.size)
            if span and s.vaddr <= addr < s.vaddr + span:
                off = s.offset + (addr - s.vaddr)
                if off < s.offset + s.size:
                    return off
        return None

    def offset_to_vaddr(self, off: int) -> Optional[int]:
        for s in self._mapped_regions():
            if s.size and s.offset <= off < s.offset + s.size:
                return s.vaddr + (off - s.offset)
        return None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def shannon_entropy(data: bytes) -> float:
    """Shannon entropy in bits per byte (0.0 – 8.0)."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = float(len(data))
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return round(ent, 3)


def file_hashes(data: bytes) -> Dict[str, str]:
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _cstr(data: bytes, off: int, maxlen: int = 4096) -> str:
    if off < 0 or off >= len(data):
        return ""
    end = data.find(b"\x00", off, min(len(data), off + maxlen))
    if end < 0:
        end = min(len(data), off + maxlen)
    return data[off:end].decode("utf-8", "replace")


def hexdump(data: bytes, base: int = 0, width: int = 16) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:08x}  {hexpart:<{width * 3 - 1}}  |{asc}|")
    return "\n".join(lines)


_ASCII_RE = re.compile(rb"[\x20-\x7e]{%d,}")
_UTF16_RE = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}")


def extract_strings(data: bytes, min_len: int = 4, *, include_utf16: bool = True,
                    limit: int = 200_000) -> List[Tuple[int, str, str]]:
    """Return ``(offset, encoding, text)`` for printable runs in *data*."""
    out: List[Tuple[int, str, str]] = []
    ascii_spans: List[Tuple[int, int]] = []
    pat = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    for m in pat.finditer(data):
        out.append((m.start(), "ascii", m.group().decode("ascii")))
        ascii_spans.append((m.start(), m.end()))
        if len(out) >= limit:
            return out
    if include_utf16:
        pat16 = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
        span_idx = 0
        for m in pat16.finditer(data):
            start = m.start()
            # The NUL that terminates an ASCII string is also a valid UTF-16
            # high byte, so a UTF-16 run can start one char *inside* the ASCII
            # string before it ("whoami\0h\0i\0" → "ihi…"). Trim the overlap.
            while span_idx < len(ascii_spans) and ascii_spans[span_idx][1] <= start:
                span_idx += 1
            if span_idx < len(ascii_spans) and ascii_spans[span_idx][0] <= start < ascii_spans[span_idx][1]:
                shift = ascii_spans[span_idx][1] - start
                shift += shift % 2  # keep UTF-16 code-unit alignment
                start += shift
            raw = data[start:m.end()]
            if len(raw) < 2 * min_len:
                continue
            out.append((start, "utf-16le", raw.decode("utf-16le", "replace")))
            if len(out) >= limit:
                break
    out.sort(key=lambda t: t[0])
    return out


def classify_string(text: str) -> List[str]:
    """Cheap heuristics that flag strings an analyst usually wants first."""
    tags: List[str] = []
    t = text
    if re.search(r"https?://|ftp://|wss?://", t, re.I):
        tags.append("url")
    if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", t):
        tags.append("ip")
    if re.search(r"[A-Za-z]:\\|/(?:etc|usr|bin|tmp|var|home|proc|sys)/", t):
        tags.append("path")
    if re.search(r"\.(?:dll|so(?:\.\d+)*|dylib|exe|sys)\b", t, re.I):
        tags.append("library")
    if re.search(r"%[-+ #0]*\d*(?:\.\d+)?[hlLqjzt]*[diouxXeEfFgGaAcspn]", t):
        tags.append("format")
    if re.search(r"(?i)\b(?:passw(?:or)?d|secret|token|api[_-]?key|bearer|auth)\b", t):
        tags.append("credential")
    if re.search(r"(?i)\b(?:select|insert|update|delete)\b.*\b(?:from|into|set|where)\b", t):
        tags.append("sql")
    if re.search(r"(?i)^(?:[A-Za-z0-9+/]{4}){8,}(?:==|=)?$", t) and len(t) >= 32:
        tags.append("base64?")
    if re.search(r"(?i)\b(?:cmd\.exe|powershell|/bin/sh|/bin/bash|system\(|execve|popen)\b", t):
        tags.append("exec")
    if re.search(r"(?i)\b(?:HKEY_|SOFTWARE\\\\|CurrentVersion\\\\Run)", t):
        tags.append("registry")
    if re.search(r"(?i)\b(?:GetProcAddress|LoadLibrary|VirtualAlloc|CreateRemoteThread|WriteProcessMemory|NtUnmapViewOfSection|ptrace|mprotect|dlopen)\b", t):
        tags.append("api")
    return tags


# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------

_ELF_MACHINES = {
    0x03: ("x86", 32), 0x3E: ("x86_64", 64), 0x28: ("arm", 32), 0xB7: ("aarch64", 64),
    0x08: ("mips", 32), 0xF3: ("riscv", 0), 0x14: ("ppc", 32), 0x15: ("ppc64", 64),
    0x2B: ("sparc", 32), 0x2A: ("superh", 32), 0x16: ("s390", 64), 0x5E: ("xtensa", 32),
    0xF7: ("bpf", 64), 0x53: ("avr", 8), 0x66: ("hexagon", 32), 0x102: ("loongarch", 64),
}
_ELF_TYPES = {0: "none", 1: "object", 2: "executable", 3: "shared library", 4: "core"}
_SHT_NOBITS = 8
_SHT_SYMTAB = 2
_SHT_DYNSYM = 11
_SHT_STRTAB = 3
_SHT_DYNAMIC = 6
_PT_LOAD, _PT_DYNAMIC, _PT_INTERP, _PT_GNU_STACK, _PT_GNU_RELRO = 1, 2, 3, 0x6474E551, 0x6474E552
_DT_NEEDED, _DT_STRTAB, _DT_FLAGS, _DT_FLAGS_1, _DT_BIND_NOW, _DT_RPATH, _DT_RUNPATH = 1, 5, 30, 0x6FFFFFFB, 24, 15, 29
_DF_BIND_NOW = 0x8
_DF_1_PIE = 0x08000000
_DF_1_NOW = 0x1


def _elf_section_kind(name: str, sh_type: int, flags: int) -> str:
    if sh_type == _SHT_NOBITS:
        return "bss"
    if flags & 0x4:  # SHF_EXECINSTR
        return "code"
    if name.startswith(".debug") or name in (".comment", ".note", ".symtab", ".strtab"):
        return "debug"
    if flags & 0x1:  # SHF_WRITE
        return "data"
    if flags & 0x2:  # SHF_ALLOC
        return "rodata"
    return ""


def parse_elf(data: bytes, info: BinaryInfo) -> BinaryInfo:
    info.format = "ELF"
    if len(data) < 52:
        info.warnings.append("truncated ELF header")
        return info
    ei_class, ei_data = data[4], data[5]
    bits = 64 if ei_class == 2 else 32
    endian = "<" if ei_data == 1 else ">"
    info.bits = bits
    info.endian = "little" if ei_data == 1 else "big"
    info.subformat = f"ELF{bits}"
    osabi = data[7]
    info.os = {0: "linux/sysv", 3: "linux", 9: "freebsd", 12: "openbsd", 6: "solaris", 97: "arm"}.get(osabi, f"osabi={osabi}")
    if bits == 64:
        fmt = endian + "HHIQQQIHHHHHH"
        hdr = struct.unpack_from(fmt, data, 16)
    else:
        fmt = endian + "HHIIIIIHHHHHH"
        hdr = struct.unpack_from(fmt, data, 16)
    e_type, e_machine, _ver, e_entry, e_phoff, e_shoff, _flags, _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = hdr
    info.entry = e_entry
    info.file_type = _ELF_TYPES.get(e_type, f"type={e_type}")
    info.parsed_end = max(e_shoff + e_shnum * e_shentsize if e_shoff else 0,
                          e_phoff + e_phnum * e_phentsize if e_phoff else 0)
    arch, abits = _ELF_MACHINES.get(e_machine, (f"machine=0x{e_machine:x}", bits))
    info.arch = arch if arch != "riscv" else ("riscv64" if bits == 64 else "riscv32")

    # Program headers
    segments: List[Section] = []
    dyn_off = dyn_size = 0
    gnu_stack_exec = None
    has_relro = False
    for i in range(min(e_phnum, 512)):
        off = e_phoff + i * e_phentsize
        if off + e_phentsize > len(data):
            break
        if bits == 64:
            p_type, p_flags, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, _align = struct.unpack_from(endian + "IIQQQQQQ", data, off)
        else:
            p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, p_flags, _align = struct.unpack_from(endian + "IIIIIIII", data, off)
        flags = ("r" if p_flags & 4 else "-") + ("w" if p_flags & 2 else "-") + ("x" if p_flags & 1 else "-")
        name = {1: "LOAD", 2: "DYNAMIC", 3: "INTERP", 4: "NOTE", 6: "PHDR", 7: "TLS",
                0x6474E550: "GNU_EH_FRAME", 0x6474E551: "GNU_STACK", 0x6474E552: "GNU_RELRO",
                0x6474E553: "GNU_PROPERTY"}.get(p_type, f"PT_0x{p_type:x}")
        segments.append(Section(name, p_offset, p_filesz, p_vaddr, p_memsz, flags,
                                "code" if p_flags & 1 else "data"))
        if p_type == _PT_INTERP:
            info.interpreter = _cstr(data, p_offset)
        elif p_type == _PT_DYNAMIC:
            dyn_off, dyn_size = p_offset, p_filesz
        elif p_type == _PT_GNU_STACK:
            gnu_stack_exec = bool(p_flags & 1)
        elif p_type == _PT_GNU_RELRO:
            has_relro = True
    info.segments = segments
    loads = [s for s in segments if s.name == "LOAD"]
    if loads:
        info.image_base = min(s.vaddr for s in loads)
    if gnu_stack_exec is None:
        # No GNU_STACK header: the kernel defaults to an executable stack on
        # most architectures, so report NX as absent for loadable images.
        info.nx = False if loads else None
    else:
        info.nx = not gnu_stack_exec

    # Section headers
    sections: List[Section] = []
    raw_sections = []
    for i in range(min(e_shnum, 4096)):
        off = e_shoff + i * e_shentsize
        if e_shoff == 0 or off + e_shentsize > len(data):
            break
        if bits == 64:
            sh = struct.unpack_from(endian + "IIQQQQIIQQ", data, off)
        else:
            sh = struct.unpack_from(endian + "IIIIIIIIII", data, off)
        raw_sections.append(sh)
    shstr_off = 0
    if raw_sections and e_shstrndx < len(raw_sections):
        shstr_off = raw_sections[e_shstrndx][4]
    for sh in raw_sections:
        sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, _align, sh_entsize = sh
        name = _cstr(data, shstr_off + sh_name, 256) if shstr_off else f"sec{len(sections)}"
        flags = ("r" if sh_flags & 0x2 else "-") + ("w" if sh_flags & 0x1 else "-") + ("x" if sh_flags & 0x4 else "-")
        sec = Section(name, sh_offset, 0 if sh_type == _SHT_NOBITS else sh_size, sh_addr, sh_size, flags,
                      _elf_section_kind(name, sh_type, sh_flags))
        sections.append(sec)
    info.sections = sections

    # Symbols (symtab + dynsym)
    symbols: List[Symbol] = []
    seen = set()
    for idx, sh in enumerate(raw_sections):
        sh_type = sh[1]
        if sh_type not in (_SHT_SYMTAB, _SHT_DYNSYM):
            continue
        sh_offset, sh_size, sh_link, sh_entsize = sh[4], sh[5], sh[6], sh[9]
        if sh_link >= len(raw_sections):
            continue
        strtab_off = raw_sections[sh_link][4]
        entsize = sh_entsize or (24 if bits == 64 else 16)
        count = min(sh_size // entsize, 200_000)
        for j in range(count):
            off = sh_offset + j * entsize
            if off + entsize > len(data):
                break
            if bits == 64:
                st_name, st_info, _other, st_shndx, st_value, st_size = struct.unpack_from(endian + "IBBHQQ", data, off)
            else:
                st_name, st_value, st_size, st_info, _other, st_shndx = struct.unpack_from(endian + "IIIBBH", data, off)
            name = _cstr(data, strtab_off + st_name, 512)
            if not name:
                continue
            stype = st_info & 0xF
            sbind = st_info >> 4
            kind = {1: "object", 2: "func", 3: "section", 4: "file", 6: "tls", 10: "ifunc"}.get(stype, "")
            bind = {0: "local", 1: "global", 2: "weak"}.get(sbind, "")
            defined = st_shndx != 0
            secname = sections[st_shndx].name if 0 < st_shndx < len(sections) else ""
            key = (name, st_value, defined)
            if key in seen:
                continue
            seen.add(key)
            sym = Symbol(name, st_value, st_size, kind, bind, secname, defined)
            symbols.append(sym)
            if not defined and kind in ("func", "object", "", "ifunc") and sh_type == _SHT_DYNSYM:
                info.imports.append(Import(name))
            elif defined and sh_type == _SHT_DYNSYM and kind in ("func", "object", "ifunc") and bind in ("global", "weak"):
                info.exports.append(Export(name, st_value))
    info.symbols = symbols
    names = {s.name for s in symbols}
    info.canary = any(n in names for n in ("__stack_chk_fail", "__stack_chk_guard", "__intel_security_cookie"))
    info.stripped = not any(sh[1] == _SHT_SYMTAB for sh in raw_sections)

    # Dynamic section: NEEDED libs, RELRO / BIND_NOW, PIE
    flags = flags_1 = 0
    needed_offsets: List[int] = []
    if dyn_off and dyn_off < len(data):
        entsize = 16 if bits == 64 else 8
        strtab_vaddr = 0
        entries = []
        for j in range(min(dyn_size // entsize, 4096)):
            off = dyn_off + j * entsize
            if off + entsize > len(data):
                break
            if bits == 64:
                d_tag, d_val = struct.unpack_from(endian + "qQ", data, off)
            else:
                d_tag, d_val = struct.unpack_from(endian + "iI", data, off)
            if d_tag == 0:
                break
            entries.append((d_tag, d_val))
            if d_tag == _DT_STRTAB:
                strtab_vaddr = d_val
        strtab_off = info.vaddr_to_offset(strtab_vaddr) if strtab_vaddr else None
        for d_tag, d_val in entries:
            if d_tag == _DT_NEEDED and strtab_off is not None:
                info.libraries.append(_cstr(data, strtab_off + d_val, 256))
            elif d_tag == _DT_FLAGS:
                flags = d_val
            elif d_tag == _DT_FLAGS_1:
                flags_1 = d_val
            elif d_tag == _DT_BIND_NOW:
                flags |= _DF_BIND_NOW
            elif d_tag in (_DT_RPATH, _DT_RUNPATH) and strtab_off is not None:
                info.notes.append(f"{'RPATH' if d_tag == _DT_RPATH else 'RUNPATH'}: {_cstr(data, strtab_off + d_val, 512)}")
    bind_now = bool(flags & _DF_BIND_NOW) or bool(flags_1 & _DF_1_NOW)
    if has_relro:
        info.relro = "full" if bind_now else "partial"
    else:
        info.relro = "none"
    info.pie = (e_type == 3 and (bool(flags_1 & _DF_1_PIE) or info.entry != 0 and any(s.name == ".interp" for s in sections)))
    if e_type == 3 and not info.pie and info.interpreter:
        info.pie = True  # shared object with an interpreter == PIE executable
    if e_type == 3 and info.interpreter:
        info.file_type = "executable (PIE)"
    info.static = not info.libraries and not info.interpreter and e_type == 2
    return info


# ---------------------------------------------------------------------------
# PE
# ---------------------------------------------------------------------------

_PE_MACHINES = {0x14C: ("x86", 32), 0x8664: ("x86_64", 64), 0x1C0: ("arm", 32), 0x1C4: ("arm", 32),
                0xAA64: ("aarch64", 64), 0x200: ("ia64", 64), 0x5032: ("riscv32", 32), 0x5064: ("riscv64", 64)}


def _rva_to_off(sections: List[Section], rva: int) -> Optional[int]:
    for s in sections:
        if s.vaddr <= rva < s.vaddr + max(s.vsize, s.size):
            off = s.offset + (rva - s.vaddr)
            return off
    return None


def parse_pe(data: bytes, info: BinaryInfo) -> BinaryInfo:
    info.format = "PE"
    info.os = "windows"
    info.endian = "little"
    if len(data) < 0x40:
        info.warnings.append("truncated DOS header")
        return info
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        info.warnings.append("PE signature not found")
        return info
    coff = e_lfanew + 4
    machine, nsec, _ts, _symptr, _nsyms, opt_size, chars = struct.unpack_from("<HHIIIHH", data, coff)
    arch, bits = _PE_MACHINES.get(machine, (f"machine=0x{machine:x}", 32))
    info.arch, info.bits = arch, bits
    info.file_type = "shared library" if chars & 0x2000 else "executable"
    if chars & 0x1000:
        info.file_type = "system file"
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0] if opt + 2 <= len(data) else 0
    plus = magic == 0x20B
    info.subformat = "PE32+" if plus else "PE32"
    info.bits = 64 if plus else 32
    entry_rva = struct.unpack_from("<I", data, opt + 16)[0]
    if plus:
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        dll_chars = struct.unpack_from("<H", data, opt + 70)[0]
        num_dirs = struct.unpack_from("<I", data, opt + 108)[0]
        dirs_off = opt + 112
    else:
        image_base = struct.unpack_from("<I", data, opt + 28)[0]
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        dll_chars = struct.unpack_from("<H", data, opt + 70)[0]
        num_dirs = struct.unpack_from("<I", data, opt + 92)[0]
        dirs_off = opt + 96
    info.image_base = image_base
    info.entry = image_base + entry_rva
    info.notes.append("subsystem: " + {1: "native", 2: "GUI", 3: "console", 9: "CE GUI", 10: "EFI app", 16: "boot app"}.get(subsystem, str(subsystem)))
    info.pie = bool(dll_chars & 0x40)          # DYNAMIC_BASE (ASLR)
    info.nx = bool(dll_chars & 0x100)          # NX_COMPAT
    if dll_chars & 0x4000:
        info.notes.append("Control Flow Guard enabled")
    if dll_chars & 0x20:
        info.notes.append("High-entropy 64-bit ASLR")
    info.relro = None
    dirs = []
    for i in range(min(num_dirs, 16)):
        off = dirs_off + i * 8
        if off + 8 > len(data):
            break
        dirs.append(struct.unpack_from("<II", data, off))
    sec_off = opt + opt_size
    sections: List[Section] = []
    for i in range(min(nsec, 96)):
        off = sec_off + i * 40
        if off + 40 > len(data):
            break
        raw_name = data[off:off + 8].rstrip(b"\0")
        name = raw_name.decode("ascii", "replace")
        vsize, vaddr, rsize, roff, _r1, _r2, _r3, _r4, sflags = struct.unpack_from("<IIIIIIHHI", data, off + 8)
        flags = ("r" if sflags & 0x40000000 else "-") + ("w" if sflags & 0x80000000 else "-") + ("x" if sflags & 0x20000000 else "-")
        kind = "code" if sflags & 0x20 or sflags & 0x20000000 else "bss" if sflags & 0x80 else "data" if sflags & 0x80000000 else "rodata"
        sections.append(Section(name, roff, rsize, image_base + vaddr, vsize, flags, kind))
    info.sections = sections
    info.segments = list(sections)
    rel_sections = [Section(s.name, s.offset, s.size, s.vaddr - image_base, s.vsize, s.flags, s.kind) for s in sections]

    # Exports
    if len(dirs) > 0 and dirs[0][0]:
        exp_off = _rva_to_off(rel_sections, dirs[0][0])
        if exp_off is not None and exp_off + 40 <= len(data):
            _c, _t, _mj, _mn, name_rva, ord_base, n_funcs, n_names, funcs_rva, names_rva, ords_rva = struct.unpack_from("<IIHHIIIIIII", data, exp_off)
            name_off = _rva_to_off(rel_sections, name_rva)
            if name_off is not None:
                info.notes.append("export name: " + _cstr(data, name_off, 256))
            funcs_off = _rva_to_off(rel_sections, funcs_rva)
            names_off = _rva_to_off(rel_sections, names_rva)
            ords_off = _rva_to_off(rel_sections, ords_rva)
            names_by_idx: Dict[int, str] = {}
            if names_off is not None and ords_off is not None:
                for i in range(min(n_names, 65536)):
                    if names_off + i * 4 + 4 > len(data) or ords_off + i * 2 + 2 > len(data):
                        break
                    nrva = struct.unpack_from("<I", data, names_off + i * 4)[0]
                    oidx = struct.unpack_from("<H", data, ords_off + i * 2)[0]
                    noff = _rva_to_off(rel_sections, nrva)
                    if noff is not None:
                        names_by_idx[oidx] = _cstr(data, noff, 512)
            if funcs_off is not None:
                for i in range(min(n_funcs, 65536)):
                    if funcs_off + i * 4 + 4 > len(data):
                        break
                    frva = struct.unpack_from("<I", data, funcs_off + i * 4)[0]
                    if not frva:
                        continue
                    nm = names_by_idx.get(i, f"ordinal_{ord_base + i}")
                    info.exports.append(Export(nm, image_base + frva, ord_base + i))
    # Imports
    if len(dirs) > 1 and dirs[1][0]:
        imp_off = _rva_to_off(rel_sections, dirs[1][0])
        guard = 0
        while imp_off is not None and imp_off + 20 <= len(data) and guard < 512:
            guard += 1
            oft, _ts, _fc, name_rva, ft = struct.unpack_from("<IIIII", data, imp_off)
            if not (oft or name_rva or ft):
                break
            lib_off = _rva_to_off(rel_sections, name_rva)
            lib = _cstr(data, lib_off, 256) if lib_off is not None else "?"
            info.libraries.append(lib)
            thunk_rva = oft or ft
            thunk_off = _rva_to_off(rel_sections, thunk_rva)
            slot = ft
            j = 0
            while thunk_off is not None and j < 4096:
                width = 8 if plus else 4
                if thunk_off + width > len(data):
                    break
                val = struct.unpack_from("<Q" if plus else "<I", data, thunk_off)[0]
                if not val:
                    break
                if val & (1 << (63 if plus else 31)):
                    info.imports.append(Import(f"ordinal_{val & 0xFFFF}", lib, image_base + slot + j * width))
                else:
                    hn_off = _rva_to_off(rel_sections, val & 0x7FFFFFFF)
                    nm = _cstr(data, hn_off + 2, 512) if hn_off is not None else "?"
                    info.imports.append(Import(nm, lib, image_base + slot + j * width))
                thunk_off += width
                j += 1
            imp_off += 20
    # Debug/symbols: PE rarely carries symbols; treat missing COFF symtab as stripped
    info.stripped = _symptr == 0
    names = {i.name for i in info.imports}
    info.canary = "__security_check_cookie" in names or any(s.name == ".gfids" for s in sections) or None
    info.static = not info.libraries
    return info


# ---------------------------------------------------------------------------
# Mach-O
# ---------------------------------------------------------------------------

_MACHO_CPUS = {7: ("x86", 32), 0x01000007: ("x86_64", 64), 12: ("arm", 32), 0x0100000C: ("aarch64", 64),
               18: ("ppc", 32), 0x01000012: ("ppc64", 64)}
_MACHO_FILETYPES = {1: "object", 2: "executable", 3: "fixed VM library", 4: "core", 5: "preload", 6: "shared library",
                    7: "dynamic linker", 8: "bundle", 9: "dylib stub", 10: "dSYM", 11: "kext"}


def parse_macho(data: bytes, info: BinaryInfo, base: int = 0) -> BinaryInfo:
    info.format = "Mach-O"
    info.os = "macos"
    magic = struct.unpack_from("<I", data, base)[0]
    if magic == 0xCAFEBABE or magic == 0xBEBAFECA:
        # Fat binary: parse members; analyze the first as the representative
        nfat = struct.unpack_from(">I", data, base + 4)[0]
        info.subformat = "Fat"
        for i in range(min(nfat, 16)):
            off = base + 8 + i * 20
            if off + 20 > len(data):
                break
            cputype, _sub, m_off, m_size, _al = struct.unpack_from(">IIIII", data, off)
            arch = _MACHO_CPUS.get(cputype, (f"cpu=0x{cputype:x}", 0))[0]
            info.members.append((arch, m_off, m_size))
        if info.members:
            first = info.members[0]
            sub = BinaryInfo(info.path, info.size)
            parse_macho(data, sub, first[1])
            for f_ in ("arch", "bits", "endian", "file_type", "entry", "image_base", "sections", "segments",
                       "symbols", "imports", "exports", "libraries", "pie", "nx", "canary", "stripped"):
                setattr(info, f_, getattr(sub, f_))
            info.notes.append(f"fat binary with {len(info.members)} slices; showing {first[0]}")
        return info
    swapped = magic in (0xCEFAEDFE, 0xCFFAEDFE)
    endian = ">" if swapped else "<"
    is64 = magic in (0xFEEDFACF, 0xCFFAEDFE)
    info.bits = 64 if is64 else 32
    info.endian = "big" if swapped else "little"
    info.subformat = "Mach-O 64-bit" if is64 else "Mach-O 32-bit"
    cputype, _cpusub, filetype, ncmds, _sizeofcmds, flags = struct.unpack_from(endian + "IIIIII", data, base + 4)
    info.arch = _MACHO_CPUS.get(cputype, (f"cpu=0x{cputype:x}", 0))[0]
    info.file_type = _MACHO_FILETYPES.get(filetype, f"type={filetype}")
    info.pie = bool(flags & 0x200000)
    info.nx = True
    off = base + (32 if is64 else 28)
    sections: List[Section] = []
    segments: List[Section] = []
    symoff = nsyms = stroff = 0
    for _ in range(min(ncmds, 512)):
        if off + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from(endian + "II", data, off)
        if cmdsize < 8:
            break
        if cmd in (0x1, 0x19):  # LC_SEGMENT / LC_SEGMENT_64
            if cmd == 0x19:
                segname, vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, _sflags = struct.unpack_from(endian + "16sQQQQiiII", data, off + 8)
                shdr_off, shdr_size, fmt = off + 72, 80, endian + "16s16sQQIIIIIIII"
            else:
                segname, vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, _sflags = struct.unpack_from(endian + "16sIIIIiiII", data, off + 8)
                shdr_off, shdr_size, fmt = off + 56, 68, endian + "16s16sIIIIIIIII"
            sname = segname.rstrip(b"\0").decode("ascii", "replace")
            prot = ("r" if initprot & 1 else "-") + ("w" if initprot & 2 else "-") + ("x" if initprot & 4 else "-")
            segments.append(Section(sname, fileoff, filesize, vmaddr, vmsize, prot, "code" if initprot & 4 else "data"))
            if sname == "__TEXT":
                info.image_base = vmaddr
            for j in range(min(nsects, 256)):
                so = shdr_off + j * shdr_size
                if so + shdr_size > len(data):
                    break
                vals = struct.unpack_from(fmt, data, so)
                sectname = vals[0].rstrip(b"\0").decode("ascii", "replace")
                addr, size, s_off, _align, _reloff, _nreloc, s_flags = vals[2], vals[3], vals[4], vals[5], vals[6], vals[7], vals[8]
                is_code = bool(s_flags & 0x80000000) or bool(s_flags & 0x400)
                kind = "code" if is_code else ("bss" if (s_flags & 0xFF) == 1 else ("data" if "w" in prot else "rodata"))
                sections.append(Section(f"{sname}.{sectname}", s_off if (s_flags & 0xFF) != 1 else 0,
                                        0 if (s_flags & 0xFF) == 1 else size, addr, size, prot, kind))
        elif cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, _strsize = struct.unpack_from(endian + "IIII", data, off + 8)
        elif cmd in (0xC, 0x80000018, 0x80000023, 0xD):  # LC_LOAD_DYLIB / WEAK / REEXPORT / ID_DYLIB
            name_off = struct.unpack_from(endian + "I", data, off + 8)[0]
            lib = _cstr(data, off + name_off, 512)
            if cmd == 0xD:
                info.notes.append("install name: " + lib)
            else:
                info.libraries.append(lib)
        elif cmd == 0xE:  # LC_LOAD_DYLINKER
            name_off = struct.unpack_from(endian + "I", data, off + 8)[0]
            info.interpreter = _cstr(data, off + name_off, 256)
        elif cmd == 0x80000028:  # LC_MAIN
            entryoff = struct.unpack_from(endian + "Q", data, off + 8)[0]
            info.entry = (info.image_base or 0) + entryoff
        elif cmd == 0x5:  # LC_UNIXTHREAD
            # Thread state: entry point is in the register state; skip detailed decode.
            info.notes.append("LC_UNIXTHREAD entry (legacy)")
        elif cmd == 0x1D:  # LC_CODE_SIGNATURE
            info.notes.append("code signature present")
        elif cmd == 0x2A:  # LC_ENCRYPTION_INFO_64
            _o, _s, cryptid = struct.unpack_from(endian + "III", data, off + 8)
            if cryptid:
                info.notes.append("ENCRYPTED (FairPlay / cryptid=%d) — decrypt before analysis" % cryptid)
        off += cmdsize
    info.sections, info.segments = sections, segments
    # Symbols
    symbols: List[Symbol] = []
    if symoff and nsyms:
        entsize = 16 if is64 else 12
        for j in range(min(nsyms, 200_000)):
            so = base + symoff + j * entsize
            if so + entsize > len(data):
                break
            if is64:
                n_strx, n_type, n_sect, _desc, n_value = struct.unpack_from(endian + "IBBHQ", data, so)
            else:
                n_strx, n_type, n_sect, _desc, n_value = struct.unpack_from(endian + "IBBHI", data, so)
            name = _cstr(data, base + stroff + n_strx, 512)
            if not name:
                continue
            ext = bool(n_type & 0x01)
            ntype = n_type & 0x0E
            if n_type & 0xE0:  # debug symbol (stab)
                continue
            defined = ntype != 0x0
            secname = sections[n_sect - 1].name if 0 < n_sect <= len(sections) else ""
            kind = "func" if secname.endswith("__text") else ("object" if defined else "")
            symbols.append(Symbol(name, n_value, 0, kind, "global" if ext else "local", secname, defined))
            if not defined:
                info.imports.append(Import(name))
            elif ext and defined:
                info.exports.append(Export(name, n_value))
    info.symbols = symbols
    names = {s.name for s in symbols}
    info.canary = "___stack_chk_fail" in names or "___stack_chk_guard" in names
    info.stripped = not any(s.defined and s.bind == "local" and s.kind == "func" for s in symbols)
    return info


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_MAGIC_HINTS = [
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
    (b"\xfe\xed\xfa\xce", "Mach-O"), (b"\xfe\xed\xfa\xcf", "Mach-O"),
    (b"\xce\xfa\xed\xfe", "Mach-O"), (b"\xcf\xfa\xed\xfe", "Mach-O"),
    (b"\xca\xfe\xba\xbe", "Mach-O"),
    (b"PK\x03\x04", "zip (APK/JAR/docx?)"), (b"\x1f\x8b", "gzip"), (b"BZh", "bzip2"), (b"\xfd7zXZ\x00", "xz"),
    (b"7z\xbc\xaf\x27\x1c", "7z"), (b"Rar!", "rar"), (b"%PDF", "PDF"), (b"dex\n", "Android DEX"),
    (b"\xca\xfe\xba\xbe\x00\x00\x00", "Java class"), (b"UPX!", "UPX packed"), (b"#!", "script"),
    (b"\x00asm", "WebAssembly"), (b"!<arch>", "ar archive"), (b"\x89PNG", "PNG"), (b"\xff\xd8\xff", "JPEG"),
    (b"SQLite format 3", "SQLite"), (b"MSCF", "MS cabinet"), (b"\xd0\xcf\x11\xe0", "OLE compound (doc/xls/msi)"),
    (b"hsqs", "SquashFS"), (b"sqsh", "SquashFS"), (b"\x27\x05\x19\x56", "U-Boot uImage"),
    (b"ANDROID!", "Android boot image"), (b"\x1b\x4c\x75\x61", "Lua bytecode"),
]


def sniff_format(data: bytes) -> str:
    head = data[:16]
    for magic, name in _MAGIC_HINTS:
        if head.startswith(magic):
            return name
    if b"\x00" not in data[:4096] and data:
        return "text"
    return "raw"


def parse_binary(path: str, data: bytes) -> BinaryInfo:
    """Parse *data* (the whole file) into a :class:`BinaryInfo`."""
    info = BinaryInfo(path=path, size=len(data))
    info.hashes = file_hashes(data)
    kind = sniff_format(data)
    try:
        if kind == "ELF":
            parse_elf(data, info)
        elif kind == "PE":
            parse_pe(data, info)
        elif kind == "Mach-O":
            parse_macho(data, info)
        else:
            info.format = kind
            info.file_type = kind
            if b"UPX!" in data[:0x400] or b"UPX0" in data[:0x400]:
                info.notes.append("UPX signature present")
    except (struct.error, IndexError, ValueError) as exc:
        info.warnings.append(f"parser stopped early: {exc.__class__.__name__}: {exc}")
    # Packer / overlay heuristics that apply to every format
    for s in info.sections:
        if s.size and 0 <= s.offset < len(data):
            s.entropy = shannon_entropy(data[s.offset:s.offset + min(s.size, 4 * 1024 * 1024)])
    if info.sections:
        end = max((s.offset + s.size) for s in info.sections if s.size) if any(s.size for s in info.sections) else 0
        end = max(end, info.parsed_end)
        if end and len(data) - end > 4096:
            info.notes.append(f"overlay: {len(data) - end} bytes appended after the last section (offset 0x{end:x})")
        for s in info.sections:
            if s.name.lower().startswith(("upx", ".packed", ".themida", ".vmp", ".aspack", ".petite", ".mpress", ".enigma")):
                info.notes.append(f"packer section name: {s.name}")
        if any(s.entropy >= 7.2 and s.kind == "code" and s.size > 4096 for s in info.sections):
            info.notes.append("high-entropy code section(s): likely packed or encrypted")
    if data and b"UPX!" in data[:0x800] and "UPX signature present" not in info.notes:
        info.notes.append("UPX signature present")
    return info


def quick_arch_for_capstone(info: BinaryInfo) -> Optional[Tuple[str, str]]:
    """Map our arch label to (capstone arch constant name, mode constant name)."""
    a = info.arch
    little = info.endian != "big"
    if a == "x86_64":
        return ("CS_ARCH_X86", "CS_MODE_64")
    if a == "x86":
        return ("CS_ARCH_X86", "CS_MODE_32")
    if a == "aarch64":
        return ("CS_ARCH_ARM64", "CS_MODE_ARM")
    if a == "arm":
        return ("CS_ARCH_ARM", "CS_MODE_ARM")
    if a == "mips":
        return ("CS_ARCH_MIPS", "CS_MODE_MIPS32" + ("" if little else "|CS_MODE_BIG_ENDIAN"))
    if a in ("ppc", "ppc64"):
        return ("CS_ARCH_PPC", "CS_MODE_64" if a == "ppc64" else "CS_MODE_32")
    if a.startswith("riscv"):
        return ("CS_ARCH_RISCV", "CS_MODE_RISCV64" if a.endswith("64") else "CS_MODE_RISCV32")
    return None
