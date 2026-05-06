"""Source-contract tests for the retained LVGL scene lifecycle seam."""

from __future__ import annotations

import re
from pathlib import Path

SHIM_PATH = (
    Path(__file__).resolve().parents[2]
    / "yoyopod"
    / "ui"
    / "lvgl_binding"
    / "native"
    / "lvgl_shim.c"
)


def _read_shim_source() -> str:
    return SHIM_PATH.read_text(encoding="utf-8")


def _function_body(signature: str) -> str:
    source = _read_shim_source()
    start = source.index(signature)
    body_start = source.index("{", start)
    depth = 1
    cursor = body_start + 1

    while depth > 0 and cursor < len(source):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
        cursor += 1

    return source[body_start + 1 : cursor - 1]


def test_release_scene_screen_replaces_active_root_before_delete() -> None:
    """Active retained scenes should load the reusable blank root before deletion."""

    body = _function_body("static void yoyopod_release_scene_screen")

    assert "yoyopod_ensure_blank_screen()" in body
    assert "lv_screen_active() == screen" in body
    assert "lv_screen_load(blank_screen);" in body
    assert "lv_obj_delete(screen);" in body
    assert "lv_obj_clean(screen);" not in body


def test_clear_screen_reuses_the_blank_screen_instead_of_allocating_placeholders() -> None:
    """Full-screen clears should rely on the shared blank root instead of per-reset screens."""

    source = _read_shim_source()
    body = _function_body("void yoyopod_lvgl_clear_screen")

    assert "static lv_obj_t * g_blank_screen = NULL;" in source
    assert "placeholder_screen" not in body
    assert "lv_obj_create(NULL)" not in body


def test_shutdown_clears_retained_scenes_before_freeing_draw_buffers() -> None:
    """Shutdown should release retained scenes before buffer storage is freed."""

    body = _function_body("void yoyopod_lvgl_shutdown")

    assert "yoyopod_lvgl_clear_screen();" in body
    assert body.index("yoyopod_lvgl_clear_screen();") < body.index("lv_free(g_draw_buf);")
    assert "lv_obj_delete(g_blank_screen);" in body
    assert body.index("lv_obj_delete(g_blank_screen);") < body.index("g_blank_screen = NULL;")
    assert "g_blank_screen = NULL;" in body


def test_retained_scene_syncs_guard_missing_roots_before_activation() -> None:
    """Each retained sync path should reject a missing scene root before load-time activation."""

    sync_functions = {
        "int yoyopod_lvgl_hub_sync": "g_hub_scene.screen",
        "int yoyopod_lvgl_talk_sync": "g_talk_scene.screen",
        "int yoyopod_lvgl_talk_actions_sync": "g_talk_actions_scene.screen",
        "int yoyopod_lvgl_listen_sync": "g_listen_scene.screen",
        "int yoyopod_lvgl_playlist_sync": "g_playlist_scene.screen",
        "int yoyopod_lvgl_now_playing_sync": "g_now_playing_scene.screen",
        "int yoyopod_lvgl_incoming_call_sync": "g_incoming_call_scene.screen",
        "int yoyopod_lvgl_outgoing_call_sync": "g_outgoing_call_scene.screen",
        "int yoyopod_lvgl_in_call_sync": "g_in_call_scene.screen",
        "int yoyopod_lvgl_ask_sync": "g_ask_scene.screen",
        "int yoyopod_lvgl_power_sync": "g_power_scene.screen",
    }

    for signature, scene_ref in sync_functions.items():
        body = _function_body(signature)
        guard_match = re.search(
            rf"yoyopod_require_scene_screen\(\s*{re.escape(scene_ref)}\s*,",
            body,
            re.MULTILINE,
        )
        activate_match = re.search(
            rf"yoyopod_activate_scene_screen\(\s*{re.escape(scene_ref)}\s*,",
            body,
            re.MULTILINE,
        )

        assert guard_match is not None, f"missing root guard in {signature}"
        assert activate_match is not None, f"missing activation helper in {signature}"
        assert (
            guard_match.start() < activate_match.start()
        ), f"root guard should run before activation in {signature}"


def test_hub_sync_keeps_fixed_scene_chrome_out_of_per_step_updates() -> None:
    """Hub card advances should not reapply static scene chrome on every sync."""

    build_body = _function_body("int yoyopod_lvgl_hub_build")
    sync_body = _function_body("int yoyopod_lvgl_hub_sync")

    assert "lv_obj_set_style_bg_color(g_hub_scene.footer_bar" in build_body
    assert "lv_obj_set_style_text_color(g_hub_scene.footer_label" in build_body

    assert "lv_obj_set_style_bg_color(g_hub_scene.screen" not in sync_body
    assert "lv_obj_set_style_bg_color(g_hub_scene.footer_bar" not in sync_body
    assert "yoyopod_apply_footer_label(g_hub_scene.footer_label" not in sync_body
    assert "state = &g_hub_scene.last_state" in sync_body
