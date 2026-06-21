"""LiangHua server launcher with crash recovery."""
import subprocess
import sys
import time
import os
from pathlib import Path

log_dir = Path.home() / ".lianghua" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

server_script = Path(__file__).parent / "app" / "main.py"
python = sys.executable

def start_server():
    log_file = log_dir / "server.log"
    err_file = log_dir / "server_err.log"
    
    # Start uvicorn directly
    cmd = [
        python, "-m", "uvicorn",
        "app.main:app",
        "--host", "127.0.0.1",
        "--port", "8765",
        "--workers", "1",
    ]
    
    with open(log_file, "a") as out, open(err_file, "a") as err:
        out.write(f"\n{'='*60}\nStarting server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        err.write(f"\n{'='*60}\nStarting server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).parent),
            stdout=out,
            stderr=err,
        )
    return proc

if __name__ == "__main__":
    max_restarts = 5
    restart_count = 0
    last_restart_time = 0
    
    print(f"Starting LiangHua server launcher (PID: {os.getpid()})")
    print(f"Log dir: {log_dir}")
    
    while restart_count < max_restarts:
        proc = start_server()
        pid = proc.pid
        print(f"Server started (PID: {pid}, restart #{restart_count})")
        
        # Wait for server to become healthy
        import urllib.request
        import json
        
        healthy = False
        for i in range(20):
            time.sleep(3)
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5)
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    healthy = True
                    print(f"Server healthy (attempt {i+1}): market_running={data.get('market_running')}")
                    break
            except Exception:
                pass
        
        if healthy:
            # Server is running - wait for it
            print("Server is up and healthy. Monitoring...")
            
            # Check health every 15 seconds
            while True:
                time.sleep(15)
                try:
                    resp = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5)
                    data = json.loads(resp.read())
                    if data.get("status") != "ok":
                        print(f"Server unhealthy: {data}")
                        break
                except Exception as e:
                    print(f"Server connection lost: {e}")
                    break
        else:
            print("Server never became healthy")
        
        # Check if server is still running
        ret = proc.poll()
        if ret is not None:
            print(f"Server exited with code {ret}")
            if time.time() - last_restart_time < 30:
                restart_count += 1
            else:
                restart_count = 1
            last_restart_time = time.time()
            print(f"Restarting ({restart_count}/{max_restarts})...")
            time.sleep(3)
        else:
            # Server is still running but not healthy
            print("Server running but not healthy - killing and restarting")
            proc.kill()
            proc.wait()
            restart_count += 1
            last_restart_time = time.time()
            time.sleep(3)
    
    print(f"Server crashed {max_restarts} times. Giving up.")
    sys.exit(1)
