use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::deck::RowModel;
use crate::scene::roles;

pub fn list_row(row: &RowModel, selected: bool, key: Key) -> Element {
    let focused = row.selected || selected;
    let foreground = ListRowForegroundRoles::for_focused(focused);
    container(roles::LIST_ROW)
        .key(key)
        .selected(focused)
        .child(image(foreground.icon).icon(&row.icon_key).accent(0x1B1B1F))
        .child(label(foreground.title).text(&row.title))
        .child(label(foreground.subtitle).text(&row.subtitle))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ListRowForegroundRoles {
    icon: &'static str,
    title: &'static str,
    subtitle: &'static str,
}

impl ListRowForegroundRoles {
    const fn for_focused(focused: bool) -> Self {
        if focused {
            Self {
                icon: roles::LIST_ROW_FOCUS_ICON,
                title: roles::LIST_ROW_FOCUS_TITLE,
                subtitle: roles::LIST_ROW_FOCUS_SUBTITLE,
            }
        } else {
            Self {
                icon: roles::LIST_ROW_IDLE_ICON,
                title: roles::LIST_ROW_IDLE_TITLE,
                subtitle: roles::LIST_ROW_IDLE_SUBTITLE,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row() -> RowModel {
        RowModel {
            id: "mama".to_string(),
            title: "Mama".to_string(),
            subtitle: "Available".to_string(),
            icon_key: "call".to_string(),
            selected: false,
        }
    }

    #[test]
    fn list_rows_expose_focus_context_to_every_foreground_child() {
        let focus = list_row(&row(), true, Key::Indexed(0));
        let idle = list_row(&row(), false, Key::Indexed(0));

        assert_eq!(focus.children[0].role, Some(roles::LIST_ROW_FOCUS_ICON));
        assert_eq!(focus.children[1].role, Some(roles::LIST_ROW_FOCUS_TITLE));
        assert_eq!(focus.children[2].role, Some(roles::LIST_ROW_FOCUS_SUBTITLE));
        assert_eq!(idle.children[0].role, Some(roles::LIST_ROW_IDLE_ICON));
        assert_eq!(idle.children[1].role, Some(roles::LIST_ROW_IDLE_TITLE));
        assert_eq!(idle.children[2].role, Some(roles::LIST_ROW_IDLE_SUBTITLE));
    }
}
