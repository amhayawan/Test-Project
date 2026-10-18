"""Hassan Abbas Zaki Association CRM - Windows launcher.

Default:   opens the CRM in its own desktop window (data stays on this PC).
--server:  shares the CRM on the office network so other PCs can open it
           in a browser at http://<this-pc-ip>:8080
"""
import argparse
import socket
import sys
import threading
import time
import webbrowser

from waitress import serve

from crm import create_app
from crm.app import APP_NAME


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


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--server", action="store_true", help="share on the local network")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", help="folder for the database (default: %%APPDATA%%\\HAZ-CRM)")
    args = parser.parse_args()

    app = create_app({"DATA_DIR": args.data} if args.data else None)

    if args.server:
        print(f"{APP_NAME} - server mode")
        print(f"Data folder: {app.config['DATA_DIR']}")
        print(f"Open from other PCs: http://{lan_ip()}:{args.port}")
        print("Keep this window open. Close it to stop the server.")
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        serve(app, host="0.0.0.0", port=args.port, threads=8)
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
