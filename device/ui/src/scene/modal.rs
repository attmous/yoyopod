use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::ElementKind;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Modal {
    Loading { spinner_step: u8 },
    Error { retryable: bool },
}

impl Modal {
    pub fn element(&self, index: usize) -> Element {
        match self {
            Self::Loading { spinner_step } => loading_content(index, *spinner_step),
            Self::Error { retryable } => error_content(index, *retryable),
        }
    }
}

const INK: u32 = 0x1B1B1F;
const INK_SOFT: u32 = 0x3A3A40;
const BUTTER: u32 = 0xFFD06A;
const TOMATO: u32 = 0xE5443B;
const DOT_RECTS: [(i32, i32); 8] = [
    (117, 93),
    (130, 98),
    (135, 111),
    (130, 124),
    (117, 129),
    (104, 124),
    (99, 111),
    (104, 98),
];
const DOT_OPACITY: [u8; 8] = [255, 226, 197, 168, 139, 110, 80, 51];

fn overlay_root(index: usize) -> Element {
    Element::new(ElementKind::Container, Some(roles::MODAL))
        .key(Key::Indexed(index))
        .child(
            Element::new(ElementKind::Container, Some(roles::SYS_SCRIM))
                .key(Key::Static("system_scrim")),
        )
}

fn loading_content(index: usize, spinner_step: u8) -> Element {
    DOT_RECTS.iter().enumerate().fold(
        overlay_root(index).child(
            Element::new(ElementKind::Label, Some(roles::SYS_MSG))
                .key(Key::Static("system_message"))
                .text("One moment...")
                .accent(INK_SOFT)
                .absolute(20, 150, 200, 16),
        ),
        |overlay, (dot_index, (x, y))| {
            let trail_index = (dot_index + 8 - usize::from(spinner_step % 8)) % 8;
            overlay.child(
                Element::new(ElementKind::Container, Some(roles::SYS_SPINNER_DOT))
                    .key(Key::Indexed(dot_index))
                    .opacity(DOT_OPACITY[trail_index])
                    .absolute(*x, *y, 6, 6),
            )
        },
    )
}

fn error_content(index: usize, retryable: bool) -> Element {
    let (badge, message) = if retryable {
        (BUTTER, "Oops, something went wrong.\nLet's try again!")
    } else {
        (
            TOMATO,
            "That's not working right now.\nAsk a grown-up to help!",
        )
    };
    overlay_root(index)
        .child(
            Element::new(ElementKind::Label, Some(roles::SYS_BADGE))
                .key(Key::Static("system_badge"))
                .text("!")
                .accent(badge),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::SYS_MSG))
                .key(Key::Static("system_message"))
                .text(message)
                .accent(INK),
        )
}
