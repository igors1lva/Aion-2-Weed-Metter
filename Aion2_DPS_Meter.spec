# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['aion2_overlay.py'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.'), ('boss_data.py', '.'), ('data', 'data'), ('AION2-DPS-Meter/data', 'AION2-DPS-Meter/data'), ('AION2-DPS-Meter/assets/classicon', 'AION2-DPS-Meter/assets/classicon')],
    hiddenimports=['boss_data'],
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
    a.binaries,
    a.datas,
    [],
    name='Aion2_Weed_Metter',
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
    icon=['app_icon.ico'],
    uac_admin=True,
)
