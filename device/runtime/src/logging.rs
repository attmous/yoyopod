use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

pub fn startup_marker(version: &str, pid: u32) -> String {
    format!("===== YoYoPod starting (version={version}, pid={pid}) =====")
}

pub fn shutdown_marker(pid: u32) -> String {
    format!("===== YoYoPod shutting down (pid={pid}) =====")
}

pub fn log_info(message: impl AsRef<str>) {
    let timestamp = OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| "unknown-time".to_string());
    eprintln!("{timestamp} | INFO     | runtime | {}", message.as_ref());
}

pub fn log_marker(log_file: impl AsRef<Path>, marker: impl AsRef<str>) -> std::io::Result<()> {
    let marker = marker.as_ref();
    log_info(marker);
    append_marker_to_log(log_file, marker)
}

pub fn append_marker_to_log(
    log_file: impl AsRef<Path>,
    marker: impl AsRef<str>,
) -> std::io::Result<()> {
    let log_file = log_file.as_ref();
    if let Some(parent) = log_file.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file)?;
    writeln!(file, "{}", marker.as_ref())
}

pub fn write_pid_file(pid_file: impl AsRef<Path>, pid: u32) -> std::io::Result<()> {
    let pid_file = pid_file.as_ref();
    if let Some(parent) = pid_file.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    let contents = format!("{pid}\n");
    match fs::write(pid_file, &contents) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
            fs::remove_file(pid_file)?;
            fs::write(pid_file, contents)
        }
        Err(error) => Err(error),
    }
}

pub fn remove_pid_file(pid_file: impl AsRef<Path>) -> std::io::Result<()> {
    match fs::remove_file(pid_file) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}
