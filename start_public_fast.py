"""
Start the diary app with a fast HTTPS public tunnel.

Default tunnel provider: Cloudflare Quick Tunnel.
It works across different networks and provides HTTPS, which mobile browsers
require for microphone permission.
"""
import argparse
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlretrieve

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
CLOUDFLARED = ROOT / "tools" / "cloudflared.exe"
CLOUDFLARED_DOWNLOAD = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)


def ensure_secret_key():
    load_dotenv(ROOT / ".env")
    if os.environ.get("SECRET_KEY"):
        return

    os.environ.setdefault("APP_ENV", "development")
    os.environ["SECRET_KEY"] = secrets.token_urlsafe(32)
    print("WARN: SECRET_KEY is not set. Using an ephemeral local key for this run.")
    print("      Add SECRET_KEY to .env if you want login sessions to survive restarts.")


def ensure_cloudflared():
    if CLOUDFLARED.exists():
        return

    CLOUDFLARED.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading cloudflared...")
    urlretrieve(CLOUDFLARED_DOWNLOAD, CLOUDFLARED)


def port_is_open(port):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_available_port(start_port):
    port = start_port
    while port_is_open(port):
        port += 1
    return port


def run_flask(port):
    load_dotenv(ROOT / ".env")
    os.environ["PORT"] = str(port)
    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("FLASK_DEBUG", "false")
    os.environ.setdefault("PUBLIC_ACCESS", "true")
    os.environ.setdefault("SESSION_COOKIE_SECURE", "true")
    os.environ.setdefault("ALLOW_PUBLIC_REGISTRATION", "false")
    ensure_secret_key()

    sys.path.insert(0, str(ROOT))
    from app import app, init_ai_engine
    from werkzeug.serving import make_server

    print(f"Starting Flask on http://127.0.0.1:{port} ...")
    init_ai_engine()
    server = make_server("0.0.0.0", port, app, threaded=True)
    server.serve_forever()


def start_tunnel(port):
    ensure_cloudflared()

    cmd = [
        str(CLOUDFLARED),
        "tunnel",
        "--no-autoupdate",
        "--protocol",
        "http2",
        "--url",
        f"http://127.0.0.1:{port}",
    ]
    return subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def main():
    parser = argparse.ArgumentParser(description="Start public HTTPS tunnel for diary_web.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5005")))
    parser.add_argument("--no-flask", action="store_true", help="Only start the tunnel; app is already running.")
    args = parser.parse_args()

    flask_thread = None
    if args.no_flask:
        print(f"Using existing local service on http://127.0.0.1:{args.port}")
    else:
        if port_is_open(args.port):
            next_port = find_available_port(args.port + 1)
            print(
                f"Port {args.port} is already in use. "
                f"Starting a separate secured public instance on {next_port}."
            )
            args.port = next_port
        flask_thread = threading.Thread(target=run_flask, args=(args.port,), daemon=True)
        flask_thread.start()
        time.sleep(2)

    public_url = ""

    try:
        for attempt in range(1, 4):
            process = start_tunnel(args.port)
            print(f"Creating Cloudflare HTTPS tunnel... (attempt {attempt}/3)")
            for line in iter(process.stdout.readline, ""):
                print(line.rstrip())
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com(?!/)", line)
                if match and not public_url:
                    public_url = match.group(0)
                    print("\nPublic HTTPS URL:")
                    print(f"  {public_url}")
                    print("\nPages:")
                    print(f"  Login:    {public_url}/login")
                    print(f"  Chat:     {public_url}/")
                    print(f"  Kaogong:  {public_url}/kaogong")
                    print("\nKeep this window open. Press Ctrl+C to stop the tunnel.")

            process.wait()
            if public_url:
                break
            print("Cloudflare quick tunnel did not return a usable URL. Retrying shortly...")
            time.sleep(3)

        if flask_thread and not public_url:
            print(f"Tunnel failed after retries. Local Flask remains available on http://127.0.0.1:{args.port}.")
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping tunnel...")
    finally:
        if 'process' in locals() and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    if flask_thread:
        print("Flask was running in this process and will stop now.")


if __name__ == "__main__":
    main()
