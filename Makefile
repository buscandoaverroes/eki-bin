# Makefile — eki-bin
# Usage:
#   make setup             — create .venv, install Python tools
#   make flash-micropython — flash MicroPython to any supported board.
#                             Optionally BOARD=pico2w|esp32c3|xiao-rp2350;
#                             omit it for an interactive picker.
#                             WIPE=1 also erases the filesystem (RP2350 only —
#                             the ESP32 path always does). Reach for it when the
#                             board is unreachable over serial: a plain reflash
#                             leaves main.py in place, so a main.py that blocks
#                             the REPL survives it.
#   make schedule          — convert schedules/*.yaml → minutes arrays
#   make led-test          — run the WS2812B bring-up sketch
#   make imu-test          — run the LSM6DSV16X (IMU) bring-up sketch
#   make i2c-scan          — find I2C devices without knowing pins/bus first
#   make rtc-drift         — measure DS3231 drift vs this Mac (edge-timed)
#   make upload            — copy main.py + config.py + schedule.json to the board
#   make run               — run main.py without saving (good for iteration)
#   make screen / repl     — open the MicroPython REPL (Ctrl+] to exit)
#   make clear-vibes       — list + confirm + delete vibration_sandbox.py /
#                             handling_test.py data files on the device's flash
#
# upload/run/led-test/screen/repl all go through mpremote, which is board-
# agnostic — the only board-specific step is the initial firmware flash, since
# RP2350 boards (mass-storage .uf2 via picotool) and ESP32 boards (serial
# bootloader via esptool) use different protocols. That dispatch now lives in
# scripts/flash_firmware.sh. Still NOT auto-detected: which board you're
# holding is something you already know, and guessing it from bootloader state
# before any firmware is running is more fragile than just naming it.

VENV     := .venv
PYTHON   := $(VENV)/bin/python
MPREMOTE := $(VENV)/bin/mpremote
ESPTOOL  := $(VENV)/bin/esptool

# Firmware filenames/globs deliberately live ONLY in
# scripts/flash_firmware.sh now — duplicating them here is what let the
# XIAO RP2350 target check the wrong board's file.
SRC_DIR      := micropython

STATION ?= testbench


# ── Setup ─────────────────────────────────────────────────────────
.PHONY: setup
setup: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --quiet --upgrade pip
	$(PYTHON) -m pip install --quiet -r requirements.txt
	@echo "✓ .venv ready — mpremote at $(MPREMOTE)"

# ── Firmware ──────────────────────────────────────────────────────
# One target for every board. Pass BOARD= to skip the prompt:
#   make flash-micropython BOARD=pico2w
#   make flash-micropython BOARD=esp32c3
#   make flash-micropython BOARD=xiao-rp2350
#   make flash-micropython                  ← interactive picker
#
# The board table, the two flashing protocols (picotool/.uf2 for RP2350
# boards, esptool/.bin for ESP32), and the firmware-file lookup all live in
# the script — previously these were three near-duplicate targets that had
# already drifted (the XIAO RP2350 one validated the PICO's firmware
# variable while flashing the XIAO's, so a missing .uf2 passed the guard and
# then ran picotool with an empty path).
.PHONY: flash-micropython
flash-micropython:
	@ESPTOOL=$(ESPTOOL) WIPE=$(WIPE) bash scripts/flash_firmware.sh $(BOARD)

# Kept so existing docs, scripts and muscle memory don't break. The old
# names were also inconsistent with each other — one named for the firmware
# (flash-micropython), one for the board (flash-esp32-c3).
.PHONY: flash-esp32-c3
flash-esp32-c3:
	@ESPTOOL=$(ESPTOOL) WIPE=$(WIPE) bash scripts/flash_firmware.sh esp32c3

.PHONY: flash-xiao2350
flash-xiao2350:
	@ESPTOOL=$(ESPTOOL) WIPE=$(WIPE) bash scripts/flash_firmware.sh xiao-rp2350

# ── Python files ──────────────────────────────────────────────────

# ── Tests ─────────────────────────────────────────────────────────
# Host-side logic tests. Run automatically before `upload`.
.PHONY: test
test:
	$(PYTHON) -m pytest -q

.PHONY: upload
upload: test _check-mpremote
	@test -f $(SRC_DIR)/config.py \
		|| (echo "✗ $(SRC_DIR)/config.py missing — cp $(SRC_DIR)/config.example.py $(SRC_DIR)/config.py and fill it in (or edit on-board via Thonny)" && exit 1)
	@# Copy order, retries and size verification all live in the script.
	@# An UNVERIFIED cp is the dangerous case: a truncated write corrupted
	@# the filesystem and bricked a board for a morning (insights.md §13).
	@MPREMOTE=$(MPREMOTE) SRC_DIR=$(SRC_DIR) STATION=$(STATION) \
		bash scripts/upload.sh

.PHONY: run
run: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/main.py

# Run ANY script once via mpremote without a full flash — for ad-hoc bring-up
# (e.g. a NUM_LEDS-tweaked led_test.py) so you don't have to drop into Thonny.
#   make run-file FILE=micropython/led_test.py
.PHONY: run-file
run-file: _check-mpremote
	@test -n "$(FILE)" || (echo "✗ usage: make run-file FILE=<path/to/script.py>" && exit 1)
	@test -f "$(FILE)" || (echo "✗ not found: $(FILE)" && exit 1)
	$(MPREMOTE) run "$(FILE)"

# Copy any script to the device AS main.py so it auto-runs on the next boot /
# power-up — needed for standalone (USB-less) tests like a Qi-powered brightness
# run, where `run-file` can't help because there's no live mpremote session.
#   make upload-file FILE=micropython/led_test.py
# Overwrites the device's main.py; re-run `make upload` to restore real firmware.
.PHONY: upload-file
upload-file: _check-mpremote
	@test -n "$(FILE)" || (echo "✗ usage: make upload-file FILE=<path/to/script.py>" && exit 1)
	@test -f "$(FILE)" || (echo "✗ not found: $(FILE)" && exit 1)
	$(MPREMOTE) cp "$(FILE)" :main.py
	@echo "✓ Copied $(FILE) → :main.py — auto-runs on next boot / power-up (e.g. on the Qi pad)"

# Hardware bring-up: cycle colours + chase across the LED strip.
.PHONY: led-test
led-test: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/led_test.py

# Board-agnostic I2C discovery: finds devices WITHOUT being told which pins
# or bus ID to use. On RP2 boards this needs no configuration at all — it
# enumerates the chip's legal pin/ID combinations and reports the config
# values to paste. Start here when a device doesn't show up; imu-test and
# rtc-test verify a chip WORKS, this one finds whether it's there at all.
.PHONY: i2c-scan
i2c-scan: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/i2c_scan.py

# Hardware bring-up: scan I2C, confirm the LSM6DSV16X IMU, stream accel data.
.PHONY: imu-test
imu-test: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/imu_test.py

# Hardware bring-up: scan I2C, confirm the DS3231 RTC, read/optionally-set
# time, watch it tick. See the file header for the power-cycle workflow —
# that's the actual point, not just "does it respond on the bus."
.PHONY: rtc-test
rtc-test: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/rtc_test.py

# Measure DS3231 drift against this Mac's clock, precisely enough to be
# worth doing: it catches the seconds-register EDGE rather than reading the
# register, which is what makes +/-2 ppm resolvable in hours instead of a
# week. Appends to data/rtc-drift.jsonl (gitignored) -- run it once to set a
# baseline, again later for a figure. Pass --mark-seed after re-setting the
# chip, since that destroys the baseline.
#   make rtc-drift                    (XIAO RP2350 defaults)
#   make rtc-drift ARGS="--mark-seed"
#   make rtc-drift ARGS="--sda 0 --scl 1 --i2c-id 0"   (Pico 2W)
.PHONY: rtc-drift
rtc-drift: _check-mpremote
	$(PYTHON) scripts/rtc_drift.py $(ARGS)

# Set the board's RTC from this Mac's clock. Needed when TIME_SOURCE="rtc"
# (no WiFi/NTP) — the only way to run a full unit on the XIAO ESP32-C3,
# which can't fit esp_wifi alongside an app this size (docs/insights.md §11).
# ⚠ The RTC survives a soft reset but NOT a power cycle — re-run after
# unplugging. A DS3231 is the permanent answer (V2).
.PHONY: set-time
set-time: _check-mpremote
	$(MPREMOTE) rtc --set
	@$(MPREMOTE) rtc
	@echo "✓ Device RTC set from host clock — re-run after any power cycle"

.PHONY: repl
repl: _check-mpremote
	$(MPREMOTE)

# Lists + confirms + deletes vibration_*.json(l) / handling_*.json(l) files
# left on-device by vibration_sandbox.py / handling_test.py sessions
# (mpremote cp only copies them off, never deletes the originals — they
# accumulate until flash fills up).
.PHONY: clear-vibes
clear-vibes: _check-mpremote
	@MPREMOTE=$(MPREMOTE) bash scripts/clear_vibes.sh

SCHEDULE_SOURCES := $(wildcard schedules/*.yaml)

.PHONY: schedule
schedule:
	@test -n "$(SCHEDULE_SOURCES)" \
		|| (echo "✗ No .yaml files found in schedules/" && exit 1)
	@for f in $(SCHEDULE_SOURCES); do \
		$(PYTHON) scripts/convert_schedule.py $$f; \
	done

.PHONY: screen
screen: _check-mpremote
	@MPREMOTE=$(MPREMOTE) bash scripts/select_port.sh

# ── Internal ──────────────────────────────────────────────────────
.PHONY: _check-mpremote
_check-mpremote:
	@test -f $(MPREMOTE) \
		|| (echo "✗ mpremote not found — run: make setup" && exit 1)
