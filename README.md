# Clawdmeter

ESP32-S3 dashboard for monitoring Claude Code usage, with BLE HID controls and pixel-art animations.

Built for the **Waveshare ESP32-S3-Touch-AMOLED-2.16** (480×480 AMOLED).

```
firmware/   — ESP32-S3 firmware (PlatformIO + LVGL 9)
daemon/     — BLE daemon that polls the Anthropic API
tools/      — sprite scraper, icon converter, font builder
windows-tray/ — Windows system tray client
```

## Quick start

### 1. Flash firmware

```bash
pio run -d firmware -t upload --upload-port /dev/ttyACM0
```

### 2. Pair Bluetooth

Flash → device advertises as "Clawdmeter" → pair via `bluetoothctl` or system settings.

### 3. Install daemon

```bash
# Linux
./install.sh && systemctl --user start claude-usage-daemon

# macOS
./install-mac.sh
```

The daemon reads your Claude Code OAuth token, polls API usage every 60 s, and pushes it to the display over BLE.

## Hardware

| Component | Interface | Pins |
|-----------|-----------|------|
| CO5300 AMOLED | QSPI | CS=12, SCLK=38, SDIO0..3=4..7, RST=2 |
| CST9220 touch | I2C | SDA=15, SCL=14, INT=11 (0x5A) |
| AXP2101 PMU | I2C | same bus (0x34) |
| QMI8658 IMU | I2C | same bus (0x6B) |
| Left button | GPIO 0 → Space (voice mode) | |
| Right button | GPIO 18 → Shift+Tab (mode toggle) | |
| Middle button | AXP PKEY → cycle screens / animations | |

## BLE protocol

Service `4c41555a-...0001` with RX (`...0002`, write), TX (`...0003`, notify), REQ (`...0004`).

```json
{ "s": 45, "sr": 120, "w": 28, "wr": 7200, "st": "allowed", "ok": true }
```

`s` = session %, `sr` = session reset (min), `w` = weekly %, `wr` = weekly reset (min), `st` = status.
