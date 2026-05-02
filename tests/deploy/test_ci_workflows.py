from __future__ import annotations

import subprocess
from pathlib import Path

CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
REPO_ROOT = CI_YML.parents[2]
RUST_UI_LOCK = REPO_ROOT / "yoyopod_rs" / "Cargo.lock"
SLOT_BUILDER_DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "slot-builder.Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def test_slot_arm64_change_detector_matches_python_release_builder() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")

    assert "build_release\\.py" in workflow
    assert "scripts/(build_release|build_slot_artifact_ci)\\.sh" not in workflow


def test_slot_arm64_pr_build_is_label_gated() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "contains(github.event.pull_request.labels.*.name, 'build-arm-slot')" in workflow
    assert "github.event_name == 'push'" in workflow


def test_rust_ci_builds_arm64_device_bundle_artifact() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")

    assert "rust-device-arm64:" in workflow
    assert "runs-on: ubuntu-24.04-arm" in workflow
    assert "needs: [changes, quality, test, voice-go, rust-device-arm64]" in workflow
    assert "RUST_ARTIFACT_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "YOYOPOD_LVGL_SOURCE_DIR: ${{ github.workspace }}/.cache/lvgl/lvgl-9.5.0" in workflow
    assert "working-directory: yoyopod_rs" in workflow
    assert "bazelbuild/setup-bazelisk" in workflow
    assert "git clone --depth 1 --branch v9.5.0 https://github.com/lvgl/lvgl.git .cache/lvgl/lvgl-9.5.0" in workflow
    assert "Install native Rust host dependencies" in workflow
    assert "pkg-config liblinphone-dev libudev-dev" in workflow
    assert (
        "bazel test --action_env=PATH //yoyopod_rs/ui-host/... //yoyopod_rs/cloud-host/... "
        "//yoyopod_rs/media-host/... //yoyopod_rs/voip-host/... //yoyopod_rs/network-host/... "
        "//yoyopod_rs/runtime/..."
    ) in workflow
    assert "cargo test --workspace --locked --features whisplay-hardware,native-lvgl" in workflow
    assert (
        "cargo build --release --locked"
        in workflow
    )
    assert "-p yoyopod-runtime" in workflow
    assert "-p yoyopod-ui-host" in workflow
    assert "-p yoyopod-cloud-host" in workflow
    assert "-p yoyopod-media-host" in workflow
    assert "-p yoyopod-voip-host" in workflow
    assert "-p yoyopod-network-host" in workflow
    assert (
        "--features yoyopod-ui-host/whisplay-hardware,yoyopod-ui-host/native-lvgl,yoyopod-voip-host/native-liblinphone"
        in workflow
    )
    assert "uses: actions/upload-artifact@v4" in workflow
    assert "name: yoyopod-rust-device-arm64-${{ env.RUST_ARTIFACT_SHA }}" in workflow
    assert "yoyopod-rust-device-arm64-${{ env.RUST_ARTIFACT_SHA }}.tar.gz" in workflow
    assert "yoyopod_rs/ui-host/build/yoyopod-ui-host" in workflow
    assert "yoyopod_rs/cloud-host/build/yoyopod-cloud-host" in workflow
    assert "yoyopod_rs/media-host/build/yoyopod-media-host" in workflow
    assert "yoyopod_rs/voip-host/build/yoyopod-voip-host" in workflow
    assert "yoyopod_rs/network-host/build/yoyopod-network-host" in workflow
    assert "yoyopod_rs/runtime/build/yoyopod-runtime" in workflow
    assert "yoyopod-liblinphone-shim" not in workflow
    assert "liblinphone-shim/build" not in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "tar -xzf" in workflow
    assert "path: .artifacts/rust-device" in workflow


def test_slot_arm64_change_detector_includes_rust_workspace() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")

    assert "|yoyopod_rs/" in workflow


def test_voip_host_runtime_loads_liblinphone_without_ci_runner_soname() -> None:
    build_rs = (REPO_ROOT / "yoyopod_rs" / "voip-host" / "build.rs").read_text(
        encoding="utf-8"
    )
    ffi_rs = (
        REPO_ROOT / "yoyopod_rs" / "voip-host" / "src" / "liblinphone" / "ffi.rs"
    ).read_text(encoding="utf-8")

    assert "cargo_metadata(false)" in build_rs
    assert "cargo:rustc-link-lib=linphone" not in build_rs
    assert "fn linphone_factory_get" not in ffi_rs
    assert 'required_symbol(library, c"linphone_factory_get")' in ffi_rs
    assert 'liblinphone.so.12' in ffi_rs


def test_rust_bazel_feature_folder_layout_is_checked_in() -> None:
    assert (REPO_ROOT / "MODULE.bazel").exists()
    assert (REPO_ROOT / "BUILD.bazel").exists()
    assert (REPO_ROOT / "defs.bzl").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "BUILD.bazel").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "ui-host" / "BUILD.bazel").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "ui-host" / "tests" / "README.md").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "cloud-host" / "BUILD.bazel").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "voip-host" / "BUILD.bazel").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "voip-host" / "tests" / "README.md").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "network-host" / "BUILD.bazel").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "network-host" / "tests" / "README.md").exists()
    assert (REPO_ROOT / "yoyopod_rs" / "runtime" / "BUILD.bazel").exists()
    assert not (REPO_ROOT / "yoyopod_rs" / "crates").exists()


def test_runtime_bazel_integration_tests_register_all_runtime_tests() -> None:
    build_file = (REPO_ROOT / "yoyopod_rs" / "runtime" / "BUILD.bazel").read_text(
        encoding="utf-8"
    )

    for test_name in (
        "cli",
        "config",
        "event",
        "protocol",
        "runtime_loop",
        "smoke",
        "state",
        "worker",
    ):
        assert f'"{test_name}"' in build_file


def test_network_host_bazel_integration_tests_register_all_network_tests() -> None:
    build_file = (
        REPO_ROOT / "yoyopod_rs" / "network-host" / "BUILD.bazel"
    ).read_text(encoding="utf-8")

    for test_name in (
        "config",
        "gps",
        "lifecycle",
        "ppp",
        "protocol",
        "runtime_snapshot",
        "worker",
    ):
        assert f'"{test_name}"' in build_file

    assert '"lifecycle": ["tests/support/mod.rs"]' in build_file
    assert '"worker": ["tests/support/mod.rs"]' in build_file


def test_rust_ui_worker_lockfile_is_committable_for_locked_ci_builds() -> None:
    assert RUST_UI_LOCK.exists()

    result = subprocess.run(
        ["git", "check-ignore", RUST_UI_LOCK.relative_to(REPO_ROOT).as_posix()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout


def test_slot_builder_copies_artifact_checkout_before_native_preflight() -> None:
    dockerfile = SLOT_BUILDER_DOCKERFILE.read_text(encoding="utf-8")

    full_checkout = dockerfile.find("COPY . /src")
    ensure_native = dockerfile.find("ensure-native")

    assert full_checkout != -1
    assert ensure_native != -1
    assert full_checkout < ensure_native


def test_dockerignore_preserves_rust_artifact_build_dirs_for_slot_builder() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")

    for artifact_dir in (
        "yoyopod_rs/ui-host/build",
        "yoyopod_rs/cloud-host/build",
        "yoyopod_rs/media-host/build",
        "yoyopod_rs/voip-host/build",
        "yoyopod_rs/network-host/build",
        "yoyopod_rs/runtime/build",
    ):
        assert f"!{artifact_dir}/" in dockerignore
