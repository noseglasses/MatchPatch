# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH)))

from PyInstaller.config import CONF

from build_support import (
    PAYLOAD_ROOT,
    PROJECT_ROOT,
    PYINSTALLER_WORK_ROOT,
    asset_datas,
    prepare_installer_assets,
    prepare_pyinstaller_paths,
    stage_installer_assets,
    stage_docs,
    stage_runtime_files,
    write_build_info,
)

block_cipher = None
CONF["distpath"] = str(PAYLOAD_ROOT.parent)
CONF["workpath"] = str(PYINSTALLER_WORK_ROOT / "gui")
prepare_pyinstaller_paths(Path(CONF["workpath"]), Path(CONF["distpath"]))

a = Analysis(
    [str(PROJECT_ROOT / "src" / "matchpatch" / "app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=asset_datas(),
    hiddenimports=["mido.backends.rtmidi", "rtmidi"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MatchPatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(prepare_installer_assets() / "matchpatch.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MatchPatch",
)

stage_installer_assets()
stage_runtime_files()
stage_docs()
write_build_info()
