"""HAZ integrated management system (v2) - launcher for Windows PCs and servers.

Default:     opens the system in its own desktop window (data on this PC).
--server:    shares it on the office network (HAZ-v2-Server.exe always does this).

First start: the setup page lets you create the administrator, or load FICTIONAL demo data with
one login per role, to try every module.

Which database (first match wins): --database-url, the HAZ_DATABASE_URL environment variable,
otherwise a local file in the data folder (default %LOCALAPPDATA%\\HAZ-v2).
"""
import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "HAZ - Integrated management system"


def default_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "HAZ-v2"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def prepare(args):
    """Environment first (settings read it at import), then database and static files."""
    data = Path(args.data or os.environ.get("HAZ_DATA_DIR") or default_data_dir()).resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ["HAZ_DATA_DIR"] = str(data)
    if args.database_url:
        os.environ["HAZ_DATABASE_URL"] = args.database_url
    os.environ.setdefault("HAZ_SERVE_STATIC", "1")
    hosts = "*" if args.server else "127.0.0.1,localhost"
    os.environ.setdefault("HAZ_ALLOWED_HOSTS", hosts)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "haz.settings")
    if getattr(sys, "frozen", False):
        sys.path.insert(0, getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    import django
    from django.core.management import call_command
    django.setup()
    from django.conf import settings
    print(f"Data folder: {data}")
    print(f"Database: {settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1]}")
    # commands are passed as objects: a packaged .exe cannot always look them up by name
    from django.contrib.staticfiles.management.commands import collectstatic
    from django.core.management.commands import migrate

    from core.management.commands import seed_defaults
    call_command(migrate.Command(), interactive=False, verbosity=0)
    call_command(seed_defaults.Command(), verbosity=0)
    call_command(collectstatic.Command(), interactive=False, verbosity=0)
    return data


def main():
    for stream in (sys.stdout, sys.stderr):  # None in the windowed exe
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True, errors="replace")
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--server", action="store_true", help="serve to other PCs / run on a server")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on in --server mode")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser in --server mode")
    parser.add_argument("--data", help="folder for the local database and files (default: %%LOCALAPPDATA%%\\HAZ-v2)")
    parser.add_argument("--database-url", help="e.g. postgresql://user:password@host:5432/dbname")
    parser.add_argument("--load-demo", action="store_true", help="fill an EMPTY database with fictional demo data, then exit")
    args = parser.parse_args()
    if "server" in Path(sys.argv[0]).stem.lower():
        args.server = True
    if sys.stdout is None or sys.stderr is None:
        # The windowed exe has no console: send messages and errors to a log file in the data folder.
        data = Path(args.data or os.environ.get("HAZ_DATA_DIR") or default_data_dir())
        data.mkdir(parents=True, exist_ok=True)
        log = open(data / "haz-v2.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    prepare(args)
    from waitress import serve

    from haz.wsgi import application

    if args.load_demo:
        from django.core.management import call_command

        from core.management.commands import load_demo
        call_command(load_demo.Command())
        return

    if args.server:
        print(f"{APP_NAME} - server mode")
        if args.host == "0.0.0.0":
            print(f"Open from other PCs: http://{lan_ip()}:{args.port}")
            print("NOTE: traffic is not encrypted (http). Use only on a trusted office network.")
        print("Keep this window open. Close it to stop the server.")
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        serve(application, host=args.host, port=args.port, threads=8)
        return

    port = free_port()
    threading.Thread(target=serve, args=(application,),
                     kwargs=dict(host="127.0.0.1", port=port, threads=4), daemon=True).start()
    wait_until_up(port)
    url = f"http://127.0.0.1:{port}/"
    try:
        import webview
    except ImportError:
        webview = None
    if webview is None:
        webbrowser.open(url)
        print(f"{APP_NAME} is running at {url} - close this window to exit.")
        threading.Event().wait()
        return
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except (AttributeError, TypeError):
        pass
    webview.create_window(APP_NAME, url, width=1320, height=860, min_size=(960, 620))
    webview.start()
    sys.exit(0)


if __name__ == "__main__":
    main()
