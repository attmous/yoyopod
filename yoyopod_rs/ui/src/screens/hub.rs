use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};
use crate::screens::{chrome, HubCardModel, HubViewModel};

pub fn model(snapshot: &RuntimeSnapshot, focus_index: usize) -> HubViewModel {
    HubViewModel {
        chrome: chrome::chrome(snapshot, "Tap = Next | 2x Tap = Open"),
        cards: snapshot
            .hub
            .cards
            .iter()
            .map(|card| HubCardModel {
                key: card.key.clone(),
                title: card.title.clone(),
                subtitle: card.subtitle.clone(),
                accent: card.accent,
            })
            .collect(),
        selected_index: focus_index,
    }
}

pub fn view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    let cards = snapshot.hub.cards.clone();
    let focused = cards.get(focus_index).or_else(|| cards.first());

    UiView {
        screen: UiScreen::Hub,
        title: focused
            .map(|card| card.title.clone())
            .unwrap_or_else(|| "Listen".to_string()),
        subtitle: focused
            .map(|card| card.subtitle.clone())
            .unwrap_or_else(String::new),
        footer: "Tap = Next | 2x Tap = Open".to_string(),
        items: cards
            .iter()
            .map(|card| {
                ListItemSnapshot::new(
                    card.key.clone(),
                    card.title.clone(),
                    card.subtitle.clone(),
                    card.key.clone(),
                )
            })
            .collect(),
        focus_index,
    }
}
