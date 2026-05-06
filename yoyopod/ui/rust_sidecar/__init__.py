"""Compatibility imports for the renamed Rust UI host bridge."""

from yoyopod_cli.pi.support.rust_ui_host import RustUiRuntimeSnapshot, UiEnvelope, UiProtocolError
from yoyopod_cli.pi.support.rust_ui_host.supervisor import (
    RustUiHostSupervisor as RustUiSidecarSupervisor,
)

from ..rust_host import RustUiFacade
from ..rust_host.facade import RustUiFacade as RustUiSidecarCoordinator

__all__ = [
    "RustUiFacade",
    "RustUiRuntimeSnapshot",
    "RustUiSidecarCoordinator",
    "RustUiSidecarSupervisor",
    "UiEnvelope",
    "UiProtocolError",
]
