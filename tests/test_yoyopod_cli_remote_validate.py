"""Tests for yoyopod_cli.remote_validate."""

from __future__ import annotations

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
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "git fetch --prune origin" in shell
    assert shell.count("git clean -fd") == 2
    assert "git checkout 'main'" in shell or "git checkout main" in shell
    assert "uv run yoyopod pi validate deploy" in shell
    assert "uv run yoyopod pi validate smoke" in shell
    assert "--with-power" not in shell
    assert "--with-rtc" not in shell
    assert "voip" not in shell or "uv run yoyopod pi validate voip" not in shell
    assert "lvgl" not in shell
    assert "navigation" not in shell


def test_build_validate_all_flags() -> None:
    shell = _build_validate(
        branch="main",
        sha="",
        with_music=True,
        with_voip=True,
        with_power=True,
        with_rtc=True,
        with_lvgl_soak=True,
        with_navigation=True,
    )
    assert "uv run yoyopod pi validate smoke --with-power --with-rtc" in shell
    assert "uv run yoyopod pi validate music" in shell
    assert "uv run yoyopod pi validate voip" in shell
    assert "uv run yoyopod pi validate lvgl" in shell
    assert "uv run yoyopod pi validate navigation" in shell


def test_build_validate_only_music() -> None:
    shell = _build_validate(
        branch="main",
        sha="",
        with_music=True,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "uv run yoyopod pi validate music" in shell
    assert "uv run yoyopod pi validate voip" not in shell


def test_build_validate_syncs_branch_before_validation_stages() -> None:
    shell = _build_validate(
        branch="feature-x",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    # Ensure sync steps appear BEFORE the first validate step.
    # shlex.quote leaves safe names unquoted, so search for both forms.
    sync_idx = max(
        shell.find("git reset --hard origin/feature-x"),
        shell.find("git reset --hard origin/'feature-x'"),
    )
    deploy_idx = shell.find("uv run yoyopod pi validate deploy")
    assert sync_idx >= 0, f"sync step missing from: {shell}"
    assert deploy_idx >= 0
    assert sync_idx < deploy_idx, "sync must happen before validation"


def test_build_validate_cleans_untracked_files_before_and_after_checkout() -> None:
    shell = _build_validate(
        branch="feature-x",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert shell.count("git clean -fd") == 2
    first_clean_idx = shell.find("git clean -fd")
    checkout_idx = shell.find("git checkout feature-x")
    if checkout_idx < 0:
        checkout_idx = shell.find("git checkout 'feature-x'")
    reset_idx = max(
        shell.find("git reset --hard origin/feature-x"),
        shell.find("git reset --hard 'origin/feature-x'"),
    )
    second_clean_idx = shell.rfind("git clean -fd")
    assert first_clean_idx >= 0
    assert checkout_idx > first_clean_idx
    assert reset_idx > checkout_idx
    assert second_clean_idx > reset_idx


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
        "--with-lvgl-soak",
        "--with-navigation",
    ):
        assert flag in names


# --- Fix 2: checkout-local uv run invocation ---


def test_build_validate_uses_uv_run_for_checkout_local_invocations() -> None:
    """Remote validate must use `uv run yoyopod` instead of a potentially stale installed script."""
    shell = _build_validate(
        branch="main",
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "uv run yoyopod pi validate deploy" in shell
    assert "uv run yoyopod pi validate smoke" in shell
    assert "source " not in shell


# --- Fix 3: SHA pinning ---


def test_build_validate_with_sha_pins_and_checks_ancestry() -> None:
    shell = _build_validate(
        branch="main",
        sha="abc123def",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
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
        sha="",
        with_music=False,
        with_voip=False,
        with_power=False,
        with_rtc=False,
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
