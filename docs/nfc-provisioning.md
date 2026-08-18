# NFC provisioning — findings, decision, tag data contract

_The one place the NFC settings/provisioning workstream is tracked. **Supersedes**
the earlier "iOS Shortcuts, no custom app" plan (roadmap.md / the givable memo) —
that route is now ruled out on the bench, see §2._

> **⚠ Update (2026-08-16) — §3's decision (build a minimal iOS app) is
> superseded by §8.** A brainstorming session found a path that removes the
> phone from provisioning entirely: a **USB NFC reader/writer on the Mac**
> writes NTAG213 (Type-2) stickers directly, with no iOS app, no Xcode, no
> Apple Developer Program. This also resolves the ⏸ on-hold status in
> `dev-status.md` § Open decisions. §1–§7 below are kept as the bench record —
> the findings remain correct and the tag data contract (§4) is still the
> durable interface. **Read §8 first.**

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

---

## 8. The phone-free path (2026-08-16) — supersedes §3

_Context: `docs/glass-stone-concept.md`. Two separable ideas here — the first
works regardless of form factor, the second needs the space a stand provides._

### 8.1 The correction that unlocked this

**The ST25DV is a *tag*, not a reader.** "Dynamic NFC tag" means it has two
interfaces — I²C to the MCU and RF to the outside world — but the RF side is
always the *target*: powered by, and responding to, someone else's field. It
cannot generate a field, and therefore **cannot read another tag.** As
currently spec'd, eki-bin has no way to read an NFC sticker; it can only *be*
read and written, by something that generates a field (i.e. a phone).

That is the real reason the plan had a phone in it, and it was never stated
this plainly before.

### 8.2 What was considered and rejected: the "candle-to-candle" relay

The obvious workaround: a phone reads a sticker (easy — Type-2, iOS Shortcuts
handles it natively), then the *same* phone immediately rewrites that data onto
the jar's ST25DV (jar as the second candle). **This does not help.** The second
hop is a write to a **Type-5** tag, which is exactly the wall §2 documents —
still needs the low-level `NFCTagReaderSession` API, still needs the custom
app. The relay relocates the problem rather than solving it. Recorded so it
isn't re-proposed.

### 8.3 Provisioning: a USB NFC reader/writer on the Mac

**Works regardless of form factor. Replaces §3's iOS app entirely.**

1. One **USB NFC reader/writer** on the Mac — an ACR122U or a PN532-based
   dongle. Both are common (Akihabara or online) and both are supported by
   Python's **`nfcpy`**.
2. A short **macOS Python script** writes each station's schedule as a plain
   NDEF record onto a blank **NTAG213** sticker.
3. Sticker goes into the book (§8.4), once.

What this eliminates, all at once: no iOS app, no Xcode, no Swift, no Apple
Developer Program ($99/yr), no entitlements, no 7-day sideload expiry, and no
dependency on the 2019 Intel MacBook Air's macOS version ceiling — **every one
of the stacked toolchain walls recorded in `dev-status.md` § Open decisions.**
It is also a Python script in a repo that already has a `scripts/` directory
full of them, rather than a second product in a second language with its own
repo (§7.1's open question becomes moot).

> **⚠ This path has its own unverified toolchain assumption — verify it
> cheaply before treating the blocker as cleared.** The claim above is "USB
> dongle + `nfcpy` works on this Mac," and that is exactly the shape of
> assumption that cost this project months on the iOS route: plausible,
> widely-reported-as-working, and untested *on this specific machine*.
> Two known friction points to check first, not after buying:
>
> - **ACR122U specifically is a PC/SC/CCID-class device.** macOS ships its
>   own CCID driver that claims such devices, and `nfcpy` wants to talk to
>   the USB interface directly — a documented source of conflict on macOS.
>   `nfcpy`'s own docs also describe ACR122U support as partial (its
>   firmware performs some operations autonomously that `nfcpy` would rather
>   drive itself).
> - **A plain PN532 breakout on a USB-serial adapter sidesteps the PC/SC
>   layer entirely** and may be the lower-risk buy, at the cost of slightly
>   more wiring. It is also the same chip §8.5 wants onboard later, so one
>   part covers both experiments.
>
> **Cheapest possible falsification: get the dongle talking to `nfcpy` and
> read any blank NTAG213 before writing a line of provisioning code.** If
> that one command works on this Mac, the path is real; if it doesn't, that
> is worth knowing before the design leans on it. Until then this section is
> a *candidate* unblock, not a cleared blocker — and `dev-status.md`'s row
> should keep saying so.

**Why NTAG213 and not the ST25DV here:** NTAG213 is **Type-2**, the tag class
every consumer NFC tool handles properly — including iOS Shortcuts' native
"Set NFC Tag" action, should a phone ever be convenient. It is also what
`docs/concept.md`'s original station-card design specified, before the pivot
to ST25DV for a different reason (live phone-editable settings). Cheap, static,
write-once-and-forget.

### 8.4 The book — provisioning as a physical artifact

The interaction this is really for: **an old used book about trains — ideally a
second-hand 時刻表 (jikokuhyō, timetable book) — with pre-programmed NFC
stickers placed on the pages where the relevant schedules are printed.**
Present a page to the stand; that station loads. Settings changes work the same
way.

The book becomes, at once, the authoritative analog *and* digital database.
Provision it once; never touch a phone again to operate the device.

This is not a departure from `docs/concept.md` § Design Principles #6
("digitize only on provision") — it is the fullest expression of it yet. That principle already
accepts one-time digital provisioning as correct; what it rejects is *daily*
digital surface. A book of pre-written stickers has none. Building a
field-generating writer into the stand would actually work *against* the
principle by making the device itself a writing tool it never needs to be.

### 8.5 Onboard reader: back to the PN532

**Needs the space a stand provides — see `docs/glass-stone-concept.md` §2.**

For the stand to read a book page directly, it needs a real **NFC reader**
(field-generating): a **PN532**-class module wired to the MCU over I²C or SPI.
One hop, no relay, no phone.

**This is a return to already-locked hardware, not a new direction.**
`docs/concept.md` § Key Hardware Decisions specifies "PN532 NFC module — reads
station cards and phone time-sync taps." Both reasons it was later set aside
are now gone:

| Original objection | Status |
|---|---|
| No space in the bottle neck | Gone — the stand has room |
| ~100mA standby draw kills a coin-cell budget (`docs/roadmap.md` § Hard Variant) | Moot — wired USB-C power |
| Needed onboard *writability* for live phone-edited settings | Not needed — the book is the only write path, and it's written from the Mac |

The ST25DV already in hand and bench-validated (§1) is **not wasted** — it is
freed up rather than required. It remains the right part if a live
phone-writable surface is ever wanted again (e.g. a rare one-off time
correction), just not load-bearing for the MVP.

**Driver-availability note, in PN532's favour:** it is a far more common
hobbyist chip than the ST25DV, so a MicroPython driver — or something close
enough to adapt — is much more likely to exist already. **Check before
assuming** you'll be porting register-level code from an Arduino library the
way §5 anticipates for the ST25DV.

**Physical constraint:** the reader needs an RF-transparent path to the book
page at 13.56MHz. `docs/hardware.md` § NFC already documents that a solid
conductive lid substantially attenuates the field via eddy currents — the same
physics applies to a **metal stand**. Wood (a suiseki daiza) is the safe
choice; a bronze koro would need the reader positioned so nothing conductive
sits between it and the page. This is a real input to stand selection, not an
afterthought — see `glass-stone-concept.md` §4.

### 8.6 What this leaves open

- **The tag data contract (§4) still stands**, and is still the durable
  interface — now shared between the `nfcpy` writer script and the firmware's
  PN532 reader, rather than between an iOS app and an I²C driver. Revisit
  whether the private binary format is still preferable to plain NDEF now that
  a well-supported library (`nfcpy`) is doing the encoding — the §7.2 argument
  for a private format was partly about *avoiding hand-rolled encode/decode
  bugs*, which a library removes.
- **Time sync may leave the NFC surface entirely** — if JJY works
  (`docs/jjy-time-signal.md`), the annual timestamp tap disappears and NFC's
  only remaining job is station schedules and occasional settings. Both change
  a few times a year at most, which the static-sticker book handles fine.
- **None of this is built.** No reader bought, no script written, no sticker
  tested. The §1 bench validation covers the ST25DV over RF only.
