# Seeed XIAO ESP32-C3

**Status: ✅ Verified** — read directly off the physical board's silkscreen
(USB-C up, chip face up, read clockwise from top-right). The D-to-GPIO mapping
itself was correct from the start; only the left/right side assignment needed
correcting — see the diagram below.

Parts context: `docs/roadmap.md` (v1.1 parts list — this board supersedes an
earlier ESP32-S3 pick; same XIAO form factor).

---

## Physical pinout (verified against the board — USB-C up, chip face up)

7 pins down each side, 14 total. Read clockwise from top-right: right side
top→bottom is 5V/GND/3V3/D10…D7; left side top→bottom is D0…D6.

```
                 ┌─────────────┐
                 │   USB-C     │
                 └──┬───────┬──┘
  ► D0/A0  ──────────┤       ├────────── 5V
     D1/A1 ──────────┤       ├────────── GND
     D2/A2 ──────────┤ ESP32 ├────────── 3V3
     D3    ──────────┤  C3   ├────────── D10 / GPIO10 (MOSI)
     D4/SDA──────────┤       ├────────── D9  / GPIO9  (MISO)  ⚠ strapping pin
     D5/SCL──────────┤       ├────────── D8  / GPIO8  (SCK)   ⚠ strapping pin
     D6/TX ──────────┤       ├────────── D7  / GPIO20 (RX)
                      └───────┘
GPIO2=D0  GPIO3=D1  GPIO4=D2  GPIO5=D3  GPIO6=D4  GPIO7=D5  GPIO21=D6
```

`►` = V1.2 LED data pin (D0 / GPIO2, top-left — see caution below)

⚠ **Strapping pins**: GPIO2, GPIO8, GPIO9 are sampled at reset to select boot
mode. Using them as ordinary GPIO after boot is usually fine (GPIO2 in
particular is one of the most commonly used arbitrary-output pins on ESP32
boards in practice) — but if the board ever fails to boot or behaves oddly only
when the LED stick is attached, that's the first thing to suspect. **D6/GPIO21**
or **D10/GPIO10** are non-strapping alternates if you want to sidestep the
question entirely.

---

## Wiring — AE-WS2812B-STICK8

Mirrors the Pico 2W wiring (`pinouts/pico2w.md`) — same 3 connections, same LED
stick, only the source board changes.

| XIAO C3 | Position (USB-C up) | GPIO (for `config.py`) | → | LED stick pad |
|---|---|---|---|---|
| 5V | top-right (analogous to Pico's VBUS) | — | → | VCC (5V) |
| GND | just below 5V, right side | — | → | GND |
| D0 | top-left | `2` | → | DIN |

**`config.py` values**: `LED_PIN = 2`

## Status heartbeat

⚠ **Unconfirmed**: no onboard-LED GPIO verified for this specific board yet.
Set `HEARTBEAT_PIN = None` (disables the heartbeat LED; the console ●/○
heartbeat still works) until you've confirmed one — then update this file and
`config.py` together.

---

## v1.2 checkpoint — ✅ PASSED (2026-07-05)

- [x] Physical pin table confirmed against the board (silkscreen, read clockwise)
- [x] USB-serial enumeration — `scripts/detect_port.sh` (shared by `make screen`
      and `make flash-esp32-c3`) globs `usbmodem*`, `wchusbserial*`,
      `SLAB_USBtoUART*`, and `usbserial*`.
- [x] D0/GPIO2 confirmed fine as the WS2812B data line in practice — `make
      led-test` lit the stick correctly; no strapping-pin issues observed.
- [x] Flashed via `make flash-esp32-c3` (esptool + the preview `.bin`);
      MicroPython boots, confirmed via `make screen`.
- [x] Full pipeline confirmed: `make upload` + `make run` — WiFi connected, NTP
      synced, display pipeline rendered correctly with `LED_PIN=2`,
      `HEARTBEAT_PIN=None`.

**Deferred, non-blocking**:
- [ ] Confirm (or rule out) an onboard-LED GPIO for the heartbeat. Not among the
      14 broken-out pins read off the silkscreen — `HEARTBEAT_PIN = None` is a
      fine permanent choice for this board, not just a placeholder.
