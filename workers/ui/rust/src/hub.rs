use anyhow::{bail, Context, Result};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HubRenderer {
    Auto,
    Lvgl,
    Framebuffer,
}

impl HubRenderer {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Lvgl => "lvgl",
            Self::Framebuffer => "framebuffer",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubSnapshot {
    pub icon_key: String,
    pub title: String,
    pub subtitle: String,
    pub footer: String,
    pub time_text: String,
    pub accent: u32,
    pub selected_index: i32,
    pub total_cards: i32,
    pub voip_state: i32,
    pub battery_percent: i32,
    pub charging: bool,
    pub power_available: bool,
}

impl HubSnapshot {
    pub fn static_default() -> Self {
        Self {
            icon_key: "listen".to_string(),
            title: "Listen".to_string(),
            subtitle: String::new(),
            footer: "Tap = Next | 2x Tap = Open".to_string(),
            time_text: "12:00".to_string(),
            accent: 0x00FF88,
            selected_index: 0,
            total_cards: 4,
            voip_state: 1,
            battery_percent: 100,
            charging: false,
            power_available: true,
        }
    }

    fn from_payload(payload: &Value) -> Result<Self> {
        let default = Self::static_default();
        Ok(Self {
            icon_key: string_field(payload, "icon_key", &default.icon_key)?,
            title: string_field(payload, "title", &default.title)?,
            subtitle: string_field(payload, "subtitle", &default.subtitle)?,
            footer: string_field(payload, "footer", &default.footer)?,
            time_text: string_field(payload, "time_text", &default.time_text)?,
            accent: u32_field(payload, "accent", default.accent)?,
            selected_index: i32_field(payload, "selected_index", default.selected_index)?,
            total_cards: i32_field(payload, "total_cards", default.total_cards)?.clamp(1, 4),
            voip_state: i32_field(payload, "voip_state", default.voip_state)?.clamp(0, 2),
            battery_percent: i32_field(payload, "battery_percent", default.battery_percent)?
                .clamp(0, 100),
            charging: bool_field(payload, "charging", default.charging)?,
            power_available: bool_field(payload, "power_available", default.power_available)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubCommand {
    pub renderer: HubRenderer,
    pub snapshot: HubSnapshot,
}

impl HubCommand {
    pub fn from_payload(payload: &Value) -> Result<Self> {
        if !payload.is_object() {
            bail!("Hub payload must be a JSON object");
        }
        Ok(Self {
            renderer: renderer_field(payload)?,
            snapshot: HubSnapshot::from_payload(payload)?,
        })
    }
}

fn renderer_field(payload: &Value) -> Result<HubRenderer> {
    match payload
        .get("renderer")
        .and_then(Value::as_str)
        .unwrap_or("auto")
    {
        "auto" => Ok(HubRenderer::Auto),
        "lvgl" => Ok(HubRenderer::Lvgl),
        "framebuffer" => Ok(HubRenderer::Framebuffer),
        value => bail!("unknown Hub renderer {value:?}"),
    }
}

fn string_field(payload: &Value, name: &str, default: &str) -> Result<String> {
    match payload.get(name) {
        Some(value) => value
            .as_str()
            .map(ToString::to_string)
            .with_context(|| format!("Hub field {name} must be a string")),
        None => Ok(default.to_string()),
    }
}

fn u32_field(payload: &Value, name: &str, default: u32) -> Result<u32> {
    match payload.get(name) {
        Some(value) => {
            let raw = value
                .as_u64()
                .with_context(|| format!("Hub field {name} must be an integer"))?;
            u32::try_from(raw).with_context(|| format!("Hub field {name} exceeds u32"))
        }
        None => Ok(default),
    }
}

fn i32_field(payload: &Value, name: &str, default: i32) -> Result<i32> {
    match payload.get(name) {
        Some(value) => {
            let raw = value
                .as_i64()
                .with_context(|| format!("Hub field {name} must be an integer"))?;
            i32::try_from(raw).with_context(|| format!("Hub field {name} exceeds i32"))
        }
        None => Ok(default),
    }
}

fn bool_field(payload: &Value, name: &str, default: bool) -> Result<bool> {
    match payload.get(name) {
        Some(value) => value
            .as_bool()
            .with_context(|| format!("Hub field {name} must be a boolean")),
        None => Ok(default),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn default_snapshot_matches_python_hub_sync_contract() {
        let command = HubCommand::from_payload(&json!({})).expect("default hub command");

        assert_eq!(command.renderer, HubRenderer::Auto);
        assert_eq!(command.snapshot.icon_key, "listen");
        assert_eq!(command.snapshot.title, "Listen");
        assert_eq!(command.snapshot.subtitle, "");
        assert_eq!(command.snapshot.footer, "Tap = Next | 2x Tap = Open");
        assert_eq!(command.snapshot.time_text, "12:00");
        assert_eq!(command.snapshot.accent, 0x00FF88);
        assert_eq!(command.snapshot.selected_index, 0);
        assert_eq!(command.snapshot.total_cards, 4);
        assert_eq!(command.snapshot.voip_state, 1);
        assert_eq!(command.snapshot.battery_percent, 100);
        assert!(!command.snapshot.charging);
        assert!(command.snapshot.power_available);
    }

    #[test]
    fn parses_explicit_python_hub_sync_fields() {
        let command = HubCommand::from_payload(&json!({
            "renderer": "lvgl",
            "icon_key": "talk",
            "title": "Talk",
            "subtitle": "Ready",
            "footer": "Tap = Next | 2x Tap = Open",
            "time_text": "17:42",
            "accent": 0x00D4FF,
            "selected_index": 1,
            "total_cards": 4,
            "voip_state": 2,
            "battery_percent": 77,
            "charging": true,
            "power_available": false
        }))
        .expect("hub command");

        assert_eq!(command.renderer, HubRenderer::Lvgl);
        assert_eq!(command.snapshot.icon_key, "talk");
        assert_eq!(command.snapshot.title, "Talk");
        assert_eq!(command.snapshot.subtitle, "Ready");
        assert_eq!(command.snapshot.time_text, "17:42");
        assert_eq!(command.snapshot.accent, 0x00D4FF);
        assert_eq!(command.snapshot.selected_index, 1);
        assert_eq!(command.snapshot.voip_state, 2);
        assert_eq!(command.snapshot.battery_percent, 77);
        assert!(command.snapshot.charging);
        assert!(!command.snapshot.power_available);
    }

    #[test]
    fn rejects_unknown_renderer() {
        let error = HubCommand::from_payload(&json!({"renderer": "slint"}))
            .expect_err("unknown renderer must fail");

        assert!(error.to_string().contains("unknown Hub renderer"));
    }
}
