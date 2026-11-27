import subprocess, tempfile
from pathlib import Path
from native_test_toolchain import COMPILER, PLATFORM_FLAGS, LIBRARIES

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    binary = Path(temp) / 'guest-page-reuse-test'
    subprocess.run([
        *COMPILER, *PLATFORM_FLAGS, '-O1', '-ffunction-sections', '-fdata-sections',
        '-I', str(root / 'macos'),
        '-I', str(root / 'upstream/recomp/host'),
        '-I', str(root / 'upstream/recomp'),
        str(root / 'tests/guest_page_reuse_test.c'),
        '-Wl,-dead_strip', *LIBRARIES, '-o', str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True, timeout=60)
