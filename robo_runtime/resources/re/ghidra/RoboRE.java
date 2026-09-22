/* RoboRE.java — Ghidra headless post-script used by Robo's reverse_engineer tool.
 *
 * Invoked as:
 *   analyzeHeadless <project_dir> RoboRE -import <binary> -postScript RoboRE.java <outdir> export
 *   analyzeHeadless <project_dir> RoboRE -process <name> -noanalysis \
 *       -postScript RoboRE.java <outdir> decompile main 0x401000 ...
 *
 * Commands (first script arg after <outdir>):
 *   export                       write <outdir>/analysis.json (program, blocks, functions
 *                                with callers/callees, imports, exports, symbols, strings
 *                                with the code that references them)
 *   decompile <name|0xaddr>...   write <outdir>/decomp/ghidra_<addr>.c per function
 *   disasm <0xaddr> <count>      write <outdir>/disasm/ghidra_<addr>.txt
 *   xrefs <0xaddr>               write <outdir>/xrefs_<addr>.json (to + from)
 *   rename <0xaddr> <newname>    rename the function / label at addr (persisted in project)
 *   comment <0xaddr> @<file>     set a plate comment at addr from a text file (persisted)
 *   search <hexbytes> [max]      write <outdir>/search.json with matching addresses
 *
 * The script only reads the program and edits its Ghidra database; it never
 * executes the analyzed binary. Output is plain JSON via Gson, which ships
 * with Ghidra.
 *
 * @category Robo
 */

import java.io.File;
import java.io.FileWriter;
import java.io.Writer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.data.DataType;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolType;

public class RoboRE extends GhidraScript {

    private static final int MAX_STRINGS = 20000;
    private static final int MAX_STRING_REFS = 32;
    private static final int MAX_SYMBOLS = 50000;

    private File outDir;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args == null || args.length < 2) {
            printerr("RoboRE: usage: <outdir> <command> [args...]");
            return;
        }
        outDir = new File(args[0]);
        outDir.mkdirs();
        String cmd = args[1];
        try {
            if (cmd.equals("export")) {
                doExport();
            } else if (cmd.equals("decompile")) {
                for (int i = 2; i < args.length; i++) {
                    doDecompile(args[i]);
                }
            } else if (cmd.equals("disasm")) {
                doDisasm(args[2], args.length > 3 ? Integer.parseInt(args[3]) : 200);
            } else if (cmd.equals("xrefs")) {
                doXrefs(args[2]);
            } else if (cmd.equals("rename")) {
                doRename(args[2], args[3]);
            } else if (cmd.equals("comment")) {
                // Text arrives via a file (headless treats any arg starting
                // with '-' as an option, so free text can't ride on argv).
                String text;
                if (args.length > 3 && args[3].startsWith("@")) {
                    text = new String(java.nio.file.Files.readAllBytes(
                            new File(args[3].substring(1)).toPath()), "UTF-8");
                } else {
                    StringBuilder sb = new StringBuilder();
                    for (int i = 3; i < args.length; i++) {
                        if (sb.length() > 0) sb.append(' ');
                        sb.append(args[i]);
                    }
                    text = sb.toString();
                }
                doComment(args[2], text);
            } else if (cmd.equals("search")) {
                doSearch(args[2], args.length > 3 ? Integer.parseInt(args[3]) : 200);
            } else {
                printerr("RoboRE: unknown command " + cmd);
            }
            println("ROBO_RE_OK " + cmd);
        } catch (Exception e) {
            printerr("ROBO_RE_ERROR " + e);
            throw e;
        }
    }

    // ------------------------------------------------------------------ util

    private void writeJson(File f, Object obj) throws Exception {
        Gson gson = new GsonBuilder().disableHtmlEscaping().create();
        try (Writer w = new FileWriter(f)) {
            gson.toJson(obj, w);
        }
    }

    private String hex(Address a) {
        return "0x" + Long.toHexString(a.getOffset());
    }

    private Address resolve(String spec) {
        if (spec == null) return null;
        String s = spec.trim();
        if (s.startsWith("0x") || s.startsWith("0X")) {
            try {
                return toAddr(Long.parseUnsignedLong(s.substring(2), 16));
            } catch (Exception e) {
                // fall through to name lookup
            }
        }
        List<Function> fs = getGlobalFunctions(s);
        if (fs != null && !fs.isEmpty()) {
            return fs.get(0).getEntryPoint();
        }
        SymbolIterator it = currentProgram.getSymbolTable().getSymbols(s);
        while (it.hasNext()) {
            Symbol sym = it.next();
            return sym.getAddress();
        }
        // Bare hex without prefix
        try {
            return toAddr(Long.parseUnsignedLong(s, 16));
        } catch (Exception e) {
            return null;
        }
    }

    private String funcNameAt(Address a) {
        Function f = getFunctionContaining(a);
        return f == null ? "" : f.getName();
    }

    // ---------------------------------------------------------------- export

    private void doExport() throws Exception {
        JsonObject root = new JsonObject();
        JsonObject prog = new JsonObject();
        prog.addProperty("name", currentProgram.getName());
        prog.addProperty("language", currentProgram.getLanguageID().getIdAsString());
        prog.addProperty("compiler", currentProgram.getCompilerSpec().getCompilerSpecID().getIdAsString());
        prog.addProperty("image_base", hex(currentProgram.getImageBase()));
        prog.addProperty("executable_format", currentProgram.getExecutableFormat());
        prog.addProperty("executable_path", currentProgram.getExecutablePath());
        prog.addProperty("md5", currentProgram.getExecutableMD5());
        prog.addProperty("sha256", currentProgram.getExecutableSHA256());
        JsonArray entries = new JsonArray();
        AddressIterator eit = currentProgram.getSymbolTable().getExternalEntryPointIterator();
        while (eit.hasNext()) {
            entries.add(hex(eit.next()));
        }
        prog.add("entry_points", entries);
        root.add("program", prog);

        // Memory blocks
        JsonArray blocks = new JsonArray();
        Memory mem = currentProgram.getMemory();
        for (MemoryBlock b : mem.getBlocks()) {
            JsonObject o = new JsonObject();
            o.addProperty("name", b.getName());
            o.addProperty("start", hex(b.getStart()));
            o.addProperty("end", hex(b.getEnd()));
            o.addProperty("size", b.getSize());
            o.addProperty("perms", (b.isRead() ? "r" : "-") + (b.isWrite() ? "w" : "-") + (b.isExecute() ? "x" : "-"));
            o.addProperty("initialized", b.isInitialized());
            blocks.add(o);
        }
        root.add("blocks", blocks);

        // Functions
        JsonArray funcs = new JsonArray();
        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            if (monitor.isCancelled()) break;
            Function f = fit.next();
            JsonObject o = new JsonObject();
            o.addProperty("name", f.getName());
            o.addProperty("addr", hex(f.getEntryPoint()));
            o.addProperty("size", f.getBody().getNumAddresses());
            try {
                o.addProperty("signature", f.getSignature().getPrototypeString());
            } catch (Exception e) {
                o.addProperty("signature", f.getName() + "()");
            }
            o.addProperty("thunk", f.isThunk());
            o.addProperty("external", f.isExternal());
            o.addProperty("params", f.getParameterCount());
            o.addProperty("source", f.getSymbol().getSource().toString());
            JsonArray callers = new JsonArray();
            try {
                Set<Function> cs = f.getCallingFunctions(monitor);
                int n = 0;
                for (Function c : cs) {
                    callers.add(c.getName());
                    if (++n >= 64) break;
                }
            } catch (Exception e) { /* ignore */ }
            o.add("callers", callers);
            JsonArray callees = new JsonArray();
            try {
                Set<Function> cs = f.getCalledFunctions(monitor);
                int n = 0;
                for (Function c : cs) {
                    callees.add(c.getName());
                    if (++n >= 64) break;
                }
            } catch (Exception e) { /* ignore */ }
            o.add("callees", callees);
            funcs.add(o);
        }
        root.add("functions", funcs);

        // Imports (external symbols) + exports (entry points with names)
        JsonArray imports = new JsonArray();
        SymbolTable st = currentProgram.getSymbolTable();
        SymbolIterator ext = st.getExternalSymbols();
        while (ext.hasNext()) {
            Symbol s = ext.next();
            JsonObject o = new JsonObject();
            o.addProperty("name", s.getName());
            o.addProperty("library", s.getParentNamespace() == null ? "" : s.getParentNamespace().getName());
            o.addProperty("addr", hex(s.getAddress()));
            imports.add(o);
        }
        root.add("imports", imports);

        JsonArray exports = new JsonArray();
        AddressIterator eit2 = st.getExternalEntryPointIterator();
        while (eit2.hasNext()) {
            Address a = eit2.next();
            Symbol s = st.getPrimarySymbol(a);
            JsonObject o = new JsonObject();
            o.addProperty("name", s == null ? "" : s.getName());
            o.addProperty("addr", hex(a));
            exports.add(o);
        }
        root.add("exports", exports);

        // Symbols (labels / data) — bounded
        JsonArray symbols = new JsonArray();
        SymbolIterator sit = st.getAllSymbols(false);
        int scount = 0;
        while (sit.hasNext() && scount < MAX_SYMBOLS) {
            Symbol s = sit.next();
            SymbolType t = s.getSymbolType();
            if (t == SymbolType.FUNCTION || t == SymbolType.PARAMETER || t == SymbolType.LOCAL_VAR) continue;
            if (s.isDynamic()) continue;
            JsonObject o = new JsonObject();
            o.addProperty("name", s.getName());
            o.addProperty("addr", hex(s.getAddress()));
            o.addProperty("type", t.toString());
            o.addProperty("external", s.isExternal());
            symbols.add(o);
            scount++;
        }
        root.add("symbols", symbols);

        // Strings with referencing code
        JsonArray strings = new JsonArray();
        Listing listing = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();
        DataIterator dit = listing.getDefinedData(true);
        int count = 0;
        while (dit.hasNext() && count < MAX_STRINGS) {
            if (monitor.isCancelled()) break;
            Data d = dit.next();
            if (!d.hasStringValue()) continue;
            Object v = d.getValue();
            if (v == null) continue;
            String text = v.toString();
            if (text.length() < 3) continue;
            JsonObject o = new JsonObject();
            o.addProperty("addr", hex(d.getAddress()));
            DataType dt = d.getDataType();
            o.addProperty("type", dt == null ? "string" : dt.getName());
            o.addProperty("value", text.length() > 512 ? text.substring(0, 512) + "…" : text);
            JsonArray refs = new JsonArray();
            ReferenceIterator rit = rm.getReferencesTo(d.getAddress());
            int rn = 0;
            while (rit.hasNext() && rn < MAX_STRING_REFS) {
                Reference r = rit.next();
                JsonObject ro = new JsonObject();
                ro.addProperty("from", hex(r.getFromAddress()));
                ro.addProperty("func", funcNameAt(r.getFromAddress()));
                refs.add(ro);
                rn++;
            }
            o.add("refs", refs);
            strings.add(o);
            count++;
        }
        root.add("strings", strings);

        writeJson(new File(outDir, "analysis.json"), root);
        println("ROBO_RE_EXPORT functions=" + funcs.size() + " strings=" + strings.size());
    }

    // ------------------------------------------------------------- decompile

    private void doDecompile(String spec) throws Exception {
        Address a = resolve(spec);
        if (a == null) {
            printerr("ROBO_RE_NOTFOUND " + spec);
            return;
        }
        Function f = getFunctionContaining(a);
        if (f == null) {
            f = getFunctionAt(a);
        }
        if (f == null) {
            // Try to create one on demand so undefined code can still be decompiled.
            f = createFunction(a, null);
        }
        if (f == null) {
            printerr("ROBO_RE_NOTFOUND " + spec + " (no function)");
            return;
        }
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(true);
        decomp.setSimplificationStyle("decompile");
        try {
            if (!decomp.openProgram(currentProgram)) {
                printerr("ROBO_RE_ERROR decompiler failed to open program: " + decomp.getLastMessage());
                return;
            }
            DecompileResults res = decomp.decompileFunction(f, 120, monitor);
            StringBuilder sb = new StringBuilder();
            sb.append("// ").append(f.getName()).append(" @ ").append(hex(f.getEntryPoint()))
              .append("  size=").append(f.getBody().getNumAddresses()).append("\n");
            try {
                sb.append("// ").append(f.getSignature().getPrototypeString()).append("\n");
            } catch (Exception e) { /* ignore */ }
            String plate = currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT, f.getEntryPoint());
            if (plate != null && !plate.isEmpty()) {
                sb.append("// note: ").append(plate.replace("\n", "\n// ")).append("\n");
            }
            if (res == null || !res.decompileCompleted() || res.getDecompiledFunction() == null) {
                sb.append("// DECOMPILE FAILED: ").append(res == null ? "null" : res.getErrorMessage()).append("\n");
            } else {
                sb.append(res.getDecompiledFunction().getC());
            }
            File dir = new File(outDir, "decomp");
            dir.mkdirs();
            File out = new File(dir, "ghidra_" + Long.toHexString(f.getEntryPoint().getOffset()) + ".c");
            try (Writer w = new FileWriter(out)) {
                w.write(sb.toString());
            }
            println("ROBO_RE_DECOMP " + hex(f.getEntryPoint()) + " " + out.getAbsolutePath());
        } finally {
            decomp.dispose();
        }
    }

    // ---------------------------------------------------------------- disasm

    private void doDisasm(String spec, int count) throws Exception {
        Address a = resolve(spec);
        if (a == null) {
            printerr("ROBO_RE_NOTFOUND " + spec);
            return;
        }
        Function f = getFunctionContaining(a);
        Address start = a;
        long limit = count;
        if (f != null && f.getEntryPoint().equals(a)) {
            start = f.getEntryPoint();
            limit = Math.max(count, f.getBody().getNumAddresses()); // whole function
        }
        StringBuilder sb = new StringBuilder();
        if (f != null) {
            sb.append("; ").append(f.getName()).append(" @ ").append(hex(f.getEntryPoint())).append("\n");
        }
        Listing listing = currentProgram.getListing();
        InstructionIterator iit = listing.getInstructions(start, true);
        int n = 0;
        while (iit.hasNext() && n < limit) {
            Instruction ins = iit.next();
            if (f != null && f.getEntryPoint().equals(a) && !f.getBody().contains(ins.getAddress())) break;
            Symbol lbl = currentProgram.getSymbolTable().getPrimarySymbol(ins.getAddress());
            if (lbl != null && !lbl.isDynamic() && n > 0) {
                sb.append(lbl.getName()).append(":\n");
            }
            String cmt = listing.getComment(CodeUnit.EOL_COMMENT, ins.getAddress());
            StringBuilder bytes = new StringBuilder();
            try {
                for (byte b : ins.getBytes()) {
                    bytes.append(String.format("%02x", b & 0xff));
                }
            } catch (Exception e) { /* ignore */ }
            sb.append(String.format("%s  %-20s  %s", hex(ins.getAddress()), bytes.toString(), ins.toString()));
            // Annotate call targets / references
            for (Reference r : ins.getReferencesFrom()) {
                if (r.getReferenceType().isCall() || r.getReferenceType().isData()) {
                    Symbol s = currentProgram.getSymbolTable().getPrimarySymbol(r.getToAddress());
                    if (s != null) {
                        sb.append("   ; -> ").append(s.getName());
                    }
                }
            }
            if (cmt != null && !cmt.isEmpty()) {
                sb.append("   ; ").append(cmt);
            }
            sb.append("\n");
            n++;
        }
        File dir = new File(outDir, "disasm");
        dir.mkdirs();
        File out = new File(dir, "ghidra_" + Long.toHexString(start.getOffset()) + ".txt");
        try (Writer w = new FileWriter(out)) {
            w.write(sb.toString());
        }
        println("ROBO_RE_DISASM " + hex(start) + " " + out.getAbsolutePath());
    }

    // ----------------------------------------------------------------- xrefs

    private void doXrefs(String spec) throws Exception {
        Address a = resolve(spec);
        if (a == null) {
            printerr("ROBO_RE_NOTFOUND " + spec);
            return;
        }
        ReferenceManager rm = currentProgram.getReferenceManager();
        JsonObject root = new JsonObject();
        root.addProperty("addr", hex(a));
        Symbol s = currentProgram.getSymbolTable().getPrimarySymbol(a);
        root.addProperty("name", s == null ? funcNameAt(a) : s.getName());
        JsonArray to = new JsonArray();
        ReferenceIterator rit = rm.getReferencesTo(a);
        int n = 0;
        while (rit.hasNext() && n < 500) {
            Reference r = rit.next();
            JsonObject o = new JsonObject();
            o.addProperty("from", hex(r.getFromAddress()));
            o.addProperty("func", funcNameAt(r.getFromAddress()));
            o.addProperty("type", r.getReferenceType().getName());
            to.add(o);
            n++;
        }
        root.add("to", to);
        JsonArray from = new JsonArray();
        Function f = getFunctionContaining(a);
        if (f != null) {
            AddressIterator ai = f.getBody().getAddresses(true);
            int m = 0;
            Set<String> seen = new HashSet<>();
            while (ai.hasNext() && m < 500) {
                Address x = ai.next();
                for (Reference r : rm.getReferencesFrom(x)) {
                    String key = hex(r.getFromAddress()) + ">" + hex(r.getToAddress());
                    if (!seen.add(key)) continue;
                    JsonObject o = new JsonObject();
                    o.addProperty("from", hex(r.getFromAddress()));
                    o.addProperty("to", hex(r.getToAddress()));
                    Symbol ts = currentProgram.getSymbolTable().getPrimarySymbol(r.getToAddress());
                    o.addProperty("target", ts == null ? "" : ts.getName());
                    o.addProperty("type", r.getReferenceType().getName());
                    from.add(o);
                    m++;
                }
            }
        } else {
            for (Reference r : rm.getReferencesFrom(a)) {
                JsonObject o = new JsonObject();
                o.addProperty("from", hex(r.getFromAddress()));
                o.addProperty("to", hex(r.getToAddress()));
                Symbol ts = currentProgram.getSymbolTable().getPrimarySymbol(r.getToAddress());
                o.addProperty("target", ts == null ? "" : ts.getName());
                o.addProperty("type", r.getReferenceType().getName());
                from.add(o);
            }
        }
        root.add("from", from);
        writeJson(new File(outDir, "xrefs_" + Long.toHexString(a.getOffset()) + ".json"), root);
        println("ROBO_RE_XREFS " + hex(a) + " to=" + to.size() + " from=" + from.size());
    }

    // --------------------------------------------------------- rename/comment

    private void doRename(String spec, String newName) throws Exception {
        Address a = resolve(spec);
        if (a == null) {
            printerr("ROBO_RE_NOTFOUND " + spec);
            return;
        }
        Function f = getFunctionAt(a);
        if (f != null) {
            String old = f.getName();
            f.setName(newName, SourceType.USER_DEFINED);
            println("ROBO_RE_RENAMED " + hex(a) + " " + old + " -> " + newName);
            return;
        }
        Symbol s = currentProgram.getSymbolTable().getPrimarySymbol(a);
        if (s != null) {
            String old = s.getName();
            s.setName(newName, SourceType.USER_DEFINED);
            println("ROBO_RE_RENAMED " + hex(a) + " " + old + " -> " + newName);
            return;
        }
        createLabel(a, newName, true, SourceType.USER_DEFINED);
        println("ROBO_RE_RENAMED " + hex(a) + " (new label) -> " + newName);
    }

    private void doComment(String spec, String text) throws Exception {
        Address a = resolve(spec);
        if (a == null) {
            printerr("ROBO_RE_NOTFOUND " + spec);
            return;
        }
        Listing listing = currentProgram.getListing();
        Function f = getFunctionAt(a);
        int kind = f != null ? CodeUnit.PLATE_COMMENT : CodeUnit.EOL_COMMENT;
        String existing = listing.getComment(kind, a);
        String merged = (existing == null || existing.isEmpty()) ? text : existing + "\n" + text;
        listing.setComment(a, kind, merged);
        println("ROBO_RE_COMMENTED " + hex(a));
    }

    // ---------------------------------------------------------------- search

    private void doSearch(String hexBytes, int max) throws Exception {
        String clean = hexBytes.replaceAll("[^0-9a-fA-F?]", "");
        int n = clean.length() / 2;
        byte[] pattern = new byte[n];
        byte[] mask = new byte[n];
        for (int i = 0; i < n; i++) {
            String pair = clean.substring(i * 2, i * 2 + 2);
            if (pair.contains("?")) {
                pattern[i] = 0;
                mask[i] = 0;
            } else {
                pattern[i] = (byte) Integer.parseInt(pair, 16);
                mask[i] = (byte) 0xff;
            }
        }
        Memory mem = currentProgram.getMemory();
        JsonArray hits = new JsonArray();
        Address cur = mem.getMinAddress();
        int found = 0;
        while (cur != null && found < max) {
            Address hit = mem.findBytes(cur, pattern, mask, true, monitor);
            if (hit == null) break;
            JsonObject o = new JsonObject();
            o.addProperty("addr", hex(hit));
            o.addProperty("func", funcNameAt(hit));
            MemoryBlock b = mem.getBlock(hit);
            o.addProperty("block", b == null ? "" : b.getName());
            hits.add(o);
            found++;
            cur = hit.add(1);
        }
        JsonObject root = new JsonObject();
        root.addProperty("pattern", clean);
        root.add("hits", hits);
        writeJson(new File(outDir, "search.json"), root);
        println("ROBO_RE_SEARCH hits=" + hits.size());
    }
}
