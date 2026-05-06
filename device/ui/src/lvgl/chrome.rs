use crate::screens::{HubCardModel, HubViewModel};

pub(crate) fn focused_hub_card(model: &HubViewModel) -> Option<&HubCardModel> {
    model
        .cards
        .get(model.selected_index)
        .or_else(|| model.cards.first())
}

pub(crate) fn focused_hub_title(model: &HubViewModel) -> &str {
    focused_hub_card(model)
        .map(|card| card.title.as_str())
        .unwrap_or("Listen")
}
