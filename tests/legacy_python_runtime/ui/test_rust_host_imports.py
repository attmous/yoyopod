from __future__ import annotations

from yoyopod.ui.rust_host import RustUiFacade, RustUiRuntimeSnapshot, UiEnvelope
from yoyopod.ui.rust_sidecar import (
    RustUiRuntimeSnapshot as LegacyRustUiRuntimeSnapshot,
)
from yoyopod.ui.rust_sidecar import (
    RustUiSidecarCoordinator,
    UiEnvelope as LegacyUiEnvelope,
)


def test_rust_host_exports_new_facade_names() -> None:
    assert RustUiFacade.__name__ == "RustUiFacade"
    assert RustUiRuntimeSnapshot.__name__ == "RustUiRuntimeSnapshot"
    assert UiEnvelope.__name__ == "UiEnvelope"


def test_rust_sidecar_imports_remain_compatible() -> None:
    assert RustUiSidecarCoordinator.__name__ == "RustUiFacade"
    assert LegacyRustUiRuntimeSnapshot is RustUiRuntimeSnapshot
    assert LegacyUiEnvelope is UiEnvelope
