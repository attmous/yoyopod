use yoyopod_ui_host::input::{ButtonTiming, InputAction, InputEvent, OneButtonMachine};

fn machine() -> OneButtonMachine {
    OneButtonMachine::new(ButtonTiming::default())
}

#[test]
fn single_tap_emits_advance_after_double_tap_window() {
    let mut machine = machine();

    assert!(machine.observe(false, 0).is_empty());
    assert!(machine.observe(true, 10).is_empty());
    assert!(machine.observe(false, 80).is_empty());
    let events = machine.tick(381);

    assert_eq!(events, vec![InputEvent::advance(80)]);
}

#[test]
fn double_tap_emits_select() {
    let mut machine = machine();

    machine.observe(true, 10);
    machine.observe(false, 80);
    machine.observe(true, 180);
    machine.observe(false, 230);
    let events = machine.tick(280);

    assert_eq!(events, vec![InputEvent::select(50)]);
    assert!(machine.tick(600).is_empty());
}

#[test]
fn long_hold_emits_back_once_at_threshold() {
    let mut machine = machine();

    machine.observe(true, 100);
    let first = machine.tick(900);
    let second = machine.tick(950);
    let release = machine.observe(false, 1000);

    assert_eq!(first, vec![InputEvent::back(800)]);
    assert!(second.is_empty());
    assert!(release
        .iter()
        .all(|event| event.action != InputAction::Back));
}

#[test]
fn debounce_filters_short_transition_noise() {
    let mut machine = machine();

    machine.observe(true, 10);
    machine.observe(false, 30);
    let events = machine.tick(400);

    assert!(events.is_empty());
}
