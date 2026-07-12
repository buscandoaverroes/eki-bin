# Makefile — eki-bin
# Usage:
#   make setup             — create .venv, install Python tools
#   make flash-micropython — flash MicroPython to the Pico 2W (picotool + .uf2)
#   make flash-esp32-c3    — flash MicroPython to the XIAO ESP32-C3 (esptool + .bin)
#   make schedule          — convert schedules/*.yaml → minutes arrays
#   make led-test          — run the WS2812B bring-up sketch
#   make upload            — copy main.py + config.py + schedule.json to the board
#   make run               — run main.py without saving (good for iteration)
#   make screen / repl     — open the MicroPython REPL (Ctrl+] to exit)
#
# upload/run/led-test/screen/repl all go through mpremote, which is board-
# agnostic — the only board-specific step is the initial firmware flash, since
# the Pico (mass-storage .uf2) and ESP32-C3 (serial bootloader) use different
# protocols. Hence two separate flash targets rather than one auto-detecting
# target: which board you're holding is something you already know, and
# guessing it from bootloader state before any firmware is even running is
# more fragile than just naming it.

VENV     := .venv
PYTHON   := $(VENV)/bin/python
MPREMOTE := $(VENV)/bin/mpremote
ESPTOOL  := $(VENV)/bin/esptool

FIRMWARE_DIR   := firmware
PICO_FIRMWARE  := $(wildcard $(FIRMWARE_DIR)/RPI_PICO2_W-*.uf2)
ESP32_FIRMWARE := $(wildcard $(FIRMWARE_DIR)/SEEED_XIAO_ESP32C3-*.bin)
SRC_DIR      := micropython

STATION ?= mystation


# ── Setup ─────────────────────────────────────────────────────────
.PHONY: setup
setup: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --quiet --upgrade pip
	$(PYTHON) -m pip install --quiet -r requirements.txt
	@echo "✓ .venv ready — mpremote at $(MPREMOTE)"

# ── Firmware ──────────────────────────────────────────────────────
.PHONY: flash-micropython
flash-micropython:
	@command -v picotool > /dev/null 2>&1 \
		|| (echo "✗ picotool not found — run: brew install picotool" && exit 1)
	@test -n "$(PICO_FIRMWARE)" \
		|| (echo "✗ No .uf2 found in $(FIRMWARE_DIR)/ — download from micropython.org/download/RPI_PICO2_W/" && exit 1)
	@echo "→ Flashing: $(PICO_FIRMWARE)"
	picotool load $(PICO_FIRMWARE) --force
	picotool reboot
	@echo "✓ Done — Pico rebooting into MicroPython"

# Flash MicroPython to the XIAO ESP32-C3. Different tool/procedure from the
# Pico above — ESP32 uses a serial bootloader protocol (esptool), not a
# mass-storage drag-and-drop. Erases first (standard MicroPython flashing
# advice — avoids stale partition/NVS state from a previous firmware).
#
# Note: esptool's CLI has changed across major versions. This targets the
# modern (v5.x) `erase-flash` / `write-flash` subcommand syntax; if it errors
# with an unrecognized command, run `esptool --help` to check your version's
# exact syntax.
.PHONY: flash-esp32-c3
flash-esp32-c3:
	@test -f $(ESPTOOL) \
		|| (echo "✗ esptool not found in .venv — run: make setup" && exit 1)
	@test -n "$(ESP32_FIRMWARE)" \
		|| (echo "✗ No .bin found in $(FIRMWARE_DIR)/ — download from micropython.org/download/SEEED_XIAO_ESP32C3/" && exit 1)
	@PORT=$$(bash scripts/detect_port.sh) && \
		echo "→ Erasing flash on $$PORT…" && \
		$(ESPTOOL) --port $$PORT --chip esp32c3 erase-flash && \
		echo "→ Flashing: $(ESP32_FIRMWARE)" && \
		$(ESPTOOL) --port $$PORT --chip esp32c3 write-flash 0x0 $(ESP32_FIRMWARE) && \
		echo "✓ Done — XIAO C3 rebooting into MicroPython"

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
	$(MPREMOTE) cp micropython/main.py :main.py
	$(MPREMOTE) cp micropython/config.py :config.py
	$(MPREMOTE) cp schedules/$(STATION).json :schedule.json
	@echo "✓ Uploaded: main.py, config.py, schedule.json ($(STATION))"

.PHONY: run
run: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/main.py

# Hardware bring-up: cycle colours + chase across the 8-LED stick.
.PHONY: led-test
led-test: _check-mpremote
	$(MPREMOTE) run $(SRC_DIR)/led_test.py

.PHONY: repl
repl: _check-mpremote
	$(MPREMOTE)

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
