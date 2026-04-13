# Cubie A7Z + Pimoroni Display HAT Mini Setup

This document covers the one-time board setup required to run YoyoPod with the Pimoroni Display HAT Mini (320x240, 4-button, RGB LED) on the Radxa Cubie A7Z.

The Pimoroni HAT was designed for the Raspberry Pi. On the Cubie, the Pi-specific `displayhatmini` library does not work. YoyoPod uses a custom driver that talks to the ST7789 display controller directly over `spidev` and reads buttons via `gpiod`.

## Prerequisites

- Radxa Cubie A7Z with Debian Bullseye and vendor BSP kernel `5.15.147-18-a733`
- SPI1 enabled via `sun60iw2p1-spi1-spidev.dtbo` overlay (see `docs/CUBIE_A7Z_BRINGUP.md`)
- YoyoPod project deployed at `~/yoyo-py` with Python 3.12 venv
- `dtc` (device tree compiler) installed: `sudo apt install device-tree-compiler`

## Pin Mapping

The Pimoroni Display HAT Mini uses these physical 40-pin header pins:

| Signal | Physical Pin | Cubie SoC Pin | gpiochip0 Line | Function |
|---|---|---|---|---|
| SPI MOSI | 19 | PD12 | 108 | SPI1 data to display |
| SPI SCLK | 23 | PD11 | 107 | SPI1 clock |
| SPI CS (CE1) | 26 | — | 110 | Software chip select (GPIO) |
| DC (data/cmd) | 21 | PD13 | 109 | GPIO toggle for ST7789 commands vs pixel data |
| Backlight | 33 | PM3 | gpiochip1:35 | GPIO on/off |
| Button A | 29 | PB2 | 34 | SELECT |
| Button B | 31 | PB3 | 35 | BACK (long press = HOME) |
| Button X | 36 | PB4 | 36 | UP |
| Button Y | 18 | PJ25 | 313 | DOWN |
| LED Red | 11 | PB1 | 33 | GPIO on/off |
| LED Green | 13 | — | gpiochip1:6 | GPIO on/off |
| LED Blue | 15 | — | gpiochip1:7 | GPIO on/off |

### Important: SPI MISO/CLK naming

The Cubie's `gpio-line-names` in the device tree have PIN_21 and PIN_23 labels swapped relative to the pinctrl pin numbering. The actual hardware routing (confirmed from the [official Radxa Cubie A7Z pinout](https://docs.radxa.com/en/cubie/a7z/hardware-use/pin-gpio)) is:

- **PIN_21** = PD13 = SPI1-**MISO** (gpiochip0 line **109**)
- **PIN_23** = PD11 = SPI1-**CLK** (gpiochip0 line **107**)

Do not trust the `gpioinfo` labels for these two pins; trust the pinctrl output or the Radxa documentation.

## Step 1: Custom SPI1 Overlay (free MISO for DC)

The Pimoroni HAT repurposes the SPI MISO pin (PIN_21) as the ST7789 DC (data/command) signal. The stock SPI1 overlay assigns all four SPI pins (MOSI, MISO, CLK, CS) to the SPI controller, which prevents using MISO as GPIO.

The fix is a modified overlay that assigns only MOSI + CLK + CS to SPI1, leaving MISO (PD13) free for GPIO.

### Create the overlay source

```bash
cat > /tmp/spi1-no-miso.dts << 'EOF'
/dts-v1/;
/plugin/;

/ {
    metadata {
        title = "Enable spidev on SPI1 (no MISO, for Pimoroni DC pin)";
        compatible = "radxa,cubie-a7a\0radxa,cubie-a7z\0radxa,cubie-a7s";
        category = "misc";
        exclusive = "spi1\0PD11\0PD12\0PD10";
        description = "SPI1 with CLK+MOSI+CS only. PD13/PIN_21 (MISO) left free for GPIO DC.";
    };

    fragment@0 {
        target = <&pio>;

        __overlay__ {

            spi1_pins_default: spi1@0 {
                pins = "PD11", "PD12";
                function = "spi1";
                drive-strength = <10>;
            };

            spi1_pins_cs: spi1@1 {
                pins = "PD10";
                function = "spi1";
                drive-strength = <10>;
                bias-pull-up;
            };

            spi1_pins_sleep: spi1@2 {
                pins = "PD11", "PD12", "PD10";
                function = "gpio_in";
                drive-strength = <10>;
            };
        };
    };

    fragment@1 {
        target = <&spi1>;

        __overlay__ {
            clock-frequency = <50000000>;
            pinctrl-0 = <&spi1_pins_default &spi1_pins_cs>;
            pinctrl-1 = <&spi1_pins_sleep>;
            pinctrl-names = "default", "sleep";
            sunxi,spi-bus-mode = <1>;
            sunxi,spi-cs-mode = <0>;
            status = "okay";

            spidev0 {
                compatible = "rohm,dh2228fv";
                reg = <0>;
                spi-max-frequency = <100000000>;
                spi-rx-bus-width = <1>;
                spi-tx-bus-width = <1>;
                status = "okay";
            };
        };
    };
};
EOF
```

### Compile and install

```bash
dtc -I dts -O dtb -o /tmp/sun60iw2p1-spi1-no-miso.dtbo /tmp/spi1-no-miso.dts

# Backup the stock overlay
sudo cp /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo.bak

# Install the modified overlay (same filename so the bootloader loads it)
sudo cp /tmp/sun60iw2p1-spi1-no-miso.dtbo /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo
```

### Verify after reboot

```bash
sudo cat /sys/kernel/debug/pinctrl/2000000.pinctrl/pinmux-pins | grep PD1
```

Expected:

```
pin 106 (PD10): device 2541000.spi function spi1 group PD10
pin 107 (PD11): device 2541000.spi function spi1 group PD11
pin 108 (PD12): device 2541000.spi function spi1 group PD12
pin 109 (PD13): UNCLAIMED
```

PD13 (MISO / PIN_21) should be UNCLAIMED. The other three remain on SPI1.

### To revert

```bash
sudo cp /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo.bak /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo
sudo reboot
```

## Step 2: Disable I2S0 (free PIN_36 for Button X)

Button X is on PIN_36 (PB4), which is assigned to the I2S0 audio controller as `i2s0_mclk`. When the Whisplay HAT is removed (no WM8960 codec), I2S0 is not needed and can be disabled to free the pin.

### Create a systemd service to unbind I2S0 at boot

```bash
sudo tee /etc/systemd/system/disable-i2s0.service > /dev/null << 'EOF'
[Unit]
Description=Unbind I2S0 to free PB4 (PIN_36) for Pimoroni Button X
Before=yoyopod@radxa.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo 2532000.i2s0_plat > /sys/bus/platform/drivers/sunxi-snd-plat-i2s/unbind"
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable disable-i2s0.service
```

### Verify after reboot

```bash
sudo cat /sys/kernel/debug/pinctrl/2000000.pinctrl/pinmux-pins | grep PB4
```

Expected:

```
pin 36 (PB4): UNCLAIMED
```

### To revert (re-enable I2S0 audio)

```bash
sudo systemctl disable disable-i2s0.service
sudo reboot
```

## Step 3: Configure YoyoPod

The GPIO pin mapping is already configured in the tracked board overlay at `config/boards/radxa-cubie-a7z/yoyopod_config.yaml`. No manual config changes are needed.

### Launch with Pimoroni display

```bash
cd ~/yoyo-py
YOYOPOD_DISPLAY=pimoroni YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z .venv/bin/python yoyopod.py
```

### Set as the default systemd service display

To make the systemd service use Pimoroni, create or update the local deploy override:

```bash
yoyoctl remote config edit --host cubie-a7z
```

Or manually add to `deploy/pi-deploy.local.yaml`:

```yaml
env:
  YOYOPOD_DISPLAY: pimoroni
  YOYOPOD_CONFIG_BOARD: radxa-cubie-a7z
```

## Verified State

The following has been validated on-device:

- ST7789 display initialized and rendering at 60 MHz SPI
- Backlight on/off via gpiod
- All 4 buttons (A, B, X, Y) read via gpiod with debounce and long-press
- RGB LED toggle via gpiod
- Full YoyoPod app: menu screen, navigation, screen transitions
- Screen timeout and wake via button press
- PIL-based rendering path (not LVGL)

## Known Limitations

- **No hardware PWM** for backlight or LED brightness. Currently on/off only.
- **Button X requires I2S0 disabled.** Re-enabling I2S0 (for WM8960 audio) will block Button X.
- **SPI `no_cs` not supported** by the Allwinner SPI driver. The driver uses hardware CS on PIN_24 (CS0) which does not reach the Pimoroni HAT's CE1 trace (PIN_26). Software CS via GPIO on PIN_26 is used as a fallback.
- **Whisplay adapter import side effects.** The Whisplay vendor driver claims GPIO pins at import time. Display adapter imports are lazy to prevent this, but importing the Whisplay adapter module (e.g., for testing) while Pimoroni is active will cause GPIO conflicts.
- **gpiod 1.x API.** The Cubie runs gpiod 1.6.2 (lowercase `gpiod.chip()`). A compatibility layer at `yoyopy/ui/gpiod_compat.py` normalizes this with the gpiod 2.x API.

## Switching Back to Whisplay

To return to the Whisplay HAT setup:

1. Restore the stock SPI1 overlay:
   ```bash
   sudo cp /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo.bak /boot/dtbo/sun60iw2p1-spi1-spidev.dtbo
   ```

2. Re-enable I2S0 audio:
   ```bash
   sudo systemctl disable disable-i2s0.service
   ```

3. Set display back to Whisplay:
   ```bash
   YOYOPOD_DISPLAY=whisplay
   ```

4. Reboot.
