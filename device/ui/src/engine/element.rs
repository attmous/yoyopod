use crate::animation::{ActorRef, TimelineRef, TrackIndex};
use crate::scene::RegionId;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct NodeId(pub u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum ElementKind {
    Container,
    Label,
    Image,
    Progress,
    Arc,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Key {
    Static(&'static str),
    Indexed(usize),
    Scene {
        screen: &'static str,
        generation: u32,
    },
    String(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Element {
    pub key: Option<Key>,
    pub kind: ElementKind,
    pub role: Option<&'static str>,
    pub props: ElementProps,
    pub layout: Layout,
    pub actor: Option<ActorRef>,
    pub anim: Option<AnimSlot>,
    pub children: Vec<Element>,
}

impl Element {
    pub fn new(kind: ElementKind, role: Option<&'static str>) -> Self {
        Self {
            key: None,
            kind,
            role,
            props: ElementProps::default(),
            layout: Layout::Region(RegionId::Auto),
            actor: None,
            anim: None,
            children: Vec::new(),
        }
    }

    pub fn text(mut self, text: impl Into<String>) -> Self {
        self.props.text = Some(text.into());
        self
    }

    pub fn icon(mut self, icon_key: impl Into<String>) -> Self {
        self.props.icon_key = Some(icon_key.into());
        self
    }

    pub fn accent(mut self, accent: u32) -> Self {
        self.props.accent = Some(accent);
        self
    }

    pub fn selected(mut self, selected: bool) -> Self {
        self.props.selected = Some(selected);
        self
    }

    pub fn visible(mut self, visible: bool) -> Self {
        self.props.visible = Some(visible);
        self
    }

    pub fn progress(mut self, progress: i32) -> Self {
        self.props.progress = Some(progress);
        self
    }

    pub fn scale_permille(mut self, scale_permille: i32) -> Self {
        self.props.scale_permille = Some(scale_permille);
        self
    }

    pub fn opacity(mut self, opacity: u8) -> Self {
        self.props.opacity = Some(opacity);
        self
    }

    pub fn offset_y(mut self, offset: i32) -> Self {
        self.props.offset_y = Some(offset);
        self
    }

    pub fn key(mut self, key: Key) -> Self {
        self.key = Some(key);
        self
    }

    pub fn child(mut self, element: Element) -> Self {
        self.children.push(element);
        self
    }

    pub fn region(mut self, region: RegionId) -> Self {
        self.layout = Layout::Region(region);
        self
    }

    pub fn with_anim(mut self, anim: AnimSlot) -> Self {
        self.anim = Some(anim);
        self
    }

    pub fn actor(mut self, actor: ActorRef) -> Self {
        self.actor = Some(actor);
        self
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ElementProps {
    pub text: Option<String>,
    pub icon_key: Option<String>,
    pub accent: Option<u32>,
    pub selected: Option<bool>,
    pub visible: Option<bool>,
    pub opacity: Option<u8>,
    pub offset_y: Option<i32>,
    pub scale_permille: Option<i32>,
    pub variant: Option<&'static str>,
    pub progress: Option<i32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Layout {
    Absolute { x: i32, y: i32, w: i32, h: i32 },
    Region(RegionId),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AnimSlot {
    pub timeline: TimelineRef,
    pub track: TrackIndex,
}
