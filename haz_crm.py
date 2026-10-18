"""Hassan Abbas Zaki Association CRM - launcher.

Default:        opens the CRM in its own desktop window.
--server:       shares the CRM on the office network / runs it on a cloud server.
--migrate-to:   copies all data from the current database into another one
                (e.g. from the local file to a cloud PostgreSQL database).

Which database is used (first match wins):
  1. --database-url
  2. the HAZ_CRM_DATABASE_URL environment variable
  3. [database] url = ...  in settings.ini inside the data folder
  4. a local file: <data folder>\\crm.db
"""
import argparse
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from waitress import serve

from crm import create_app, storage
from crm.app import APP_NAME
from crm.models import db

BACKUP_CHECK_SECONDS = 6 * 3600


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(port, timeout=15):
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


def start_auto_backups(app, backup_dir):
    """Daily backup in the background, keeping the last 30."""
    def loop():
        while True:
            try:
                path = storage.auto_backup(app.config["DATABASE_URL"], backup_dir, db.metadata)
                if path:
                    print(f"Backup written: {path}")
                uploads = Path(app.config["UPLOAD_DIR"])
                if uploads.exists():  # case documents live outside the database
                    shutil.copytree(uploads, Path(backup_dir) / "uploads", dirs_exist_ok=True)
            except Exception as exc:  # never let a failed backup stop the app
                print(f"WARNING: automatic backup failed: {exc}", file=sys.stderr)
            time.sleep(BACKUP_CHECK_SECONDS)
    threading.Thread(target=loop, daemon=True).start()


def main():
    for stream in (sys.stdout, sys.stderr):  # None in the windowed exe
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True, errors="replace")
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--server", action="store_true", help="serve to other PCs / run on a server")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on in --server mode")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser in --server mode")
    parser.add_argument("--data", help="folder for settings and the local database "
                                       "(default: %%APPDATA%%\\HAZ-CRM)")
    parser.add_argument("--database-url", help="e.g. postgresql://user:password@host:5432/dbname")
    parser.add_argument("--backup-dir", help="folder for automatic daily backups "
                                             "(default: <data folder>\\backups). "
                                             "Use a USB drive or synced folder.")
    parser.add_argument("--no-auto-backup", action="store_true")
    parser.add_argument("--load-demo", action="store_true",
                        help="fill an EMPTY database with fictional sample data for demos, then exit")
    parser.add_argument("--migrate-to", metavar="DATABASE_URL",
                        help="copy all data into another (empty) database, then exit")
    args = parser.parse_args()
    if "server" in Path(sys.argv[0]).stem.lower():  # HAZ-CRM-Server.exe always runs in server mode
        args.server = True

    config = {}
    if args.data:
        config["DATA_DIR"] = args.data
    if args.database_url:
        config["DATABASE_URL"] = args.database_url
    app = create_app(config or None)
    db_url = app.config["DATABASE_URL"]
    print(f"Database: {storage.masked(db_url)}")

    if args.load_demo:
        from crm.demo import load_demo_data
        with app.app_context():
            counts = load_demo_data()
        print("Fictional demo data loaded:", ", ".join(f"{k}: {v}" for k, v in counts.items()))
        print("Logins (password demo1234): admin, accountant, manager, researcher, researcher2")
        return

    if args.migrate_to:
        target = storage.normalize_url(args.migrate_to)
        print(f"Copying all data to {storage.masked(target)} ...")
        counts = storage.copy_database(db_url, target, db.metadata)
        for table, n in counts.items():
            print(f"  {table}: {n} rows")
        print("Done. Point the app at the new database with --database-url or settings.ini.")
        return

    if not args.no_auto_backup:
        backup_dir = args.backup_dir or os.environ.get("HAZ_CRM_BACKUP_DIR") or Path(app.config["DATA_DIR"]) / "backups"
        start_auto_backups(app, backup_dir)
        print(f"Automatic backups: {backup_dir}")

    if args.server:
        print(f"{APP_NAME} - server mode")
        if args.host == "0.0.0.0" and os.environ.get("HAZ_CRM_BEHIND_PROXY") != "1":
            print(f"Open from other PCs: http://{lan_ip()}:{args.port}")
            print("NOTE: traffic is not encrypted (http). Use only on a trusted office network,")
            print("      never expose this port to the internet. See docs/DATABASE_AND_SECURITY.md")
        print("Keep this window open. Close it to stop the server.")
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        options = dict(host=args.host, port=args.port, threads=8)
        if os.environ.get("HAZ_CRM_BEHIND_PROXY") == "1":
            # Behind Caddy: take the real client IP and https scheme from its headers.
            # Safe only because the app port is reachable solely by the proxy (see docker-compose.yml).
            options.update(trusted_proxy="*", trusted_proxy_count=1,
                           trusted_proxy_headers="x-forwarded-for x-forwarded-proto x-forwarded-host",
                           clear_untrusted_proxy_headers=True)
        serve(app, **options)
        return

    port = free_port()
    threading.Thread(target=serve, args=(app,),
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
    webview.create_window(APP_NAME, url, width=1280, height=820, min_size=(900, 600))
    webview.start()
    sys.exit(0)


if __name__ == "__main__":
    main()
