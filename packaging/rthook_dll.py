"""PyInstaller runtime hook. Runs before Plan Marks imports PyMuPDF.

Windows looks for MuPDF's DLLs beside the program. The packaged copies live
in the pymupdf folder, so that folder has to be on the DLL search path first.
"""

import os
import sys

if getattr(sys, "frozen", False) and hasattr(os, "add_dll_directory"):
    base = getattr(sys, "_MEIPASS", "")
    for folder in (os.path.join(base, "pymupdf"), base):
        if folder and os.path.isdir(folder):
            os.add_dll_directory(folder)
