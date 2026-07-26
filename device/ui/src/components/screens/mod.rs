pub mod ask;
pub mod call_history;
pub mod chrome;
pub mod common;
pub mod contacts;
pub mod error;
pub mod hub;
pub mod in_call;
pub mod incoming_call;
pub mod listen;
pub mod loading;
mod media_wheel;
pub mod now_playing;
pub mod outgoing_call;
pub mod playlist_tracks;
pub mod playlists;
pub mod recent_tracks;
pub mod replay;
pub mod setup;
pub mod talk;
pub mod talk_contact;
pub mod voice_note;
pub mod watch_face;

use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::scene::{Scene, SceneDefaults};

pub fn scene_for_screen(
    screen: UiScreen,
    snapshot: &RuntimeSnapshot,
    focus: usize,
    selected_playlist: Option<&ListItemSnapshot>,
    selected_contact: Option<&ListItemSnapshot>,
    replay_index: usize,
    defaults: SceneDefaults,
) -> Scene {
    let scene = match screen {
        UiScreen::Hub => hub::scene(&hub::props_from(snapshot, focus, defaults.clone())),
        UiScreen::Listen => listen::scene(&listen::props_from(snapshot, focus, defaults.clone())),
        UiScreen::Playlists => {
            playlists::scene(&playlists::props_from(snapshot, focus, defaults.clone()))
        }
        UiScreen::PlaylistTracks => playlist_tracks::scene(&playlist_tracks::props_from(
            snapshot,
            focus,
            selected_playlist,
            defaults.clone(),
        )),
        UiScreen::RecentTracks => recent_tracks::scene(&recent_tracks::props_from(
            snapshot,
            focus,
            defaults.clone(),
        )),
        UiScreen::NowPlaying => {
            now_playing::scene(&now_playing::props_from(snapshot, focus, defaults.clone()))
        }
        UiScreen::Ask => ask::scene(&ask::props_from(snapshot, focus, defaults.clone())),
        UiScreen::Talk => talk::scene(&talk::props_from(snapshot, focus, defaults.clone())),
        UiScreen::Contacts => {
            contacts::scene(&contacts::props_from(snapshot, focus, defaults.clone()))
        }
        UiScreen::CallHistory => {
            call_history::scene(&call_history::props_from(snapshot, focus, defaults.clone()))
        }
        UiScreen::TalkContact => talk_contact::scene(&talk_contact::props_from(
            snapshot,
            focus,
            selected_contact,
            defaults.clone(),
        )),
        UiScreen::Replay => replay::scene(&replay::props_from(
            snapshot,
            focus,
            selected_contact,
            replay_index,
            defaults.clone(),
        )),
        UiScreen::VoiceNote => {
            voice_note::scene(&voice_note::props_from(snapshot, focus, defaults.clone()))
        }
        UiScreen::IncomingCall => incoming_call::scene(&incoming_call::props_from(
            snapshot,
            focus,
            defaults.clone(),
        )),
        UiScreen::OutgoingCall => outgoing_call::scene(&outgoing_call::props_from(
            snapshot,
            focus,
            defaults.clone(),
        )),
        UiScreen::InCall => in_call::scene(&in_call::props_from(snapshot, focus, defaults.clone())),
        UiScreen::Setup
        | UiScreen::SetupVolume
        | UiScreen::SetupCompanion
        | UiScreen::SetupContacts
        | UiScreen::SetupTheme
        | UiScreen::SetupAbout
        | UiScreen::SetupWifi => setup::scene(screen, snapshot, focus, defaults.clone()),
        UiScreen::Loading => loading::scene(&loading::props_from(snapshot, defaults.clone())),
        UiScreen::Error => error::scene(&error::props_from(snapshot, defaults.clone())),
    };
    with_scene_timelines(&defaults, scene)
}

fn with_scene_timelines(defaults: &crate::scene::SceneDefaults, mut scene: Scene) -> Scene {
    let scene_timelines = defaults.scene_timelines(&scene.decks);
    scene.timelines.splice(0..0, scene_timelines);
    for (deck_index, deck) in scene.decks.iter().enumerate() {
        if let Some(timeline) = deck.swap_timeline() {
            scene.timelines.push(timeline);
        }
        if let Some(timeline) = deck.item_timeline(deck_index) {
            scene.timelines.push(timeline);
        }
    }
    scene
}
