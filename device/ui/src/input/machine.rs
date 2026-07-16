use yoyopod_protocol::ui::InputAction;

use super::config::ButtonTiming;

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

    pub fn home(duration_ms: u64) -> Self {
        Self {
            action: InputAction::Home,
            method: "long_hold",
            timestamp_ms: 0,
            duration_ms,
        }
    }

    pub fn ptt_press(duration_ms: u64) -> Self {
        Self {
            action: InputAction::PttPress,
            method: "hold_started",
            timestamp_ms: 0,
            duration_ms,
        }
    }

    pub fn ptt_release(duration_ms: u64) -> Self {
        Self {
            action: InputAction::PttRelease,
            method: "hold_released",
            timestamp_ms: 0,
            duration_ms,
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

    pub fn observe_ptt_passthrough(&mut self, pressed: bool, now_ms: u64) -> Vec<InputEvent> {
        let events = self.advance_ptt_passthrough(now_ms);
        if pressed != self.raw_pressed {
            self.raw_pressed = pressed;
            self.raw_transition_at_ms = Some(now_ms);
        }
        events
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
                    events.push(InputEvent::home(duration));
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

    fn advance_ptt_passthrough(&mut self, now_ms: u64) -> Vec<InputEvent> {
        let mut events = Vec::new();

        if let Some(transition_at_ms) = self.raw_transition_at_ms {
            if now_ms.saturating_sub(transition_at_ms) >= self.timing.debounce_ms {
                self.raw_transition_at_ms = None;
                if self.raw_pressed != self.debounced_pressed {
                    if self.raw_pressed {
                        events.extend(self.handle_press(transition_at_ms));
                    } else {
                        events.extend(self.handle_ptt_release(transition_at_ms));
                    }
                }
            }
        }

        if self.debounced_pressed && !self.hold_back_fired {
            if let Some(press_start_ms) = self.press_start_ms {
                let duration = now_ms.saturating_sub(press_start_ms);
                if duration >= self.timing.long_hold_ms {
                    self.hold_back_fired = true;
                    self.pending_single_tap_ms = None;
                    self.double_tap_candidate = false;
                    events.push(InputEvent::ptt_press(duration));
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

        if duration >= self.timing.short_press_max_ms {
            self.pending_single_tap_ms = None;
            self.double_tap_candidate = false;
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

    fn handle_ptt_release(&mut self, now_ms: u64) -> Vec<InputEvent> {
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
            return vec![InputEvent::ptt_release(duration)];
        }

        if duration >= self.timing.short_press_max_ms {
            self.pending_single_tap_ms = None;
            self.double_tap_candidate = false;
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

    fn actions(events: Vec<InputEvent>) -> Vec<InputAction> {
        events.into_iter().map(|event| event.action).collect()
    }

    fn tap(machine: &mut OneButtonMachine, pressed_at: u64, released_at: u64) -> Vec<InputEvent> {
        let mut events = machine.observe(true, pressed_at);
        events.extend(machine.observe(true, pressed_at + 50));
        events.extend(machine.observe(false, released_at));
        events.extend(machine.observe(false, released_at + 50));
        events
    }

    #[test]
    fn short_press_advances_after_double_window() {
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        tap(&mut machine, 0, 100);

        assert_eq!(
            actions(machine.observe(false, 451)),
            vec![InputAction::Advance]
        );
    }

    #[test]
    fn double_press_selects() {
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        tap(&mut machine, 0, 100);
        assert_eq!(
            actions(tap(&mut machine, 220, 320)),
            vec![InputAction::Select]
        );
    }

    #[test]
    fn medium_press_is_dead_zone() {
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        tap(&mut machine, 0, 250);

        assert!(machine.observe(false, 700).is_empty());
    }

    #[test]
    fn long_press_goes_home_once() {
        let mut machine = OneButtonMachine::new(ButtonTiming::default());
        machine.observe(true, 0);
        machine.observe(true, 50);

        assert_eq!(actions(machine.observe(true, 400)), vec![InputAction::Home]);
        assert!(machine.observe(true, 700).is_empty());
        machine.observe(false, 750);
        assert!(machine.observe(false, 800).is_empty());
    }
}
