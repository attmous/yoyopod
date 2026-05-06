use std::io::{self, Read, Write};
use std::time::{Duration, Instant};

use serialport::{ClearBuffer, SerialPort};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum TransportError {
    #[error("serial port is not open")]
    NotOpen,
    #[error("failed to open serial port: {0}")]
    Open(#[from] serialport::Error),
    #[error("serial transport I/O failed: {0}")]
    Io(#[from] io::Error),
}

pub trait LineTransport {
    fn send_command(
        &mut self,
        command: &str,
        timeout: Option<Duration>,
    ) -> Result<String, TransportError>;
}

impl<T> LineTransport for &mut T
where
    T: LineTransport + ?Sized,
{
    fn send_command(
        &mut self,
        command: &str,
        timeout: Option<Duration>,
    ) -> Result<String, TransportError> {
        (**self).send_command(command, timeout)
    }
}

#[derive(Debug)]
pub struct SerialLineTransport {
    port_name: String,
    baud_rate: u32,
    timeout: Duration,
    port: Option<Box<dyn SerialPort>>,
}

impl SerialLineTransport {
    pub fn new(port_name: impl Into<String>, baud_rate: u32, timeout: Duration) -> Self {
        Self {
            port_name: port_name.into(),
            baud_rate,
            timeout,
            port: None,
        }
    }

    pub fn with_port(
        port_name: impl Into<String>,
        baud_rate: u32,
        timeout: Duration,
        port: Box<dyn SerialPort>,
    ) -> Self {
        Self {
            port_name: port_name.into(),
            baud_rate,
            timeout,
            port: Some(port),
        }
    }

    pub fn open(&mut self) -> Result<(), TransportError> {
        let port = serialport::new(&self.port_name, self.baud_rate)
            .timeout(self.timeout)
            .open()?;
        self.port = Some(port);
        Ok(())
    }

    pub fn close(&mut self) {
        self.port.take();
    }

    pub fn is_open(&self) -> bool {
        self.port.is_some()
    }
}

impl LineTransport for SerialLineTransport {
    fn send_command(
        &mut self,
        command: &str,
        timeout: Option<Duration>,
    ) -> Result<String, TransportError> {
        let port = self.port.as_mut().ok_or(TransportError::NotOpen)?;
        let deadline = Instant::now() + timeout.unwrap_or(self.timeout);
        let mut lines = Vec::new();
        let mut current_line = Vec::new();

        let _ = port.clear(ClearBuffer::Input);
        port.set_timeout(Duration::from_millis(100))?;
        port.write_all(format!("{}\r\n", command.trim()).as_bytes())?;
        port.flush()?;

        while Instant::now() < deadline {
            let mut byte = [0_u8; 1];
            match port.read(&mut byte) {
                Ok(0) => continue,
                Ok(_) => {
                    if byte[0] == b'\n' {
                        if let Some(line) = finalize_line(&mut current_line) {
                            let terminal = is_terminal_line(&line);
                            lines.push(line);
                            if terminal {
                                break;
                            }
                        }
                        continue;
                    }
                    current_line.push(byte[0]);
                }
                Err(err) if err.kind() == io::ErrorKind::TimedOut => continue,
                Err(err) => return Err(TransportError::Io(err)),
            }
        }

        if let Some(line) = finalize_line(&mut current_line) {
            lines.push(line);
        }

        Ok(lines.join("\n"))
    }
}

fn finalize_line(buffer: &mut Vec<u8>) -> Option<String> {
    if buffer.is_empty() {
        return None;
    }

    let line = String::from_utf8_lossy(buffer).trim().to_string();
    buffer.clear();
    (!line.is_empty()).then_some(line)
}

fn is_terminal_line(line: &str) -> bool {
    matches!(line, "OK" | "ERROR") || line.starts_with("+CME ERROR")
}
