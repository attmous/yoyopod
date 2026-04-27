"""Tests for yoyopod_cli.remote_validate."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from yoyopod_cli.remote_validate import app, _build_validate, _build_preflight_steps


def _collect_option_names(click_cmd: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(click_cmd, "params", []):
        names.update(getattr(param, "opts", []))
    return names


def test_build_preflight_steps_include_git_and_quality() -> None:
    steps = _build_preflight_steps()
    assert any("git diff" in " ".join(argv) for _, argv in steps)
    assert any("quality.py" in " ".join(argv) for _, argv in steps)


def test_build_validate_minimal() -> None:
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "git fetch --prune origin" in shell
    assert shell.count("git clean -fd") == 2
    assert "git checkout --force -B main origin/main" in shell or (
        "git checkout --force -B 'main' 'origin/main'" in shell
    )
    assert ".venv/bin/python -m yoyopod_cli.main pi validate deploy" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate smoke" in shell
    assert "--with-power" not in shell
    assert "--with-rtc" not in shell
    assert (
        "voip" not in shell or ".venv/bin/python -m yoyopod_cli.main pi validate voip" not in shell
    )
    assert "lvgl" not in shell
    assert "navigation" not in shell


def test_build_validate_all_flags() -> None:
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="",
        with_music=True,
        with_voip=True,
        with_power=True,
        with_rtc=True,
        with_cloud_voice=True,
        with_lvgl_soak=True,
        with_navigation=True,
    )
    assert ".venv/bin/python -m yoyopod_cli.main pi validate smoke --with-power --with-rtc" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate cloud-voice" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate music" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate voip" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate lvgl" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate navigation" in shell


def test_build_validate_with_rust_ui_poc() -> None:
    shell = _build_validate(
        branch="feature",
        venv_relpath="venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
        with_rust_ui_poc=True,
    )

    assert "venv/bin/python -m yoyopod_cli.main build rust-ui-poc" in shell
    assert "venv/bin/python -m yoyopod_cli.main pi rust-ui-poc" in shell


def test_build_validate_only_music() -> None:
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="",
        with_music=True,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert ".venv/bin/python -m yoyopod_cli.main pi validate music" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate voip" not in shell


def test_build_validate_syncs_branch_before_validation_stages() -> None:
    shell = _build_validate(
        branch="feature-x",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    # Ensure sync steps appear BEFORE the first validate step.
    # shlex.quote leaves safe names unquoted, so search for both forms.
    sync_idx = max(
        shell.find("git reset --hard origin/feature-x"),
        shell.find("git reset --hard origin/'feature-x'"),
    )
    deploy_idx = shell.find(".venv/bin/python -m yoyopod_cli.main pi validate deploy")
    assert sync_idx >= 0, f"sync step missing from: {shell}"
    assert deploy_idx >= 0
    assert sync_idx < deploy_idx, "sync must happen before validation"


def test_build_validate_cleans_untracked_files_before_and_after_checkout() -> None:
    shell = _build_validate(
        branch="feature-x",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert shell.count("git clean -fd") == 2
    first_clean_idx = shell.find("git clean -fd")
    checkout_idx = shell.find("git checkout --force -B feature-x origin/feature-x")
    if checkout_idx < 0:
        checkout_idx = shell.find("git checkout --force -B 'feature-x' 'origin/feature-x'")
    reset_idx = max(
        shell.find("git reset --hard origin/feature-x"),
        shell.find("git reset --hard 'origin/feature-x'"),
    )
    second_clean_idx = shell.rfind("git clean -fd")
    assert first_clean_idx >= 0
    assert checkout_idx > first_clean_idx
    assert reset_idx > checkout_idx
    assert second_clean_idx > reset_idx


def test_build_validate_force_resets_branch_before_validation() -> None:
    shell = _build_validate(
        branch="feature-x",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "git checkout --force -B feature-x origin/feature-x" in shell or (
        "git checkout --force -B 'feature-x' 'origin/feature-x'" in shell
    )


def test_preflight_help() -> None:
    runner = CliRunner(env={"COLUMNS": "200"})
    result = runner.invoke(app, ["preflight", "--help"])
    assert result.exit_code == 0


def test_validate_has_all_with_flags() -> None:
    import typer.main

    click_cmd = typer.main.get_command(app)
    validate_cmd = click_cmd.commands["validate"]  # type: ignore[attr-defined]
    names = _collect_option_names(validate_cmd)
    for flag in (
        "--with-music",
        "--with-voip",
        "--with-power",
        "--with-rtc",
        "--with-cloud-voice",
        "--with-lvgl-soak",
        "--with-navigation",
        "--with-rust-ui-poc",
    ):
        assert flag in names


# --- Fix 2: checkout-local module invocation ---


def test_build_validate_uses_checkout_python_for_checkout_local_invocations() -> None:
    """Remote validate must use the checkout venv instead of a stale installed script."""
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert ".venv/bin/python -m yoyopod_cli.main pi validate deploy" in shell
    assert ".venv/bin/python -m yoyopod_cli.main pi validate smoke" in shell
    assert "source " not in shell
    assert "uv run" not in shell


# --- Fix 3: SHA pinning ---


def test_build_validate_with_sha_pins_and_checks_ancestry() -> None:
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="abc123def",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    # Must use the SHA in git reset --hard
    assert "git reset --hard" in shell
    assert "abc123def" in shell
    # Must include ancestry check
    assert "git merge-base --is-ancestor" in shell
    # Must NOT reset to origin/main when SHA given
    assert "git reset --hard origin/'main'" not in shell
    assert "git reset --hard origin/main" not in shell


def test_build_validate_without_sha_uses_branch_tip() -> None:
    shell = _build_validate(
        branch="main",
        venv_relpath=".venv",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_cloud_voice=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "git reset --hard origin/" in shell
    assert "merge-base" not in shell


def test_validate_has_sha_flag() -> None:
    import typer.main

    click_cmd = typer.main.get_command(app)
    validate_cmd = click_cmd.commands["validate"]  # type: ignore[attr-defined]
    names = _collect_option_names(validate_cmd)
    assert "--sha" in names, f"--sha flag missing; found: {names}"


def test_validate_cli_stops_on_dirty_local_worktree(monkeypatch) -> None:
    remote_calls: list[str] = []

    def fake_local(argv: list[str]) -> SimpleNamespace:
        if argv == ["git", "diff", "--quiet"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("yoyopod_cli.remote_validate.run_local_capture", fake_local)
    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_remote",
        lambda conn, cmd, tty=False: remote_calls.append(cmd) or 0,
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 1
    assert "Local worktree has uncommitted changes" in result.output
    assert remote_calls == []


def test_validate_cli_stops_when_requested_branch_has_unpushed_commits(monkeypatch) -> None:
    remote_calls: list[str] = []

    def fake_local(argv: list[str]) -> SimpleNamespace:
        if argv in (
            ["git", "diff", "--quiet"],
            ["git", "diff", "--cached", "--quiet"],
            ["git", "fetch", "--quiet", "origin", "feature-x"],
            ["git", "rev-parse", "--verify", "origin/feature-x^{commit}"],
        ):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == ["git", "show-ref", "--verify", "--quiet", "refs/heads/feature-x"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == ["git", "rev-list", "--count", "origin/feature-x..feature-x"]:
            return SimpleNamespace(returncode=0, stdout="2\n", stderr="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr("yoyopod_cli.remote_validate.run_local_capture", fake_local)
    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_remote",
        lambda conn, cmd, tty=False: remote_calls.append(cmd) or 0,
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["--branch", "feature-x", "validate"])

    assert result.exit_code == 1
    assert "has unpushed commits" in result.output
    assert remote_calls == []


def test_validate_cli_accepts_pushed_sha_before_running_remote(monkeypatch) -> None:
    remote_calls: list[str] = []

    def fake_local(argv: list[str]) -> SimpleNamespace:
        if argv in (
            ["git", "diff", "--quiet"],
            ["git", "diff", "--cached", "--quiet"],
            ["git", "fetch", "--quiet", "origin", "feature-x"],
            ["git", "rev-parse", "--verify", "origin/feature-x^{commit}"],
            ["git", "merge-base", "--is-ancestor", "abc123", "origin/feature-x"],
        ):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr("yoyopod_cli.remote_validate.run_local_capture", fake_local)
    monkeypatch.setattr(
        "yoyopod_cli.remote_validate.run_remote",
        lambda conn, cmd, tty=False: remote_calls.append(cmd) or 0,
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["--branch", "feature-x", "validate", "--sha", "abc123"])

    assert result.exit_code == 0, result.output
    assert len(remote_calls) == 1
    assert "abc123" in remote_calls[0]
