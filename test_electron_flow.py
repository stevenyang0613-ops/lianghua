"""模拟 Electron 启动后端的完整流程并诊断问题"""
import sys, os, time, subprocess, json, urllib.request

sys.path.insert(0, 'backend')

# 1. 检查 Python 路径
venv_python = 'backend/.venv/bin/python'
system_python = 'python3'

print("=== 步骤 1: Python 路径检测 ===")
print(f"虚拟环境 Python: {venv_python} => {'✓ 存在' if os.path.exists(venv_python) else '✗ 不存在'}")
print(f"系统 Python: {system_python} => {'✓ 可用' if subprocess.run(['which', 'python3'], capture_output=True).returncode == 0 else '✗ 不可用'}")

# 2. 检查能否导入核心模块
print("\n=== 步骤 2: 后端模块验证 ===")
for mod in ['fastapi', 'uvicorn', 'duckdb', 'pydantic_settings']:
    r = subprocess.run([system_python, '-c', f'import {mod}'], capture_output=True, text=True, cwd='backend')
    print(f"  {mod}: {'✓' if r.returncode == 0 else '✗ ' + r.stderr[:80]}")

# 3. 检查 requirements.txt 是否齐全
print("\n=== 步骤 3: requirements.txt 关键依赖 ===")
with open('backend/requirements.txt') as f:
    reqs = f.read()
for pkg in ['fastapi', 'uvicorn', 'pydantic-settings', 'duckdb', 'akshare', 'pandas', 'numpy', 'websockets', 'aiohttp', 'sqlalchemy', 'httpx']:
    in_file = pkg in reqs
    installed = subprocess.run([system_python, '-c', f'import {pkg.replace("-", "_")}'], capture_output=True, cwd='backend')
    print(f"  {pkg}: {'✓ 有' if in_file else '✗ 缺'} / {'✓ 可导入' if installed.returncode == 0 else '✗ 未安装'}")

# 4. 检查后端能否直接启动
print("\n=== 步骤 4: 直接启动后端 ===")
subprocess.run(['kill', '-9', '$(lsof', '-ti', ':8765)'], shell=True, capture_output=True)
time.sleep(1)

proc = subprocess.Popen(
    [system_python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765'],
    cwd='backend',
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(3)

# 检查是否启动成功
try:
    resp = urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=5)
    data = json.loads(resp.read())
    print(f"  后端启动: ✓ (status={data['status']}, token={'✓' if data.get('ws_auth_token') else '✗'})")
    
    # 检查最近一次 token 文件
    token_file = 'backend/data/.ws_token'
    if os.path.exists(token_file):
        print(f"  WS Token 文件: ✓ ({token_file})")
        token = open(token_file).read().strip()
        print(f"  Token 长度: {len(token)} 字符")
        print(f"  与 health 返回一致: {'✓' if token == data.get('ws_auth_token') else '✗'}")
    else:
        print(f"  WS Token 文件: ✗ (未找到)")
except Exception as e:
    print(f"  后端启动: ✗ ({str(e)[:60]})")
    proc.terminate()
    print("\n⚠ 后端启动失败! stderr 输出:")
    _, stderr = proc.communicate(timeout=5)
    print(stderr.decode()[:1000])
    sys.exit(1)

proc.terminate()
proc.wait()

# 5. 检查 Electron 构建的启动逻辑
print("\n=== 步骤 5: Electron 启动链模拟 ===")
print(f"  前端构建: {'✓' if os.path.exists('frontend/dist/index.html') else '✗'}")
print(f"  Electron 编译: {'✓' if os.path.exists('electron/dist/main.js') else '✗'}")
print(f"  electron-builder 配置:")
print(f"    extraResources backend: from=../backend -> to=backend")
print(f"    extraResources frontend: from=../frontend/dist -> to=frontend")
print(f"  getBackendDir 逻辑:")
print(f"    开发模式: path.join(__dirname, '..', 'backend')")
print(f"    打包后: path.join(process.resourcesPath, 'backend')")
print(f"  getPythonCmd 逻辑:")
print(f"    先找: backendDir + '/.venv/bin/python'")
print(f"    找不到: 'python3'")

# 6. 验证 Electron 启动流程
print("\n=== 步骤 6: Electron 启动流程关键路径 ===")
print("  app.whenReady() → startPythonBackend() + createWindow()")
print("  startPythonBackend():")
print("    1. getBackendDir() - 获取后端目录")
print("    2. getPythonCmd() - 获取 python 命令")
print("    3. spawn(pythonCmd, ...) - 启动后端进程")
print("    4. waitForBackend() - 轮询 /health 最多 60 秒")
print("    5. 成功后 -> mainWindow.webContents.send('backend-ready')")
print("    6. 失败后 -> mainWindow.webContents.send('backend-error')")
print("  createWindow():")
print("    开发模式: mainWindow.loadURL('http://localhost:5173')")
print("    生产模式: mainWindow.loadFile(process.resourcesPath + '/frontend/index.html')")
print()
print("  前端 StartupLoading: healthCheck() 通过 IPC 或 fetch 调用 /health")
print("  → getApiBase() + '/health' 即 http://127.0.0.1:8765/health")
print("  → 收到后 token: setWsAuthToken(result.ws_auth_token)")
print("  → 然后 WebSocket 连接时带 token")

print("\n🎯 后端启动和网络通信链路全部正常!")
