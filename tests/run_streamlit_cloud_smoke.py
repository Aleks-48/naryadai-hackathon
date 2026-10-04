"""Bounded HTTP startup check for `streamlit run streamlit_app.py` with no API server."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    env = os.environ.copy()
    env.pop("NARYADAI_API_URL", None)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "streamlit", "run", str(ROOT / "streamlit_app.py"),
               "--server.address", "127.0.0.1", "--server.port", str(port),
               "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 20
        last_error = "not ready yet"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"streamlit exited with {process.returncode}:\n{output}")
            try:
                response = requests.get(base + "/_stcore/health", timeout=1)
                response.raise_for_status()
                root = requests.get(base + "/", timeout=1)
                root.raise_for_status()
                print(f"PASS: streamlit run started without server.py; health={response.status_code}, app={root.status_code}")
                return
            except requests.RequestException as error:
                last_error = str(error)
                time.sleep(0.2)
        output = ""
        if process.stdout:
            try:
                output = process.stdout.read(10_000)
            except OSError:
                pass
        raise RuntimeError(f"streamlit did not become healthy within 20s: {last_error}\n{output}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()

if __name__ == "__main__":
    main()
