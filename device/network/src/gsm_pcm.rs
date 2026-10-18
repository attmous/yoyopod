//! Private bridge to the real USB PCM owner; injection exists only in Rust tests.
use std::path::Path;

use anyhow::Result;

use crate::gsm_audio::{PreparedUsbPcm, UsbPcmAudio};
use crate::gsm_provider::VerifiedPcm;

pub(crate) trait PcmEngine: Send {
    fn available(&self) -> bool;
    fn prepare(&self, format: &VerifiedPcm) -> Result<Box<dyn PreparedPcm>>;
}

pub(crate) trait PreparedPcm: Send {
    fn port(&self) -> &Path;
    fn start(self: Box<Self>) -> Result<Box<dyn ActivePcm>>;
}

pub(crate) trait ActivePcm: Send {
    fn set_mute(&self, muted: bool);
    fn healthy(&mut self) -> Result<bool>;
}

pub(crate) struct PcmAdapter(Box<dyn PcmEngine>);

impl Default for PcmAdapter {
    fn default() -> Self {
        Self(Box::new(RealPcmEngine))
    }
}

impl PcmAdapter {
    pub(crate) fn prepare(&self, format: &VerifiedPcm) -> Result<Box<dyn PreparedPcm>> {
        anyhow::ensure!(self.0.available(), "GSM USB PCM or ALSA tools unavailable");
        self.0.prepare(format)
    }

    #[cfg(test)]
    pub(crate) fn with_engine(engine: impl PcmEngine + 'static) -> Self {
        Self(Box::new(engine))
    }
}

struct RealPcmEngine;
struct RealPreparedPcm(PreparedUsbPcm);
struct RealActivePcm(UsbPcmAudio);

impl PcmEngine for RealPcmEngine {
    fn available(&self) -> bool {
        UsbPcmAudio::available()
    }

    fn prepare(&self, format: &VerifiedPcm) -> Result<Box<dyn PreparedPcm>> {
        Ok(Box::new(RealPreparedPcm(UsbPcmAudio::prepare(
            format.sample_rate_hz(),
        )?)))
    }
}

impl PreparedPcm for RealPreparedPcm {
    fn port(&self) -> &Path {
        &self.0.port
    }

    fn start(self: Box<Self>) -> Result<Box<dyn ActivePcm>> {
        Ok(Box::new(RealActivePcm(UsbPcmAudio::start(self.0)?)))
    }
}

impl ActivePcm for RealActivePcm {
    fn set_mute(&self, muted: bool) {
        self.0.set_mute(muted);
    }

    fn healthy(&mut self) -> Result<bool> {
        self.0.healthy()
    }
}
