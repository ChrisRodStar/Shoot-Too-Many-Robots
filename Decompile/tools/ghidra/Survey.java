// Survey symbol quality and recoverable source-file tags.
//
// Run headless:
//   analyzeHeadless <proj_dir> <proj_name> -process <program> -noanalysis \
//       -scriptPath Decompile/tools/ghidra -postScript Survey.java [outdir]
//@category SMR

import java.io.*;
import java.util.*;
import java.util.regex.*;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class Survey extends GhidraScript {

    private static final Pattern SRC = Pattern.compile(
        "(?i)([a-z]:\\\\.*\\\\)?([A-Za-z0-9_]+)\\.(cpp|c|h|inl)$");
    private static final Pattern SRC_ANY = Pattern.compile(
        "(?i)([a-z]:\\\\[^\\s\"']*?\\\\([A-Za-z0-9_]+)\\.(cpp|c|h|inl))");

    @Override
    public void run() throws Exception {
        FunctionManager fm = currentProgram.getFunctionManager();
        int total = 0, funNames = 0, qualified = 0, demangled = 0, withComment = 0;
        long bytes = 0, namedBytes = 0;
        Map<String, Integer> byPrefix = new TreeMap<>();
        List<Function> examples = new ArrayList<>();

        for (Function f : fm.getFunctions(true)) {
            total++;
            long n = f.getBody().getNumAddresses();
            bytes += n;
            String name = f.getName();
            if (name.startsWith("FUN_")) funNames++;
            else { namedBytes += n; }
            if (name.contains("::")) qualified++;
            if (name.contains("(") && name.contains(")")) demangled++;
            String c = f.getComment();
            if (c != null && !c.isBlank()) withComment++;
            String ns = f.getParentNamespace() == null ? "" : f.getParentNamespace().getName(true);
            byPrefix.merge(ns.isEmpty() ? "(global)" : ns, 1, Integer::sum);
            if (!name.startsWith("FUN_") && !name.startsWith("thunk_")
                && examples.size() < 15 && n > 120 && !f.isThunk()) {
                examples.add(f);
            }
        }

        int sourceFiles = 0, tagged = 0;
        Map<String, Integer> fileHits = new TreeMap<>();
        Map<String, String> fullPaths = new TreeMap<>();
        Listing listing = currentProgram.getListing();
        ReferenceManager refs = currentProgram.getReferenceManager();
        Map<Function, Set<String>> funcFiles = new HashMap<>();
        for (Data d : listing.getDefinedData(true)) {
            if (monitor.isCancelled()) break;
            StringDataInstance s = StringDataInstance.getStringDataInstance(d);
            if (s == StringDataInstance.NULL_INSTANCE) continue;
            String v = s.getStringValue();
            if (v == null || v.isEmpty()) continue;
            Matcher m = SRC_ANY.matcher(v);
            while (m.find()) {
                String file = m.group(2) + "." + m.group(3).toLowerCase();
                fullPaths.putIfAbsent(file, m.group(1));
                fileHits.merge(file, 1, Integer::sum);
                sourceFiles++;
                for (Reference r : refs.getReferencesTo(d.getAddress())) {
                    Function f = fm.getFunctionContaining(r.getFromAddress());
                    if (f != null) funcFiles.computeIfAbsent(f, k -> new TreeSet<>()).add(file);
                }
            }
        }
        tagged = funcFiles.size();

        println("functions          = " + total);
        println("bytes (sum)        = " + bytes);
        println("FUN_ names         = " + funNames);
        println("non-FUN_ names     = " + (total - funNames) + " (" + namedBytes + " bytes)");
        println("names with ::      = " + qualified);
        println("names with ()      = " + demangled);
        println("functions w/comment= " + withComment);
        println("source strings     = " + sourceFiles + " in " + fileHits.size() + " distinct files");
        println("functions taggable = " + tagged);

        List<Map.Entry<String, Integer>> top = new ArrayList<>(fileHits.entrySet());
        top.sort((a, b) -> b.getValue() - a.getValue());
        println("\nTop source files by string count:");
        for (int i = 0; i < Math.min(30, top.size()); i++) {
            println(String.format("  %-52s %5d  %s", top.get(i).getKey(), top.get(i).getValue(),
                fullPaths.get(top.get(i).getKey())));
        }

        List<Map.Entry<String, Integer>> ns = new ArrayList<>(byPrefix.entrySet());
        ns.sort((a, b) -> b.getValue() - a.getValue());
        println("\nTop namespaces:");
        for (int i = 0; i < Math.min(30, ns.size()); i++) {
            println(String.format("  %-52s %5d", ns.get(i).getKey(), ns.get(i).getValue()));
        }

        println("\nSample named functions with bodies > 120 bytes:");
        for (Function f : examples) {
            println("  " + f.getEntryPoint() + "  " + f.getName() + "  ("
                + f.getBody().getNumAddresses() + " bytes)");
        }

        if (getScriptArgs().length > 0) {
            File out = new File(getScriptArgs()[0]);
            out.mkdirs();
            try (PrintWriter w = new PrintWriter(new File(out, "source-twofiles.csv"), "UTF-8")) {
                w.println("file,path,strings,functions");
                for (Map.Entry<String, String> e : fullPaths.entrySet()) {
                    int funcs = 0;
                    for (Set<String> s : funcFiles.values()) if (s.contains(e.getKey())) funcs++;
                    w.printf("%s,\"%s\",%d,%d%n", e.getKey(), e.getValue(),
                        fileHits.getOrDefault(e.getKey(), 0), funcs);
                }
            }
        }
    }
}
