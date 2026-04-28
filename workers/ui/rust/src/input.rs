#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputAction {
    Advance,
    Select,
    Back,
    #[allow(dead_code)]
    PttPress,
    #[allow(dead_code)]
    PttRelease,
}

impl InputAction {
    #[allow(dead_code)]
    pub fn as_str(self) -> &'static str {
        match self {
            InputAction::Advance => "advance",
            InputAction::Select => "select",
            InputAction::Back => "back",
            InputAction::PttPress => "ptt_press",
            InputAction::PttRelease => "ptt_release",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputEvent {
    pub action: InputAction,
    pub method: &'static str,
    pub timestamp_ms: u64,
    pub duration_ms: u64,
}

impl InputEvent {
    pub fn advance(timestamp_ms: u64) -> Self {
        Self {
            action: InputAction::Advance,
            method: "single_tap",
            timestamp_ms,
            duration_ms: 0,
        }
    }

    pub fn select(duration_ms: u64) -> Self {
        Self {
            action: InputAction::Select,
            method: "double_tap",
            timestamp_ms: 0,
            duration_ms,
        }
    }

    pub fn back(duration_ms: u64) -> Self {
        Self {
            action: InputAction::Back,
            method: "long_hold",
            timestamp_ms: 0,
            duration_ms,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ButtonTiming {
    pub debounce_ms: u64,
    pub double_tap_ms: u64,
    pub long_hold_ms: u64,
}

impl Default for ButtonTiming {
    fn default() -> Self {
        Self {
            debounce_ms: 50,
            double_tap_ms: 300,
            long_hold_ms: 800,
        }
    }
}

#[derive(Debug, Clone)]
pub struct OneButtonMachine {
    timing: ButtonTiming,
    debounced_pressed: bool,
    raw_pressed: bool,
    raw_transition_at_ms: Option<u64>,
    press_start_ms: Option<u64>,
    pending_single_tap_ms: Option<u64>,
    double_tap_candidate: bool,
    hold_back_fired: bool,
}

impl OneButtonMachine {
    pub fn new(timing: ButtonTiming) -> Self {
        Self {
            timing,
            debounced_pressed: false,
            raw_pressed: false,
            raw_transition_at_ms: None,
            press_start_ms: None,
            pending_single_tap_ms: None,
            double_tap_candidate: false,
            hold_back_fired: false,
        }
    }

    pub fn observe(&mut self, pressed: bool, now_ms: u64) -> Vec<InputEvent> {
        let events = self.advance(now_ms);
        if pressed != self.raw_pressed {
            self.raw_pressed = pressed;
            self.raw_transition_at_ms = Some(now_ms);
        }
        events
    }

    #[allow(dead_code)]
    pub fn tick(&mut self, now_ms: u64) -> Vec<InputEvent> {
        self.advance(now_ms)
    }

    fn advance(&mut self, now_ms: u64) -> Vec<InputEvent> {
        let mut events = Vec::new();

        if let Some(transition_at_ms) = self.raw_transition_at_ms {
            if now_ms.saturating_sub(transition_at_ms) >= self.timing.debounce_ms {
                self.raw_transition_at_ms = None;
                if self.raw_pressed != self.debounced_pressed {
                    if self.raw_pressed {
                        events.extend(self.handle_press(transition_at_ms));
                    } else {
                        events.extend(self.handle_release(transition_at_ms));
                    }
                }
            }
        }

        if self.debounced_pressed && !self.hold_back_fired {
            if let Some(press_start_ms) = self.press_start_ms {
                let duration = now_ms.saturating_sub(press_start_ms);
                if duration >= self.timing.long_hold_ms {
                    self.hold_back_fired = true;
                    events.push(InputEvent::back(duration));
                }
            }
        }

        if !self.debounced_pressed {
            if let Some(pending_ms) = self.pending_single_tap_ms {
                if now_ms.saturating_sub(pending_ms) >= self.timing.double_tap_ms {
                    self.pending_single_tap_ms = None;
                    events.push(InputEvent::advance(pending_ms));
                }
            }
        }

        events
    }

    fn handle_press(&mut self, now_ms: u64) -> Vec<InputEvent> {
        let mut events = Vec::new();
        self.debounced_pressed = true;
        self.double_tap_candidate = self
            .pending_single_tap_ms
            .map(|pending| now_ms.saturating_sub(pending) < self.timing.double_tap_ms)
            .unwrap_or(false);
        if !self.double_tap_candidate {
            if let Some(pending) = self.pending_single_tap_ms.take() {
                events.push(InputEvent::advance(pending));
            }
        }
        self.press_start_ms = Some(now_ms);
        self.hold_back_fired = false;
        events
    }

    fn handle_release(&mut self, now_ms: u64) -> Vec<InputEvent> {
        self.debounced_pressed = false;
        let duration = self
            .press_start_ms
            .map(|started| now_ms.saturating_sub(started))
            .unwrap_or(0);
        self.press_start_ms = None;

        if self.hold_back_fired || duration >= self.timing.long_hold_ms {
            self.pending_single_tap_ms = None;
            self.double_tap_candidate = false;
            self.hold_back_fired = false;
            return Vec::new();
        }

        if self.double_tap_candidate {
            self.pending_single_tap_ms = None;
            self.double_tap_candidate = false;
            return vec![InputEvent::select(duration)];
        }

        self.pending_single_tap_ms = Some(now_ms);
        self.double_tap_candidate = false;
        Vec::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
