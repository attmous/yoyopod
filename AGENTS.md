# YoyoPod Development Status & Debug Guide

**Last Updated:** 2025-10-19
**Hardware:** Raspberry Pi Zero 2W (416 MB RAM)
**Project:** iPod-inspired VoIP music player with I2C display

---

## Current Development Status

### ✅ Completed Features

#### Phase 1-3: Core Infrastructure
- Display driver (DisplayHATMini 320x240)
- Input handling (4 buttons: A, B, X, Y)
- Screen management system with stack navigation
- Audio playback via Mopidy
- Playlist management
- Contact management

#### Phase 4: VoIP Integration (COMPLETED)
- **VoIPManager** with linphonec backend
- SIP registration with HA1 hash authentication
- Contact lookup and caller name resolution
- **Outgoing calls:** Working perfectly with contact names and live duration
- **Incoming calls:** Working perfectly with caller name display and call acceptance
- **Call state management:** Proper screen transitions between states
- **Screen navigation:** Fixed stack overflow issues and proper cleanup on call end

### 🎯 Current Status: VoIP Fully Functional

**What Works:**
- Outgoing calls display contact names correctly
- Live call duration updates during calls
- Incoming calls show caller name during ring
- Call acceptance/rejection with proper UI feedback
- Screen transitions: Menu → Contact List → Outgoing → In Call → Back to Menu
- Incoming call: Any Screen → Incoming Call → In Call → Back to Previous Screen

### ✅ Phase 5: Integration (COMPLETE)

**Goal:** Merge VoIP and music streaming into unified YoyoPod application

**Status:** ALL PHASES COMPLETE ✓ - Production Ready

**Key Integration Points:**
- Unified state machine managing both VoIP and music
- Auto-pause music on incoming calls
- Auto-resume music after call ends (configurable)
- Seamless screen transitions during call interruptions
- Context-sensitive button controls

**Phase 1 Complete (2025-10-19):**
- ✅ Enhanced StateMachine with 3 new states
- ✅ Added 24+ new state transitions
- ✅ Created `YoyoPodApp` coordinator class
- ✅ Implemented callback coordination
- ✅ All state machine tests passing

**Phase 2 Complete (2025-10-19):**
- ✅ Implemented `_setup_screens()` - registers all 9 screens
- ✅ Screen integration complete:
  - Music screens: MenuScreen, NowPlayingScreen, PlaylistScreen
  - VoIP screens: CallScreen, ContactListScreen, IncomingCallScreen, OutgoingCallScreen, InCallScreen
  - Navigation: HomeScreen
- ✅ Screen transitions wired to callbacks:
  - Incoming call → push IncomingCallScreen
  - Call connected → push InCallScreen
  - Call ended → pop all call screens
  - Track change → refresh NowPlayingScreen
- ✅ `_pop_call_screens()` helper prevents stack overflow
- ✅ Created `yoyopod.py` - production application
- ✅ Full UI navigation working

**Phase 3 Complete (2025-10-19):**
- ✅ Music auto-pause on incoming call working perfectly
- ✅ Music auto-resume after call ends (configurable)
- ✅ Call interruption tested on hardware
- ✅ Microphone configuration fixed (USB audio card direct access)
- ✅ All state transitions validated
- ✅ User confirmation: "Perfect all works!!"

**Phase 4 Complete (2025-10-19):**
- ✅ RAM profiling: 54.5 MB app, 151 MB available system RAM
- ✅ UX refinements implemented:
  1. Progress bar animation (1 Hz updates)
  2. Pause icon sync after call ends
  3. State machine sync with mopidy/VoIP states
  4. Audible ringing for incoming calls (800Hz tone)
- ✅ Bug fixes applied:
  - Added `StateMachine.is_call_active()` method
  - Added missing CALL_INCOMING state transitions
- ✅ Documentation complete:
  - `docs/SYSTEM_ARCHITECTURE.md` - Full system diagrams
  - `docs/INTEGRATION_PLAN.md` - Updated with completion status
  - `docs/PHASE2_SUMMARY.md` - Screen integration details

**Next Steps:**
1. Deploy to production (running on hardware)
2. Monitor for edge cases
3. Future enhancements (see Phase 5+ in integration plan)

**Integration Plan:** See `docs/INTEGRATION_PLAN.md` for complete architecture, state diagrams, and implementation phases.

---

## Key Technical Details

### Hardware Setup
- **Device:** Raspberry Pi Zero 2W
- **Display:** Pimoroni DisplayHATMini (I2C, 320x240 LCD)
- **Buttons:** 4 tactile buttons (A, B, X, Y)
- **Audio:** USB sound card or built-in audio
- **Network:** WiFi for SIP and mopidy streaming

### Software Stack
- **OS:** Raspberry Pi OS
- **Python:** 3.x with virtual environment
- **VoIP:** linphonec (Linphone 5.3.105 CLI)
- **Music:** mopidy server + mopidy-local extension
- **Display:** ST7789 driver via SPI
- **Dependencies:** Managed via uv/pip

### Critical Linphone Version Differences

**Linphone 5.x vs 4.x Output Patterns:**
- Linphone 5.x uses `"CallSession"` (not just `"Call"`)
- Linphone 5.x uses `"LinphoneCallIncoming"` state
- Linphone 5.x uses **square brackets** `[sip:user@domain]` not angle brackets
- Linphone 5.x outputs **lowercase** `"New incoming call from..."` not `"Call from..."`

**Impact:** Pattern matching must be case-insensitive and support multiple formats.

---

## RAM Usage Analysis

### Test Results (Actual Use Case)

**Scenario:** Music streaming + VoIP ready to receive calls

```
Total RAM: 416 MB
Used RAM:  264 MB
Free RAM:  92 MB
Available: 151 MB ✅

Process Breakdown:
- demo_playlists.py:  54.5 MB (12.7%)
- mopidy (streaming): 28.7 MB (6.7%)
- linphonec:          21.7 MB (5.1%)
- Total apps:        ~105 MB
```

**Conclusion:** System is viable with 151 MB available RAM remaining.

### RAM Optimization Options

**Non-Essential Services (Headless Setup):**
- `wf-panel-pi` + `pcmanfm`: ~11 MB (desktop environment)
- `cups` + `cups-browsed`: ~8 MB (printing)
- `bluetooth`: ~6 MB (if not using Bluetooth)
- `avahi-daemon`: ~3 MB (mDNS, lose .local hostname)
- `ModemManager`: ~3 MB (mobile modems)

**Conservative optimization:** Disable desktop + cups = ~20 MB saved → ~170 MB available
**Aggressive optimization:** Above + Bluetooth + Avahi = ~35 MB saved → ~185 MB available

---

## Development & Debug Workflow

### Remote Development Setup

**SSH Access:**
```bash
ssh rpi-zero  # or ssh tifo@192.168.x.x
```

**Project Location:**
- Local: `/home/tifo/Workspace/yoyo-py`
- RPi: `/home/tifo/yoyo-py`

**Deploy & Test Workflow:**
```bash
# On local machine: commit and push changes
git add . && git commit -m "message" && git push

# On RPi: pull and test
ssh rpi-zero "cd yoyo-py && git pull origin main"
ssh rpi-zero "cd yoyo-py && source .venv/bin/activate && python demo_voip.py"
```

### Running Demos

**VoIP Demo:**
```bash
# On RPi (with hardware)
cd yoyo-py
source .venv/bin/activate
python demo_voip.py

# Simulation mode (no hardware required)
python demo_voip.py --simulate
```

**Music Demo:**
```bash
python demo_playlists.py  # Playlist browser
python demo_mopidy.py     # Full mopidy integration
```

**Test Scripts:**
```bash
python test_voip_registration.py      # Test SIP registration
python test_incoming_call_debug.py    # Debug incoming call detection
```

### Common Debug Commands

**Check running processes:**
```bash
ssh rpi-zero "ps aux | grep -E '(python|linphonec|mopidy)'"
```

**Check RAM usage:**
```bash
ssh rpi-zero "free -h"
ssh rpi-zero "ps aux --sort=-%mem | head -20"
```

**Kill stuck processes:**
```bash
ssh rpi-zero "killall -9 python linphonec"
```

**Check VoIP logs:**
```bash
# Logs are output to stderr by demo scripts
# Use DEBUG level for detailed linphonec output
```

**Check mopidy service:**
```bash
ssh rpi-zero "systemctl --user status mopidy"
ssh rpi-zero "systemctl --user restart mopidy"
```

### Python Module Reload Issue

**Problem:** After `git pull`, Python doesn't reload cached modules
**Solution:** Kill all Python processes before restarting:
```bash
ssh rpi-zero "killall -9 python linphonec"
# Then start demo again
```

---

## Configuration Files

### VoIP Configuration
**Location:** `config/voip_config.yaml`

```yaml
account:
  sip_server: "sip.linphone.org"
  sip_username: "your_username"
  sip_password: "your_password"          # Plain text (optional)
  sip_password_ha1: "hash_here"          # HA1 hash (preferred)
  sip_identity: "sip:user@sip.linphone.org"
  transport: "tcp"
  display_name: "YoyoPod"

network:
  stun_server: "stun.linphone.org"
  enable_ice: true

linphonec_path: "/usr/bin/linphonec"
```

### Contacts Configuration
**Location:** `config/contacts.yaml`

```yaml
contacts:
  - name: "John Doe"
    sip_address: "sip:john@sip.linphone.org"
    favorite: true
    notes: "Friend"

  - name: "Jane Smith"
    sip_address: "sip:jane@example.com"
    favorite: false
    notes: ""

speed_dial:
  1: "sip:john@sip.linphone.org"
  2: "sip:jane@example.com"
```

---

## Known Issues & Solutions

### Issue 1: Incoming Call Not Detected

**Symptoms:**
- Call comes in but no UI update
- LED changes but screen frozen

**Root Causes:**
1. Case-sensitive pattern matching (Linphone 5.x uses lowercase "call")
2. Square bracket format `[sip:...]` not matched
3. Caller address extraction fails → callback not fired

**Solution Applied:**
- `yoyopy/connectivity/voip_manager.py:376-377` - Case-insensitive matching
- `yoyopy/connectivity/voip_manager.py:382-417` - Support multiple SIP address formats

### Issue 2: Caller Name Not Shown During Ring

**Symptoms:**
- Incoming call screen shows "Unknown"
- Name appears correctly after answering

**Root Cause:**
- IncomingCallScreen created at startup with empty values
- Callback didn't update screen instance variables before pushing

**Solution Applied:**
- `demo_voip.py:208-217` - Update screen properties in callback before push

### Issue 3: Screen Frozen After Call Ends

**Symptoms:**
- After hangup, stuck on call screen
- Can't return to menu

**Root Causes:**
1. Incoming call callback fires repeatedly during ring → screen stack overflow
2. Only one screen popped when call ends → stuck in deep stack

**Solutions Applied:**
- `demo_voip.py:216-217` - Guard condition: only push if not already on screen
- `demo_voip.py:229-235` - Loop to pop ALL call-related screens on release

---

## Important Code Locations

### Core VoIP Implementation
- `yoyopy/connectivity/voip_manager.py` - VoIPManager class, linphonec interface
- `yoyopy/connectivity/voip_config.py` - VoIP configuration dataclass
- `yoyopy/config/config_manager.py` - Config and contact management

### UI Screens
- `yoyopy/ui/screens.py` - All screen implementations:
  - CallScreen (VoIP status)
  - ContactListScreen (browsable contacts)
  - OutgoingCallScreen (calling...)
  - IncomingCallScreen (incoming ring)
  - InCallScreen (active call with duration)

### Demo Applications
- **`yoyopod.py`** - ⭐ **PRODUCTION APP** - Full VoIP + Music integration (Phase 2 complete)
- `demo_yoyopod_phase1.py` - Phase 1 core framework test (state machine only)
- `demo_voip.py` - VoIP-only demo with full UI
- `demo_playlists.py` - Music playlist browser
- `demo_mopidy.py` - Mopidy streaming demo

### Test Scripts
- `test_phase1_state_machine.py` - Phase 1 state machine validation (8 tests)
- `test_voip_registration.py` - Test SIP registration
- `test_incoming_call_debug.py` - Debug incoming call detection with DEBUG logs

---

## Debug Patterns

### Pattern 1: Check Linphonec Output

When calls don't work, use DEBUG logging to see raw linphonec output:

```python
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")  # Enable DEBUG level
```

**Look for:**
- `"New incoming call from [sip:user@domain]"` - Incoming call detected
- `"Call state: idle -> incoming"` - State change
- `"Extracted caller address: ..."` - Address extraction working
- `"INCOMING CALL CALLBACK FIRED!"` - Callback triggered

### Pattern 2: Test in Isolation

Create minimal test scripts to isolate issues:

```python
# Minimal VoIP test
from yoyopy.connectivity import VoIPManager, VoIPConfig
from yoyopy.config import ConfigManager

cm = ConfigManager("config")
vc = VoIPConfig.from_config_manager(cm)
vm = VoIPManager(vc, cm)

def on_incoming(addr, name):
    print(f"CALL FROM: {name} ({addr})")

vm.on_incoming_call(on_incoming)
vm.start()

import time
while True:
    time.sleep(1)
```

### Pattern 3: Check Call State Flow

Expected state transitions:

**Outgoing Call:**
```
idle → outgoing → connected → streams_running → released
```

**Incoming Call:**
```
idle → incoming → connected → streams_running → released
```

Monitor in logs:
```python
def on_call_state_change(state):
    logger.info(f"Call state: {state.value}")
```

---

## Next Development Steps

### 🔥 PRIORITY: Phase 5 Integration (See docs/INTEGRATION_PLAN.md)
1. **Create YoyoPodApp coordinator** - Unified application class
2. **Enhance state machine** - Add combined VoIP+music states
3. **Implement call interruption** - Auto-pause/resume music
4. **Integration testing** - Test on hardware with real calls

### Future Features (Post-Integration)
1. **Dial pad screen** - Manual SIP address entry
2. **Call history** - Track incoming/outgoing/missed calls
3. **Volume control during call** - Adjust mic/speaker
4. **Bluetooth headset** - Support wireless audio
5. **Speed dial** - Quick access to favorite contacts
6. **Conference calling** - Multiple participants

### Optimization Ideas
1. Reduce VoIPManager RAM usage (~57 MB is high)
2. Implement lazy loading for screens
3. Profile and optimize mopidy integration
4. Consider lighter VoIP alternatives to linphonec

---

## Useful References

**Project Documentation:**
- `docs/INTEGRATION_PLAN.md` - VoIP + Music integration architecture and plan
- `.Codex/AGENTS.md` - This file (development status and debug guide)

**Linphone Documentation:**
- https://wiki.linphone.org/
- linphonec commands: `help` in linphonec console

**Mopidy Documentation:**
- https://docs.mopidy.com/
- Extensions: https://mopidy.com/ext/

**DisplayHATMini:**
- https://github.com/pimoroni/displayhatmini-python

**Project Repository:**
- https://github.com/your-username/yoyo-py (update with actual repo)

---

## Development Notes

**Date: 2025-10-19 (Phase 2 Complete)**
- **Phase 2: Screen Integration COMPLETE** ✓
- Implemented:
  - `_setup_screens()` method - creates and registers all 9 screens
  - Screen transitions wired to VoIP/music callbacks
  - `_pop_call_screens()` helper - prevents stack overflow
  - Full UI navigation with all screens
  - Production app: `yoyopod.py`
- All callbacks now update screens:
  - Incoming call → push IncomingCallScreen
  - Call connected → push InCallScreen
  - Call ended → pop all call screens
  - Track change → refresh NowPlayingScreen
  - Registration change → refresh CallScreen
- Ready for Phase 3: Hardware testing and refinement

**Date: 2025-10-19 (Phase 1 Complete)**
- **Phase 1: Core Integration Framework COMPLETE** ✓
- Enhanced StateMachine with 3 new states, 24+ transitions
- YoyoPodApp coordinator class with callback coordination
- Configuration system (yoyopod_config.yaml)
- State machine testing (all 8 tests passing)

**Date: 2025-10-19 (Planning)**
- **Phase 5 Integration Planning:** Created comprehensive integration plan (`docs/INTEGRATION_PLAN.md`)
- Integration plan covers:
  - Enhanced state machine with combined VoIP+music states
  - YoyoPodApp coordinator architecture
  - Call interruption flow (auto-pause/resume music)
  - Screen transition scenarios
  - Context-sensitive button mapping
  - 4-phase implementation roadmap

**Date: 2025-10-13**
- VoIP Phase 4.2 completed: Full incoming and outgoing call support
- RAM testing confirmed viability on Pi Zero 2W (151 MB available with music+VoIP)
- All major VoIP bugs fixed (caller detection, screen navigation, stack overflow)
- System ready for integration work (music pause on call, etc.)
