# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('core', 'core')],
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
    upx_exclude=[],
    name='SingBoxClient',
)
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
