# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

akshare_data = collect_data_files('akshare')

a = Analysis(
    ['backend/run_app.py'],
    pathex=[],
    binaries=[],
    datas=[('backend/app', 'app')] + akshare_data,
    hiddenimports=[
        'uvicorn', 'fastapi', 'starlette', 'pydantic',
        'app.main', 'app.config',
        'app.api.router', 'app.api.auth', 'app.api.backtest',
        'app.api.strategies', 'app.api.health', 'app.api.metrics',
        'app.api.score', 'app.api.settings', 'app.api.signals',
        'app.api.trade', 'app.api.ws', 'app.api.community',
        'app.api.accounts', 'app.api.data_source',
        'app.engine.market', 'app.engine.storage', 'app.engine.scheduler',
        'app.engine.signals', 'app.engine.trade', 'app.engine.backtest',
        'app.adapters.akshare',
        'duckdb', 'pandas', 'numpy', 'akshare',
        'httpx', 'aiohttp', 'multidict', 'yarl',
        'jose', 'passlib', 'passlib.handlers.bcrypt',
        'bcrypt', 'cryptography',
        'slowapi', 'limits',
        'sqlalchemy', 'aiosqlite',
        'httptools', 'websockets', 'aiofiles',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'PIL', 'scipy', 'IPython', 'mypyc', 'tkinter', 'PyQt5', 'PySide2', 'PyQt6', 'PySide6'],
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
