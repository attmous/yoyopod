use anyhow::Result;
use yoyopod_ui_host::lvgl::{
    theme, CallController, LvglFacade, LvglRenderer, NativeSceneKey, NativeSceneRenderer,
    OverlayController, PowerController, RustSceneBridge, SceneKey, ScreenController, WidgetId,
};
use yoyopod_ui_host::runtime::UiScreen;
use yoyopod_ui_host::screens::{
    CallViewModel, ChromeModel, HubCardModel, HubViewModel, ListRowModel, ListScreenModel,
    OverlayViewModel, PowerViewModel, ScreenModel, StatusBarModel,
};

#[derive(Debug, Clone, PartialEq, Eq)]
enum FacadeEvent {
    CreateRoot {
        id: WidgetId,
    },
    CreateContainer {
        id: WidgetId,
        parent: WidgetId,
        role: &'static str,
    },
    CreateLabel {
        id: WidgetId,
        parent: WidgetId,
        role: &'static str,
    },
    SetText {
        id: WidgetId,
        text: String,
    },
    SetSelected {
        id: WidgetId,
        selected: bool,
    },
    SetIcon {
        id: WidgetId,
        icon_key: String,
    },
    SetProgress {
        id: WidgetId,
        value: i32,
    },
    SetVisible {
        id: WidgetId,
        visible: bool,
    },
    Destroy {
        id: WidgetId,
    },
}

#[derive(Default)]
struct FakeFacade {
    next_id: u64,
    destroy_failures_remaining: usize,
    events: Vec<FacadeEvent>,
}

impl FakeFacade {
    fn with_destroy_failures(destroy_failures_remaining: usize) -> Self {
        Self {
            next_id: 0,
            destroy_failures_remaining,
            events: Vec::new(),
        }
    }

    fn events(&self) -> &[FacadeEvent] {
        &self.events
    }
}

impl LvglFacade for FakeFacade {
    fn create_root(&mut self) -> Result<WidgetId> {
        let id = WidgetId::new(self.next_id);
        self.next_id += 1;
        self.events.push(FacadeEvent::CreateRoot { id });
        Ok(id)
    }

    fn create_container(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        let id = WidgetId::new(self.next_id);
        self.next_id += 1;
        self.events
            .push(FacadeEvent::CreateContainer { id, parent, role });
        Ok(id)
    }

    fn create_label(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        let id = WidgetId::new(self.next_id);
        self.next_id += 1;
        self.events
            .push(FacadeEvent::CreateLabel { id, parent, role });
        Ok(id)
    }

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
        self.events.push(FacadeEvent::SetText {
            id: widget,
            text: text.to_string(),
        });
        Ok(())
    }

    fn set_selected(&mut self, widget: WidgetId, selected: bool) -> Result<()> {
        self.events.push(FacadeEvent::SetSelected {
            id: widget,
            selected,
        });
        Ok(())
    }

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()> {
        self.events.push(FacadeEvent::SetIcon {
            id: widget,
            icon_key: icon_key.to_string(),
        });
        Ok(())
    }

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()> {
        self.events
            .push(FacadeEvent::SetProgress { id: widget, value });
        Ok(())
    }

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()> {
        self.events.push(FacadeEvent::SetVisible {
            id: widget,
            visible,
        });
        Ok(())
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()> {
        self.events.push(FacadeEvent::Destroy { id: widget });
        if self.destroy_failures_remaining > 0 {
            self.destroy_failures_remaining -= 1;
            anyhow::bail!("destroy failed for widget {}", widget.raw());
        }
        Ok(())
    }
}

fn created_label_id(events: &[FacadeEvent], role_name: &'static str) -> WidgetId {
    events
        .iter()
        .find_map(|event| match event {
            FacadeEvent::CreateLabel { id, role, .. } if *role == role_name => Some(*id),
            _ => None,
        })
        .unwrap_or_else(|| panic!("{role_name} label should exist"))
}

fn created_container_ids(events: &[FacadeEvent], role_name: &'static str) -> Vec<WidgetId> {
    events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == role_name => Some(*id),
            _ => None,
        })
        .collect()
}

fn has_text(events: &[FacadeEvent], id: WidgetId, text: &str) -> bool {
    events.iter().any(|event| {
        matches!(
            event,
            FacadeEvent::SetText {
                id: event_id,
                text: event_text,
            } if *event_id == id && event_text == text
        )
    })
}

#[test]
fn theme_styles_keep_native_lvgl_away_from_default_white_widgets() {
    let root = theme::style_for_role("root");
    assert_eq!(root.bg_color, Some(theme::BACKGROUND_RGB));
    assert_eq!(root.bg_opa, theme::OPA_COVER);
    assert_ne!(root.bg_color, Some(0xFFFFFF));

    let title = theme::style_for_role("list_title");
    assert_eq!(title.text_color, Some(theme::INK_RGB));

    let row = theme::style_for_role("list_row");
    assert_eq!(row.bg_color, Some(theme::SURFACE_RAISED_RGB));
    assert_eq!(row.border_color, Some(theme::BORDER_RGB));

    let selected_row = theme::style_for_selected_role("list_row", true);
    assert_eq!(selected_row.bg_color, Some(theme::SELECTED_ROW_RGB));
    assert_eq!(selected_row.border_color, Some(theme::SELECTED_ROW_RGB));
}

#[test]
fn persistent_hub_controller_builds_widgets_once_and_updates_text_in_place() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&hub_screen_model(&["Listen", "Talk"], 0))?;
    let first_len = renderer.facade().events().len();
    renderer.render(&hub_screen_model(&["Listen", "Talk"], 1))?;
    renderer.clear()?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let title_id = created_label_id(events, "hub_title");

    assert!(events.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateContainer {
            role: "hub_card_panel",
            ..
        }
    )));
    assert!(events.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateContainer {
            role: "status_bar",
            ..
        }
    )));
    assert!(events.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateContainer {
            role: "footer_bar",
            ..
        }
    )));
    assert!(has_text(events, title_id, "Listen"));
    assert!(has_text(second_pass, title_id, "Talk"));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert!(events.contains(&FacadeEvent::Destroy {
        id: WidgetId::new(0),
    }));

    Ok(())
}

#[test]
fn controller_mismatch_errors_remain_contextual() {
    let mut facade = FakeFacade::default();
    let mut call = CallController::default();
    let mut power = PowerController::default();
    let mut overlay = OverlayController::default();

    let call_error = call
        .sync(&mut facade, &listen_screen_model())
        .expect_err("call controller should reject list models");
    assert!(call_error.to_string().contains("call controller"));
    assert!(call_error.to_string().contains(UiScreen::Listen.as_str()));

    let power_error = power
        .sync(&mut facade, &ask_screen_model())
        .expect_err("power controller should reject ask models");
    assert!(power_error.to_string().contains("power controller"));
    assert!(power_error.to_string().contains(UiScreen::Ask.as_str()));

    let overlay_error = overlay
        .sync(&mut facade, &hub_screen_model(&["Listen"], 0))
        .expect_err("overlay controller should reject hub models");
    assert!(overlay_error.to_string().contains("overlay controller"));
    assert!(overlay_error.to_string().contains(UiScreen::Hub.as_str()));
}

#[test]
fn list_scene_reuses_widgets_across_listen_to_playlists_transition() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&listen_screen_model())?;
    let first_len = renderer.facade().events().len();

    renderer.render(&playlists_screen_model())?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let row_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == "list_row" => Some(*id),
            _ => None,
        })
        .collect();
    let row_icon_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateLabel { id, role, .. } if *role == "list_row_icon" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(renderer.active_scene(), Some(SceneKey::List));
    assert_eq!(renderer.active_screen(), Some(UiScreen::Playlists));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert_eq!(row_ids.len(), 2);
    assert_eq!(row_icon_ids.len(), 2);
    assert!(second_pass.contains(&FacadeEvent::SetSelected {
        id: row_ids[0],
        selected: false,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetSelected {
        id: row_ids[1],
        selected: true,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetIcon {
        id: row_icon_ids[0],
        icon_key: "playlist".to_string(),
    }));
    assert!(second_pass.contains(&FacadeEvent::SetIcon {
        id: row_icon_ids[1],
        icon_key: "playlist".to_string(),
    }));
    assert!(second_pass.contains(&FacadeEvent::SetText {
        id: WidgetId::new(1),
        text: "Playlists".to_string(),
    }));

    Ok(())
}

#[test]
fn shrinking_list_scene_hides_stale_rows_without_rebuild() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&listen_screen_model())?;
    let first_len = renderer.facade().events().len();

    renderer.render(&recent_tracks_screen_model())?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let row_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == "list_row" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(renderer.active_scene(), Some(SceneKey::List));
    assert_eq!(renderer.active_screen(), Some(UiScreen::RecentTracks));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert_eq!(row_ids.len(), 2);
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[0],
        visible: true,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetSelected {
        id: row_ids[0],
        selected: true,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[1],
        visible: false,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetSelected {
        id: row_ids[1],
        selected: false,
    }));

    Ok(())
}

#[test]
fn ask_scene_updates_title_subtitle_footer_in_place() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&ask_screen_model())?;
    let first_len = renderer.facade().events().len();

    renderer.render(&voice_note_screen_model())?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let title_id = created_label_id(events, "ask_title");
    let subtitle_id = created_label_id(events, "ask_subtitle");
    let footer_id = created_label_id(events, "ask_footer");
    let icon_id = created_label_id(events, "ask_icon");

    assert_eq!(renderer.active_scene(), Some(SceneKey::Ask));
    assert_eq!(renderer.active_screen(), Some(UiScreen::VoiceNote));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert!(has_text(second_pass, title_id, "Voice Note"));
    assert!(has_text(second_pass, subtitle_id, "Ready to record"));
    assert!(has_text(
        second_pass,
        footer_id,
        "2x Tap = Record | Hold = Back"
    ));
    assert!(second_pass.contains(&FacadeEvent::SetIcon {
        id: icon_id,
        icon_key: "microphone".to_string(),
    }));

    Ok(())
}

#[test]
fn now_playing_scene_updates_progress_state_and_title_without_rebuild() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&now_playing_screen_model(
        "Track A", "Artist A", "Playing", 120,
    ))?;
    let first_len = renderer.facade().events().len();

    renderer.render(&now_playing_screen_model(
        "Track B", "Artist A", "Paused", 640,
    ))?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let title_id = created_label_id(events, "now_playing_title");
    let state_id = created_label_id(events, "now_playing_state_label");
    let progress_id = created_container_ids(events, "now_playing_progress_fill")
        .into_iter()
        .next()
        .expect("now-playing progress fill should exist");

    assert_eq!(renderer.active_scene(), Some(SceneKey::NowPlaying));
    assert_eq!(renderer.active_screen(), Some(UiScreen::NowPlaying));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert!(has_text(second_pass, title_id, "Track B"));
    assert!(has_text(second_pass, state_id, "Paused"));
    assert!(second_pass.contains(&FacadeEvent::SetProgress {
        id: progress_id,
        value: 640,
    }));

    Ok(())
}

#[test]
fn now_playing_progress_is_clamped_before_reaching_the_facade() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&now_playing_screen_model(
        "Track A", "Artist A", "Playing", -50,
    ))?;
    renderer.render(&now_playing_screen_model(
        "Track B", "Artist B", "Playing", 1200,
    ))?;

    let progress_values: Vec<_> = renderer
        .facade()
        .events()
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::SetProgress { value, .. } => Some(*value),
            _ => None,
        })
        .collect();

    assert_eq!(progress_values, vec![0, 1000]);

    Ok(())
}

#[test]
fn ask_scene_uses_semantic_icon_updates_instead_of_text_encoding() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&ask_screen_model())?;

    let icon_id = renderer
        .facade()
        .events()
        .iter()
        .find_map(|event| match event {
            FacadeEvent::CreateLabel { id, role, .. } if *role == "ask_icon" => Some(*id),
            _ => None,
        })
        .expect("ask icon widget should exist");
    let icon_text_write = renderer.facade().events().iter().any(|event| {
        matches!(
            event,
            FacadeEvent::SetText {
                id,
                text
            } if *id == icon_id && text == "ask"
        )
    });

    assert!(!icon_text_write);
    assert!(renderer.facade().events().contains(&FacadeEvent::SetIcon {
        id: icon_id,
        icon_key: "ask".to_string(),
    }));

    Ok(())
}

#[test]
fn destroy_failure_clears_stale_widget_ids_before_retry_render() -> Result<()> {
    let facade = FakeFacade::with_destroy_failures(1);
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&hub_screen_model(&["Listen"], 0))?;

    let error = renderer.clear().expect_err("destroy should fail once");
    assert!(error.to_string().contains("destroy failed"));

    renderer.render(&hub_screen_model(&["Talk"], 0))?;

    let events = renderer.facade().events();
    let root_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateRoot { id } => Some(*id),
            _ => None,
        })
        .collect();
    let title_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateLabel {
                id,
                role: "hub_title",
                ..
            } => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(root_ids.len(), 2);
    assert!(events.contains(&FacadeEvent::Destroy {
        id: WidgetId::new(0),
    }));
    assert!(has_text(events, title_ids[0], "Listen"));
    assert!(has_text(events, title_ids[1], "Talk"));

    Ok(())
}

#[test]
fn scene_key_groups_raw_screens_into_future_shared_controller_families() {
    assert_eq!(SceneKey::for_screen(UiScreen::Hub), SceneKey::Hub);
    assert_eq!(SceneKey::for_screen(UiScreen::Listen), SceneKey::List);
    assert_eq!(SceneKey::for_screen(UiScreen::Playlists), SceneKey::List);
    assert_eq!(SceneKey::for_screen(UiScreen::RecentTracks), SceneKey::List);
    assert_eq!(SceneKey::for_screen(UiScreen::IncomingCall), SceneKey::Call);
    assert_eq!(SceneKey::for_screen(UiScreen::OutgoingCall), SceneKey::Call);
    assert_eq!(SceneKey::for_screen(UiScreen::InCall), SceneKey::Call);
    assert_eq!(SceneKey::for_screen(UiScreen::Power), SceneKey::Power);
    assert_eq!(SceneKey::for_screen(UiScreen::Loading), SceneKey::Overlay);
    assert_eq!(SceneKey::for_screen(UiScreen::Error), SceneKey::Overlay);
}

#[test]
fn native_scene_key_matches_python_c_lvgl_retained_scene_contract() {
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Hub),
        NativeSceneKey::Hub
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Listen),
        NativeSceneKey::Listen
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Playlists),
        NativeSceneKey::Playlist
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::RecentTracks),
        NativeSceneKey::Playlist
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::NowPlaying),
        NativeSceneKey::NowPlaying
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Talk),
        NativeSceneKey::Talk
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Contacts),
        NativeSceneKey::Playlist
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::CallHistory),
        NativeSceneKey::Playlist
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::VoiceNote),
        NativeSceneKey::TalkActions
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::IncomingCall),
        NativeSceneKey::IncomingCall
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::OutgoingCall),
        NativeSceneKey::OutgoingCall
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::InCall),
        NativeSceneKey::InCall
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Ask),
        NativeSceneKey::Ask
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Power),
        NativeSceneKey::Power
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Loading),
        NativeSceneKey::Overlay
    );
    assert_eq!(
        NativeSceneKey::for_screen(UiScreen::Error),
        NativeSceneKey::Overlay
    );
}

#[test]
fn rust_scene_bridge_preserves_native_list_scene_lifecycle_boundary() -> Result<()> {
    let bridge = RustSceneBridge::new(FakeFacade::default());
    let mut renderer = NativeSceneRenderer::new(bridge);

    renderer.render(&listen_screen_model())?;
    let listen_pass_len = renderer.bridge().facade().events().len();

    renderer.render(&playlists_screen_model())?;

    let events = renderer.bridge().facade().events();
    let playlist_pass = &events[listen_pass_len..];

    assert_eq!(renderer.active_scene(), Some(NativeSceneKey::Playlist));
    assert_eq!(renderer.active_screen(), Some(UiScreen::Playlists));
    assert!(playlist_pass.contains(&FacadeEvent::Destroy {
        id: WidgetId::new(0),
    }));
    assert!(playlist_pass
        .iter()
        .any(|event| matches!(event, FacadeEvent::CreateRoot { .. })));
    assert!(playlist_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateContainer {
            role: "playlist_row",
            ..
        }
    )));

    Ok(())
}

#[test]
fn rust_scene_bridge_reuses_playlist_family_without_rebuilding_widgets() -> Result<()> {
    let bridge = RustSceneBridge::new(FakeFacade::default());
    let mut renderer = NativeSceneRenderer::new(bridge);

    renderer.render(&playlists_screen_model())?;
    let playlists_pass_len = renderer.bridge().facade().events().len();

    renderer.render(&recent_tracks_screen_model())?;

    let events = renderer.bridge().facade().events();
    let recent_pass = &events[playlists_pass_len..];
    let row_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == "playlist_row" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(renderer.active_scene(), Some(NativeSceneKey::Playlist));
    assert_eq!(renderer.active_screen(), Some(UiScreen::RecentTracks));
    assert!(!recent_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
            | FacadeEvent::Destroy { .. }
    )));
    assert_eq!(row_ids.len(), 4);
    assert!(recent_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[0],
        visible: true,
    }));
    assert!(recent_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[1],
        visible: false,
    }));

    Ok(())
}

#[test]
fn rust_scene_bridge_caps_playlist_family_to_native_visible_rows() -> Result<()> {
    let bridge = RustSceneBridge::new(FakeFacade::default());
    let mut renderer = NativeSceneRenderer::new(bridge);

    renderer.render(&many_playlist_rows_screen_model(4))?;

    let events = renderer.bridge().facade().events();
    let row_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == "playlist_row" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(row_ids.len(), 4);
    assert!(!events.iter().any(|event| matches!(
        event,
        FacadeEvent::SetText { text, .. } if text == "Playlist 5"
    )));
    assert!(events.contains(&FacadeEvent::SetSelected {
        id: row_ids[3],
        selected: true,
    }));

    Ok(())
}

#[test]
fn rust_scene_bridge_wraps_listen_selection_after_native_row_cap() -> Result<()> {
    let bridge = RustSceneBridge::new(FakeFacade::default());
    let mut renderer = NativeSceneRenderer::new(bridge);

    renderer.render(&many_listen_rows_screen_model(4))?;

    let events = renderer.bridge().facade().events();
    let row_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateContainer { id, role, .. } if *role == "listen_row" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(row_ids.len(), 4);
    assert!(events.contains(&FacadeEvent::SetSelected {
        id: row_ids[0],
        selected: true,
    }));
    assert!(!events.iter().any(|event| matches!(
        event,
        FacadeEvent::SetText { text, .. } if text == "Listen Item 5"
    )));

    Ok(())
}

#[test]
fn empty_hub_model_preserves_listen_title_fallback() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&ScreenModel::Hub(HubViewModel {
        chrome: chrome_model(),
        cards: Vec::new(),
        selected_index: 0,
    }))?;

    let events = renderer.facade().events();
    let title_id = created_label_id(events, "hub_title");
    assert!(has_text(events, title_id, "Listen"));

    Ok(())
}

#[test]
fn call_scene_updates_icon_footer_and_mute_visibility_without_rebuild() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&incoming_call_screen_model())?;
    let first_len = renderer.facade().events().len();

    renderer.render(&in_call_screen_model())?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let title_id = created_label_id(events, "call_title");
    let state_id = created_label_id(events, "call_state_label");
    let footer_id = created_label_id(events, "call_footer");
    let icon_id = created_label_id(events, "call_state_icon");
    let mute_badge_id = created_container_ids(events, "call_mute_badge")
        .into_iter()
        .next()
        .expect("call mute badge should exist");

    assert_eq!(renderer.active_scene(), Some(SceneKey::Call));
    assert_eq!(renderer.active_screen(), Some(UiScreen::InCall));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert!(has_text(second_pass, title_id, "Alice"));
    assert!(has_text(second_pass, state_id, "IN CALL | 00:42"));
    assert!(has_text(
        second_pass,
        footer_id,
        "Tap = Mute | Hold = Hang Up"
    ));
    assert!(has_text(second_pass, icon_id, "AL"));
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: mute_badge_id,
        visible: true,
    }));

    Ok(())
}

#[test]
fn power_scene_reuses_rows_and_hides_stale_entries_without_rebuild() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&power_screen_model(
        "Battery 88%",
        &[
            ("battery", "Battery 88%", "Charging", true),
            ("network", "Network", "Connected", false),
        ],
    ))?;
    let first_len = renderer.facade().events().len();

    renderer.render(&power_screen_model(
        "Battery 64%",
        &[("battery", "Battery 64%", "On battery", true)],
    ))?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let row_ids = created_container_ids(events, "power_row");
    let row_title_ids: Vec<_> = events
        .iter()
        .filter_map(|event| match event {
            FacadeEvent::CreateLabel { id, role, .. } if *role == "power_row_title" => Some(*id),
            _ => None,
        })
        .collect();

    assert_eq!(renderer.active_scene(), Some(SceneKey::Power));
    assert_eq!(renderer.active_screen(), Some(UiScreen::Power));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. }
            | FacadeEvent::CreateContainer { .. }
            | FacadeEvent::CreateLabel { .. }
    )));
    assert_eq!(row_ids.len(), 5);
    assert_eq!(row_title_ids.len(), 5);
    assert!(has_text(second_pass, row_title_ids[0], "Battery 64%"));
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[0],
        visible: true,
    }));
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: row_ids[1],
        visible: false,
    }));

    Ok(())
}

#[test]
fn overlay_scene_reuses_widgets_and_toggles_footer_visibility() -> Result<()> {
    let facade = FakeFacade::default();
    let mut renderer = LvglRenderer::new(facade);

    renderer.render(&loading_screen_model("Booting services"))?;
    let first_len = renderer.facade().events().len();

    renderer.render(&error_screen_model("Network unavailable"))?;

    let events = renderer.facade().events();
    let second_pass = &events[first_len..];
    let footer_id = events
        .iter()
        .find_map(|event| match event {
            FacadeEvent::CreateLabel { id, role, .. } if *role == "overlay_footer" => Some(*id),
            _ => None,
        })
        .expect("overlay footer widget should exist");

    assert_eq!(renderer.active_scene(), Some(SceneKey::Overlay));
    assert_eq!(renderer.active_screen(), Some(UiScreen::Error));
    assert!(!second_pass.iter().any(|event| matches!(
        event,
        FacadeEvent::CreateRoot { .. } | FacadeEvent::CreateLabel { .. }
    )));
    assert!(second_pass.contains(&FacadeEvent::SetText {
        id: WidgetId::new(1),
        text: "Error".to_string(),
    }));
    assert!(second_pass.contains(&FacadeEvent::SetText {
        id: WidgetId::new(2),
        text: "Network unavailable".to_string(),
    }));
    assert!(second_pass.contains(&FacadeEvent::SetText {
        id: footer_id,
        text: "Hold = Back".to_string(),
    }));
    assert!(second_pass.contains(&FacadeEvent::SetVisible {
        id: footer_id,
        visible: true,
    }));

    Ok(())
}

fn hub_screen_model(titles: &[&str], selected_index: usize) -> ScreenModel {
    ScreenModel::Hub(HubViewModel {
        chrome: chrome_model(),
        cards: titles
            .iter()
            .map(|title| HubCardModel {
                key: title.to_lowercase(),
                title: (*title).to_string(),
                subtitle: format!("{title} subtitle"),
                accent: 0x00FF88,
            })
            .collect(),
        selected_index,
    })
}

fn listen_screen_model() -> ScreenModel {
    ScreenModel::Listen(ListScreenModel {
        chrome: chrome_model(),
        title: "Listen".to_string(),
        subtitle: "Music".to_string(),
        rows: vec![
            ListRowModel {
                id: "now_playing".to_string(),
                title: "Now Playing".to_string(),
                subtitle: "Track A".to_string(),
                icon_key: "track".to_string(),
                selected: true,
            },
            ListRowModel {
                id: "playlists".to_string(),
                title: "Playlists".to_string(),
                subtitle: "Saved mixes".to_string(),
                icon_key: "playlist".to_string(),
                selected: false,
            },
        ],
    })
}

fn many_listen_rows_screen_model(selected_index: usize) -> ScreenModel {
    ScreenModel::Listen(ListScreenModel {
        chrome: chrome_model(),
        title: "Listen".to_string(),
        subtitle: "Music".to_string(),
        rows: (0..5)
            .map(|index| ListRowModel {
                id: format!("listen_{index}"),
                title: format!("Listen Item {}", index + 1),
                subtitle: format!("Action {}", index + 1),
                icon_key: "playlist".to_string(),
                selected: index == selected_index,
            })
            .collect(),
    })
}

fn playlists_screen_model() -> ScreenModel {
    ScreenModel::Playlists(ListScreenModel {
        chrome: chrome_model(),
        title: "Playlists".to_string(),
        subtitle: "Saved mixes".to_string(),
        rows: vec![
            ListRowModel {
                id: "favorites".to_string(),
                title: "Favorites".to_string(),
                subtitle: "12 tracks".to_string(),
                icon_key: "playlist".to_string(),
                selected: false,
            },
            ListRowModel {
                id: "driving".to_string(),
                title: "Driving".to_string(),
                subtitle: "28 tracks".to_string(),
                icon_key: "playlist".to_string(),
                selected: true,
            },
        ],
    })
}

fn many_playlist_rows_screen_model(selected_index: usize) -> ScreenModel {
    ScreenModel::Playlists(ListScreenModel {
        chrome: chrome_model(),
        title: "Playlists".to_string(),
        subtitle: "Saved mixes".to_string(),
        rows: (0..5)
            .map(|index| ListRowModel {
                id: format!("playlist_{index}"),
                title: format!("Playlist {}", index + 1),
                subtitle: format!("{} tracks", 10 + index),
                icon_key: "playlist".to_string(),
                selected: index == selected_index,
            })
            .collect(),
    })
}

fn recent_tracks_screen_model() -> ScreenModel {
    ScreenModel::RecentTracks(ListScreenModel {
        chrome: chrome_model(),
        title: "Recent".to_string(),
        subtitle: "Recently played".to_string(),
        rows: vec![ListRowModel {
            id: "track_b".to_string(),
            title: "Track B".to_string(),
            subtitle: "Yesterday".to_string(),
            icon_key: "recent".to_string(),
            selected: true,
        }],
    })
}

fn ask_screen_model() -> ScreenModel {
    ScreenModel::Ask(yoyopod_ui_host::screens::AskViewModel {
        chrome: ChromeModel {
            footer: "2x Tap = Ask | Hold = Back".to_string(),
            ..chrome_model()
        },
        title: "Ask".to_string(),
        subtitle: "What do you want to know?".to_string(),
        icon_key: "ask".to_string(),
    })
}

fn voice_note_screen_model() -> ScreenModel {
    ScreenModel::VoiceNote(yoyopod_ui_host::screens::AskViewModel {
        chrome: ChromeModel {
            footer: "2x Tap = Record | Hold = Back".to_string(),
            ..chrome_model()
        },
        title: "Voice Note".to_string(),
        subtitle: "Ready to record".to_string(),
        icon_key: "microphone".to_string(),
    })
}

fn now_playing_screen_model(
    title: &str,
    artist: &str,
    state_text: &str,
    progress_permille: i32,
) -> ScreenModel {
    ScreenModel::NowPlaying(yoyopod_ui_host::screens::NowPlayingViewModel {
        chrome: ChromeModel {
            footer: "Tap = Next | 2x Tap = Play/Pause | Hold = Back".to_string(),
            ..chrome_model()
        },
        title: title.to_string(),
        artist: artist.to_string(),
        state_text: state_text.to_string(),
        progress_permille,
    })
}

fn incoming_call_screen_model() -> ScreenModel {
    ScreenModel::IncomingCall(CallViewModel {
        chrome: chrome_model(),
        title: "Alice".to_string(),
        subtitle: "+1 555-0100".to_string(),
        detail: "Incoming Call".to_string(),
        muted: false,
    })
}

fn in_call_screen_model() -> ScreenModel {
    ScreenModel::InCall(CallViewModel {
        chrome: ChromeModel {
            footer: "Tap = Mute | Hold = Hang Up".to_string(),
            ..chrome_model()
        },
        title: "Alice".to_string(),
        subtitle: "00:42".to_string(),
        detail: "+1 555-0100".to_string(),
        muted: true,
    })
}

fn power_screen_model(subtitle: &str, rows: &[(&str, &str, &str, bool)]) -> ScreenModel {
    ScreenModel::Power(PowerViewModel {
        chrome: ChromeModel {
            footer: "Tap = Next | Hold = Back".to_string(),
            ..chrome_model()
        },
        title: "Status".to_string(),
        subtitle: subtitle.to_string(),
        rows: rows
            .iter()
            .map(|(id, title, row_subtitle, selected)| ListRowModel {
                id: (*id).to_string(),
                title: (*title).to_string(),
                subtitle: (*row_subtitle).to_string(),
                icon_key: (*id).to_string(),
                selected: *selected,
            })
            .collect(),
    })
}

fn loading_screen_model(subtitle: &str) -> ScreenModel {
    ScreenModel::Loading(OverlayViewModel {
        chrome: ChromeModel {
            footer: String::new(),
            ..chrome_model()
        },
        title: "Loading".to_string(),
        subtitle: subtitle.to_string(),
    })
}

fn error_screen_model(subtitle: &str) -> ScreenModel {
    ScreenModel::Error(OverlayViewModel {
        chrome: ChromeModel {
            footer: "Hold = Back".to_string(),
            ..chrome_model()
        },
        title: "Error".to_string(),
        subtitle: subtitle.to_string(),
    })
}

fn chrome_model() -> ChromeModel {
    ChromeModel {
        status: StatusBarModel {
            network_connected: true,
            network_enabled: true,
            signal_strength: 4,
            battery_percent: 88,
            charging: false,
            voip_state: 1,
        },
        footer: "Footer".to_string(),
    }
}
