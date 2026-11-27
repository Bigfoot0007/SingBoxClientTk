# -*- mode: python ; coding: utf-8 -*-

import json
import os
import sys

# Bundled sing-box engine (CI downloads it; absent in bare git checkouts).
_datas = [('core', 'core')]
_sb = os.path.join('assets', 'sing-box.exe' if sys.platform == 'win32' else 'sing-box')
if os.path.exists(_sb):
    _datas.append((_sb, 'assets'))

# Runtime window icon: the EXE `icon=` only covers Explorer's file icon —
# Tk shows its feather default in the taskbar/titlebar until app.py loads
# the .ico (PNG master = iconphoto fallback on other platforms).
for _ic in ('AppIcon.ico', 'AppIcon.png'):
    _p = os.path.join('assets', _ic)
    if os.path.exists(_p):
        _datas.append((_p, 'assets'))

# GEO rule-set bootstrap copies (offline first boot)
_rs = os.path.join('assets', 'rule-sets')
if os.path.isdir(_rs):
    for _f in sorted(os.listdir(_rs)):
        if _f.endswith('.srs'):
            _datas.append((os.path.join(_rs, _f), os.path.join('assets', 'rule-sets')))

# Version stamp: CI exports APP_VERSION from the git tag; the UI reads
# assets/version.json from the bundle at startup ("dev" from source).
_APP_VER = os.environ.get('APP_VERSION', 'dev')
_vj = os.path.join('assets', 'version.json')
with open(_vj, 'w', encoding='utf-8') as _f:
    json.dump({'version': _APP_VER}, _f)
_datas.append((_vj, 'assets'))

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
            'CFBundleShortVersionString': _APP_VER,
            'NSHighResolutionCapable': True,
        },
    )
