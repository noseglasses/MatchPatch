# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH)))

from PyInstaller.config import CONF

from build_support import (
    MACOS_BUNDLE_IDENTIFIER,
    MACOS_PAYLOAD_ROOT,
    PROJECT_ROOT,
    PYINSTALLER_WORK_ROOT,
    asset_datas,
    macos_info_plist,
    payload_runtime_root,
    prepare_macos_icon,
    prepare_pyinstaller_paths,
    stage_docs,
    stage_runtime_files,
    write_build_info,
)

block_cipher = None
CONF["distpath"] = str(MACOS_PAYLOAD_ROOT.parent)
CONF["workpath"] = str(PYINSTALLER_WORK_ROOT / "macos-gui")
prepare_pyinstaller_paths(Path(CONF["workpath"]), Path(CONF["distpath"]))

macos_icon = prepare_macos_icon()

a = Analysis(
    [str(PROJECT_ROOT / "src" / "matchpatch" / "app.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=asset_datas(),
    hiddenimports=[
        "matchpatch.devices.helix.preset_handling",
        "matchpatch.devices.line6.podgo.preset_handling",
        "mido.backends.rtmidi",
        "rtmidi",
    ],
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
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MatchPatch",
)
app = BUNDLE(
    coll,
    name="MatchPatch.app",
    icon=str(macos_icon),
    bundle_identifier=MACOS_BUNDLE_IDENTIFIER,
    info_plist=macos_info_plist(),
)

payload_runtime_root(MACOS_PAYLOAD_ROOT).mkdir(parents=True, exist_ok=True)
stage_runtime_files(MACOS_PAYLOAD_ROOT)
stage_docs(MACOS_PAYLOAD_ROOT)
write_build_info(MACOS_PAYLOAD_ROOT)
