use std::collections::HashMap;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::thread::JoinHandle;
use std::time::Duration;

use anyhow::{anyhow, Result};
use serde_json::{json, Value};

pub struct MpvIpcClient {
    #[cfg_attr(not(unix), allow(dead_code))]
    socket_path: String,
    connected: bool,
    request_id: u64,
    pending: Arc<Mutex<HashMap<u64, Sender<Value>>>>,
    event_rx: Receiver<Value>,
    writer: Option<Arc<Mutex<Box<dyn Write + Send>>>>,
    stop: Arc<AtomicBool>,
    reader_thread: Option<JoinHandle<()>>,
}

impl MpvIpcClient {
    pub fn new(socket_path: impl Into<String>) -> Self {
        let (_event_tx, event_rx) = mpsc::channel();
        Self {
            socket_path: socket_path.into(),
            connected: false,
            request_id: 0,
            pending: Arc::new(Mutex::new(HashMap::new())),
            event_rx,
            writer: None,
            stop: Arc::new(AtomicBool::new(false)),
            reader_thread: None,
        }
    }

    pub fn connect(&mut self) -> Result<()> {
        #[cfg(unix)]
        {
            use std::os::unix::net::UnixStream;

            let stream = UnixStream::connect(&self.socket_path)?;
            stream.set_read_timeout(Some(Duration::from_millis(250)))?;
            let reader = Box::new(stream.try_clone()?);
            let writer = Box::new(stream);
            return self.attach_handles(reader, writer);
        }

        #[cfg(not(unix))]
        {
            Err(anyhow!(
                "mpv IPC Unix socket connection is unsupported on this platform"
            ))
        }
    }

    pub fn connect_with_handles(
        socket_path: impl Into<String>,
        reader: Box<dyn Read + Send>,
        writer: Box<dyn Write + Send>,
    ) -> Result<Self> {
        let mut client = Self::new(socket_path);
        client.attach_handles(reader, writer)?;
        Ok(client)
    }

    pub fn connected(&self) -> bool {
        self.connected
    }

    pub fn disconnect(&mut self) {
        self.connected = false;
        self.stop.store(true, Ordering::Relaxed);
        self.writer = None;
        self.pending.lock().expect("pending").clear();
        if let Some(handle) = self.reader_thread.take() {
            if handle.is_finished() {
                let _ = handle.join();
            }
        }
    }

    pub fn send_command(&mut self, args: &[Value], timeout: Duration) -> Result<Value> {
        if !self.connected {
            return Err(anyhow!("mpv IPC is not connected"));
        }

        self.request_id += 1;
        let request_id = self.request_id;
        let (tx, rx) = mpsc::channel();
        self.pending.lock().expect("pending").insert(request_id, tx);

        let payload = json!({
            "command": args,
            "request_id": request_id,
        });
        let mut encoded = serde_json::to_vec(&payload)?;
        encoded.push(b'\n');

        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| anyhow!("mpv IPC writer is not connected"))?;
        {
            let mut writer = writer.lock().expect("writer");
            writer.write_all(&encoded)?;
            writer.flush()?;
        }

        match rx.recv_timeout(timeout) {
            Ok(value) => Ok(value),
            Err(RecvTimeoutError::Timeout) => {
                self.pending.lock().expect("pending").remove(&request_id);
                Err(anyhow!("mpv command timed out"))
            }
            Err(RecvTimeoutError::Disconnected) => Err(anyhow!("mpv reader disconnected")),
        }
    }

    pub fn observe_property(&mut self, name: &str, observe_id: i64) -> Result<()> {
        let args = vec![json!("observe_property"), json!(observe_id), json!(name)];
        let _ = self.send_command(&args, Duration::from_secs(1))?;
        Ok(())
    }

    pub fn drain_events(&mut self) -> Result<Vec<Value>> {
        let mut events = Vec::new();
        while let Ok(event) = self.event_rx.try_recv() {
            events.push(event);
        }
        Ok(events)
    }

    fn attach_handles(
        &mut self,
        reader: Box<dyn Read + Send>,
        writer: Box<dyn Write + Send>,
    ) -> Result<()> {
        let (event_tx, event_rx) = mpsc::channel();
        self.stop.store(false, Ordering::Relaxed);
        self.writer = Some(Arc::new(Mutex::new(writer)));
        self.event_rx = event_rx;
        self.connected = true;
        let pending = Arc::clone(&self.pending);
        let stop = Arc::clone(&self.stop);
        self.reader_thread = Some(thread::spawn(move || {
            reader_loop(reader, pending, event_tx, stop);
        }));
        Ok(())
    }
}

fn reader_loop(
    reader: Box<dyn Read + Send>,
    pending: Arc<Mutex<HashMap<u64, Sender<Value>>>>,
    event_tx: Sender<Value>,
    stop: Arc<AtomicBool>,
) {
    let mut reader = BufReader::new(reader);
    let mut line = String::new();
    while !stop.load(Ordering::Relaxed) {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let Ok(message) = serde_json::from_str::<Value>(trimmed) else {
                    continue;
                };
                if let Some(request_id) = message.get("request_id").and_then(Value::as_u64) {
                    if let Some(sender) = pending.lock().expect("pending").remove(&request_id) {
                        let _ = sender.send(message);
                    }
                    continue;
                }
                if message.get("event").is_some() {
                    let _ = event_tx.send(message);
                }
            }
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
                ) =>
            {
                continue;
            }
            Err(_) => break,
        }
    }
}
