"""
tunnel.py — HTTPS tunnel for the Telegram Mini App.

Telegram only allows **https://** addresses on Web App buttons, so a local
http://localhost URL is rejected by Telegram ("only https links are allowed").
This script starts a free **Cloudflare Quick Tunnel** (no account, no config)
pointing at the local Flask server, captures the fresh https://….trycloudflare.com
URL, writes it into `.env` (APP_URL) and `tunnel_url.txt`, and keeps the tunnel
alive until you close the window.

Run:   python tunnel.py          (or double-click run_tunnel.bat)
Setup: setup_tunnel.bat          (one-time download of cloudflared.exe)

The URL is new every run (free throwaway address) — that is expected. Always
start the bot AFTER the tunnel so it picks up the fresh URL (run_all.bat does
this for you).
"""
import os
import re
import subprocess
import sys
from shutil import which

# when frozen (PyInstaller) the app's folder is the exe's folder, not the
# bundle's _internal dir
if getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# Overridable via env (used by tests / power users).
ENV_PATH = os.getenv("TUNNEL_ENV_PATH", os.path.join(PROJECT_DIR, ".env"))
URL_FILE = os.getenv("TUNNEL_URL_FILE", os.path.join(PROJECT_DIR, "tunnel_url.txt"))
CLOUDFLARED = os.path.join(PROJECT_DIR, "tools", "cloudflared.exe")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def default_local_url() -> str:
    """http://127.0.0.1:<SERVER_PORT> — port read from .env when present."""
    port = "5000"
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if key == "SERVER_PORT" and value.strip().isdigit():
                    port = value.strip()
    return f"http://127.0.0.1:{port}"


def find_cloudflared() -> str:
    """Path to cloudflared.exe — either tools\\cloudflared.exe or one on PATH."""
    if os.path.exists(CLOUDFLARED):
        return CLOUDFLARED
    found = which("cloudflared")
    if found:
        return found
    print("cloudflared is missing.")
    print("Run setup_tunnel.bat once — it downloads cloudflared.exe into tools\\.")
    sys.exit(1)


def update_env(app_url: str, env_path: str = ENV_PATH) -> None:
    """Set APP_URL=<url> in .env — replaces an existing line or appends one."""
    encoding = "utf-8"
    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except UnicodeDecodeError:
            with open(env_path, "r", encoding="cp1252") as fh:
                lines = fh.readlines()
            encoding = "cp1252"
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith("APP_URL="):
            lines[i] = f"APP_URL={app_url}\n"
            replaced = True
            break
    if not replaced:
        lines.append(f"\n# auto-set by tunnel.py - fresh HTTPS Mini App URL\n"
                     f"APP_URL={app_url}\n")
    with open(env_path, "w", encoding=encoding) as fh:
        fh.writelines(lines)


def main() -> None:
    local_url = os.getenv("TUNNEL_LOCAL_URL") or default_local_url()
    cloudflared = find_cloudflared()

    print("=" * 64)
    print("  Bingo Arena - HTTPS tunnel (Cloudflare Quick Tunnel)")
    print(f"  local server: {local_url}")
    print("  free, no account needed - the URL changes on every run.")
    print("  keep this window open while playing.")
    print("=" * 64)

    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--url", local_url, "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )

    url = None
    interrupted = False
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if line:
                print(line[:160])
            match = URL_RE.search(line)
            if match and not url:
                url = match.group(0)
                update_env(url)
                with open(URL_FILE, "w", encoding="utf-8") as fh:
                    fh.write(url)
                print()
                print("=" * 64)
                print(f"  TUNNEL READY:  {url}")
                print("=" * 64)
                print("  APP_URL written to .env - the bot picks up the new URL\n"
                      "  automatically on its next command (no restart needed).")
                print()
    except KeyboardInterrupt:
        interrupted = True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if url and not interrupted:
        print("\ncloudflared exited - the tunnel is closed.")
        print("Restart run_tunnel.bat to reconnect (the URL will be new).")
        sys.exit(1)
    if not url:
        print("No tunnel URL was received.")
        print("Make sure the server is running (run_server.bat), then try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
