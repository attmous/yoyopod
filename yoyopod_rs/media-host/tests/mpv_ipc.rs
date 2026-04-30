use std::collections::VecDeque;
use std::io::{self, Read, Write};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::Value;
use yoyopod_media_host::mpv_ipc::MpvIpcClient;

struct ChannelReader {
    rx: Receiver<Vec<u8>>,
    buffer: VecDeque<u8>,
}

impl ChannelReader {
    fn new(rx: Receiver<Vec<u8>>) -> Self {
        Self {
            rx,
            buffer: VecDeque::new(),
        }
    }
}

impl Read for ChannelReader {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        while self.buffer.is_empty() {
            match self.rx.recv_timeout(Duration::from_secs(1)) {
                Ok(chunk) => self.buffer.extend(chunk),
                Err(mpsc::RecvTimeoutError::Timeout) => return Ok(0),
                Err(mpsc::RecvTimeoutError::Disconnected) => return Ok(0),
            }
        }

        let count = buf.len().min(self.buffer.len());
        for slot in buf.iter_mut().take(count) {
            *slot = self.buffer.pop_front().expect("buffer");
        }
        Ok(count)
    }
}

type WriteHandler = Arc<Mutex<dyn FnMut(Vec<u8>, &Sender<Vec<u8>>) + Send>>;

struct ScriptedWriter {
    tx: Sender<Vec<u8>>,
    handler: WriteHandler,
}

impl Write for ScriptedWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        (self.handler.lock().expect("handler"))(buf.to_vec(), &self.tx);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn make_client(handler: impl FnMut(Vec<u8>, &Sender<Vec<u8>>) + Send + 'static) -> MpvIpcClient {
    let (tx, rx) = mpsc::channel();
    let reader = ChannelReader::new(rx);
    let writer = ScriptedWriter {
        tx,
        handler: Arc::new(Mutex::new(handler)),
    };
    MpvIpcClient::connect_with_handles("/tmp/yoyopod-mpv.sock", Box::new(reader), Box::new(writer))
        .expect("connect")
}

#[test]
fn send_command_waits_for_matching_response() {
    let mut client = make_client(|request, tx| {
        let request: Value = serde_json::from_slice(&request).expect("request json");
        let response = serde_json::json!({
            "request_id": request["request_id"],
            "error": "success",
            "data": "0.38.0"
        });
        tx.send(format!("{response}\n").into_bytes())
            .expect("response");
    });

    let response = client
        .send_command(
            &["get_property".into(), "mpv-version".into()],
            Duration::from_secs(1),
        )
        .expect("response");

    assert_eq!(response["data"], "0.38.0");
    client.disconnect();
}

#[test]
fn drain_events_returns_reader_events() {
    let mut sent_event = false;
    let mut client = make_client(move |_request, tx| {
        if !sent_event {
            tx.send(br#"{"event":"file-loaded"}"#.to_vec())
                .expect("event");
            tx.send(b"\n".to_vec()).expect("newline");
            sent_event = true;
        }
    });

    let _ = client
        .send_command(
            &["get_property".into(), "path".into()],
            Duration::from_millis(10),
        )
        .err();

    let events = client.drain_events().expect("events");

    assert_eq!(events.len(), 1);
    assert_eq!(events[0]["event"], "file-loaded");
    client.disconnect();
}

#[test]
fn event_before_response_does_not_block_followup_command() {
    let mut client = make_client(|request, tx| {
        let request: Value = serde_json::from_slice(&request).expect("request json");
        tx.send(br#"{"event":"file-loaded"}"#.to_vec())
            .expect("event");
        tx.send(b"\n".to_vec()).expect("newline");
        let response = serde_json::json!({
            "request_id": request["request_id"],
            "error": "success",
            "data": "/music/alpha.ogg"
        });
        tx.send(format!("{response}\n").into_bytes())
            .expect("response");
    });

    let response = client
        .send_command(
            &["get_property".into(), "path".into()],
            Duration::from_secs(1),
        )
        .expect("response");

    assert_eq!(response["data"], "/music/alpha.ogg");
    let events = client.drain_events().expect("events");
    assert_eq!(events.len(), 1);
    assert_eq!(events[0]["event"], "file-loaded");
    client.disconnect();
}
