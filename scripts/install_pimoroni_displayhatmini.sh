#!/bin/bash
# Install Pimoroni Display HAT Mini support on Radxa Cubie A7Z.
#
# This script:
# 1. Compiles and installs a custom SPI1 overlay that frees PD13/MISO (PIN_21)
#    for use as the ST7789 DC (data/command) GPIO pin.
# 2. Creates a systemd service that unbinds I2S0 at boot to free PB4 (PIN_36)
#    for Pimoroni Button X.
#
# Requires: dtc (device-tree-compiler), sudo access.
# Run once, then reboot.
#
# See docs/CUBIE_A7Z_PIMORONI_SETUP.md for full details.

set -euo pipefail

OVERLAY_PATH="/boot/dtbo/sun60iw2p1-spi1-spidev.dtbo"
OVERLAY_BACKUP="${OVERLAY_PATH}.bak"
SERVICE_NAME="disable-i2s0"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "=== Pimoroni Display HAT Mini installer for Cubie A7Z ==="
echo

# --- Check prerequisites ---

if ! command -v dtc &> /dev/null; then
    echo "ERROR: dtc (device-tree-compiler) is required."
    echo "  Install with: sudo apt install device-tree-compiler"
    exit 1
fi

if [ ! -f "$OVERLAY_PATH" ]; then
    echo "ERROR: Stock SPI1 overlay not found at $OVERLAY_PATH"
    echo "  Is the SPI1 overlay enabled via rsetup?"
    exit 1
fi

# --- Step 1: Custom SPI1 overlay ---

echo "[1/3] Building custom SPI1 overlay (freeing MISO for DC pin)..."

DTS_FILE=$(mktemp /tmp/spi1-no-miso.XXXXXX.dts)
DTBO_FILE=$(mktemp /tmp/spi1-no-miso.XXXXXX.dtbo)
trap "rm -f $DTS_FILE $DTBO_FILE" EXIT

cat > "$DTS_FILE" << 'DTS'
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
DTS

dtc -I dts -O dtb -o "$DTBO_FILE" "$DTS_FILE" 2>/dev/null
echo "  Overlay compiled."

if [ ! -f "$OVERLAY_BACKUP" ]; then
    sudo cp "$OVERLAY_PATH" "$OVERLAY_BACKUP"
    echo "  Stock overlay backed up to $OVERLAY_BACKUP"
else
    echo "  Backup already exists at $OVERLAY_BACKUP"
fi

sudo cp "$DTBO_FILE" "$OVERLAY_PATH"
echo "  Custom overlay installed."

# --- Step 2: I2S0 unbind service ---

echo "[2/3] Installing I2S0 unbind service (freeing PIN_36 for Button X)..."

sudo tee "$SERVICE_PATH" > /dev/null << 'SVC'
[Unit]
Description=Unbind I2S0 to free PB4 (PIN_36) for Pimoroni Button X
Before=yoyopod-dev.service yoyopod-prod.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c "echo 2532000.i2s0_plat > /sys/bus/platform/drivers/sunxi-snd-plat-i2s/unbind"
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" --quiet
echo "  Service installed and enabled."

# --- Done ---

echo "[3/3] Done."
echo
echo "Reboot to activate:"
echo "  sudo reboot"
echo
echo "After reboot, launch YoYoPod with:"
echo "  YOYOPOD_DISPLAY=pimoroni YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z device/runtime/build/yoyopod-runtime --config-dir config --hardware pimoroni"
