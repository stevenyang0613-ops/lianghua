# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['backend/run_app.py'],
    pathex=[],
    binaries=[],
    datas=[('backend/app', 'app')],
    hiddenimports=[
        'uvicorn', 'fastapi', 'starlette', 'pydantic',
        'duckdb', 'pandas', 'httpx',
        'jose', 'passlib', 'passlib.handlers.bcrypt',
        'bcrypt', 'cryptography', 'slowapi',
        'sqlalchemy', 'aiosqlite', 'httptools',
        'websockets', 'aiofiles', 'aiohttp',
        'numpy', 'multidict', 'yarl',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'PIL', 'scipy', 'IPython', 'mypyc'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='lianghua-backend',
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[],
    runtime_tmpdir=None, console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)