import http.server
import socketserver
import sys
import webbrowser
from threading import Timer

PORT = 8080
DIRECTORY = "."


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)


def open_browser():
    webbrowser.open(f"http://localhost:{PORT}/dashboard/index.html")


def main():
    # Print welcome message

    # Delay opening browser by 1 second to give the server time to start up
    Timer(1.0, open_browser).start()

    # Disable socket reuse delays
    socketserver.TCPServer.allow_reuse_address = True

    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        pass


if __name__ == "__main__":
    main()
