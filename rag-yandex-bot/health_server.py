"""
Simple HTTP health check server for Docker health checks
Runs alongside the bot in a separate thread
"""
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple health check handler"""

    def do_GET(self):
        """Handle GET request"""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy", "service": "yandex_bot"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


def start_health_server(port=8003):
    """
    Start health check server in background thread

    Args:
        port: Port to listen on
    """
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)

    def run():
        server.serve_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
