// Prints a quick health check for the analyzed program: function counts, how many
// functions carry a "Source: <file>" plate comment (added by TagSources.java),
// and a few sample decompilations.
//
// Run headless:
//   analyzeHeadless <proj_dir> <proj_name> -process <program> -noanalysis \
//       -scriptPath Decompile/tools/ghidra \
//       -postScript Inspect.java [sampleCount]
//@category SMR

import java.util.*;

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;

public class Inspect extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        int samples = args.length > 0 ? Integer.parseInt(args[0]) : 3;

        FunctionManager fm = currentProgram.getFunctionManager();
        int total = 0, tagged = 0, external = 0, thunks = 0;
        Set<String> files = new TreeSet<>();
        List<Function> sampleList = new ArrayList<>();

        for (Function f : fm.getFunctions(true)) {
            total++;
            if (f.isExternal()) { external++; continue; }
            if (f.isThunk()) thunks++;
            String c = f.getComment();
            if (c != null) {
                for (String line : c.split("\n")) {
                    if (line.startsWith("Source: ")) {
                        tagged++;
                        files.addAll(Arrays.asList(line.substring(8).split(",\\s*")));
                        break;
                    }
                }
            }
            if (sampleList.size() < samples) sampleList.add(f);
        }

        println("program       = " + currentProgram.getName());
        println("language      = " + currentProgram.getLanguageID());
        println("compiler      = " + currentProgram.getCompiler());
        println("image base    = " + currentProgram.getImageBase());
        println("functions     = " + total);
        println("  external    = " + external);
        println("  thunks      = " + thunks);
        println("  source-tagged = " + tagged + " across " + files.size() + " files");
        println("files         = " + files);

        DecompInterface dec = new DecompInterface();
        dec.setOptions(new DecompileOptions());
        dec.toggleCCode(true);
        dec.openProgram(currentProgram);
        for (Function f : sampleList) {
            DecompileResults r = dec.decompileFunction(f, 60, monitor);
            println("\n===== " + f.getName() + " @ " + f.getEntryPoint()
                + " (" + f.getBody().getNumAddresses() + " bytes) =====");
            if (r != null && r.decompileCompleted()) {
                String c = r.getDecompiledFunction().getC();
                println(c.length() > 3000 ? c.substring(0, 3000) + "\n... [truncated]" : c);
            } else {
                println("decompile failed: " + (r == null ? "null" : r.getErrorMessage()));
            }
        }
        dec.dispose();
    }
}
