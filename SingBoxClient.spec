# -*- mode: python ; coding: utf-8 -*-

import os
import sys

# Bundled sing-box engine (CI downloads it; absent in bare git checkouts).
_datas = [('core', 'core')]
_sb = os.path.join('assets', 'sing-box.exe' if sys.platform == 'win32' else 'sing-box')
if os.path.exists(_sb):
    _datas.append((_sb, 'assets'))

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=['tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SingBoxClient',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/AppIcon.ico' if sys.platform == 'win32' else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    # UPX on a Go binary (sing-box) is a known corruption risk — never touch it.
    upx_exclude=['sing-box', 'sing-box.exe'],
    name='SingBoxClient',
)
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='SingBoxClient.app',
        icon='assets/AppIcon.icns',
        bundle_identifier='local.singboxclient.app',
        info_plist={
            'CFBundleDisplayName': 'SingBox Client',
            'CFBundleShortVersionString': '1.0',
            'NSHighResolutionCapable': True,
        },
    )
