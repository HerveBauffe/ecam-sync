# BikeTo roadmap (Tauri 2 + Svelte)

## Context
`velo-app` is a new project. So far it has only `project.txt` (the brief) and `CLAUDE.md`. The goal is an ERG-first training hub for a single rider, replacing intervals.icu, Dreeve and Strava. It covers riding workouts with a Zwift Ride controller, building workouts and plans, the training calendar, fitness analytics, bike wear tracking, WebDAV sync between devices, and Garmin sync.

Decisions made by the user:
- **Platform:** a native **Tauri 2** app in a **new repo**. Rust modules are copied or adapted from zwo-trainer, which is MIT-licensed.
- **Frontend:** **Svelte + TypeScript**.
- **Targets:** Android APK for the tablet, which is the main device, and a Linux/desktop build for editing on the computer.
- **No server.** The native HTTP client means no browser CORS restrictions, so Garmin and WebDAV can be called directly.
- **This document:** a full roadmap.

## Reference repos: what we can reuse

| Repo | License | What to take |
|---|---|---|
| steffenr/zwo-trainer | MIT | **Copy and adapt the Rust code**: `src-tauri/src/shifter.rs` (Zwift Ride/Click/Play: the "RideOn" handshake, opcode 0x23 bitmap, left controller only, and its unit tests), `ble.rs` (FTMS 0x1826: request control, start, ERG `[0x05,lo,hi]`, simulation mode 0x11, data parsers), `zwo.rs` (ZWO parsing, TSS estimate, zone time), `fit.rs` (FIT export), `garmin.rs` (Garmin OAuth via an embedded window, plus upload), `services.rs` (intervals.icu), `library.rs` (plan folders), and `state.rs`/`sync.rs` as reference. **JS to port into Svelte**: `ui/js/vshift.js`, `ui/js/zwo.js`, the logic in `ui/js/ride/ride.js`, and `BUTTON_ACTIONS` in `ui/js/devices.js`. Take design tokens from `DESIGN.md`. **It has no workout builder or generator, so we write those ourselves.** |
| steffenr/zwo-workout-builder | **none (all rights reserved)** | **Re-implement it ourselves from its README and our own design. Don't copy or translate its code, and never use its data** (`data/library*.json` and `.tar.gz` contain coach-made content). Optionally, ask the author (same as zwo-trainer) to add an MIT license so we could port the code directly. **Ideas to use** (all in `velo-core::generator` and `::plan`): an athlete model (level 1–5 and a hardness value from W/kg, hours and experience), a seeded PRNG so results are reproducible, and `compose`: warm-up, openers, the interval format closest to the target work time, filler, then cool-down. For plans: 2–24 weeks, a 3:1 load-to-recovery cycle, 40/40/20 base/build/peak, a start of about hours × 52 TSS, a ramp of `min(0.10, 0.03+0.01·intensity+0.03 if under-trained)`, recovery weeks at 55%, taper at 50%, and `chooseKeyDays` scoring combinations of days so hard days aren't adjacent or after the long ride. Plans export to `WeekNN_DayNN_Title.zwo` folders, compatible with zwo-trainer. It has **no adaptation**, so rebalancing comes from Apex. **We write our own `workDoseMin` table** (work minutes per type and duration). |
| dacronje-quant/Apex-Velo-Lab | MIT | Analytics formulas to port to Rust: `js/velo-analytics.js` (CTL/ATL/TSB), `velo-metrics.js` (zones and best-power durations), `velo-power.js` (power curve, CP/W′, W′bal, polarization index), `velo-health.js` (readiness from HRV, resting HR and sleep), `velo-block-planner.js` (adaptive plan math), `velo-erg.js` (ERG soft start and anti-death-spiral) and `velo-ftp-model.js`. |
| Arthurpfz/croissant-ride | Apache-2.0 | Reference only: the trainer/HR/rider simulator (`src/trainer/sim.ts`), crash recovery in `src/recorder.ts`, and wake lock. |
| dreeveapp/dreeve | AGPL-3.0 | **Re-implement only, never copy code.** Borrow the formulas: hrTSS (Banister), monotony and strain, TSB and ACWR bands, rest days, polarization targets of 75–90 / 0–10 / 10–20, and goals. Borrow the wear model: Gear, Component with nested installations, MaintenanceTask with an interval in km, hours, days or daysUsed, due when ≥98%, and a maintenance log. |
| pedalcraft-site | none | Protocol reference only: Ride paddle analog values, the 20 s keepalive, and opcode `0xFE` meaning another app took the controller. |

Our app will be **MIT-licensed**, with credits in `NOTICE`.

## Architecture
- **Cargo workspace** with these parts:
  - **`crates/velo-core`**: pure Rust with no Tauri or I/O dependency. Holds the domain model (Workout, Plan, Activity, Bike/Component, Wellness), the ZWO and text parsers, metrics, the plan engine, wear, FIT encoding (and decoding via the `fitparser` crate), and the ride engine as a state machine (tick, target power, intensity, skip, virtual shifting). It is tested with `cargo test`.
  - **`crates/velo-ble`**: the `Trainer`, `HeartRate`, `PowerMeter` and `Controller` traits; the FTMS and Zwift Ride implementations from zwo-trainer; and a simulator. BLE goes through a thin adapter: `btleplug` on desktop, and `tauri-plugin-blec` on Android (or our own Kotlin plugin if the spike shows we need one).
  - **`crates/velo-sync`**: the WebDAV client (`reqwest` + PROPFIND, or the `reqwest_dav` crate), the Garmin client (adapted from `garmin.rs`), and intervals.icu.
  - **`src-tauri`**: Tauri commands and events, storage in SQLite (`rusqlite`), and **the ride engine running in Rust on a tokio task**. Running it there keeps timing correct even if the WebView is throttled, and it sends `ride:state` events to the UI every 250 ms.
  - **`src/` (Svelte 5 + TypeScript + Vite)**: the screens only. Types are generated from Rust with `ts-rs` or `specta`. Charts use uPlot.
- **Data layer.** Every entity is a record of the form `{id (ULID), updated_at, deleted}`, which makes per-entity sync straightforward.
- **Input.** One `Action` bus that keyboard, touch and the Zwift Ride all feed into. Controller events come from Rust as Tauri events. On non-ride screens, a focus-navigation system handles the arrows, A (select) and B (back). This is what lets every screen work with controller buttons.
- **Simulator mode** for a fake trainer, heart-rate monitor and Zwift Ride, so we can develop without hardware.

## Phases

**0. Scaffold and Android Bluetooth spike. This is a go/no-go gate.**
- Cargo workspace, Tauri 2 with Svelte and TypeScript, Android target (NDK/SDK), CI with `cargo test`, Vitest and clippy.
- **Spike:** an APK on the tablet that connects the FTMS trainer, holds ERG at 150 W, reads Zwift Ride buttons, and stays connected for 30 minutes with the screen on.
- If Android Bluetooth fails through the plugin, write a small Kotlin Tauri plugin for BLE. Fall back to a PWA only as a last resort.
- Update CLAUDE.md with the commands.

**1. Ride core.**
- Workout model and ZWO import/export (a port of `zwo.rs`).
- FTMS driver, Zwift Ride driver and virtual shifting, all in Rust.
- Ride engine in Rust; ride page in Svelte modeled on zwoTrainer: chart, gauges, play/pause, skip, ±intensity 50–150%.
- Recorder with crash recovery, FIT export (`fit.rs`), and a summary screen.

**2. Workout builder and library.**
- Three editors over one shared model:
  1. Text editor using intervals.icu-style syntax, with a parser and serializer in `velo-core` that round-trip.
  2. Drag-and-drop blocks.
  3. An auto-generator modeled on zwo-workout-builder's design but written from scratch. Its inputs are the rider profile, type, duration and intensity. It returns three seeded options, each with a "swap" button.
- Home page in suffer.online style: library with categories, filters and cards.
- Settings page: FTP, zones, weight, devices, button mapping, theme (dark first).

**3. WebDAV sync.**
- One JSON file per entity under `velo-app/{type}/{id}.json`, with FIT files in `activities/{id}.fit`.
- Pull when the app opens or regains focus, push on change. Uses ETags. Conflicts are resolved per entity: the newest `updated_at` wins, and deletions are kept as tombstones.

**4. Activities and analytics.**
- FIT import. NP, IF and TSS, plus hrTSS for rides without power.
- CTL (42 days), ATL (7 days) and TSB, with ACWR bands.
- Monotony and strain, rest days, polarization, and a power curve with CP/W′.
- Readiness from HRV, resting heart rate and sleep, falling back to TSB when that data is missing.
- Rolling 7-day distance and time goals.
- Dashboard.

**5. Calendar and adaptive plans.**
- Calendar with drag-to-move.
- A plan generator in the style of zwo-workout-builder: a wizard covering goal, available days and time, and style (polarized or sweet spot). It handles periodization, the load ramp, recovery weeks and taper, and placement of key days.
- When a session is moved, skipped or ridden differently, the rebalancing engine (Apex block-planner math) adjusts the rest of the week. It keeps the weekly TSS and CTL ramp targets, with no hard sessions on back-to-back days, keeps recovery weeks, and scales down when TSB < −15 or readiness is poor.

**6. Bikes and component wear.**
- Bikes and nested components with install/remove history.
- Maintenance tasks with intervals in km, hours, days or days-used, plus due and overdue alerts.
- Each activity is assigned a bike: the indoor default for app rides, chosen per activity for outdoor Garmin rides.

**7. Garmin Connect.**
- Login through Tauri's embedded window, using the OAuth flow adapted from `garmin.rs`. Tokens are stored by the app itself (on Android, in Keystore / secure storage).
- Pull activities (FIT) and wellness data (weight, HRV, sleep, resting HR).
- Push our FIT activities, and push scheduled workouts to the Garmin calendar.
- It uses the unofficial API, so it sits behind a `GarminSource` trait. Manual FIT import/export is always available as a fallback.
- **To check in this phase:** whether the `garmin.rs` tokens also grant access to the wellness and calendar endpoints, or whether we need the garth-style login.

## Verification
- **`cargo test` on `velo-core`, `velo-ble` and `velo-sync`:**
  - Zwift Ride decoding, using shifter.rs's test vectors.
  - FTMS encoding and parsing.
  - ZWO and text-syntax round-trips.
  - CTL/ATL against values from Apex and intervals.icu.
  - FIT export, checked by decoding the output with `fitparser`.
  - Plan rebalancing scenarios.
  - Generator: the same seed gives the same output, generated TSS lands within ±10% of the target, and hard days are never adjacent.
  - WebDAV sync against a local server (`rclone serve webdav`).
- **Vitest** for the focus-navigation system and the Svelte components.
- **On real hardware:** end of Phase 0 (spike), end of Phase 1 (a full workout with the trainer and Zwift Ride on the tablet), and Phase 3 (edit on desktop, then see it on the tablet after sync).
