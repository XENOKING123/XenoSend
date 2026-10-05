# PyInstaller spec for the modified SendPP (language + theme support).
# Build:  venv312\Scripts\python -m PyInstaller build_exe\sendpp.spec --noconfirm --distpath build_exe\dist --workpath build_exe\work
import os
from kivymd import hooks_path as kivymd_hooks_path

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
TREE = os.path.join(ROOT, "modded")

# Every non-Python file under app/ keeps its relative location, as in the original build.
datas = []
for dirpath, dirnames, filenames in os.walk(os.path.join(TREE, "app")):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for name in filenames:
        if name.endswith((".py", ".pyc")):
            continue
        rel_dir = os.path.relpath(dirpath, TREE)
        datas.append((os.path.join(dirpath, name), rel_dir))

a = Analysis(
    [os.path.join(TREE, "main.py")],
    pathex=[TREE],
    binaries=[],
    datas=datas,
    hiddenimports=["arabic_reshaper"],
    hookspath=[kivymd_hooks_path],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sendpp",
    debug=False,
    strip=False,
    upx=False,
    console=False,           # GUI subsystem, like the original exe
    icon=os.path.join(SPECPATH, "sendpp.ico"),
)
