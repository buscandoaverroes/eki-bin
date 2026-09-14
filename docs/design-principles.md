# Design Principles

_The canonical principles that should guide eki-bin decisions. Seeded from
`README.md` and `docs/concept.md`; some entries are **stubs** marked 🔲 — leave
them for us to fill in together as testing teaches us more. Field evidence lives
in `docs/insights.md`._

---

## Product / experience

1. **Ambient, not demanding.** Information is *present* in the environment like a
   clock or sundial — never pushed, notified, or unlocked.
2. **Lean into the physical medium.** Translucency, diffusion, and glass are
   features, not obstacles. The "reveal" only works when the technology is hidden
   by the material. _(Field-validated: clear glass ruins it; thick translucent
   works — see insights §3.)_
3. **Glanceable first, precise second.** The across-the-room read (arc length,
   colour, motion) matters more than exact times. Detail is for when you lean in.
4. **Answer "when do I leave," not "when does it depart."** The walk to the
   platform is part of the question.
5. **A bottle has no sharp edges; the language is curves.** _(Field-decided
   2026-09-14, `insights.md` §19.)_ Six train-movement styles and five
   station fades were compared on real glass, and the smooth ones won
   every time — crossfade over a cut, `slow_out` over a flicker. The ones
   that read as **alive** (a firefly hop, a guttering fade) turned out to
   read as *"something needs your attention"*, which is the opposite of
   ambient. **A thing with intent wants something from you; physics is
   indifferent, and indifference is what lets an object be ambient.**
   Corollary worth keeping: GUIs are boxes, straight lines and furniture.
   This is a break from that, and the break is the point.
   **Narrowed 2026-09-14 (§20):** sharp edges are the problem, *not*
   irregularity. Irregularity reads as ALIVE when it looks decided and as
   PHYSICAL when it looks unchosen — a firefly hops because it chose to,
   broken glass lands where it lands.
6. **The object has no front; don't pretend otherwise.** _(§20.)_ A bottle
   is radially symmetric — no front, back, left or right. The anchor
   imposes one and is allowed to, because it is a single declared fixed
   point that is honest about being an imposition and absent most of the
   time. A symmetric arrival sweep is an imposition *pretending to be a
   property*, and reads as facetious.
7. **Don't represent state you don't have.** _(§20.)_ The train positions
   are unknown in advance — that is the whole point of the device — so a
   choreographed arrival asserts an order the data does not contain.
   Scatter asserts nothing. The same commitment as "a plausible wrong time
   is worse than a dark jar", applied to motion.
8. 🔲 **Colour should feel native to the jar, not like a gadget.** _(stub: amber
   reads "natural" in brown glass, red reads "artificial" — formalise what this
   means for palette design per enclosure.)_

## Architecture

9. **Two-stage pipeline.** Abstract signal (what's the urgency?) is decoupled
   from rendering (how do we show it?). Inputs attach to Stage 1, outputs to
   Stage 2.
10. **Config is intent; firmware is logic.** `config.py` holds per-device,
   per-person settings; the code holds behaviour. Hardware specifics belong
   behind an abstraction, not sprinkled through logic.
11. **Composable rendering.** Prefer small reusable primitives (colour helpers,
   animation curves) assembled by contracts over bespoke per-contract code.
12. **Backward-compatible configuration.** New settings are optional with
   defaults (`getattr` pattern), so an existing device keeps working untouched.
13. **MicroPython V1 validates; Rust V2 is the goal.** Don't let V1 ergonomics
    block the logic; don't let V1 shortcuts become V2 debt.

## Hardware / enclosure  🔲 (stubs — fill together)

14. 🔲 **Preferred jar:** thick, translucent, coloured. _(stub: quantify — wall
    thickness, opacity, colour range that works.)_
15. 🔲 **Orientation/mounting:** the arc's logical origin should map to a physical
    "fills up = relax / drains = go." _(stub: define once the mount is chosen.)_
16. 🔲 **Brightness baseline is per-enclosure.** _(stub: thick jars need a higher
    floor; clear jars need a ceiling to avoid glare.)_

## Open questions to refine 🔲

- 🔲 Colour semantics per enclosure (which hue = which urgency, and where hue
  gives way to brightness/motion).
- 🔲 Multi-train visual language (how to show "next" vs "the one after" without
  clutter).
- 🔲 Sub-minute urgency behaviour (blink/breathe under ~30 s).
- 🔲 How much to abstract the LED hardware now vs. when the ring arrives.
