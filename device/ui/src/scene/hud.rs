use crate::engine::Element;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HudScene {
    root: Element,
}

impl HudScene {
    pub fn new(root: Element) -> Self {
        Self { root }
    }

    pub fn element(&self) -> Element {
        self.root.clone()
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct HudStatus {
    pub time: String,
    pub connectivity: HudConnectivity,
    pub gps_has_fix: bool,
    pub voip_registered: bool,
    pub battery: HudBattery,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum HudConnectivityKind {
    #[default]
    Unknown,
    Cellular,
    Wifi,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct HudConnectivity {
    pub kind: HudConnectivityKind,
    pub connected: bool,
    pub strength: u8,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct HudBattery {
    pub percent: u8,
    pub charging: bool,
    pub available: bool,
}
