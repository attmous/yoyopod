//! Shell quoting helpers.
//!
//! Ports `common.py:shell_quote_preserving_home` and
//! `remote_transport.py:quote_remote_project_dir` byte-for-byte. The key
//! behaviour to preserve: leading `~/` expands via the remote shell's
//! `$HOME` rather than being literal-quoted, so the Pi can resolve paths
//! configured in `deploy/pi-deploy.local.yaml`.

/// POSIX-style shell single-quote escaping.
///
/// Wraps the value in single quotes and escapes embedded single quotes
/// using the `'\''` idiom.
pub fn shell_quote(value: &str) -> String {
    shell_escape::unix::escape(value.into()).into_owned()
}

/// Shell-quote a value while preserving leading `~/` expansion via `$HOME`.
///
/// - `~` returns `"$HOME"`
/// - `~/foo` returns `"$HOME/foo"` (with embedded `$`, backticks, `"`,
///   and `\` escaped inside the double-quoted suffix)
/// - anything else falls through to plain shell_quote()
///
/// Intended for trusted, developer-controlled paths from deploy YAML or
/// CLI flags.
pub fn shell_quote_preserving_home(value: &str) -> String {
    if value == "~" {
        return "\"$HOME\"".to_string();
    }
    if let Some(suffix) = value.strip_prefix("~/") {
        // Escape order matches the Python implementation:
        //   backslash first, then ", then $, then `.
        let escaped = suffix
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('$', "\\$")
            .replace('`', "\\`");
        return format!("\"$HOME/{escaped}\"");
    }
    shell_quote(value)
}

/// Quote a remote project_dir path. Same semantics as
/// `shell_quote_preserving_home` but its own function so SSH callers
/// can be grepped distinctly from local shell-quote use.
pub fn quote_remote_project_dir(project_dir: &str) -> String {
    shell_quote_preserving_home(project_dir)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tilde_alone() {
        assert_eq!(shell_quote_preserving_home("~"), r#""$HOME""#);
    }

    #[test]
    fn tilde_slash_simple() {
        assert_eq!(
            shell_quote_preserving_home("~/yoyopod"),
            r#""$HOME/yoyopod""#
        );
    }

    #[test]
    fn tilde_slash_with_dollar() {
        assert_eq!(
            shell_quote_preserving_home("~/foo$bar"),
            r#""$HOME/foo\$bar""#
        );
    }

    #[test]
    fn tilde_slash_with_backtick() {
        assert_eq!(
            shell_quote_preserving_home("~/foo`bar"),
            r#""$HOME/foo\`bar""#
        );
    }

    #[test]
    fn tilde_slash_with_quote() {
        assert_eq!(
            shell_quote_preserving_home(r#"~/foo"bar"#),
            r#""$HOME/foo\"bar""#
        );
    }

    #[test]
    fn tilde_slash_with_backslash() {
        // backslash gets doubled, so input `~/a\b` becomes `"$HOME/a\\b"`
        assert_eq!(shell_quote_preserving_home("~/a\\b"), r#""$HOME/a\\b""#);
    }

    #[test]
    fn absolute_path_falls_through() {
        assert_eq!(
            shell_quote_preserving_home("/opt/yoyopod-dev/checkout"),
            "/opt/yoyopod-dev/checkout"
        );
    }

    #[test]
    fn absolute_path_with_spaces_falls_through() {
        // shell_quote wraps with single quotes
        let q = shell_quote_preserving_home("/opt/with spaces/checkout");
        assert!(q.starts_with('\''));
        assert!(q.contains("with spaces"));
    }

    #[test]
    fn relative_tilde_not_special() {
        // `~user/...` is NOT special: only literal `~` or `~/`.
        let q = shell_quote_preserving_home("~user/foo");
        // shell_quote will wrap this in single quotes.
        assert!(q.starts_with('\''));
        assert!(q.contains("~user/foo"));
    }
}
