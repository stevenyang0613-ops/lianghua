# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['backend/run_app.py'],
    pathex=[],
    binaries=[],
    datas=[('backend/app', 'app')],
    hiddenimports=['uvicorn', 'fastapi', 'duckdb', 'akshare', 'websockets', 'pydantic_settings', 'app.main', 'app.config', 'app.engine.market', 'app.engine.data_enrich', 'app.engine.storage', 'app.api.router', 'app.adapters.akshare', 'app.models.convertible'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'PIL', 'tkinter', 'PyQt5', 'scipy', 'sympy', 'notebook', 'jupyter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lianghua-backend',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lianghua-backend',
)
