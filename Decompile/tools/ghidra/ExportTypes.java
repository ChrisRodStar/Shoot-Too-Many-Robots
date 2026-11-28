// Writes every data type in the Ghidra program as a C header, so the exported
// function bodies have declarations for the structs, unions, enums and
// typedefs they mention.
//
//   include/<module>/smr_types.h
//
// Run headless:
//   analyzeHeadless <proj_dir> <proj_name> -process <program> -noanalysis -readOnly \
//     -scriptPath Decompile/tools/ghidra -postScript ExportTypes.java <outdir> <module>
//@category SMR

import java.io.*;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataTypeWriter;

public class ExportTypes extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File dir = new File(a[0], "include/" + a[1]);
        dir.mkdirs();
        File out = new File(dir, "smr_types.h");

        try (Writer w = new OutputStreamWriter(new FileOutputStream(out), "UTF-8")) {
            w.write("/* Data types recovered/inferred by Ghidra. Reference aid; not original source. */\n");
            w.write("#ifndef SMR_GAME_TYPES_H\n#define SMR_GAME_TYPES_H\n\n");
            DataTypeWriter writer = new DataTypeWriter(
                currentProgram.getDataTypeManager(), w, true);
            writer.write(monitor);
            w.write("\n/* Ghidra vocabulary not present in the generated body. */\n");
            w.write("#ifndef __thiscall\n#define __thiscall\n#endif\n");
            w.write("#ifndef __stdcall\n#define __stdcall\n#endif\n");
            w.write("#ifndef __cdecl\n#define __cdecl\n#endif\n");
            w.write("typedef long double float10;\ntypedef void code;\n");
            w.write("\n#endif /* SMR_GAME_TYPES_H */\n");
        }

        println("ExportTypes: wrote " + out + " (" + out.length() + " bytes)");
    }
}
