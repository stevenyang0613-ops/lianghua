#!/usr/bin/env python3
"""PyInstaller entry point for LiangHua backend"""
import sys
import os

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _fix_ssl_certs():
    try:
        import certifi
        cert_path = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', cert_path)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', cert_path)
        return
    except ImportError:
        pass
    macos_cert = '/etc/ssl/cert.pem'
    if os.path.isfile(macos_cert):
        os.environ.setdefault('SSL_CERT_FILE', macos_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', macos_cert)
        return
    brew_cert = '/opt/homebrew/etc/openssl@3/cert.pem'
    if os.path.isfile(brew_cert):
        os.environ.setdefault('SSL_CERT_FILE', brew_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', brew_cert)

_fix_ssl_certs()

sys.path.insert(0, BASE_DIR)

app_path = os.path.join(BASE_DIR, 'app')
if not os.path.isdir(app_path):
    parent = os.path.dirname(BASE_DIR)
    if os.path.isdir(os.path.join(parent, 'app')):
        sys.path.insert(0, parent)

os.environ.setdefault('LH_DB_PATH', os.path.join(os.path.expanduser('~'), '.lianghua', 'market.db'))

import socket
import multiprocessing
multiprocessing.set_start_method('spawn', force=True)
multiprocessing.freeze_support()

import argparse


def _check_port(host: str, port: int) -> bool:
    """检查端口是否可用，返回 True 表示可用"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return False  # 能连接说明端口已被占用
    except (ConnectionRefusedError, OSError):
        return True  # 端口可用

def parse_args():
    parser = argparse.ArgumentParser(description='LiangHua Backend')
    parser.add_argument('--host', type=str, default=None, help='Bind address')
    parser.add_argument('--port', type=int, default=None, help='Bind port')
    return parser.parse_args()

if __name__ == '__main__':
    print('[LH] Starting LiangHua backend...', flush=True)
    from app.config import settings
    print(f'[LH] Config loaded: {settings.host}:{settings.port}', flush=True)

    cli_args = parse_args()
    if cli_args.host:
        settings.host = cli_args.host
    if cli_args.port:
        settings.port = cli_args.port

    # 端口冲突检测：检查目标端口是否已被占用
    port_available = _check_port(settings.host, settings.port)
    if not port_available:
        print(f'[LH] ERROR: Port {settings.port} on {settings.host} is already in use!', flush=True)
        print(f'[LH] Please kill the existing process first:', flush=True)
        print(f'[LH]   lsof -ti:{settings.port} | xargs kill -9', flush=True)
        sys.exit(1)

    print('[LH] Importing app...', flush=True)
    from app.main import app
    print('[LH] App imported, starting uvicorn...', flush=True)
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level='info' if not settings.debug else 'debug',
    )
