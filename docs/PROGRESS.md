# Progress

**Read this first at the start of a session.** Update it at the end: move items between sections, add a dated entry to the log, and keep "Next steps" current. Keep it short; put the details in commits and code.

## Current state (2026-11-20, end of session 1)

**Phase 0 is done.** Everything was confirmed on the tablet with a Wahoo KICKR CORE 2 and a Zwift Ride: scanning, trainer data, **ERG** (thanks to the patched plugin, D-15), every Ride button including Z (D-17), and the controller battery.

**Latest build: v0.1.3.** It adds the BikeTo launcher icon (adaptive icon, D-18). The APK is at `src-tauri/gen/android/app/build/outputs/apk/universal/release/app-universal-release.apk`. The user installs it by hand (D-13). Build it with `npm run tauri android build -- --apk --target aarch64`.

The spike screen in `src/App.svelte` is temporary. Phase 1 replaces it with the real app shell.

## Next steps (session 2: Phase 1, "Ride core")
Read `docs/ROADMAP.md` § Phase 1 and `docs/FEATURES.md` § Riding. Suggested split into subagent tasks, each with tests:
1. **`crates/velo-core` workout model:** steps, ramps, repeats, cadence, text cues. Add a `.zwo` parser and writer ported from zwo-trainer's `src-tauri/src/zwo.rs` (MIT), plus `powerAt`/`segmentAt`/`estimateTss` from `ui/js/zwo.js`. Fetch sources with `gh api repos/steffenr/zwo-trainer/contents/<path>?ref=develop`.
2. **Ride engine** in `velo-core` as a pure state machine (port of `ui/js/ride/ride.js`: tick/drive, intensity 50–150%, skip/back, auto-pause), plus virtual shifting (`ui/js/vshift.js`). `src-tauri` runs it on a tokio task and sends `ride:state` every 250 ms.
3. **App shell and ride page** in Svelte: routing, the input `Action` bus with focus navigation for the controller, and a ride page modeled on zwoTrainer.
4. **Device robustness:** auto-reconnect, heart-rate strap connection, simulator.
5. **Recorder** (crash recovery) and **FIT export** (port of `fit.rs`).
6. **Storage:** SQLite with records of the form `{id ULID, updated_at, deleted}` (D-09).

## Not verified / known issues
- **Battery scope:** only the left Ride's battery is likely reported. Whether the right one's level is relayed is unknown.
- **Long sessions:** the 30-minute stability run (disconnect counters) hasn't been reported.
- **Device behavior not yet handled:**
  - No auto-reconnect.
  - Heart-rate straps appear in scans but can't be connected.
  - No simulator.
- **Upstream bug report:** not filed. Ask the user before reporting the blec indication bug (D-15) to MnlPhlp/tauri-plugin-blec.
- **Git:** files are staged but **not committed**. Ask the user before the first commit.
- **Build:** the Android build prints deprecation warnings from Tauri's own Kotlin code. They are harmless.
- **Build after moving the folder:** Gradle fails with a `NullPointerException` because of stale absolute paths. Delete `src-tauri/gen/android/{.gradle,build,app/build,buildSrc/.gradle,buildSrc/build}` and `vendor/*/android/{build,.tauri}`, then rebuild.

## Log
- **2026-11-20:**
  - Wrote the roadmap. Researched the reference repos (licenses and reusable parts); see D-05 and `ROADMAP.md`.
  - Set up the toolchain under `~/.local/share` (D-12).
  - Scaffolded the workspace. `velo-ble` (FTMS, HR, Zwift) is adapted from zwo-trainer, with tests.
  - Built `devices.rs` on `tauri-plugin-blec`, and the spike UI.
  - Applied the BikeTo branding: SVG logo, icons, indigo accent.
  - Created the Android project: minSdk 26, keep-screen-on, release signing.
- **2026-11-20, first tablet test (v0.1.0):** data, shift levers and A worked; ERG and Z didn't. Root cause for ERG: blec's Android backend only enables notifications, never indications (D-15). Released v0.1.1 with the vendored, patched plugin and diagnostics.
- **2026-11-20, second test (v0.1.1):** ERG works on the KICKR CORE 2 (D-15 fix confirmed). The Z capture showed bit 0x80 (D-17). Added battery. Released v0.1.2.
- **2026-11-20, third test (v0.1.2):** Z and battery work, so Phase 0 is done. The Android icon was still Tauri's (the icons had been generated before `android init`). Fixed with an adaptive icon and `scripts/android-icons.sh` (D-18), released as v0.1.3. The project folder was renamed to `~/Projets/biketo` (D-19).
