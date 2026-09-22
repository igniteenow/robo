# Tool Cheatsheet

Concrete commands for Phase 1 (recon) and Phase 2 (static analysis). All of these are
read-only against the target binary — none of them execute it. Check what's actually
installed before assuming a tool is available (`command -v <tool>`); fall back gracefully
rather than stalling the investigation on a missing optional tool.

## Format identification (always start here)

```bash
file target_binary
# ELF:
readelf -h target_binary        # header: arch, entry point, type
readelf -S target_binary        # section layout
readelf -d target_binary        # dynamic section (needed libs, RPATH, etc.)
# PE (via objdump on Linux, or a Windows box):
objdump -f target.exe
# Mach-O:
otool -hv target_binary         # macOS only
```

## Symbol / function inventory (build the coverage checklist from this)

```bash
nm target_binary                # symbol table (empty/sparse if stripped)
nm -D target_binary             # dynamic symbols (often survive stripping)
objdump -t target_binary        # symbol table, alternate view
readelf -sW target_binary       # wide symbol listing, easier to grep

# Stripped binary — recover a function address list without symbols:
objdump -d target_binary | grep -E '^[0-9a-f]+ <.*>:' | awk '{print $1}'
```

## Strings and constants (cheap, high-signal, do this early)

```bash
strings -n 8 target_binary          # printable strings, min length 8 to cut noise
strings -a target_binary | grep -i 'http\|password\|key\|error'   # targeted sweep
```

Cross-reference interesting strings back to the functions that reference them —
`objdump -d` output includes the address of string literals near their usage; a string like
`"invalid signature"` next to a comparison is a strong, citable lead (log it as
`string_xref` evidence), not yet a conclusion about what the comparison does.

## Full disassembly (the core of Phase 2 — read every function on the checklist)

```bash
objdump -d target_binary                      # AT&T syntax
objdump -d -M intel target_binary              # Intel syntax (often easier to read)
objdump -d --start-address=0x4011a0 --stop-address=0x401220 target_binary   # one function
```

If `radare2`/`r2` is installed, it gives a faster function-by-function workflow:

```bash
r2 -A target_binary          # -A: run full auto-analysis on load
# inside r2:
afl                          # list all analyzed functions (your coverage checklist source)
pdf @ sym.validate_token     # disassemble one function
axt @ sym.validate_token     # find cross-references TO this function
```

If Ghidra is installed, its headless analyzer produces a full decompilation pass without a
GUI — useful for a first structured pass over a large binary before hand-verifying the parts
that matter:

```bash
$GHIDRA_HOME/support/analyzeHeadless /tmp/ghidra_project ReProject \
  -import target_binary -postScript DecompileAll.java -deleteProject
```

(`DecompileAll.java` isn't bundled with Ghidra — either use an existing headless decompile
script from your toolchain, or drive `ghidra_bridge`/the Ghidra scripting API directly if one
isn't already set up. Don't assume it exists without checking.)

## Dynamic analysis (Phase 3 — only in an isolated environment, see SKILL.md guardrail #8)

```bash
gdb target_binary
(gdb) break *0x4011a0
(gdb) run <args>
(gdb) info registers
(gdb) x/20i $pc              # disassemble around current instruction pointer

strace -f -o trace.log ./target_binary <args>     # Linux syscalls
ltrace -f -o trace.log ./target_binary <args>      # Linux library calls
dtruss ./target_binary <args>                      # macOS (needs sudo)
```

## Windows targets from a non-Windows host

```bash
objdump -d -M intel target.exe        # works cross-platform if binutils supports PE
# For deeper PE-specific work (imports, resources, .NET), a Windows VM/container with
# a real disassembler (x64dbg, dnSpy for .NET, IDA/Ghidra) is usually more productive
# than fighting Linux toolchains against PE-specific structures.
```
