"""
SmartTradeAI one-click launcher.

Starts the Flask/SocketIO server (run.py) using the installed system
Python, waits for it to accept connections, opens the default browser to
the app, and streams the server's logs into this console window.

Close this window (or press Ctrl+C) to STOP the server.

This is a thin bootstrapper: it shells out to the already-working Python
environment that runs the app, so the built .exe stays tiny instead of
bundling pandas/flask/yfinance/etc.
"""
import os
import sys
import time
import socket
import shutil
import ctypes
import subprocess
import webbrowser

# Absolute path to the project (this machine). If the launcher is ever
# moved next to the project, we also fall back to the exe's own folder.
PROJECT_DIR = r"D:\Claude\SmartTradeAI"
PORT = int(os.environ.get("PORT", "5000"))
URL = f"http://localhost:{PORT}"
STARTUP_TIMEOUT = 90  # seconds to wait for the server to come up


def _resolve_project_dir() -> str:
    if os.path.isfile(os.path.join(PROJECT_DIR, "run.py")):
        return PROJECT_DIR
    # Fallback: folder containing this exe/script, or its parent.
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for cand in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        if os.path.isfile(os.path.join(cand, "run.py")):
            return cand
    return PROJECT_DIR


def _find_python() -> str:
    for cand in (
        r"C:\Program Files\Python312\python.exe",
        shutil.which("python"),
        shutil.which("py"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return "python"


def _port_open(host: str = "127.0.0.1", port: int = PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _set_title(text: str) -> None:
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def main() -> int:
    _set_title("SmartTradeAI Server")
    print("=" * 54)
    print("   SmartTradeAI  —  starting local server ...")
    print("=" * 54)

    project = _resolve_project_dir()
    if not os.path.isfile(os.path.join(project, "run.py")):
        print(f"ERROR: could not find run.py under: {project}")
        input("Press Enter to exit...")
        return 1

    # Already running? Just open the browser and exit.
    if _port_open():
        print(f"Server already running — opening {URL}")
        webbrowser.open(URL)
        time.sleep(1)
        return 0

    python = _find_python()
    print(f"Project : {project}")
    print(f"Python  : {python}")
    print(f"Command : \"{python}\" run.py\n")

    # Child inherits this console, so server logs stream here.
    proc = subprocess.Popen([python, "run.py"], cwd=project)

    print("Waiting for server to come up", end="", flush=True)
    for _ in range(STARTUP_TIMEOUT):
        if _port_open():
            break
        if proc.poll() is not None:
            print("\nERROR: the server process exited early (see log above).")
            input("Press Enter to exit...")
            return 1
        print(".", end="", flush=True)
        time.sleep(1)
    else:
        print(f"\nERROR: server did not start within {STARTUP_TIMEOUT}s.")
        proc.terminate()
        input("Press Enter to exit...")
        return 1

    print(f"\n\n  ✔ SmartTradeAI is up — opening {URL}")
    webbrowser.open(URL)
    print("\n  Leave this window open while you use the app.")
    print("  Close this window (or press Ctrl+C) to STOP the server.\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
