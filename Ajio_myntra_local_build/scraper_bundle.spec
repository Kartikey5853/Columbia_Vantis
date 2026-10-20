# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

base_dir = os.path.abspath(SPECPATH)
scrapers_dir = os.path.join(base_dir, 'scrapers')

datas = [
    (scrapers_dir, 'scrapers'),
]
datas += collect_data_files('playwright')

hiddenimports = [
    'playwright',
    'playwright.async_api',
    'httpx',
    'dotenv',
    'supabase_sync',
]
hiddenimports += collect_submodules('playwright')

a = Analysis(
    [os.path.join(base_dir, 'run_local_scrapers.py')],
    pathex=[base_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'tkinter', 'PyQt5', 'PyQt6', 'torch'],
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
    name='Vantis_Local_Scraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Vantis_Local_Scraper',
)
