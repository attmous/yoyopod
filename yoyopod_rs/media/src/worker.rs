use std::io::{BufRead, BufReader, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

use anyhow::{anyhow, Result};
use serde_json::json;

use crate::config::MediaConfig;
use crate::events::MediaRuntimeEvent;
use crate::host::MediaHost;
use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::remote_media::MediaImportRequest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopAction {
    Continue,
    Shutdown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CommandOutcome {
    pub action: LoopAction,
    pub envelopes: Vec<WorkerEnvelope>,
}

impl CommandOutcome {
    fn continue_with(envelopes: Vec<WorkerEnvelope>) -> Self {
        Self {
            action: LoopAction::Continue,
            envelopes,
        }
    }

    fn shutdown_with(envelopes: Vec<WorkerEnvelope>) -> Self {
        Self {
            action: LoopAction::Shutdown,
            envelopes,
        }
    }
}

pub fn run() -> Result<()> {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    let mut stderr = std::io::stderr();
    run_io(stdin, &mut stdout, &mut stderr)
}

pub fn run_io<R, W, E>(input: R, output: &mut W, errors: &mut E) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    E: Write,
{
    let mut host = MediaHost::default();
    emit(
        output,
        &WorkerEnvelope::event(
            "media.ready",
            json!({"capabilities":["configure", "health", "playback", "library", "remote_media"]}),
        ),
    )?;

    let (stdin_tx, stdin_rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = BufReader::new(input);
        for line in reader.lines() {
            if stdin_tx.send(line).is_err() {
                break;
            }
        }
    });

    loop {
        match stdin_rx.recv_timeout(next_loop_timeout(&host)) {
            Ok(Ok(line)) => {
                if line.trim().is_empty() {
                    continue;
                }

                match WorkerEnvelope::decode(line.as_bytes()) {
                    Ok(envelope) => {
                        if envelope.kind != EnvelopeKind::Command {
                            writeln!(
                                errors,
                                "invalid media worker envelope kind: {:?}",
                                envelope.kind
                            )?;
                            emit(
                                output,
                                &WorkerEnvelope::error(
                                    "media.error",
                                    envelope.request_id.clone(),
                                    "invalid_kind",
                                    "media worker accepts commands only",
                                ),
                            )?;
                            continue;
                        }

                        let request_id = envelope.request_id.clone();
                        match handle_command(envelope, &mut host) {
                            Ok(outcome) => {
                                for envelope in &outcome.envelopes {
                                    emit(output, envelope)?;
                                }
                                emit_runtime_events(output, &mut host)?;
                                if matches!(outcome.action, LoopAction::Shutdown) {
                                    break;
                                }
                            }
                            Err(error) => {
                                writeln!(errors, "media worker command failed: {error}")?;
                                emit(
                                    output,
                                    &WorkerEnvelope::error(
                                        "media.error",
                                        request_id,
                                        "command_failed",
                                        error.to_string(),
                                    ),
                                )?;
                            }
                        }
                    }
                    Err(error) => {
                        writeln!(errors, "media protocol decode error: {error}")?;
                        emit(
                            output,
                            &WorkerEnvelope::error(
                                "media.error",
                                None,
                                "protocol_error",
                                error.to_string(),
                            ),
                        )?;
                    }
                }
            }
            Ok(Err(error)) => return Err(error.into()),
            Err(RecvTimeoutError::Timeout) => {
                emit_runtime_events(output, &mut host)?;
            }
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }

    Ok(())
}

fn next_loop_timeout(host: &MediaHost) -> Duration {
    if host.has_active_runtime() {
        Duration::from_millis(250)
    } else {
        Duration::from_secs(60)
    }
}

fn emit_runtime_events<W: Write>(output: &mut W, host: &mut MediaHost) -> Result<()> {
    let events = host.drain_runtime_events()?;
    if events.is_empty() {
        return Ok(());
    }
    for envelope in runtime_event_envelopes(events, host) {
        emit(output, &envelope)?;
    }
    Ok(())
}

fn runtime_event_envelopes(
    events: Vec<MediaRuntimeEvent>,
    host: &MediaHost,
) -> Vec<WorkerEnvelope> {
    let mut envelopes = Vec::new();
    for event in events {
        match event {
            MediaRuntimeEvent::TrackChanged(track) => {
                envelopes.push(WorkerEnvelope::event(
                    "media.track_changed",
                    json!({"track": track}),
                ));
            }
            MediaRuntimeEvent::PlaybackStateChanged(state) => {
                envelopes.push(WorkerEnvelope::event(
                    "media.playback_state_changed",
                    json!({"state": state.as_str()}),
                ));
            }
            MediaRuntimeEvent::TimePositionChanged(_) => {}
            MediaRuntimeEvent::BackendAvailabilityChanged { connected, reason } => {
                envelopes.push(WorkerEnvelope::event(
                    "media.backend_availability_changed",
                    json!({"connected": connected, "reason": reason}),
                ));
            }
        }
    }
    envelopes.push(WorkerEnvelope::event(
        "media.snapshot",
        host.snapshot_payload(),
    ));
    envelopes
}

pub fn handle_command(envelope: WorkerEnvelope, host: &mut MediaHost) -> Result<CommandOutcome> {
    host.record_command();

    let request_id = envelope.request_id.clone();
    match envelope.message_type.as_str() {
        "media.configure" => {
            let config = MediaConfig::from_payload(&envelope.payload)?;
            host.configure(config);
            Ok(CommandOutcome::continue_with(vec![
                WorkerEnvelope::result("media.configure", request_id, json!({"configured": true})),
                WorkerEnvelope::event("media.snapshot", host.snapshot_payload()),
            ]))
        }
        "media.start" => {
            host.start_backend()?;
            Ok(CommandOutcome::continue_with(vec![
                WorkerEnvelope::result("media.start", request_id, json!({"started": true})),
                WorkerEnvelope::event("media.snapshot", host.snapshot_payload()),
            ]))
        }
        "media.stop" => {
            host.stop_backend()?;
            Ok(CommandOutcome::continue_with(vec![
                WorkerEnvelope::result("media.stop", request_id, json!({"stopped": true})),
                WorkerEnvelope::event("media.snapshot", host.snapshot_payload()),
            ]))
        }
        "media.health" => Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
            "media.health",
            request_id,
            host.health_payload(),
        )])),
        "media.play" => {
            host.play()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.play",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.pause" => {
            host.pause()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.pause",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.resume" => {
            host.resume()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.resume",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.stop_playback" => {
            host.stop_playback()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.stop_playback",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.next_track" => {
            host.next_track()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.next_track",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.previous_track" => {
            host.previous_track()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.previous_track",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.load_tracks" => {
            let uris = envelope
                .payload
                .get("uris")
                .and_then(|value| value.as_array())
                .ok_or_else(|| anyhow!("media.load_tracks requires uris"))?
                .iter()
                .map(|value| {
                    value
                        .as_str()
                        .map(ToString::to_string)
                        .ok_or_else(|| anyhow!("media.load_tracks requires string uris"))
                })
                .collect::<Result<Vec<_>>>()?;
            host.load_tracks(&uris)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.load_tracks",
                request_id,
                json!({"accepted": true, "count": uris.len()}),
            )]))
        }
        "media.load_playlist" => {
            let path = envelope
                .payload
                .get("path")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.load_playlist requires path"))?;
            host.load_playlist_file(path)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.load_playlist",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.list_playlists" => {
            let fetch_track_counts = envelope
                .payload
                .get("fetch_track_counts")
                .and_then(|value| value.as_bool())
                .unwrap_or(false);
            let playlists = host.list_playlists(fetch_track_counts)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.list_playlists",
                request_id,
                json!({"playlists": playlists, "count": playlists.len()}),
            )]))
        }
        "media.list_recent_tracks" => {
            let limit = envelope
                .payload
                .get("limit")
                .and_then(|value| value.as_u64())
                .map(|value| value as usize);
            let recent_tracks = host.list_recent_tracks(limit)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.list_recent_tracks",
                request_id,
                json!({"recent_tracks": recent_tracks, "count": recent_tracks.len()}),
            )]))
        }
        "media.shuffle_all" => {
            host.shuffle_all()?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.shuffle_all",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.play_recent_track" => {
            let track_uri = envelope
                .payload
                .get("track_uri")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.play_recent_track requires track_uri"))?;
            host.play_recent_track(track_uri)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.play_recent_track",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.prepare_remote_asset" => {
            let track_id = envelope
                .payload
                .get("track_id")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.prepare_remote_asset requires track_id"))?;
            let media_url = envelope
                .payload
                .get("media_url")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.prepare_remote_asset requires media_url"))?;
            let checksum_sha256 = envelope
                .payload
                .get("checksum_sha256")
                .and_then(|value| value.as_str());
            let extension = envelope
                .payload
                .get("extension")
                .and_then(|value| value.as_str())
                .unwrap_or(".mp3");
            let asset = host.prepare_remote_playback_asset(
                track_id,
                media_url,
                checksum_sha256,
                extension,
            )?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.prepare_remote_asset",
                request_id,
                json!({"path": asset.path, "cache_hit": asset.cache_hit}),
            )]))
        }
        "media.import_remote_asset" => {
            let track_id = envelope
                .payload
                .get("track_id")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.import_remote_asset requires track_id"))?;
            let cached_path = envelope
                .payload
                .get("cached_path")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.import_remote_asset requires cached_path"))?;
            let request = MediaImportRequest {
                track_id: track_id.to_string(),
                title: envelope
                    .payload
                    .get("title")
                    .and_then(|value| value.as_str())
                    .map(ToString::to_string),
                filename: envelope
                    .payload
                    .get("filename")
                    .and_then(|value| value.as_str())
                    .map(ToString::to_string),
            };
            let target_path =
                host.import_remote_media_asset(&request, std::path::Path::new(cached_path))?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.import_remote_asset",
                request_id,
                json!({"path": target_path.display().to_string()}),
            )]))
        }
        "media.set_volume" => {
            let volume = envelope
                .payload
                .get("volume")
                .and_then(|value| value.as_i64())
                .ok_or_else(|| anyhow!("media.set_volume requires volume"))?
                as i32;
            host.set_volume(volume)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.set_volume",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.set_audio_device" => {
            let device = envelope
                .payload
                .get("device")
                .and_then(|value| value.as_str())
                .ok_or_else(|| anyhow!("media.set_audio_device requires device"))?;
            host.set_audio_device(device)?;
            Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
                "media.set_audio_device",
                request_id,
                json!({"accepted": true}),
            )]))
        }
        "media.shutdown" | "worker.stop" => {
            let _ = host.stop_backend();
            Ok(CommandOutcome::shutdown_with(vec![WorkerEnvelope::result(
                envelope.message_type,
                request_id,
                json!({"shutdown": true}),
            )]))
        }
        _ => Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::error(
            "media.error",
            request_id,
            "unsupported_command",
            format!("unsupported command {}", envelope.message_type),
        )])),
    }
}

fn emit<W: Write>(output: &mut W, envelope: &WorkerEnvelope) -> Result<()> {
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}
