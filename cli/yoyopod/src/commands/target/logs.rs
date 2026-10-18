//! `yoyopod target logs`

use anyhow::Result;

use crate::cli::LogsArgs;
use crate::paths::PiPaths;
use crate::quoting::shell_quote;
use crate::ssh::{run_remote, RemoteWorkdir};

use super::{maybe_dry_run, TargetContext};

pub fn run(ctx: &TargetContext, args: LogsArgs) -> Result<i32> {
    let cmd = build(&ctx.pi, args.lines, args.follow, args.errors, &args.filter);
    if let Some(code) = maybe_dry_run(ctx, "logs", &cmd) {
        return Ok(code);
    }
    run_remote(&ctx.conn, &cmd, args.follow, RemoteWorkdir::Default)
}

pub fn build(pi: &PiPaths, lines: u32, follow: bool, errors: bool, filter: &str) -> String {
    let log_path = if errors {
        &pi.error_log_file
    } else {
        &pi.log_file
    };
    let mut cmd = if follow {
        format!("tail -n {lines} -f {}", shell_quote(log_path))
    } else {
        format!("tail -n {lines} {}", shell_quote(log_path))
    };
    if !filter.is_empty() {
        // Single-quote-safe escape for grep: POSIX `'\''`.
        let escaped = filter.replace('\'', "'\\''");
        cmd.push_str(" | grep -- '");
        cmd.push_str(&escaped);
        cmd.push('\'');
    }
    cmd
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pi() -> PiPaths {
        PiPaths::default()
    }

    #[test]
    fn basic_tail() {
        let s = build(&pi(), 50, false, false, "");
        assert!(s.contains("tail -n 50 logs/yoyopod.log"));
    }

    #[test]
    fn errors_log() {
        let s = build(&pi(), 50, false, true, "");
        assert!(s.contains("logs/yoyopod_errors.log"));
    }

    #[test]
    fn follow_adds_flag() {
        let s = build(&pi(), 50, true, false, "");
        assert!(s.contains("tail -n 50 -f "));
    }

    #[test]
    fn filter_appended() {
        let s = build(&pi(), 50, false, false, "ERROR");
        assert!(s.ends_with("| grep -- 'ERROR'"));
    }

    #[test]
    fn filter_with_single_quote_escaped() {
        let s = build(&pi(), 50, false, false, "it's broken");
        assert!(s.ends_with(r"| grep -- 'it'\''s broken'"));
    }
}
