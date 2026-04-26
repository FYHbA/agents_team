from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO_ROOT / ".agents-team" / "processes"
LOG_DIR = REPO_ROOT / ".agents-team" / "logs"

SERVICES = {
    "backend": {
        "port": 8000,
        "cwd": REPO_ROOT,
        "argv": [
            str(REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--app-dir",
            "backend",
        ],
    },
    "frontend": {
        "port": 5173,
        "cwd": REPO_ROOT / "frontend",
        "argv": [
            "node",
            str(REPO_ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"),
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort",
        ],
    },
}


def pid_file(name: str) -> Path:
    return RUNTIME_DIR / f"{name}.pid"


def service_logs(name: str) -> tuple[Path, Path]:
    return LOG_DIR / f"{name}.out.log", LOG_DIR / f"{name}.err.log"


def ensure_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, timeout_seconds: float = 20) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.25)
    return False


def wait_for_port_close(port: int, timeout_seconds: float = 10) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not port_open(port):
            return True
        time.sleep(0.25)
    return not port_open(port)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_for_port(port: int) -> int | None:
    if os.name != "nt":
        return None
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if f":{port}" not in line or "LISTENING" not in line:
            continue
        parts = [part for part in line.split() if part]
        if not parts:
            continue
        try:
            return int(parts[-1])
        except ValueError:
            continue
    return None


def write_pid_file(name: str, pid: int) -> None:
    stdout_path, stderr_path = service_logs(name)
    payload = {
        "pid": pid,
        "port": SERVICES[name]["port"],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }
    pid_file(name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_pid(name: str) -> int | None:
    path = pid_file(name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    pid = payload.get("pid")
    return int(pid) if isinstance(pid, int) else None


def _status_snapshot(name: str) -> dict[str, object]:
    port = int(SERVICES[name]["port"])
    recorded_pid = read_pid(name)
    listening_pid = pid_for_port(port)
    listener_running = bool(listening_pid and process_exists(listening_pid))
    recorded_running = bool(recorded_pid and process_exists(recorded_pid))
    port_running = port_open(port)
    active_pid = listening_pid if listener_running else recorded_pid if recorded_running else listening_pid or recorded_pid
    pid_source = "listener" if listener_running else "pid_file" if recorded_running else "listener" if listening_pid else "pid_file" if recorded_pid else None
    pid_mismatch = bool(recorded_pid and listening_pid and recorded_pid != listening_pid)
    running = port_running or listener_running or recorded_running
    return {
        "service": name,
        "port": port,
        "state": "running" if running else "stopped",
        "pid": active_pid,
        "recorded_pid": recorded_pid,
        "listening_pid": listening_pid,
        "pid_source": pid_source,
        "pid_mismatch": pid_mismatch,
    }


def start_service(name: str) -> None:
    ensure_dirs()
    service = SERVICES[name]
    if port_open(service["port"]):
        print(f"{name} already appears to be running on port {service['port']}.")
        return

    stdout_path, stderr_path = service_logs(name)
    creationflags = 0
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(  # noqa: S603
            service["argv"],
            cwd=service["cwd"],
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
            close_fds=True,
            **popen_kwargs,
        )

    write_pid_file(name, process.pid)
    if wait_for_port(service["port"]):
        print(f"Started {name} on port {service['port']} (PID {process.pid}).")
    else:
        print(f"{name} did not bind port {service['port']} within the expected time window.")


def stop_service(name: str) -> None:
    snapshot = _status_snapshot(name)
    pid = snapshot["listening_pid"] or snapshot["recorded_pid"]
    if pid is None:
        print(f"{name} pid file not found.")
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    wait_for_port_close(SERVICES[name]["port"])
    print(f"Stopped {name} (PID {pid}).")
    pid_file(name).unlink(missing_ok=True)


def status_service(name: str) -> dict[str, object]:
    snapshot = _status_snapshot(name)
    return {
        "service": snapshot["service"],
        "port": snapshot["port"],
        "state": snapshot["state"],
        "pid": snapshot["pid"],
        "note": "pid file differs from live listener" if snapshot["pid_mismatch"] else "",
    }


def print_status() -> None:
    rows = [status_service("backend"), status_service("frontend")]
    print(f"{'service':<10} {'port':<6} {'state':<8} {'pid':<8} note")
    for row in rows:
        print(f"{row['service']:<10} {row['port']:<6} {row['state']:<8} {str(row['pid'] or ''):<8} {row['note']}")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"up", "down", "status"}:
        print("Usage: python scripts/dev_launcher.py [up|down|status]")
        return 1

    command = sys.argv[1]
    if command == "up":
        start_service("backend")
        start_service("frontend")
        print("")
        print("Frontend: http://127.0.0.1:5173")
        print("Backend:  http://127.0.0.1:8000")
        return 0
    if command == "down":
        stop_service("frontend")
        stop_service("backend")
        return 0
    print_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
