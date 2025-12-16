"""
Quick ngrok launcher for this repo (no secrets committed).

What it does:
- Reads NGROK_AUTHTOKEN from environment or from a local `.ngrok.env` file (gitignored)
- Ensures the token is registered with ngrok (`ngrok config add-authtoken ...`)
- Starts an ngrok HTTP tunnel to your local port (default: 8000)
- Detects the public URL via the local ngrok API (http://127.0.0.1:4040)
- Writes that public URL to `.tunnel-url` in the repo root so Django auto-allows it

Usage:
  python tools/quick_ngrok.py
  python tools/quick_ngrok.py --port 8000

Create `.ngrok.env` in the repo root (recommended, gitignored):
  NGROK_AUTHTOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TUNNEL_URL_FILE = REPO_ROOT / ".tunnel-url"
DEFAULT_NGROK_ENV_FILE = REPO_ROOT / ".ngrok.env"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k:
            data[k] = v
    return data


def _http_get_json(url: str, timeout_s: float = 1.5) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "noctis-pro-ngrok-helper"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (local URL)
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def _wait_for_public_url(timeout_s: float = 20.0) -> str:
    """
    Polls the local ngrok API until a public https URL is available.
    """
    deadline = time.time() + timeout_s
    last_err: str | None = None
    while time.time() < deadline:
        try:
            data = _http_get_json("http://127.0.0.1:4040/api/tunnels")
            tunnels = data.get("tunnels") or []
            # Prefer https URL if present
            for t in tunnels:
                public_url = (t or {}).get("public_url") or ""
                if public_url.startswith("https://"):
                    return public_url
            for t in tunnels:
                public_url = (t or {}).get("public_url") or ""
                if public_url.startswith("http://"):
                    return public_url
            last_err = "No tunnels reported yet."
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            last_err = str(e)
        time.sleep(0.35)
    raise RuntimeError(f"Timed out waiting for ngrok public URL. Last error: {last_err}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start ngrok and write public URL to .tunnel-url")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--tunnel-url-file",
        default=str(DEFAULT_TUNNEL_URL_FILE),
        help="Where to write the detected public URL (default: .tunnel-url in repo root).",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_NGROK_ENV_FILE),
        help="Local env file to read (default: .ngrok.env in repo root).",
    )
    args = parser.parse_args()

    if not shutil.which("ngrok"):
        print("ngrok is not installed or not on PATH.")
        print("Install it, then re-run. Example (Ubuntu): snap install ngrok")
        return 2

    env_file = Path(args.env_file)
    file_env = _load_env_file(env_file)
    for k, v in file_env.items():
        os.environ.setdefault(k, v)

    token = os.environ.get("NGROK_AUTHTOKEN", "").strip()
    if not token:
        print(
            "Missing NGROK_AUTHTOKEN.\n"
            "Set it as an environment variable or create a local .ngrok.env file in the repo root:\n"
            "  NGROK_AUTHTOKEN=YOUR_TOKEN\n"
        )
        return 3

    # Register token (idempotent; safe to run repeatedly).
    subprocess.run(
        ["ngrok", "config", "add-authtoken", token],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start ngrok. We'll poll the local API for the public URL.
    cmd = ["ngrok", "http", str(args.port), "--log=stdout", "--log-format=json"]
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT))

    def _shutdown(_signum: int, _frame) -> None:  # type: ignore[override]
        try:
            proc.terminate()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        public_url = _wait_for_public_url(timeout_s=25.0)
        tunnel_url_path = Path(args.tunnel_url_file)
        tunnel_url_path.write_text(public_url + "\n", encoding="utf-8")
        print(public_url)
        print(f"(saved to {tunnel_url_path})")
        print("Leave this running while you use the app; Ctrl+C to stop.")
    except Exception as e:
        print(f"Failed to start ngrok tunnel: {e}", file=sys.stderr)
        try:
            proc.terminate()
        except Exception:
            pass
        return 4

    # Keep running until ngrok exits or we are interrupted.
    try:
        return proc.wait()
    finally:
        # Best-effort cleanup: if ngrok exits, leave the last URL in place.
        pass


if __name__ == "__main__":
    raise SystemExit(main())

