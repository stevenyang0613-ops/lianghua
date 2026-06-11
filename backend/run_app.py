#!/usr/bin/env python3
"""PyInstaller entry point for LiangHua backend - 修正路径问题"""
import sys
import os

# PyInstaller temp path
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# SSL 证书修复：PyInstaller 打包后 Python 找不到系统证书
# 必须在所有网络库 import 之前设置
def _fix_ssl_certs():
    # 1. certifi 提供的证书（最可靠）
    try:
        import certifi
        cert_path = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', cert_path)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', cert_path)
        return
    except ImportError:
        pass
    # 2. macOS 系统证书
    macos_cert = '/etc/ssl/cert.pem'
    if os.path.isfile(macos_cert):
        os.environ.setdefault('SSL_CERT_FILE', macos_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', macos_cert)
        return
    # 3. Homebrew OpenSSL 证书
    brew_cert = '/opt/homebrew/etc/openssl@3/cert.pem'
    if os.path.isfile(brew_cert):
        os.environ.setdefault('SSL_CERT_FILE', brew_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', brew_cert)

_fix_ssl_certs()

# 关键：确保 app/ 目录在 Python path 中
sys.path.insert(0, BASE_DIR)

# 如果 app 不在 BASE_DIR 下，尝试上一级
app_path = os.path.join(BASE_DIR, 'app')
if not os.path.isdir(app_path):
    parent = os.path.dirname(BASE_DIR)
    if os.path.isdir(os.path.join(parent, 'app')):
        sys.path.insert(0, parent)

# Set db_path relative to user data dir instead of bundle
os.environ.setdefault('LH_DB_PATH', os.path.join(os.path.expanduser('~'), '.lianghua', 'market.db'))

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description='LiangHua Backend')
    parser.add_argument('--host', type=str, default=None, help='Bind address')
    parser.add_argument('--port', type=int, default=None, help='Bind port')
    return parser.parse_args()

if __name__ == '__main__':
    from app.config import settings

    # CLI 参数解析
    cli_args = parse_args()
    if cli_args.host:
        settings.host = cli_args.host
    if cli_args.port:
        settings.port = cli_args.port

    # Apple Silicon + PyInstaller fix: use spawn method for multiprocessing
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)
    multiprocessing.freeze_support()

    import uvicorn
    uvicorn.run(
        'app.main:app',
        host=settings.host,
        port=settings.port,
        log_level='info' if not settings.debug else 'debug',
        reload=False,
        workers=1,
    )
