use anyhow::{Context, Result};
use rppal::gpio::{Gpio, InputPin, Level, OutputPin};
use rppal::spi::{Bus, Mode, SlaveSelect, Spi};

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};
use crate::whisplay_panel::{
    backlight_output_high, whisplay_address_window, whisplay_init_sequence,
    DEFAULT_BACKLIGHT_ACTIVE_LOW, DEFAULT_BACKLIGHT_GPIO, DEFAULT_BUTTON_ACTIVE_LOW,
    DEFAULT_BUTTON_GPIO, DEFAULT_DC_GPIO, DEFAULT_RESET_GPIO, DEFAULT_SPI_HZ, HEIGHT, WIDTH,
};

const SPI_CHUNK_BYTES: usize = 4096;

pub struct WhisplayDisplay {
    spi: Spi,
    dc: OutputPin,
    reset: Option<OutputPin>,
    backlight: Option<OutputPin>,
    backlight_active_low: bool,
}

pub struct WhisplayButton {
    pin: InputPin,
    active_low: bool,
}

pub fn open_from_env() -> Result<(WhisplayDisplay, WhisplayButton)> {
    let spi_bus = env_u8("YOYOPOD_WHISPLAY_SPI_BUS", 0)?;
    let spi_cs = env_u8("YOYOPOD_WHISPLAY_SPI_CS", 0)?;
    let spi_hz = env_u32("YOYOPOD_WHISPLAY_SPI_HZ", DEFAULT_SPI_HZ)?;
    let dc_gpio = env_u8("YOYOPOD_WHISPLAY_DC_GPIO", DEFAULT_DC_GPIO)?;
    let reset_gpio = optional_env_u8("YOYOPOD_WHISPLAY_RESET_GPIO")?.or(Some(DEFAULT_RESET_GPIO));
    let backlight_gpio =
        optional_env_u8("YOYOPOD_WHISPLAY_BACKLIGHT_GPIO")?.or(Some(DEFAULT_BACKLIGHT_GPIO));
    let backlight_active_low = env_bool(
        "YOYOPOD_WHISPLAY_BACKLIGHT_ACTIVE_LOW",
        DEFAULT_BACKLIGHT_ACTIVE_LOW,
    )?;
    let button_gpio = env_u8("YOYOPOD_WHISPLAY_BUTTON_GPIO", DEFAULT_BUTTON_GPIO)?;
    let button_active_low = env_bool(
        "YOYOPOD_WHISPLAY_BUTTON_ACTIVE_LOW",
        DEFAULT_BUTTON_ACTIVE_LOW,
    )?;

    let spi = Spi::new(
        spi_bus_from_u8(spi_bus)?,
        spi_cs_from_u8(spi_cs)?,
        spi_hz,
        Mode::Mode0,
    )
    .context("opening Whisplay SPI")?;
    let gpio = Gpio::new().context("opening GPIO")?;
    let dc = gpio.get(dc_gpio)?.into_output();
    let reset = match reset_gpio {
        Some(pin) => Some(gpio.get(pin)?.into_output()),
        None => None,
    };
    let backlight = match backlight_gpio {
        Some(pin) => Some(gpio.get(pin)?.into_output()),
        None => None,
    };
    let button = gpio.get(button_gpio)?.into_input_pullup();

    let mut display = WhisplayDisplay {
        spi,
        dc,
        reset,
        backlight,
        backlight_active_low,
    };
    display.init_panel()?;

    Ok((
        display,
        WhisplayButton {
            pin: button,
            active_low: button_active_low,
        },
    ))
}

impl WhisplayDisplay {
    fn init_panel(&mut self) -> Result<()> {
        if let Some(reset) = self.reset.as_mut() {
            reset.set_high();
            std::thread::sleep(std::time::Duration::from_millis(100));
            reset.set_low();
            std::thread::sleep(std::time::Duration::from_millis(100));
            reset.set_high();
            std::thread::sleep(std::time::Duration::from_millis(120));
        }

        for panel_command in whisplay_init_sequence() {
            self.command(panel_command.command, panel_command.data)?;
            if panel_command.delay_ms > 0 {
                std::thread::sleep(std::time::Duration::from_millis(panel_command.delay_ms));
            }
        }
        self.set_backlight(1.0)?;
        Ok(())
    }

    fn command(&mut self, command: u8, data: &[u8]) -> Result<()> {
        self.dc.set_low();
        self.spi.write(&[command])?;
        if !data.is_empty() {
            self.dc.set_high();
            self.write_data(data)?;
        }
        Ok(())
    }

    fn write_data(&mut self, data: &[u8]) -> Result<()> {
        for chunk in spi_chunks(data) {
            self.spi.write(chunk)?;
        }
        Ok(())
    }

    fn set_address_window(&mut self, x0: u16, y0: u16, x1: u16, y1: u16) -> Result<()> {
        let window = whisplay_address_window(x0, y0, x1, y1);
        self.command(0x2A, &window.x)?;
        self.command(0x2B, &window.y)?;
        self.command(0x2C, &[])?;
        Ok(())
    }
}

impl DisplayDevice for WhisplayDisplay {
    fn width(&self) -> usize {
        WIDTH
    }

    fn height(&self) -> usize {
        HEIGHT
    }

    fn flush_full_frame(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        self.set_address_window(0, 0, (WIDTH - 1) as u16, (HEIGHT - 1) as u16)?;
        self.dc.set_high();
        self.write_data(&framebuffer.as_be_bytes())?;
        Ok(())
    }

    fn set_backlight(&mut self, brightness: f32) -> Result<()> {
        let output_high = backlight_output_high(brightness, self.backlight_active_low);
        if let Some(pin) = self.backlight.as_mut() {
            if output_high {
                pin.set_high();
            } else {
                pin.set_low();
            }
        }
        Ok(())
    }
}

impl ButtonDevice for WhisplayButton {
    fn pressed(&mut self) -> Result<bool> {
        let is_low = self.pin.read() == Level::Low;
        Ok(if self.active_low { is_low } else { !is_low })
    }
}

fn optional_env_u8(name: &str) -> Result<Option<u8>> {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => Ok(Some(
            value
                .parse::<u8>()
                .with_context(|| format!("parsing {name}={value}"))?,
        )),
        _ => Ok(None),
    }
}

fn env_u8(name: &str, default: u8) -> Result<u8> {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => value
            .parse::<u8>()
            .with_context(|| format!("parsing {name}={value}")),
        _ => Ok(default),
    }
}

fn env_u32(name: &str, default: u32) -> Result<u32> {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => value
            .parse::<u32>()
            .with_context(|| format!("parsing {name}={value}")),
        _ => Ok(default),
    }
}

fn env_bool(name: &str, default: bool) -> Result<bool> {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => match value.to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Ok(true),
            "0" | "false" | "no" | "off" => Ok(false),
            _ => anyhow::bail!("parsing {name}={value} as bool"),
        },
        _ => Ok(default),
    }
}

fn spi_bus_from_u8(value: u8) -> Result<Bus> {
    match value {
        0 => Ok(Bus::Spi0),
        1 => Ok(Bus::Spi1),
        _ => anyhow::bail!("unsupported SPI bus {value}"),
    }
}

fn spi_cs_from_u8(value: u8) -> Result<SlaveSelect> {
    match value {
        0 => Ok(SlaveSelect::Ss0),
        1 => Ok(SlaveSelect::Ss1),
        _ => anyhow::bail!("unsupported SPI chip select {value}"),
    }
}

fn spi_chunks(data: &[u8]) -> impl Iterator<Item = &[u8]> {
    data.chunks(SPI_CHUNK_BYTES)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunks_full_frame_under_linux_spi_message_limit() {
        let payload = vec![0u8; WIDTH * HEIGHT * 2];
        let chunk_lengths: Vec<usize> = spi_chunks(&payload).map(|chunk| chunk.len()).collect();

        assert!(chunk_lengths
            .iter()
            .all(|length| *length <= SPI_CHUNK_BYTES));
        assert_eq!(chunk_lengths.iter().sum::<usize>(), payload.len());
        assert_eq!(chunk_lengths[0], SPI_CHUNK_BYTES);
        assert_eq!(*chunk_lengths.last().unwrap(), 3328);
    }
}
