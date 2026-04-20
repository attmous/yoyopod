"""
Web server for YoyoPod simulation mode.

Provides a Flask + SocketIO web server that serves the simulation UI and handles
real-time display updates and input events.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:
    from flask import Flask
    from flask_socketio import SocketIO


def _load_dependencies() -> dict[str, Any]:
    """Import Flask/SocketIO dependencies on demand."""
    try:
        from flask import Flask, jsonify, render_template
        from flask_cors import CORS
        from flask_socketio import SocketIO, emit
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Simulation web server requires optional dependencies: flask, flask-socketio, and "
            "flask-cors. Install them to run simulation mode."
        ) from exc

    return {
        "Flask": Flask,
        "jsonify": jsonify,
        "render_template": render_template,
        "CORS": CORS,
        "SocketIO": SocketIO,
        "emit": emit,
    }


class SimulationWebServer:
    """
    Web server for YoyoPod simulation mode.

    Manages a Flask + SocketIO server that provides:
    - HTML5 Canvas display of YoyoPod screen
    - Real-time WebSocket updates for display
    - Web button controls for input
    - Keyboard event forwarding

    The server runs in a background thread and automatically cleans up
    when the application exits.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5000) -> None:
        """
        Initialize the web server.

        Args:
            host: Host address to bind to (default: 0.0.0.0 for all interfaces)
            port: Port number to listen on (default: 5000)
        """
        self.host = host
        self.port = port
        self._flask_objects = _load_dependencies()

        self.app = self._flask_objects["Flask"](
            __name__,
            template_folder=str(Path(__file__).resolve().parent / "templates"),
        )
        self.app.config["SECRET_KEY"] = "yoyopod-simulation-key"

        # Enable CORS for development
        self._flask_objects["CORS"](self.app)

        # Initialize SocketIO
        self.socketio = self._flask_objects["SocketIO"](
            self.app,
            cors_allowed_origins="*",
            async_mode="threading",
        )

        # State
        self.running = False
        self.server_thread: Optional[threading.Thread] = None
        self.input_callback: Optional[Callable[[str], None]] = None
        self.latest_display_data: str = ""

        # Setup routes
        self._setup_routes()
        self._setup_socket_handlers()

        logger.info(f"Web server initialized on {host}:{port}")

    def _setup_routes(self) -> None:
        """Setup Flask HTTP routes."""

        @self.app.route("/")
        def index() -> str:
            """Serve main simulation UI page."""
            return self._flask_objects["render_template"]("display.html")

        @self.app.route("/api/health")
        def health() -> tuple[dict[str, str], int]:
            """Health check endpoint."""
            return (
                {
                    "status": "running",
                    "server": "YoyoPod Simulation",
                    "display": "ready",
                },
                200,
            )

        @self.app.route("/api/input/<action>", methods=["POST"])
        def handle_input(action: str):
            """Handle input action from web UI buttons."""
            if self.input_callback:
                try:
                    self.input_callback(action.upper())
                    return self._flask_objects["jsonify"](
                        {"status": "success", "action": action}
                    ), 200
                except Exception as exc:
                    logger.error(f"Error handling input action {action}: {exc}")
                    return self._flask_objects["jsonify"](
                        {"status": "error", "message": str(exc)}
                    ), 500
            return self._flask_objects["jsonify"](
                {"status": "error", "message": "No input handler registered"}
            ), 503

    def _setup_socket_handlers(self) -> None:
        """Setup SocketIO event handlers."""

        @self.socketio.on("connect")
        def handle_connect() -> None:
            """Handle client connection."""
            logger.info("Browser client connected to simulation server")
            # Send latest display data to newly connected client
            if self.latest_display_data:
                self._flask_objects["emit"](
                    "display_update", {"image": self.latest_display_data}
                )

        @self.socketio.on("disconnect")
        def handle_disconnect() -> None:
            """Handle client disconnection."""
            logger.info("Browser client disconnected from simulation server")

        @self.socketio.on("keyboard_input")
        def handle_keyboard(data: dict[str, str]) -> None:
            """Handle keyboard input from browser."""
            if "action" in data and self.input_callback:
                try:
                    self.input_callback(data["action"].upper())
                except Exception as exc:
                    logger.error(f"Error handling keyboard input: {exc}")

    def set_input_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback function for input events."""
        self.input_callback = callback
        logger.info("Input callback registered")

    def send_display_update(self, image_data: str) -> None:
        """
        Send display update to all connected browsers.

        Args:
            image_data: Base64-encoded PNG image data
        """
        self.latest_display_data = image_data

        if self.running:
            try:
                self.socketio.emit("display_update", {"image": image_data})
            except Exception as exc:
                logger.warning(f"Failed to send display update: {exc}")

    def start(self) -> None:
        """
        Start the web server in a background thread.

        The server will continue running until stop() is called.
        """
        if self.running:
            logger.warning("Web server already running")
            return

        self.running = True

        def run_server() -> None:
            """Server thread target function."""
            try:
                logger.info(f"Starting web server on http://{self.host}:{self.port}")
                logger.info("Open this URL in your browser to view the simulation")

                # Run the server
                self.socketio.run(
                    self.app,
                    host=self.host,
                    port=self.port,
                    debug=False,
                    use_reloader=False,
                    log_output=False,
                    allow_unsafe_werkzeug=True,
                )
            except Exception as exc:
                logger.error(f"Web server error: {exc}")
                self.running = False

        # Start server thread
        self.server_thread = threading.Thread(
            target=run_server,
            daemon=True,
            name="WebServerThread",
        )
        self.server_thread.start()

        # Wait a moment for server to start
        time.sleep(1)

        if self.running:
            logger.info("Web server started successfully")
        else:
            logger.error("Failed to start web server")

    def stop(self) -> None:
        """Stop the web server and clean up resources."""
        if not self.running:
            return

        logger.info("Stopping web server...")
        self.running = False

        # SocketIO server cleanup
        try:
            self.socketio.stop()
        except Exception:
            pass

        if self.server_thread:
            # Give thread a moment to clean up
            self.server_thread.join(timeout=2.0)
            self.server_thread = None

        logger.info("Web server stopped")

    def is_running(self) -> bool:
        """Check if web server is currently running."""
        return self.running


# Global server instance (singleton)
_server_instance: Optional[SimulationWebServer] = None


def get_server(host: str = "0.0.0.0", port: int = 5000) -> SimulationWebServer:
    """
    Get or create the global web server instance.

    This ensures only one web server runs at a time.
    """
    global _server_instance

    if _server_instance is None:
        _server_instance = SimulationWebServer(host=host, port=port)
    return _server_instance


def cleanup_server() -> None:
    """Clean up and stop the global web server instance."""
    global _server_instance

    if _server_instance:
        _server_instance.stop()
        _server_instance = None
