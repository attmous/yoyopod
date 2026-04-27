"""VoIP sidecar process entry point.

The sidecar runs the protocol handshake, owns a :class:`VoIPBackend`
instance, and routes incoming commands and outgoing events through a
:class:`SidecarBackendAdapter`. The default backend factory lazily imports
:class:`yoyopod.backends.voip.LiblinphoneBackend` so the import chain is
only paid in the sidecar process; tests inject a mock-backend factory
instead.

The function :func:`run_sidecar` is what
:class:`yoyopod.integrations.call.sidecar_supervisor.SidecarSupervisor`
passes to ``multiprocessing.Process(target=...)`` (or to the loopback
thread runner), so it must remain importable at module level for
``spawn`` and ``forkserver`` start methods.
"""

from __future__ import annotations

import sys
from multiprocessing.connection import Connection

from yoyopod.integrations.call.sidecar_adapter import (
    BackendFactory,
    SidecarBackendAdapter,
)
from yoyopod.integrations.call.sidecar_protocol import (
    Error,
    Hello,
    PROTOCOL_VERSION,
    ProtocolError,
    Ready,
    Shutdown,
    recv_command,
    send_message,
)


def run_sidecar(conn: Connection, backend_factory: BackendFactory | None = None) -> None:
    """Run the sidecar command loop until :class:`Shutdown` or the pipe closes."""

    _set_parent_death_signal()

    factory = backend_factory or _default_liblinphone_factory

    try:
        send_message(conn, Hello(version=PROTOCOL_VERSION, capabilities=("voip",)))
    except (BrokenPipeError, EOFError, OSError):
        return

    try:
        peer_hello = recv_command(conn)
    except (BrokenPipeError, EOFError, OSError):
        return
    except ProtocolError as exc:
        _safe_send(
            conn,
            Error(code="protocol_error", message=f"handshake decode failed: {exc}"),
        )
        return

    if not isinstance(peer_hello, Hello) or peer_hello.version != PROTOCOL_VERSION:
        _safe_send(
            conn,
            Error(
                code="protocol_mismatch",
                message=(
                    f"sidecar speaks version {PROTOCOL_VERSION}; "
                    f"received {type(peer_hello).__name__}"
                ),
            ),
        )
        return

    if not _safe_send(conn, Ready()):
        return

    adapter = SidecarBackendAdapter(conn=conn, backend_factory=factory)
    try:
        while True:
            try:
                command = recv_command(conn)
            except (BrokenPipeError, EOFError, OSError):
                return
            except ProtocolError as exc:
                if not _safe_send(conn, Error(code="protocol_error", message=str(exc))):
                    return
                continue

            if isinstance(command, Shutdown):
                return

            adapter.handle_command(command)
    finally:
        adapter.shutdown()


def _safe_send(conn: Connection, message: object) -> bool:
    """Send one message, returning False if the parent has closed the pipe."""

    try:
        send_message(conn, message)
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


def _set_parent_death_signal() -> None:
    """On Linux, ask the kernel to send SIGTERM if the parent process dies."""

    if sys.platform != "linux":
        return

    try:
        import ctypes
        import signal as signal_module

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        # PR_SET_PDEATHSIG = 1; the second argument is the signal to deliver.
        libc.prctl(1, signal_module.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        # If prctl is unavailable the supervisor still detects death via the
        # closed pipe; this is a defense-in-depth signal, not a hard requirement.
        pass


def _default_liblinphone_factory(config: object) -> object:
    """Lazily construct a :class:`LiblinphoneBackend` from the supplied config.

    The import happens here so the sidecar process pays it only once on first
    :class:`Configure` and tests that inject a different factory never trigger
    the native shim load.
    """

    from yoyopod.backends.voip import LiblinphoneBackend
    from yoyopod.integrations.call.models import VoIPConfig

    if not isinstance(config, VoIPConfig):
        raise TypeError(
            f"_default_liblinphone_factory expected VoIPConfig, got {type(config).__name__}"
        )
    return LiblinphoneBackend(config)
