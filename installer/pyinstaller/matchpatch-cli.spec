# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH)))

from PyInstaller.config import CONF

from build_support import (
    PAYLOAD_ROOT,
    PROJECT_ROOT,
    PYINSTALLER_WORK_ROOT,
    write_build_info,
)

block_cipher = None
CONF["distpath"] = str(PAYLOAD_ROOT)
CONF["workpath"] = str(PYINSTALLER_WORK_ROOT / "cli")

a = Analysis(
    [str(PROJECT_ROOT / "src" / "matchpatch" / "cli.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="matchpatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

write_build_info()
