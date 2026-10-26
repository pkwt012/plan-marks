# -*- mode: python ; coding: utf-8 -*-
"""Windows build. From the repository root:

    py -3 -m PyInstaller packaging/planmarks.spec
"""

import runpy
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent

runpy.run_path(str(SPEC_DIR / "make_icon.py"), run_name="__main__")


def _keep(item) -> bool:
    """Leave layout models and MuPDF dev headers out of the program."""
    src, dest = item
    text = f"{src} {dest}".replace("\\", "/")
    dropped = ("pymupdf/layout", "pymupdf/mupdf-devel", "pymupdf4llm", "/fitz/")
    return not any(part in text for part in dropped)


datas = [
    (str(ROOT / "elecplan" / "static"), "elecplan/static"),
    (str(ROOT / "symbols"), "symbols"),
]
binaries = []
hiddenimports = ["tkinter", "tkinter.messagebox"]
collected = collect_all("pymupdf")
datas += [item for item in collected[0] if _keep(item)]
binaries += [item for item in collected[1] if _keep(item)]
hiddenimports += [
    name
    for name in collected[2]
    if not name.startswith(("pymupdf.layout", "pymupdf4llm"))
]

# Versioned libraries such as libmupdf.so.28.5 are easy to miss.
try:
    import pymupdf
except ImportError:
    pymupdf = None
if pymupdf is not None:
    package_dir = Path(pymupdf.__file__).resolve().parent
    seen = {Path(src).resolve() for src, _dest in binaries}
    for path in package_dir.rglob("*"):
        if not path.is_file() or path.resolve() in seen:
            continue
        if "layout" in path.parts or "mupdf-devel" in path.parts:
            continue
        name = path.name.lower()
        if not (name.endswith((".dll", ".pyd", ".dylib", ".so")) or ".so." in name):
            continue
        rel_parent = path.parent.relative_to(package_dir)
        dest = "pymupdf" if rel_parent == Path(".") else f"pymupdf/{rel_parent.as_posix()}"
        binaries.append((str(path), dest))
        seen.add(path.resolve())

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "rthook_dll.py")],
    excludes=["pymupdf.layout", "pymupdf4llm"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlanMarks",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(SPEC_DIR / "planmarks.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PlanMarks",
)
