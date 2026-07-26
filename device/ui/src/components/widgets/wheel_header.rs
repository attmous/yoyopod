use crate::components::primitives::{container, label};
use crate::engine::Key;
use crate::scene::{roles, WheelHeaderModel};

pub fn wheel_header(model: &WheelHeaderModel) -> crate::engine::Element {
    let header = container(roles::MEDIA_WHEEL_HEADER)
        .key(Key::Static("media_wheel_header"))
        .child(label(roles::MEDIA_WHEEL_HEADER_TITLE).text(&model.title))
        .child(container(roles::MEDIA_WHEEL_HEADER_DIVIDER));

    match model.counter.as_deref() {
        Some(counter) => header.child(label(roles::MEDIA_WHEEL_HEADER_COUNTER).text(counter)),
        None => header,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counter_is_a_separate_header_label() {
        let element = wheel_header(&WheelHeaderModel::new("HOLST", Some("1 / 3".to_string())));

        assert_eq!(element.role, Some(roles::MEDIA_WHEEL_HEADER));
        assert_eq!(element.children.len(), 3);
        assert_eq!(
            element.children[0].role,
            Some(roles::MEDIA_WHEEL_HEADER_TITLE)
        );
        assert_eq!(
            element.children[1].role,
            Some(roles::MEDIA_WHEEL_HEADER_DIVIDER)
        );
        assert_eq!(
            element.children[2].role,
            Some(roles::MEDIA_WHEEL_HEADER_COUNTER)
        );
    }
}
