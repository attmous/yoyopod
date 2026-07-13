//! Result model + summary printer for validation stages.
//!
//! Ports `_CheckResult` / `_print_summary` from the deleted
//! `yoyopod_cli/pi/validate/_common.py`. The summary format is kept
//! byte-compatible so operators (and log-scraping tooling) see the
//! same output the Python suite produced.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckStatus {
    Pass,
    Warn,
    Fail,
}

impl fmt::Display for CheckStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let text = match self {
            Self::Pass => "PASS",
            Self::Warn => "WARN",
            Self::Fail => "FAIL",
        };
        write!(f, "{text}")
    }
}

#[derive(Debug, Clone)]
pub struct CheckResult {
    pub name: String,
    pub status: CheckStatus,
    pub details: String,
}

impl CheckResult {
    pub fn pass(name: impl Into<String>, details: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Pass,
            details: details.into(),
        }
    }

    pub fn warn(name: impl Into<String>, details: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Warn,
            details: details.into(),
        }
    }

    pub fn fail(name: impl Into<String>, details: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            status: CheckStatus::Fail,
            details: details.into(),
        }
    }
}

/// Print the compact summary table for one validation stage.
pub fn print_summary(stage: &str, results: &[CheckResult]) {
    println!();
    println!("YoYoPod target validation summary: {stage}");
    println!("{}", "=".repeat(48));
    for result in results {
        println!("[{}] {}: {}", result.status, result.name, result.details);
    }
}

/// Stage exit code: 1 when any check failed, 0 otherwise (warns pass).
pub fn exit_code(results: &[CheckResult]) -> i32 {
    if results.iter().any(|r| r.status == CheckStatus::Fail) {
        1
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exit_code_fails_on_any_fail() {
        let results = vec![
            CheckResult::pass("a", "ok"),
            CheckResult::fail("b", "broken"),
        ];
        assert_eq!(exit_code(&results), 1);
    }

    #[test]
    fn exit_code_passes_with_warns() {
        let results = vec![CheckResult::pass("a", "ok"), CheckResult::warn("b", "meh")];
        assert_eq!(exit_code(&results), 0);
    }

    #[test]
    fn status_renders_four_chars() {
        assert_eq!(CheckStatus::Pass.to_string(), "PASS");
        assert_eq!(CheckStatus::Warn.to_string(), "WARN");
        assert_eq!(CheckStatus::Fail.to_string(), "FAIL");
    }
}
