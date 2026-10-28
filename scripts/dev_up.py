"""一键起停整套开发环境（数据库 → Python Agent → Java 网关 → 前端）。

为什么需要它：
    录演示视频时要起四个服务、还要等模型加载。手工敲四条命令，
    中间任何一步顺序错（比如网关先于数据库起来）都会白等一轮，
    而且录屏时手忙脚乱最容易出岔子。这个脚本把顺序和等待都固化下来。

用法：
    python scripts/dev_up.py              # 起全套，等全部就绪后打印地址表
    python scripts/dev_up.py --preheat    # 起完再跑一次真实问答，把链路和模型都热透
    python scripts/dev_up.py --check      # 只报告状态，不动任何东西
    python scripts/dev_up.py --hold       # 起完留在前台，Ctrl+C 一起停
    python scripts/dev_up.py --stop       # 停掉三个应用进程（数据库容器保留）

设计上的两个取舍：
    1. **日志写到 logs/ 而不是 /tmp**。Windows 下 /tmp 不在每台机器上，
       而录屏前排查问题第一件事就是看日志。
    2. **不自动拉起 Docker Desktop**。它需要 GUI 和 WSL，脚本里调不起来；
       数据库没起时直接说清楚要手动做什么，比卡住不动强。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
IS_WIN = os.name == "nt"

DB_PORT = 5433
AGENT_PORT = 8000
GATEWAY_PORT = 8080
WEB_PORT = 5173

DB_CONTAINER = "codeatlas-db"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()

# 这台机器上挂着一个失效的 HTTP_PROXY，urllib 会把它套到 localhost 上，
# 表现为健康检查莫名其妙 502。访问本机服务必须显式绕开。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------- 基础探测

def port_open(port: int, timeout: float = 1.0) -> bool:
    """IPv4 和 IPv6 都试一遍。

    为什么必须两个都试：Vite 默认只绑 IPv6（`::1`），用 127.0.0.1 探测永远失败。
    这个坑在分镜里写过（"localhost 能开、127.0.0.1 打不开"），脚本自己又踩了一次。
    """
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def http_get(url: str, timeout: float = 5.0,
             headers: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 —— 探测失败的原因不重要，重要的是"没通"
        return 0, str(e)


def wait_for(name: str, port: int, health_url: str | None = None,
             timeout: int = 180, quiet: bool = False,
             headers: dict[str, str] | None = None) -> bool:
    """等端口（或健康接口）就绪。超时返回 False，不抛异常。"""
    start = time.time()
    tick = 0
    while time.time() - start < timeout:
        if port_open(port):
            if health_url is None:
                return True
            code, _ = http_get(health_url, headers=headers)
            if code == 200:
                if not quiet:
                    print(f"  ✓ {name} 就绪（{time.time() - start:.1f}s）")
                return True
        time.sleep(1.5)
        tick += 1
        if tick % 8 == 0 and not quiet:
            print(f"    …等待 {name}（{int(time.time() - start)}s）")
    return False


# ---------------------------------------------------------------- 进程管理

def python_exe() -> str:
    cand = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
    return str(cand) if cand.exists() else sys.executable


def spawn(name: str, cmd: list[str], cwd: Path) -> subprocess.Popen:
    """后台起一个进程，stdout/stderr 落到 logs/<name>.log。"""
    LOG_DIR.mkdir(exist_ok=True)
    log = (LOG_DIR / f"{name}.log").open("w", encoding="utf-8", errors="replace")
    # 关掉窗口：Windows 下不隐藏会弹黑框，录屏时很难看
    kwargs: dict = {}
    if IS_WIN:
        # DETACHED_PROCESS：脱离当前控制台。少了它，父进程一退出子进程就跟着死
        # （第一次实测就是这样：脚本超时退出，Agent 也一起没了）。
        # CREATE_NEW_PROCESS_GROUP 让 Ctrl+C 不会同时打死三个服务。
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    env = {**os.environ, **{k: v for k, v in ENV.items() if k.isupper()}}
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=env, **kwargs)
    print(f"  → {name} 已启动（pid={p.pid}，日志 logs/{name}.log）")
    return p


def pids_on_port(port: int) -> list[int]:
    """按端口找 PID。Windows 用 netstat，其它用 lsof。"""
    pids: set[int] = set()
    try:
        if IS_WIN:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout
            for line in out.splitlines():
                # netstat 形如 `TCP 0.0.0.0:8080 0.0.0.0:0 LISTENING 1234`
                if "LISTENING" in line and f":{port} " in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True,
                                 text=True).stdout
            pids = {int(x) for x in out.split() if x.strip().isdigit()}
    except Exception:  # noqa: BLE001
        pass
    return sorted(pids)


def kill_port(port: int) -> None:
    for pid in pids_on_port(port):
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True)
            else:
                subprocess.run(["kill", "-9", str(pid)], capture_output=True)
            print(f"  ✓ 已停止端口 {port} 上的进程（pid={pid}）")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 停止 pid={pid} 失败：{e}")


# ---------------------------------------------------------------- 各步骤

def ensure_db(auto_start: bool) -> bool:
    if port_open(DB_PORT):
        print(f"  ✓ 数据库在线（{DB_PORT}）")
        return True

    print(f"  ✗ 数据库未启动（{DB_PORT}）")
    if not shutil.which("docker"):
        print("    Docker 命令不可用。请先安装/启动 Docker Desktop。")
        return False

    probe = subprocess.run(["docker", "ps"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if probe.returncode != 0:
        print("    Docker 守护进程没在跑。**请手动启动 Docker Desktop**，")
        print("    等托盘图标变绿后再执行本脚本（脚本不代劳：它需要 GUI 和 WSL）。")
        return False

    if not auto_start:
        print("    容器存在但未启动，加 --start-db 可自动 docker start。")
        return False

    print(f"    docker start {DB_CONTAINER} …")
    r = subprocess.run(["docker", "start", DB_CONTAINER], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"    ✗ 启动失败：{(r.stderr or r.stdout).strip()[:200]}")
        return False
    return wait_for("数据库", DB_PORT, timeout=90)


def start_agent() -> None:
    if port_open(AGENT_PORT):
        print(f"  · Agent 已在运行（{AGENT_PORT}），跳过")
        return
    spawn("agent", [python_exe(), "-m", "uvicorn", "app.main:app",
                    "--host", "127.0.0.1", "--port", str(AGENT_PORT)],
          ROOT / "services" / "python-agent")


def start_gateway() -> None:
    if port_open(GATEWAY_PORT):
        print(f"  · 网关已在运行（{GATEWAY_PORT}），跳过")
        return
    jar = ROOT / "services" / "java-gateway" / "target" / "java-gateway-0.1.0.jar"
    if not jar.exists():
        print(f"  ✗ 找不到 {jar.relative_to(ROOT)}，先执行：")
        print("    cd services/java-gateway && mvn -DskipTests package")
        return
    spawn("gateway", ["java", "-jar", str(jar), f"--server.port={GATEWAY_PORT}"],
          ROOT / "services" / "java-gateway")


def start_web() -> None:
    if port_open(WEB_PORT):
        print(f"  · 前端已在运行（{WEB_PORT}），跳过")
        return
    vite = ROOT / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.exists():
        print("  ✗ 前端依赖没装，先执行：cd web && npm install")
        return
    node = shutil.which("node") or "node"
    # 必须用 localhost 访问：Vite 只监听 IPv6，127.0.0.1 连不上
    spawn("web", [node, str(vite), "--port", str(WEB_PORT)], ROOT / "web")


def preheat() -> None:
    """跑一次真实问答，把检索缓存、模型连接都热起来。

    Agent 启动时已经加载了本地模型，但第一次真实请求还要建 HTTP 连接、
    加载 BM25 索引，冷跑一次 20~30 秒。录屏前先跑一遍，正片才稳定。
    """
    print("\n预热：跑一次真实问答（约 20~40s，失败不影响启动）…")
    body = json.dumps({"question": "什么是回表", "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{GATEWAY_PORT}/api/chat/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.time()
    try:
        with _OPENER.open(req, timeout=180) as r:
            first = None
            while True:
                chunk = r.read(256)
                if not chunk:
                    break
                if first is None:
                    first = time.time() - start
            total = time.time() - start
        print(f"  ✓ 预热完成：首包 {first:.1f}s，全程 {total:.1f}s")
    except Exception as e:  # noqa: BLE001
        print(f"  ! 预热未完成（{e}）——服务已起，但首次提问可能偏慢")


def status() -> None:
    print("服务状态：")
    rows = [
        ("数据库", DB_PORT, None),
        ("Agent", AGENT_PORT, f"http://127.0.0.1:{AGENT_PORT}/internal/health"),
        ("网关", GATEWAY_PORT, f"http://localhost:{GATEWAY_PORT}/api/health"),
        ("前端", WEB_PORT, f"http://localhost:{WEB_PORT}/"),
    ]
    for name, port, health in rows:
        up = port_open(port)
        mark = "✓" if up else "✗"
        extra = ""
        if up and health:
            hdrs = {"X-Internal-Token": ENV.get("INTERNAL_TOKEN", "dev_internal_token")}
            code, _ = http_get(health, headers=hdrs)
            extra = f"  健康接口 {code}"
            if code != 200:
                mark = "!"
        print(f"  {mark} {name:<6} :{port}{extra}")
    print(f"\n  打开 http://localhost:{WEB_PORT}/  （localhost，不是 127.0.0.1）")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="一键起停 CodeAtlas 开发环境")
    ap.add_argument("--check", action="store_true", help="只报告状态")
    ap.add_argument("--stop", action="store_true", help="停掉三个应用进程")
    ap.add_argument("--preheat", action="store_true", help="起完跑一次真实问答")
    ap.add_argument("--start-db", action="store_true", help="数据库未起时尝试 docker start")
    ap.add_argument("--hold", action="store_true",
                    help="起完不退出，留在前台守着（Ctrl+C 停掉三个服务）")
    args = ap.parse_args()

    if args.check:
        status()
        return 0

    if args.stop:
        print("停止应用进程（数据库容器保留，下次起得更快）：")
        for port in (WEB_PORT, GATEWAY_PORT, AGENT_PORT):
            kill_port(port)
        time.sleep(1)
        status()
        return 0

    print("启动 CodeAtlas：\n")

    print("[1/4] 数据库")
    if not ensure_db(args.start_db):
        print("\n数据库没起来，后面三步没有意义，先解决它。")
        return 1

    print("\n[2/4] Python Agent（含模型预热，约 25s）")
    start_agent()
    token = ENV.get("INTERNAL_TOKEN", "dev_internal_token")
    if not wait_for("Agent", AGENT_PORT,
                    f"http://127.0.0.1:{AGENT_PORT}/internal/health",
                    timeout=180, headers={"X-Internal-Token": token}):
        print("  ✗ Agent 没起来，看 logs/agent.log")
        return 1

    print("\n[3/4] Java 网关")
    start_gateway()
    if not wait_for("网关", GATEWAY_PORT,
                    f"http://localhost:{GATEWAY_PORT}/api/health", timeout=120):
        print("  ✗ 网关没起来，看 logs/gateway.log")
        return 1

    print("\n[4/4] 前端")
    start_web()
    if not wait_for("前端", WEB_PORT, timeout=90):
        print("  ✗ 前端没起来，看 logs/web.log")
        return 1

    if args.preheat:
        preheat()

    print()
    status()
    print("\n提示：录屏前先 localStorage.clear() 再刷新，否则开场不是首页。")

    if args.hold:
        print("监督模式：Ctrl+C 停止三个服务。")
        try:
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n正在停止…")
            for port in (WEB_PORT, GATEWAY_PORT, AGENT_PORT):
                kill_port(port)
            return 0

    print("停止：python scripts/dev_up.py --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
