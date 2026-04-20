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
    shell = _build_validate(branch="main", sha="", with_music=False, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    assert "git fetch origin" in shell
    assert "git checkout 'main'" in shell or "git checkout main" in shell
    assert "yoyopod pi validate deploy" in shell
    assert "yoyopod pi validate smoke" in shell
    assert "voip" not in shell or "yoyopod pi validate voip" not in shell
    assert "lvgl" not in shell
    assert "navigation" not in shell


def test_build_validate_all_flags() -> None:
    shell = _build_validate(branch="main", sha="", with_music=True, with_voip=True, with_lvgl_soak=True, with_navigation=True)
    assert "yoyopod pi validate music" in shell
    assert "yoyopod pi validate voip" in shell
    assert "yoyopod pi validate lvgl" in shell
    assert "yoyopod pi validate navigation" in shell


def test_build_validate_only_music() -> None:
    shell = _build_validate(branch="main", sha="", with_music=True, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    assert "yoyopod pi validate music" in shell
    assert "yoyopod pi validate voip" not in shell


def test_build_validate_syncs_branch_before_validation_stages() -> None:
    shell = _build_validate(branch="feature-x", sha="", with_music=False, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    # Ensure sync steps appear BEFORE the first validate step.
    # shlex.quote leaves safe names unquoted, so search for both forms.
    sync_idx = max(
        shell.find("git reset --hard origin/feature-x"),
        shell.find("git reset --hard origin/'feature-x'"),
    )
    deploy_idx = shell.find("yoyopod pi validate deploy")
    assert sync_idx >= 0, f"sync step missing from: {shell}"
    assert deploy_idx >= 0
    assert sync_idx < deploy_idx, "sync must happen before validation"


def test_preflight_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["preflight", "--help"])
    assert result.exit_code == 0


def test_validate_has_all_with_flags() -> None:
    import typer.main

    click_cmd = typer.main.get_command(app)
    validate_cmd = click_cmd.commands["validate"]  # type: ignore[attr-defined]
    names = _collect_option_names(validate_cmd)
    for flag in ("--with-music", "--with-voip", "--with-lvgl-soak", "--with-navigation"):
        assert flag in names


# --- Fix 2: venv activation ---

def test_build_validate_activates_venv_before_yoyopod_invocations() -> None:
    """Venv activation must appear before first yoyopod invocation."""
    shell = _build_validate(
        branch="main", sha="",
        with_music=False, with_voip=False,
        with_lvgl_soak=False, with_navigation=False,
    )
    activate_idx = shell.find("source")
    yoyopod_idx = shell.find("yoyopod pi validate")
    assert activate_idx >= 0, f"expected venv activation in: {shell}"
    assert activate_idx < yoyopod_idx, "venv must activate BEFORE yoyopod invocations"


# --- Fix 3: SHA pinning ---

def test_build_validate_with_sha_pins_and_checks_ancestry() -> None:
    shell = _build_validate(
        branch="main", sha="abc123def",
        with_music=False, with_voip=False,
        with_lvgl_soak=False, with_navigation=False,
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
        branch="main", sha="",
        with_music=False, with_voip=False,
        with_lvgl_soak=False, with_navigation=False,
    )
    assert "git reset --hard origin/" in shell
    assert "merge-base" not in shell


def test_validate_has_sha_flag() -> None:
    import typer.main

    click_cmd = typer.main.get_command(app)
    validate_cmd = click_cmd.commands["validate"]  # type: ignore[attr-defined]
    names = _collect_option_names(validate_cmd)
    assert "--sha" in names, f"--sha flag missing; found: {names}"
