// Exports the program's data symbols, class namespaces and RTTI-ish labels.
//
// Output (relative to <outdir>):
//   build/<module>/data_symbols.csv   address,type,name,namespace,datatype
//   build/<module>/classes.txt        class / namespace symbols
//
// Run headless:
//   analyzeHeadless <proj_dir> <proj_name> -process <program> -noanalysis -readOnly \
//     -scriptPath Decompile/tools/ghidra -postScript ExportData.java <outdir> <module>
//@category SMR

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class ExportData extends GhidraScript {

    private static String csv(String s) {
        return '"' + s.replace("\"", "\"\"") + '"';
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File buildDir = new File(a[0], "build/" + a[1]);
        buildDir.mkdirs();

        Listing listing = currentProgram.getListing();
        SymbolTable st = currentProgram.getSymbolTable();
        int rows = 0, classes = 0;

        try (PrintWriter w = new PrintWriter(new OutputStreamWriter(
                 new FileOutputStream(new File(buildDir, "data_symbols.csv")),
                 StandardCharsets.UTF_8));
             PrintWriter c = new PrintWriter(new OutputStreamWriter(
                 new FileOutputStream(new File(buildDir, "classes.txt")),
                 StandardCharsets.UTF_8))) {

            w.println("address,type,name,namespace,datatype");
            c.println("# namespace\tkind\taddress");

            for (Data d : listing.getDefinedData(true)) {
                Symbol s = d.getPrimarySymbol();
                if (s == null) continue;
                DataType dt = d.getDataType();
                String ns = s.getParentNamespace() == null
                    ? "" : s.getParentNamespace().getName(true);
                w.printf("%s,%s,%s,%s,%s%n",
                    d.getAddress(), s.getSymbolType(), csv(s.getName()),
                    csv(ns), csv(dt == null ? "?" : dt.getName()));
                rows++;
            }

            for (Symbol s : st.getAllSymbols(true)) {
                SymbolType t = s.getSymbolType();
                if (t == SymbolType.CLASS || t == SymbolType.NAMESPACE
                    || t == SymbolType.LIBRARY) {
                    c.printf("%s\t%s\t%s%n", s.getName(true), t, s.getAddress());
                    classes++;
                }
            }
        }
        println("ExportData: " + rows + " data symbols, " + classes + " namespace symbols");
    }
}
