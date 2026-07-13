# NFC provisioning — findings, decision, tag data contract

_The one place the NFC settings/provisioning workstream is tracked. **Supersedes**
the earlier "iOS Shortcuts, no custom app" plan (roadmap.md / the givable memo) —
that route is now ruled out on the bench, see §2._

**Goal:** the jar needs occasional digital input (load a station schedule, adjust
brightness/pattern, sync time) *without* a persistent phone/WiFi dependency —
"digitize only on provision." NFC tap is the input surface: an iPhone writes
settings to the ST25DV tag over RF; the firmware reads them over I²C.

---

## 1. Bench-validated — works (build on this, don't re-derive)

All RF-only so far (phone ↔ tag, tag loose on bench, no ESP32/I²C involvement),
via ST's "NFC Tap" **raw block editor**:

- Tag detects reliably with zero firmware/power — manufacturer/serial, 8192 bytes.
- Raw block read/write clean: wrote `DEADBEEF` to block 2, read back, re-zeroed.
- Valid **extended (8-byte) Capability Container**, by hand:
  - Block 0: `E1 40 00 00` (magic, mapping v1.0, extended-format flag, no pw restriction)
  - Block 1: `00 00 04 00` (memory size 1024×8 = 8192 B)
  - ⚠ The **basic 4-byte CC cannot address this tag** — its length field maxes at
    255×8 = 2040 B, so extended format is *mandatory* here.
- Empty NDEF TLV `03 03 D0 00 00 FE FF FF` — read back correct.
- Full NDEF **Text record** ("hello eki-bin"), hand-encoded across blocks 2–7,
  read back **byte-perfect**:
  ```
  Block 2: 03 13 D1 01     Block 5: 6F 20 65 6B
  Block 3: 10 54 65 6E     Block 6: 69 2D 62 69
  Block 4: 68 65 6C 6C     Block 7: 6E FE 00 00
  ```

**The tag, the CC, and the encoding are all fine — nothing here is a hardware problem.**

## 2. Bench-validated — fails, and why (this killed the no-app plan)

Every read/write through a **generic high-level NDEF API** — Apple's
`NFCNDEFReaderSession`, which backs ST's "NFC Tap" NDEF tab, iOS Shortcuts, and
NFC ReWriter — **times out or fails to detect NDEF**, despite the bytes being
verified correct by direct block read.

| Tool | Result |
|---|---|
| ST "NFC Tap" NDEF tab | times out (raw-block tab works) |
| iOS **Shortcuts** | no native NDEF content read/write action at all (only a UID-keyed trigger) → the no-app path isn't viable regardless |
| NFC Tools (wakdev) | read once; write paywalled/untested |
| NFC ReWriter | failed to detect NDEF |

This matches a documented multi-year pattern: iOS's generic NDEF reader breaks
specifically on **ISO-15693 / NFC-Forum Type-5** tags. The confirmed workaround is
to bypass `NFCNDEFReaderSession` and use the lower-level **`NFCTagReaderSession` +
`NFCISO15693Tag`** API — i.e. exactly the raw-block approach that worked every time
above.

**Entitlements:** standard ISO-15693 block read/write needs **none**. Only vendor
custom commands (`0xA0`–`0xDF`: password, kill, area config, FTM mailbox) need
Apple's restricted entitlement — all out of scope.

## 3. Decision

**Build a minimal first-party Swift/SwiftUI app** on the low-level ISO-15693 API.
Not a general NFC utility — a purpose-built settings tool scoped to eki-bin's own
data format. The no-app / Shortcuts route is closed (proven, not guessed).

## 4. Tag data contract — the durable interface

Both the (future) ST25DV MicroPython driver (I²C side) and the iOS app (RF side)
must agree on this. It's the real deliverable of this doc; the app UI and driver
internals are replaceable, this format is the contract.

**Format: private, not NFC-compliant NDEF** (MVP recommendation — see §7). No
third-party reader is in the picture anymore, so NDEF compliance buys only
debuggability at the cost of encode/decode bug surface.

Proposed layout:
- **Blocks 0–1:** leave a valid extended CC (§1) in place — harmless, and keeps
  ST's tools recognising the tag as NDEF-capable for debugging.
- **Block 2 onward:** a small binary header + UTF-8 JSON:
  - `version` (1 B) · `length` (2 B) · `crc16` (2 B) · then `length` bytes of JSON.
  - JSON mirrors a subset of `config.py`'s knobs (start: `brightness`, `contract`,
    `walk_to_station_mins`; expand later), consistent with the `getattr` fallback
    pattern — the phone sends only changed fields.
- The **checksum** lets firmware reject a torn read (an I²C poll landing
  mid-RF-write) and only apply a clean payload.

## 5. Firmware side (later — not this pass)

- **ST25DV MicroPython driver:** none off-the-shelf; port register-level I²C from
  the SparkFun ST25DV64KC Arduino lib + DS13519. Read the user-EEPROM block range
  over I²C. Links + wiring in `docs/hardware.md` (I²C **not yet wired** — all bench
  work so far is RF-only; XIAO pins D4/SDA=GPIO6, D5/SCL=GPIO7 per `pinouts/`).
- **Settings hot-reload:** poll once per `LOOP_INTERVAL_SECS` tick, validate the
  checksum, merge the partial diff onto in-RAM state, echo active settings back so
  a phone read reflects ground truth.

## 6. iOS app side (build brief — candidate for its own repo)

- Swift/SwiftUI, single screen: **Scan & Read** → decode payload → editable form →
  **Write to Tag** → confirm. No persistent state, no pairing, no background mode.
- `NFCTagReaderSession(pollingOption: .iso15693)` → cast to `NFCISO15693Tag` →
  read/write the defined block range; session lifecycle
  (`alertMessage`/`invalidate(errorMessage:)`/`invalidate()`).
- `Info.plist`: `NFCReaderUsageDescription` + the
  `com.apple.developer.nfc.readersession.formats` entitlement with `TAG` (add
  `NDEF` only if §7 option (a) is chosen).
- Free Apple ID sideload is fine (7-day provisioning-profile expiry → periodic
  resign during active dev).
- MVP: a raw editable JSON text field first, a proper form second.

## 7. Open questions (discuss before coding)

1. **Separate repo for the iOS app?** Leaning **yes** — different toolchain
   (Swift/Xcode vs MicroPython), platform, and build/CI; keeping Xcode project cruft
   out of the firmware repo is cleaner. The **tag data contract (§4) stays here** as
   the shared interface both repos reference.
2. **Private format vs. real NDEF** — leaning **(b) private** for the MVP (drops a
   whole class of encode/decode bugs; keep the CC block as harmless debug aid).
   Revisit only if third-party compatibility is ever needed.
3. **Xcode / Intel-Mac / iOS-version env** — phone on iOS 17.2, Xcode 15.1 on an
   Intel Mac. Core NFC's ISO-15693 API has existed since iOS 13, so this is
   sufficient; **no need to chase "iOS 26" or a newer Xcode** unless the phone
   updates. Confirm with an env check.
4. Modularity — if (b), treat the app as its own small documented product.
