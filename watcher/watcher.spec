# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for KJ BridgeDeck Watcher
#
# Build from the watcher/ directory:
#   pip install -r requirements.txt
#   pip install pyinstaller
#   pyinstaller watcher.spec

import os
from pathlib import Path

HERE = Path(os.path.abspath(SPECPATH))
REPO_ROOT = HERE.parent

a = Analysis(
    ['main.py'],
    pathex=[str(HERE), str(REPO_ROOT)],
    binaries=[],
    datas=[
        ('config.py', '.'),
        (str(REPO_ROOT / 'shared'), 'shared'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'win32timezone',
        'pkg_resources.py2_warn',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'anthropic',
        'supabase',
        'postgrest',
        'gotrue',
        'httpx',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='kj-bridgedeck-watcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/bridgedeck.ico',
    version='version_info.txt',
)
