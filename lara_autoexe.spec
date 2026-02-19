# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for LARA Auto-Reply Bot
# Usage: pyinstaller lara_autoexe.spec

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect meshcore and its dependencies
meshcore_datas = collect_data_files('meshcore')
meshcore_hiddenimports = collect_submodules('meshcore')

a = Analysis(
    ['auto_reply_priv.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('lara_config.yaml', '.'),  # Include config file
    ] + meshcore_datas,
    hiddenimports=[
        'meshcore',
        'requests',
        'yaml',
        'asyncio',
        'serial',
        'urllib3',
    ] + meshcore_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
        'PyQt5',
        'PySide2',
    ],
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
    name='LARA_AutoReply',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress with UPX (ha telepítve van)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Console ablak megjelenítése (logok láthatóak)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add meg az .ico fájl útvonalát, ha van ikonod
    version_file=None,
)

# Ha szeretnéd directory módban (nem egyetlen .exe):
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='LARA_AutoReply'
# )
