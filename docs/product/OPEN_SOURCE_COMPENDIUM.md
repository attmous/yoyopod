# YoYoPod Open Source & Open Hardware Research Compendium

**Compiled:** 2026-04-25  
**Device:** YoYoPod (Raspberry Pi Zero 2W-based kid communicator)  
**Purpose:** Identify actively maintained, license-compatible OSS/OH projects for integration

---

## 1. Embedded Linux / Pi Distros / Base OS

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **Raspberry Pi OS (Lite)** | https://www.raspberrypi.com/software/ | Official Debian-based OS for Pi Zero 2W | Base OS; use Lite variant to minimize footprint. Enable systemd, disable unnecessary services. |
| **Buildroot** | https://buildroot.org/ | Custom embedded Linux build system | Build fully custom image with only needed packages (mpv, python3, lvgl deps). Better for production than Raspbian. |
| **Yocto Project** | https://www.yoctoproject.org/ | Industrial-grade embedded Linux builder | Overkill for YoYoPod but provides reproducible builds, layer for Pi Zero 2W exists (meta-raspberrypi). |
| **DietPi** | https://dietpi.com/ | Lightweight optimized Debian for Pi | Pre-optimized for minimal resource use; could fork for YoYoPod base. Active community. |
| **Alpine Linux** | https://alpinelinux.org/ | Musl-based, security-focused, small | ~130MB base. musl libc may cause Python C extension issues (test Vosk/Liblinphone). |
| **NixOS** | https://nixos.org/ | Reproducible declarative Linux | Nix expressions for reproducible YoYoPod builds; steep learning curve but atomic rollbacks complement slot-deploy. |
| **postmarketOS** | https://postmarketos.org/ | Alpine-based mobile/embedded OS | Phone-oriented but has good ARM support, power management, modem integration patterns. |
| **Mender Hub meta-mender** | https://hub.mender.io/t/raspberry-pi-3-and-4/ | OTA-enabled Yocto layer for Pi | If migrating to Yocto, Mender integration provides robust A/B OTA (alternative to custom slot-deploy). |
| **Raspberry Pi OS (64-bit)** | https://www.raspberrypi.com/software/ | 64-bit kernel with 32-bit userland | Pi Zero 2W has 64-bit capable CPU; evaluate if 64-bit Python+Vosk improves STT performance vs memory use. |
| **PikaOS** | https://github.com/PikaOS-Linux | Gaming/performance oriented Debian fork | Not ideal for YoYoPod but has interesting low-latency kernel patches applicable to audio. |
| **Ubuntu Core** | https://ubuntu.com/core | Snap-based embedded Ubuntu | Snaps are heavy for Pi Zero 2W; however, strict confinement useful for parental control sandboxing. |
| **BalenaOS** | https://www.balena.io/os/ | Container-based IoT OS | Docker/Podman pre-integrated; fleet management via balenaCloud. Good if containerizing services. |

---

## 2. Audio / Music / Media Playback

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **mpv** | https://mpv.io/ | YoYoPod's current media backend | Already integrated. Use `--no-video`, `--ao=alsa`, JSON IPC for control. Ensure `--cache=no` for local files. |
| **PipeWire** | https://pipewire.org/ | Modern low-latency audio/video server | Replaces PulseAudio/JACK. Better Bluetooth support for future headset integration. Resource use acceptable on Zero 2W. |
| **ALSA (Advanced Linux Sound Architecture)** | https://www.alsa-project.org/ | Kernel-level audio drivers and utils | Current YoYoPod audio path. Use `dmix` plugin for multiple stream mixing (music + TTS + call audio). |
| **GStreamer** | https://gstreamer.freedesktop.org/ | Pipeline-based multimedia framework | Alternative to mpv; better for VoIP integration (WebRTC, RTP). Use `playbin` for music, `webrtcbin` for calls. |
| **Snapcast** | https://github.com/badaix/snapcast | Synchronous multiroom audio client/server | Future feature: sync YoYoPod with home speakers. Client is lightweight, runs on Pi Zero. |
| **Mopidy** | https://mopidy.com/ | Extensible music server (MPD-compatible) | Python-based; could replace direct mpv control. Extensions for Spotify, local files. REST API for UI. |
| **MPD (Music Player Daemon)** | https://www.musicpd.org/ | Lightweight music server | Very low resource use. Client libraries in many languages. Good if UI and playback must decouple. |
| **Clementine / Strawberry** | https://www.strawberrymusicplayer.org/ | Qt music player (Strawberry is fork) | Too heavy for Zero 2W directly, but code structure useful for playlist/metadata handling reference. |
| **tinytag** | https://github.com/devsnd/tinytag | YoYoPod's current metadata reader | Already integrated. Pure Python, no deps. Supports MP3, OGG, FLAC, MP4, M4A, WMA, Wave, AIFF. |
| **Mutagen** | https://mutagen.readthedocs.io/ | Python audio metadata library | More comprehensive than tinytag. Consider if needing to WRITE metadata (voice message tags). |
| **SoX (Sound eXchange)** | http://sox.sourceforge.net/ | Swiss army knife of audio processing | Useful for audio format conversion, resampling, effects. Command-line friendly for scripts. |
| **shairport-sync** | https://github.com/mikebrady/shairport-sync | AirPlay audio receiver | Let parents stream music/podcasts to YoYoPod from iPhone. Low latency, runs well on Pi Zero. |
| **librespot** | https://github.com/librespot-org/librespot | Open source Spotify client | Rust-based, low resource. Could add Spotify Kids integration if account supports it. |
| **upmpdcli** | https://www.lesbonscomptes.com/upmpdcli/ | UPnP/DLNA renderer front-end for MPD | Integrate with home NAS/media server. Lightweight, well-maintained. |

---

## 3. VoIP / SIP / Real-time Communication

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **Liblinphone** | https://gitlab.linphone.org/BC/public/linphone-sdk | YoYoPod's current VoIP/SIP backend | Already integrated via C shim. Evaluate SDK v5+ for improved ARM support. Consider Belledonne's Flexisip for server. |
| **PJSIP** | https://www.pjsip.org/ | Open source SIP stack (C) | Alternative to Liblinphone. Smaller footprint, excellent embedded support. pjsua Python bindings available. |
| **Jami (GNU Ring)** | https://jami.net/ | Distributed SIP-compatible communicator | P2P architecture reduces server dependency. Qt-heavy but daemon (`dring`) can run headless. |
| **baresip** | https://github.com/baresip/baresip | Modular portable SIP user-agent | Extremely lightweight, modular. Perfect for embedded. JSON/HTTP control interface. Active development. |
| **SIPp** | https://github.com/SIPp/sipp | SIP test tool/traffic generator | Use for load-testing YoYoPod SIP integration, regression testing call flows in CI. |
| **re (libre)** | https://github.com/baresip/re | Async SIP stack (C) used by baresip | Could use standalone for custom lightweight SIP client if baresip too opinionated. |
| **Kamailio** | https://www.kamailio.org/ | Open source SIP server | If self-hosting SIP infrastructure for YoYoPod families. Very efficient, handles registrations, routing. |
| **Asterisk** | https://www.asterisk.org/ | PBX and telephony toolkit | Heavier than Kamailio but includes voicemail, IVR. Useful if building family "cloud" PBX. |
| **FreeSWITCH** | https://freeswitch.com/ | Soft-switch for VoIP/WebRTC | Alternative to Asterisk. Better WebRTC support if adding browser-based parent dashboard calling. |
| **Janus WebRTC Server** | https://janus.conf.meetecho.com/ | WebRTC gateway | Bridge YoYoPod SIP to WebRTC for parent browser calls without plugins. |
| **Matrix / Element (Matrix)** | https://matrix.org/ | Decentralized comms with VoIP | Synapse homeserver + Matrix SDK. E2EE messaging + VoIP. Overkill but future-proof for teen expansion. |
| **Jitsi Meet** | https://jitsi.org/ | Open source video conferencing | Not for YoYoPod directly, but Jitsi Videobridge could handle family group calls if expanding. |
| **SIP.js** | https://github.com/onsip/SIP.js/ | JavaScript SIP library | For parent web dashboard to call YoYoPod via WebRTC/SIP gateway. |
| **drachtio** | https://drachtio.org/ | Node.js SIP application framework | Rapidly build custom SIP server logic for YoYoPod-specific features (voicemail boxes, kid routing rules). |

---

## 4. Speech (STT / TTS / Voice AI)

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **Vosk** | https://github.com/alphacep/vosk-api | YoYoPod's current offline STT | Already integrated. Use small model (vosk-model-small-en-us-0.15, ~40MB). GPU not needed. Good for command recognition. |
| **Whisper.cpp** | https://github.com/ggerganov/whisper.cpp | Port of OpenAI Whisper to C++ | Higher accuracy than Vosk, especially for kids' voices. tiny.en model runs on Pi Zero 2W (~1-2x real-time). |
| **Piper** | https://github.com/rhasspy/piper | Fast local neural TTS | Much better quality than espeak-ng. ONNX-based, runs on CPU. ~1MB models. Ideal for YoYoPod responses. |
| **espeak-ng** | https://github.com/espeak-ng/espeak-ng | YoYoPod's current TTS backend | Already integrated. Robotic but tiny (~2MB). Keep as fallback; switch to Piper for main TTS. |
| **Coqui TTS** | https://github.com/coqui-ai/TTS | Deep learning TTS toolkit | Excellent quality but Python+PyTorch heavy. May not fit Pi Zero 2W memory constraints. Evaluate XTTS v2. |
| **Mycroft Precise** | https://github.com/MycroftAI/mycroft-precise | Lightweight wake-word engine | Replace "push-to-talk" with "Hey YoYo" wake word. TensorFlow Lite, runs on Pi. |
| **Porcupine (Picovoice)** | https://github.com/Picovoice/porcupine | Commercial wake-word engine (free tier) | More accurate than Precise. Free for personal use. Evaluate license for commercial YoYoPod. |
| **OpenWakeWord** | https://github.com/dscripka/openWakeWord | Open source wake-word detection | Pure Python + ONNX. Train custom "YoYo" wake word. Lower resource use than Mycroft. |
| **Sherpa/Sherpa-ONNX** | https://github.com/k2-fsa/sherpa-onnx | Next-gen Kaldi with ONNX | Streaming ASR, TTS, speaker ID. Very active. May supersede Vosk for embedded. |
| **DeepSpeech (Mozilla)** | https://github.com/mozilla/DeepSpeech | Deprecated but stable STT | No longer maintained (last release 2020). Not recommended for new work; listed for comparison only. |
| **Faster-Whisper** | https://github.com/SYSTRAN/faster-whisper | Optimized Whisper with CTranslate2 | More efficient than base Whisper. Still likely too heavy for Pi Zero 2W; test on target. |
| **Rhasspy** | https://rhasspy.readthedocs.io/ | Open source voice assistant toolkit | Full pipeline: wake word + STT + intent + TTS. Can self-host. YoYoPod could be a Rhasspy satellite. |
| **Home Assistant Assist** | https://www.home-assistant.io/voice_control/ | Open source voice pipeline | Willow / Assist pipeline. Could integrate for smart home control if expanding scope. |
| **SpeechRecognition (Python)** | https://github.com/Uberi/speech_recognition | Python wrapper for multiple STT engines | Useful abstraction if supporting multiple STT backends (Vosk, Whisper, cloud). |
| **Silero Models** | https://github.com/snakers4/silero-models | Pre-trained STT/TTS models (PyTorch) | Quality TTS models. Evaluate ONNX export for Pi Zero 2W inference. |

---

## 5. UI / Display / Embedded Graphics

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **LVGL** | https://lvgl.io/ | YoYoPod's current embedded GUI library | Already integrated via CFFI. Use v8.3+ for improved ARM performance. Consider v9 for future rendering improvements. |
| **SDL2 / pygame** | https://www.pygame.org/ | YoYoPod's simulator UI toolkit | Already used for sim. SDL2 directly (C) could replace LVGL if Python overhead acceptable. |
| **Whisplay HAT / ST7789** | https://github.com/pimoroni/st7789-python | Display driver for YoYoPod screen | Already integrated. 240x240 or 320x240 IPS. Hardware SPI. Check for kernel fb driver alternatives. |
| **Pimoroni Display HAT Mini** | https://shop.pimoroni.com/products/display-hat-mini | Alternative display hardware for YoYoPod | 320x240 IPS, four buttons. Different form factor. Driver: `displayhatmini` Python lib. |
| **Framebuffer (fbdev)** | https://www.kernel.org/doc/html/latest/fb/ | Linux kernel framebuffer interface | Bypass X11/Wayland entirely. Direct pixel writing. Fastest for Pi Zero 2W. LVGL can target fbdev. |
| **DirectFB2** | https://github.com/directfb2/DirectFB2 | Lightweight graphics library (revived) | Modern revival of DirectFB. Hardware acceleration where available. Smaller than SDL2. |
| **Cairo** | https://www.cairographics.org/ | 2D graphics library with multiple backends | Use with fbdev or image surface. Good for custom widget rendering if LVGL too restrictive. |
| **Pango** | https://pango.gnome.org/ | Text layout and rendering library | Internationalization, complex scripts. Pair with Cairo for non-Latin text (if expanding markets). |
| **Flutter Embedded** | https://github.com/sony/flutter-embedded-linux | Sony's Flutter for embedded Linux | Dart UI framework. Beautiful results but ~50MB+ binary. Evaluate if targeting Pi 3/4 in future. |
| **GTK4 / libadwaita** | https://gtk.org/ | GNOME toolkit (lightweight modes exist) | Too heavy for Pi Zero 2W directly, but GTK4 Broadway backend allows remote HTML5 UI for parent app. |
| **WPE WebKit** | https://wpewebkit.org/ | Embedded WebKit port | If wanting HTML/CSS/JS UI. Much lighter than full Chromium. ~30MB RAM. Consider for parent dashboard. |
| **Slint** | https://slint.dev/ | Declarative UI for embedded (Rust) | Modern alternative to LVGL. Rust/C++/JS API. Good designer tool. Evaluate for YoYoPod v2. |
| **TouchGFX** | https://www.touchgfx.com/ | STMicro's embedded GUI (free with STM, paid otherwise) | Excellent but proprietary/expensive. Listed for comparison; LVGL/Slint preferred. |
| **imgui** | https://github.com/ocornut/imgui | Immediate mode GUI (C++) | Game/debug oriented. Fast but not great for embedded. Could use for simulator/internal tools. |
| **Mesa / Lima (Mali GPU)** | https://docs.mesa3d.org/drivers/lima.html | Open source GPU driver for Mali-400 | Pi Zero 2W has VideoCore IV, not Mali. But relevant if porting to alternative ARM boards. |

---

## 6. Input / Buttons / Haptics

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **libgpiod** | https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git/ | Modern GPIO character device interface | YoYoPod already uses gpiod. Prefer over sysfs GPIO (deprecated). Supports events, multiple lines. |
| **gpiozero** | https://gpiozero.readthedocs.io/ | Friendly Python GPIO library | Higher-level than libgpiod. Good for prototypes. `Button` class with hold/repeat logic. |
| **evdev (python-evdev)** | https://github.com/gvalkov/python-evdev | Python bindings for Linux input subsystem | Read push-to-talk as evdev device. Useful for integrating GPIO keyboard events into LVGL input system. |
| **input-event-daemon** | https://github.com/gandro/input-event-daemon | Simple input event handler | Run scripts on button presses without full Python stack. Lightweight C daemon. |
| **kbd / loadkeys** | https://kbd-project.org/ | Linux keyboard tools | If using GPIO keyboard matrix or USB keypad for input. Map custom keys for YoYoPod functions. |
| **FFmpeg haptics** | N/A (use PWM directly) | Haptic feedback control | No specific OSS haptics lib. Use Pi GPIO PWM + drv2605 LRA driver (Adafruit lib) for vibration. |
| **Adafruit DRV2605** | https://github.com/adafruit/Adafruit_DRV2605_Library | Haptic motor driver library | Arduino lib portable to Linux. I2C control of LRA/ERM motors. Add "call buzzing" feedback. |
| **pigpio** | https://abyz.me.uk/rpi/pigpio/ | GPIO library with DMA, PWM, servo | Alternative to gpiod. Better for precise PWM (haptics, LED brightness). Daemon architecture. |
| **RPi.GPIO** | https://sourceforge.net/projects/raspberry-gpio-python/ | Legacy Python GPIO library | Still works but deprecated in favor of gpiod. Avoid for new code. |
| **smbus2** | https://github.com/kplindegaard/smbus2 | Python I2C/SMBus interface | For I2C-connected buttons, expanders (MCP23017). Pure Python, no C dependencies. |
| **mcp23017** | https://github.com/adafruit/Adafruit_CircuitPython_MCP23017 | I2C GPIO expander | Add more buttons via I2C if Pi GPIOs exhausted by modem/display/power. |
| **rotary-encoder** | https://github.com/mathertel/RotaryEncoder | Arduino-style rotary encoder lib | If adding volume knob. Portable to Linux GPIO. Interrupt-driven for responsiveness. |
| **uinput** | https://github.com/tuomasjjrasanen/python-uinput | Python virtual input device | Create virtual keyboard from GPIO buttons. Makes any app see "real" key presses. |
| **keyd** | https://github.com/rvaiya/keyd | Key remapping daemon at evdev level | Remap any input device (GPIO, USB, Bluetooth) to custom YoYoPod key layout. System-wide. |

---

## 7. Power Management / Battery / PMIC

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **PiSugar2 Pro** | https://github.com/PiSugar/PiSugar | YoYoPod's current power management HAT | Already integrated. I2C/UDP interface for battery %, RTC wake. Open-source case designs available. |
| **PiSugar Power Manager** | https://github.com/PiSugar/pisugar-power-manager-rs | Rust-based power manager for PiSugar | Official but community-enhanced. Better for embedded than Python scripts. |
| **INA219** | https://github.com/adafruit/Adafruit_INA219 | I2C current/voltage sensor | Add precise power monitoring if PiSugar readings insufficient. 0.1mA resolution. |
| **MAX17048** | https://github.com/adafruit/Adafruit_MAX17048_Library | LiPo fuel gauge via I2C | Alternative/additional battery monitoring. More accurate % than voltage-only measurement. |
| **UPower** | https://upower.freedesktop.org/ | D-Bus power management service | Abstract battery info across hardware. Integrate with YoYoPod UI for consistent "low battery" warnings. |
| **tlp / laptop-mode-tools** | https://linrunner.de/tlp/ | Linux power saving tools | Some optimizations applicable (USB autosuspend, SATA power). Adapt for Pi Zero 2W. |
| **cpufrequtils / cpufreqd** | https://github.com/Vladimir-csp/kernel-tools | CPU frequency scaling | Underclock Pi Zero 2W to 600MHz during idle to save power. Scale up for Vosk STT. |
| **rtcwake** | https://man7.org/linux/man-pages/man8/rtcwake.8.html | Linux RTC wake alarm | Core to YoYoPod's scheduled wake. Ensure PiSugar RTC is registered as `/dev/rtc0`. |
| **systemd-sleep / systemd-timers** | https://www.freedesktop.org/software/systemd/man/systemd-sleep.html | Systemd power management | Use systemd timers instead of cron for RTC-resilient scheduling. Suspend hooks for safe shutdown. |
| **Watchdog (bcm2835_wdt)** | https://github.com/raspberrypi/linux | Hardware watchdog timer | Enable in device tree. Reboot if YoYoPod UI process freezes. Critical for kid device reliability. |
| **pmu-tools** | https://github.com/andikleen/pmu-tools | Intel/ARM performance monitoring | Profile YoYoPod power consumption by subsystem. Identify battery drain sources. |
| **powertop** | https://github.com/fenrus75/powertop | Linux power consumption analyzer | Interactive tuning. Find processes preventing CPU sleep. Use in development, not production. |
| **gpio-shutdown** | https://github.com/Howchoo/pi-power-button | GPIO-triggered safe shutdown | Add physical power button via GPIO with safe shutdown script. Complement PiSugar auto-shutdown. |
| **PinePower / IronOS** | https://github.com/Ralim/IronOS | Open source soldering iron firmware | Not directly relevant, but IronOS has excellent battery/PWM management code patterns for STM32. |

---

## 8. Cellular / Modem / GPS / IoT Connectivity

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **SIM7600G-H** | https://www.simcom.com/product/SIM7600G.html | YoYoPod's current cellular modem | Already integrated. PPP for data, AT commands for SMS/GPS. Check SIMCom firmware updates. |
| **libqmi / qmicli** | https://www.freedesktop.org/wiki/Software/libqmi/ | Qualcomm QMI protocol library | If switching to Quectel EC25/EG25-G (QMI-based). More efficient than PPP. |
| **ModemManager** | https://www.freedesktop.org/wiki/Software/ModemManager/ | Unified modem management D-Bus service | Abstracts SIM7600, Quectel, etc. Handles registration, SMS, GPS, data. Better than raw AT in long run. |
| **Ofono** | https://git.kernel.org/pub/scm/network/ofono/ofono.git/ | Linux telephony stack | Alternative to ModemManager. More lightweight, but less active. Good for embedded voice-centric devices. |
| **ppp** | https://ppp.samba.org/ | Point-to-Point Protocol daemon | YoYoPod likely uses this for SIM7600 data. Consider `pppd` options for persistent connection, auto-redial. |
| **wvdial** | https://github.com/wvdial/wvdial | Easier PPP dialer | Simpler config than raw pppd. Good for development, but pppd preferred for production robustness. |
| **gpsd** | https://gpsd.gitlab.io/gpsd/ | GPS service daemon | Read SIM7600 GPS NMEA via gpsd. Unified interface for location. Python bindings available. |
| **cgps / xgps** | https://gpsd.gitlab.io/gpsd/gpsd-client-howto.html | GPSd clients | Visual GPS debugging. xgps requires X11; use cgps in terminal for headless debugging. |
| **minicom / picocom** | https://github.com/npat-efault/picocom | Serial terminal emulators | Essential for AT command debugging with SIM7600. picocom is smaller than minicom. |
| **atinout** | https://sourceforge.net/projects/atinout/ | Send AT commands, capture output | Scriptable AT commands from shell. Better than expect for simple queries (signal strength, IMEI). |
| **Sakari / Twilio Open** | N/A (API services) | SMS/voice gateway services | Not OSS, but Twilio has open SDKs. For parent→YoYoPod SMS notifications if SIP unavailable. |
| **ChirpStack** | https://www.chirpstack.io/ | Open source LoRaWAN network server | If adding LoRa for location/range (alternative to cellular GPS). Gateway on home router. |
| **The Things Network** | https://www.thethingsnetwork.org/ | Global open LoRaWAN network | Free tier for low-bandwidth IoT. Could send "I'm OK" beacons from YoYoPod if cellular fails. |
| **WireGuard** | https://www.wireguard.com/ | Modern fast VPN | Secure tunnel from YoYoPod to family server/cloud. Kernel module in modern Pi OS. Low overhead. |
| **Tailscale** | https://tailscale.com/ | Mesh VPN based on WireGuard | Closed coordination server, but open client. MagicDNS + NAT traversal simplifies family networking. Free personal plan. |
| **OpenThread / RCP** | https://openthread.io/ | IPv6-based mesh networking (Thread) | Future: mesh with other home IoT. Border router on Pi. Not directly needed for YoYoPod v1. |

---

## 9. OTA Updates / Device Management / Security

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **YoYoPod slot-deploy** | Custom | YoYoPod's custom atomic OTA system | Already integrated. Symlink swap A/B partitions. Ensure rollback on failed boot. Document and open-source this. |
| **Mender** | https://mender.io/ | Open source OTA for embedded Linux | Robust A/B updates with rollback. Client runs on Pi. Consider migrating from custom slot-deploy. |
| **RAUC** | https://rauc.io/ | Safe and secure Linux updating | From Pengutronix. A/B + symmetric/asymmetric keys. Yocto integration. Good if switching to Yocto. |
| **SWUpdate** | https://github.com/sbabic/swupdate | Linux software updater for embedded | Suricatta daemon for remote updates. Supports multiple media (USB, network, OTA). |
| **OSTree** | https://ostreedev.github.io/ostree/ | Git-like model for OS binaries | Atomic upgrades, rollback. Used by Flatpak, Fedora Silverblue. Could underpin slot-deploy with proven tech. |
| **fwupd / LVFS** | https://fwupd.org/ | Linux firmware update service | Primarily for x86/UEFI, but ARM support growing. Relevant if managing HAT firmware updates. |
| **Uptane** | https://uptane.github.io/ | Secure software update framework (AUTOSAR/OTA) | Security framework for OTA. Overkill for YoYoPod but good reference for threat model. |
| **sigstore / cosign** | https://www.sigstore.dev/ | Software signing and transparency | Sign OTA payloads. Free OIDC-based code signing. Reproducible builds + signed artifacts. |
| **The Update Framework (TUF)** | https://theupdateframework.io/ | Secure content delivery / update system | Framework for securing software updates. Uptane is automotive TUF profile. Reference for OTA security design. |
| **OpenSSL / LibreSSL** | https://www.openssl.org/ | Cryptographic library | TLS for MQTT/WSS, SIP SRTP. Keep updated for CVEs. LibreSSL is smaller alternative. |
| **mbedtls** | https://github.com/Mbed-TLS/mbedtls | Lightweight crypto library (ARM optimized) | Smaller than OpenSSL. Good for resource-constrained TLS. Used by many embedded projects. |
| **Dropbear** | https://matt.ucc.asn.au/dropbear/dropbear.html | Small SSH server/client | Replace OpenSSH on YoYoPod for remote debugging. ~100KB vs 1MB+. Disable in production. |
| **sudo / doas** | https://github.com/Duncaen/OpenDoas | Privilege escalation | Use doas instead of sudo for smaller footprint. Restrict which commands kids/parents can run. |
| **AppArmor / SELinux** | https://apparmor.net/ | Mandatory access control | Confine YoYoPod processes (mpv, python, linphone) to minimum permissions. AppArmor easier than SELinux. |
| **auditd / audit framework** | https://github.com/linux-audit/audit-documentation | Linux audit subsystem | Log security-relevant events. Track OTA attempts, config changes, unusual SIP connections. |
| **Tripwire / AIDE** | https://github.com/aide/aide | File integrity checker | Detect unauthorized modifications. Run after OTA to verify payload integrity. |
| **LUKS / dm-crypt** | https://gitlab.com/cryptsetup/cryptsetup/ | Disk encryption | Encrypt user data partition (voice messages, contacts). Not full disk (too slow on Zero 2W). |

---

## 10. Cloud / Backend / MQTT / Sync

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **paho-mqtt** | https://github.com/eclipse/paho.mqtt.python | YoYoPod's current MQTT client | Already integrated. Use WSS for firewall-friendly transport. Auto-reconnect, last will for offline detection. |
| **Mosquitto** | https://mosquitto.org/ | Open source MQTT broker | Self-host family broker. ACL per device. Bridge to cloud broker. Very lightweight. |
| **EMQX** | https://www.emqx.io/ | Scalable MQTT broker (open source core) | If scaling beyond family to product. MQTT v5, WebSocket, rule engine. |
| **HiveMQ (community)** | https://www.hivemq.com/ | Enterprise MQTT broker | Free for <100 devices. Cloud option. Evaluate if not self-hosting Mosquitto. |
| **Flask-SocketIO** | https://github.com/miguelgrinberg/Flask-SocketIO | YoYoPod sim server WebSocket layer | Already integrated. Use for real-time parent dashboard. Consider migrating to FastAPI + websockets for async. |
| **FastAPI** | https://fastapi.tiangolo.com/ | Modern async Python web framework | Alternative to Flask for parent API. Native async/await, automatic OpenAPI docs, pydantic validation. |
| **Django / Django REST Framework** | https://www.django-rest-framework.org/ | Full-featured Python web framework | If parent dashboard needs ORM, admin, auth. Heavy but rapid development. |
| **Node-RED** | https://nodered.org/ | Visual programming for IoT | Rapidly prototype family automation flows. YoYoPod MQTT → Node-RED → notifications, logging. |
| **Home Assistant** | https://www.home-assistant.io/ | Open source home automation platform | Parent dashboard foundation. MQTT integration, mobile app, automation. Self-hosted, privacy-first. |
| **Nextcloud** | https://nextcloud.com/ | Self-hosted cloud platform | Family file sync, calendar, contacts. Could host voice message backups via WebDAV. |
| **Syncthing** | https://syncthing.net/ | Continuous file synchronization | P2P sync of voice messages/music between YoYoPod and parent devices. No central server. |
| **Caddy** | https://caddyserver.com/ | Easy automatic HTTPS web server | Reverse proxy for parent dashboard. Auto Let's Encrypt. Much simpler than Nginx config. |
| **Nginx** | https://nginx.org/ | High-performance web server/proxy | Standard reverse proxy, load balancer. Use if team already familiar. |
| **Traefik** | https://traefik.io/ | Cloud-native edge router | Auto-discovery of Docker services. Useful if containerizing YoYoPod services. |
| **Cloudflare Tunnel (cloudflared)** | https://github.com/cloudflare/cloudflared | Secure tunnel to Cloudflare edge | YoYoPod already uses this. Open source client. No open inbound ports needed. |
| **ngrok** | https://ngrok.com/ | Secure tunnel to localhost | Alternative to Cloudflare Tunnel. Free tier has limitations. Closed source; prefer cloudflared. |
| **frp (Fast Reverse Proxy)** | https://github.com/fatedier/frp | Open source reverse proxy tunnel | Self-hosted alternative to Cloudflare/ngrok. Run frps on cloud VM, frpc on YoYoPod. |

---

## 11. Build / Deploy / Packaging / CI

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **GitHub Actions** | https://github.com/features/actions | CI/CD automation | Build YoYoPod OS images, run tests, publish releases. Self-hosted runner on ARM for native builds. |
| **GitLab CI** | https://docs.gitlab.com/ee/ci/ | Alternative CI/CD with self-hosting option | Self-host for private kid-safety codebase. Built-in container registry. |
| **debos** | https://github.com/go-debos/debos | Debian OS image builder | Build custom Raspberry Pi images from Debian packages. YAML-based recipes. Faster than debootstrap scripts. |
| **pi-gen** | https://github.com/RPi-Distro/pi-gen | Official Raspberry Pi OS image generator | Fork to build custom YoYoPod Raspbian variant. Stage-based build. Well-documented. |
| **Packer** | https://www.packer.io/ | Multi-platform image builder | Build YoYoPod images for Pi + simulator environments. HCL-based templates. |
| **Docker / Podman** | https://podman.io/ | Container engines | Containerize YoYoPod services (sim, build env). Podman daemonless, rootless - better for embedded. |
| **Buildah** | https://buildah.io/ | OCI container image builder | Build containers without Docker daemon. Integrate in CI for YoYoPod service containers. |
| **crossenv / cross-python** | https://github.com/benfogle/crossenv | Cross-compile Python packages | Build ARM Python wheels on x86 CI. Essential for Vosk, Liblinphone Python bindings. |
| **cibuildwheel** | https://github.com/pypa/cibuildwheel | Build Python wheels across platforms | Automate ARMv7/aarch64 wheel builds for YoYoPod Python deps in CI. |
| **Poetry** | https://python-poetry.org/ | Python dependency management and packaging | Lockfile for reproducible YoYoPod Python environment. Better than requirements.txt for embedded. |
| **pip-tools** | https://github.com/jazzband/pip-tools/ | pip workflow for deterministic deps | Alternative to Poetry. `pip-compile` for lockfiles. Lighter weight. |
| **PyOxidizer** | https://github.com/indygreg/PyOxidizer | Package Python as standalone executable | Single binary for YoYoPod app. No system Python deps. Faster startup. Evaluate for production. |
| **Nuitka** | https://nuitka.net/ | Python to C compiler | Compile YoYoPod Python to C for performance + obfuscation. Long build times but faster runtime. |
| **GitVersion** | https://gitversion.net/ | Semantic versioning from Git history | Auto-version YoYoPod releases based on commits. Integrate with slot-deploy OTA versioning. |
| **Renovate / Dependabot** | https://github.com/renovatebot/renovate | Automated dependency updates | Keep Python, JS, GitHub Actions deps updated. Critical for security (mqtt, flask, crypto libs). |

---

## 12. Open Hardware / Reference Designs / HATs

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **Raspberry Pi Zero 2 W** | https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/ | YoYoPod compute module | Already chosen. 1GHz quad-core ARM Cortex-A53, 512MB RAM. Verify supply chain availability. |
| **PiSugar2 Pro** | https://github.com/PiSugar/PiSugar | Battery HAT with RTC | Already integrated. 5000mAh. Open-source case STLs. Consider contributing PCB improvements. |
| **Pimoroni Display HAT Mini** | https://shop.pimoroni.com/products/display-hat-mini | 320x240 IPS LCD + buttons | Alternative to current ST7789/Whisplay. Better button integration. Python library well-maintained. |
| **Adafruit PiTFT** | https://www.adafruit.com/product/2423 | 2.8" 320x240 TFT + resistive touch | Touch option for YoYoPod. Capacitive version available. Kernel fb driver + tslib for touch. |
| **Waveshare LCD HATs** | https://www.waveshare.com/ | Wide range of Pi LCD HATs | Cost-effective alternatives. 1.3" OLED, 1.54" LCD, 2.0" IPS options. Check SPI speed compatibility. |
| **ReSpeaker HATs** | https://wiki.seeedstudio.com/ReSpeaker_2_Mics_Pi_HAT/ | Microphone array HATs | 2-mic or 4-mic array with LED ring. Better Vosk accuracy than single mic. WS2812 LED for status. |
| **IQaudio / Raspberry Pi Audio HATs** | https://www.raspberrypi.com/products/iqaudio-dac-pro/ | High-quality audio DAC HATs | If PCM audio quality insufficient. DAC Pro, Codec Zero for speaker + mic in one HAT. |
| **Sixfab Cellular HATs** | https://sixfab.com/product-category/shields/hat-shields/ | Alternative cellular HATs | Quectel EG25-G based. Better Linux driver support than SIM7600. GPS + LTE in one. |
| **Waveshare SIM7600G-H HAT** | https://www.waveshare.com/sim7600g-h-4g-hat.htm | YoYoPod modem hardware reference | Verify against current HAT. Waveshare provides open schematics. Check antenna placement in case design. |
| **ArduCam** | https://www.arducam.com/ | Camera modules for Pi | Future feature: video messages. Mini 2MP or OV5647. libcamera on modern Pi OS. |
| **HiFiBerry** | https://www.hifiberry.com/ | Audiophile DAC/AMP HATs | If targeting premium audio. DAC+ AMP for direct speaker drive. DSP versions for EQ. |
| **Enviro HATs (Pimoroni)** | https://shop.pimoroni.com/products/enviro?variant=31155658457171 | Environmental sensors | Not core to YoYoPod but interesting for "weather report" voice feature. BME280 temp/humidity/pressure. |
| **Open Book / Oddly Specific Objects** | https://github.com/joeycastillo/The-Open-Book | Open source e-reader hardware | Reference for kid-friendly case design, button layout, durability. E-ink not suitable for YoYoPod UI. |
| **Framework Laptop (open ecosystem)** | https://frame.work/ | Modular repairable laptop | Not Pi-related, but open hardware philosophy aligns. Reference for repairability documentation. |
| **OSHWA Certification** | https://certification.oshwa.org/ | Open source hardware certification | Pursue for YoYoPod hardware design. Marketing value, community trust. |
| **KiCad** | https://www.kicad.org/ | Open source PCB design | Design YoYoPod custom carrier board if moving beyond HATs. Active development, huge community. |
| **FreeCAD** | https://www.freecad.org/ | Open source parametric 3D CAD | Design YoYoPod case. Export STL for 3D printing. Assembly workbench for fitting PCBs. |
| **OpenSCAD** | https://openscad.org/ | Code-based 3D CAD | Parametric case design. Version-control friendly. Good for programmatic case variations (size, port placement). |

---

## 13. Kids / Parental Control / Safety

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **Gabb Phone (reference)** | https://gabb.com/ | Commercial kid-safe phone | Not OSS. Study as competitor: limited apps, parent portal, no internet. YoYoPod should differentiate on open platform. |
| **Pinwheel (reference)** | https://www.pinwheel.com/ | Another kid phone | Not OSS. Parent-approved contact list, scheduled availability. Feature reference. |
| **Kidslox / Qustodio (reference)** | https://www.qustodio.com/ | Parental control apps | Not OSS. Study their parent dashboard UX. YoYoPod's open alternative should match usability. |
| **OpenDNS Family Shield** | https://www.opendns.com/setupguide/?url=familyshield | Free DNS-based content filtering | Block adult content at DNS level. Configure on YoYoPod or home router. Cisco-owned but free. |
| **Pi-hole** | https://pi-hole.net/ | Network-wide ad/tracker blocking | Run on home router. Block ads, trackers, unwanted domains for YoYoPod. Dashboard shows queries. |
| **AdGuard Home** | https://github.com/AdguardTeam/AdGuardHome | Pi-hole alternative with DoH/DoT | Better encryption defaults. Parental control filtering lists. Single binary, easy setup. |
| **Let's Encrypt / certbot** | https://certbot.eff.org/ | Free TLS certificates | Secure parent dashboard, MQTT WSS, SIP TLS. Automate renewal. |
| **Step-CA** | https://github.com/smallstep/certificates | Private ACME certificate authority | Issue internal certs for YoYoPod fleet without public DNS. mTLS between devices. |
| **Headscale** | https://github.com/juanfont/headscale | Self-hosted Tailscale control server | Fully open source Tailscale alternative. Family VPN mesh without external dependency. |
| **NetBird** | https://github.com/netbirdio/netbird | Open source Tailscale/ZeroTier alternative | WireGuard-based mesh. Self-hosted. Good for family device networking with open stack. |
| **FreedomBox** | https://freedombox.org/ | Personal home server for non-experts | Run on home Pi. Provides VPN, chat, file share. YoYoPod could integrate as "FreedomBox device." |
| **Sugar Learning Platform** | https://www.sugarlabs.org/ | OLPC educational desktop | Not directly usable, but UI metaphors (activities, journal) relevant for kid UX design. |
| **GCompris** | https://gcompris.net/ | Educational software suite | Qt-based. Too heavy for Zero 2W but mini-games could inspire YoYoPod "activity" concepts. |
| **Scratch / ScratchJr** | https://scratch.mit.edu/ | Visual programming for kids | Future: YoYoPod could expose simple "program your button actions" via block-based editor. |
| **micro:bit / MakeCode** | https://makecode.microbit.org/ | Educational embedded programming | Similar age target. Study their UX for simplicity. Could support micro:bit radio as expansion. |
| **COPPA / GDPR-K compliance guides** | https://www.ftc.gov/business-guidance/privacy-security/childrens-privacy | Legal compliance resources | Not software, but essential. YoYoPod must comply. Open-source policies and consent flows. |

---

## 14. Testing / Observability / Debugging

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **pytest** | https://docs.pytest.org/ | Python testing framework | Test YoYoPod Python components. Fixtures for simulating GPIO, audio, SIP. Parametrize for hardware variants. |
| **pytest-asyncio** | https://github.com/pytest-dev/pytest-asyncio | Pytest support for async tests | Test async MQTT, WebSocket, SIP handlers. Essential for modern Python concurrency. |
| **coverage.py** | https://coverage.readthedocs.io/ | Code coverage measurement | Track test coverage. Target 80%+ for safety-critical code (OTA, calling, power). |
| **Hypothesis** | https://hypothesis.readthedocs.io/ | Property-based testing | Generate random SIP messages, audio files, button sequences to find edge cases. |
| **Locust** | https://locust.io/ | Load testing via Python | Simulate many parent dashboard users. Test Flask-SocketIO concurrency limits. |
| **SIPp** | https://github.com/SIPp/sipp | SIP protocol test tool | Load-test Liblinphone integration. Simulate call floods, malformed messages, registration storms. |
| **Wireshark / tshark** | https://www.wireshark.org/ | Network protocol analyzer | Debug SIP, RTP, MQTT, TLS issues. Capture on Pi via SSH + tshark. Essential for VoIP QA. |
| **tcpdump** | https://www.tcpdump.org/ | Command-line packet analyzer | Lightweight capture on YoYoPod itself. Save to file, analyze on desktop Wireshark. |
| **strace** | https://strace.io/ | System call tracer | Debug why mpv/Liblinphone hangs. Trace file accesses, network calls. Low overhead. |
| **ltrace** | https://ltrace.org/ | Library call tracer | Trace C library calls (libc, libgpiod, liblinphone). Complement to strace. |
| **perf / perf-tools** | https://github.com/brendangregg/perf-tools | Linux performance analysis | Profile CPU usage by function. Identify Vosk/Whisper hotspots. Flame graphs for visualization. |
| **py-spy** | https://github.com/benfred/py-spy | Sampling profiler for Python | Profile YoYoPod Python without code changes. Top-like live view, flame graphs. |
| **memray** | https://github.com/bloomberg/memray | Python memory profiler | Track memory leaks in long-running YoYoPod process. Essential for 512MB Pi Zero 2W. |
| **Prometheus** | https://prometheus.io/ | Metrics collection and alerting | Scrape YoYoPod metrics (battery, signal strength, temperature). Alert on anomalies. |
| **Grafana** | https://grafana.com/ | Metrics visualization dashboard | Parent/fleet dashboard for device health. Open source, rich alerting. |
| **Node-Exporter** | https://github.com/prometheus/node_exporter | Hardware/OS metrics for Prometheus | Standard Pi metrics. Extend with textfile collector for YoYoPod-specific metrics (battery %, SIP status). |
| **Loki** | https://grafana.com/oss/loki/ | Log aggregation system | Collect YoYoPod logs centrally. Label by device ID. Grafana integration for log-based alerting. |
| **Promtail** | https://grafana.com/docs/loki/latest/send-data/promtail/ | Log shipper for Loki | Run on YoYoPod to ship logs. Low resource use. Journald integration on systemd systems. |
| **systemd-cgtop** | https://www.freedesktop.org/software/systemd/man/systemd-cgtop.html | Control group top | Monitor resource use by YoYoPod services in real-time. Built into systemd. |
| **htop** | https://htop.dev/ | Interactive process viewer | Better than top. Essential for SSH debugging on YoYoPod. Tree view, color-coded. |
| **dmesg / journalctl** | Built-in | Kernel and system logs | First stop for hardware issues (modem not detected, I2C errors, audio card probe). |

---

## 15. Alternative Languages / Runtimes / Performance

| Project | URL | One-Line Relevance | Integration Note |
|---------|-----|-------------------|------------------|
| **CPython 3.12** | https://www.python.org/ | YoYoPod's current runtime | Already integrated. Faster than 3.9. Use `--enable-optimizations` when building. Consider 3.13 (faster). |
| **PyPy** | https://www.pypy.org/ | Fast Python implementation with JIT | 3-5x faster for pure Python. ARM builds available. Test with YoYoPod code; may help UI responsiveness. |
| **Cython** | https://cython.org/ | Python to C compiler | Speed critical paths (LVGL bindings, audio pipeline). Type-annotated Python → C extension. |
| **mypyc** | https://github.com/mypyc/mypyc | Compile typed Python to C | Similar to Cython but from type hints. Gradual migration. Good for hot paths. |
| **Rust** | https://www.rust-lang.org/ | Systems language with safety guarantees | Rewrite C shims (Liblinphone, LVGL bindings) in Rust for memory safety. `pyo3` for Python interop. |
| **PyO3** | https://github.com/PyO3/pyo3 | Rust bindings for Python | Write performance-critical YoYoPod modules in Rust, call from Python. Safer than C extensions. |
| **Maturin** | https://github.com/PyO3/maturin/ | Build and publish Rust/Python crates | Easy PyO3 project packaging. `maturin build` produces pip-installable wheels. |
| **Zig** | https://ziglang.org/ | Systems language with C interop | Cross-compile C dependencies (mpv, LVGL) with Zig toolchain. Better cross-compilation than gcc. |
| **Nim** | https://nim-lang.org/ | Python-like syntax, C performance | Could replace Python for YoYoPod core. Compiles to C. `nimpy` for Python interop. Niche but interesting. |
| **MicroPython** | https://micropython.org/ | Python for microcontrollers | Not for Pi Zero 2W directly, but useful for co-processor (RP2040) if adding custom peripheral controller. |
| **CircuitPython** | https://circuitpython.org/ | Adafruit's MicroPython fork | Better library ecosystem for sensors/displays. Use on RP2040 companion board for HAT management. |
| **Zephyr RTOS** | https://zephyrproject.org/ | Real-time OS for microcontrollers | If adding STM32/RP2040 co-processor for real-time tasks (audio, button latency). Not for Linux Pi. |
| **FreeRTOS** | https://www.freertos.org/ | Popular embedded RTOS | Alternative to Zephyr. Simpler. Use on co-processor for deterministic audio pipeline. |
| **WebAssembly (Wasmtime / Wasmer)** | https://wasmtime.dev/ | Wasm runtime outside browser | Sandboxed plugins for YoYoPod (games, voice effects). Secure, portable. Overhead acceptable? |
| **LuaJIT** | https://luajit.org/ | High-performance Lua JIT | Embed for configuration, scripting, UI logic. Very fast, tiny. mpv uses Lua for user scripts. |
| **Duktape / QuickJS** | https://bellard.org/quickjs/ | Lightweight JavaScript engines | If wanting JS for YoYoPod extensions. QuickJS is small and fast. Duktape even smaller. |
| **Bun** | https://bun.sh/ | Fast JavaScript runtime | Not for Pi Zero 2W (requires 64-bit, ARMv8.2+). Listed for future ARM server parent backend. |
| **Go** | https://go.dev/ | Fast compiling language with concurrency | Rewrite parent backend or device services in Go. Efficient goroutines for MQTT/SIP handling. |
| **TinyGo** | https://tinygo.org/ | Go for microcontrollers and WASM | Go on RP2040/STM32. If choosing Go ecosystem but need bare-metal performance. |
| **NATS** | https://nats.io/ | High-performance messaging (Go-based) | Alternative to MQTT for internal service communication. Faster, simpler protocol. |

---

## Integration Priority Matrix

| Priority | Cluster | Rationale |
|----------|---------|-----------|
| **P0 - Immediate** | 2 (Audio), 3 (VoIP), 4 (Speech), 5 (UI), 7 (Power) | YoYoPod core functionality; evaluate alternatives to current stack |
| **P1 - Near-term** | 1 (OS), 8 (Cellular), 9 (OTA), 10 (Cloud) | Production readiness, reliability, parent experience |
| **P2 - Medium-term** | 6 (Input), 11 (Build), 14 (Observability) | Developer experience, manufacturing, fleet management |
| **P3 - Future** | 12 (Open HW), 13 (Safety), 15 (Alt langs) | v2 hardware, regulatory, performance optimization |

---

## License Summary of Key Projects

| Project | License | Notes |
|---------|---------|-------|
| mpv | GPL-2.1+ | OK for YoYoPod |
| Liblinphone | GPL-3.0 / Commercial | Check SDK v5 license; dual-licensed |
| Vosk | Apache-2.0 | Models have separate licenses (Apache-2.0) |
| LVGL | MIT | Very permissive |
| Python 3.12 | PSF-2.0 | OK |
| mosquitto | EPL-2.0 / EDL-1.0 | Dual license, OK |
| WireGuard | GPL-2.0 | OK |
| Mender | Apache-2.0 / Commercial | Client OSS, management server commercial |
| RAUC | LGPL-2.1 | OK |
| Buildroot | GPL-2.0+ | OK |
| Whisper.cpp | MIT | OK |
| Piper | MIT | OK |
| paho-mqtt | EPL-2.0 / EDL-1.0 | OK |

---

*Document compiled for YoYoPod engineering team. Verify all URLs and licenses before integration. Last updated: 2026-04-25*
