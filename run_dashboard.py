import os
import sys
import webbrowser
import http.server
import socketserver
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
    print("="*60)
    print("           STOCKCALLS QUANT BACKTEST DASHBOARD")
    print("="*60)
    print(f"Starting local server at http://localhost:{PORT}/dashboard/index.html")
    print("Press Ctrl+C to stop the server.")
    print("="*60)

    # Delay opening browser by 1 second to give the server time to start up
    Timer(1.0, open_browser).start()

    # Disable socket reuse delays
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server. Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\nFailed to start server: {e}")
        print(f"Please run: python -m http.server {PORT}")

if __name__ == "__main__":
    main()
