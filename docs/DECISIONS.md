# Decisions

This is a log of the decisions that shape BikeTo. Each entry gives the decision, the reason for it, and its status. Add new entries at the bottom with the next number. Don't rewrite old entries: if a decision changes, add a new entry and mark the old one **Superseded by D-NN**.

Statuses: **Accepted** (in force), **Superseded**, **Open** (to be decided).

---

### D-01 · Native Tauri 2 app, not a PWA — Accepted (2026-11-20)
- **Decision:** a native Tauri 2 app, built as an Android APK for the tablet and a desktop build for the computer.
- **Why:**
  - Native HTTP means no CORS restrictions, so Garmin Connect and any WebDAV server can be called directly.
  - Garmin login can run in Tauri's embedded webview, as zwo-trainer does.
  - zwo-trainer's Rust code can be reused.
- **Rejected:** a Svelte PWA. It would need a side container for Garmin and CORS set up on the WebDAV server.
- **Risk:** Bluetooth on Android. This is why Phase 0 is a hardware spike.

### D-02 · New repo, not a fork of zwo-trainer — Accepted (2026-11-20)
- **Decision:** start a new repo and copy only the modules we need from zwo-trainer, adapting them.
- **Why:** zwo-trainer's UI is plain JavaScript and it targets desktop only, while we want Svelte and a different architecture.

### D-03 · Svelte 5 + TypeScript + Vite frontend — Accepted (2026-11-20)
- **Decision:** the frontend uses Svelte 5, TypeScript and Vite.
- **Why:** the app is large (builder, calendar, analytics), and plain JS would be hard to maintain at that size.
- **Pin:** TypeScript stays on 6.x, because `svelte-check` 4.7 does not support TypeScript 7.

### D-04 · Business logic in Rust; Svelte only displays — Accepted (2026-11-20)
- **Decision:** all business logic lives in the Cargo workspace (`velo-core`, `velo-ble`, `velo-sync`), and the ride engine runs on a tokio task.
- **Why:**
  - It can be tested with `cargo test`.
  - The same code runs on Android and desktop.
  - Ride timing doesn't depend on the WebView being throttled.

### D-05 · Licensing rules for reference repos — Accepted (2026-11-20)
- **Our license:** MIT.
- **Code we may copy and adapt** (credit in `NOTICE`):
  - zwo-trainer (MIT)
  - Apex-Velo-Lab (MIT)
  - croissant-ride (Apache-2.0)
- **Re-implement ideas only:**
  - dreeve (AGPL)
  - zwo-workout-builder (no license)
  - pedalcraft-site (no license)
- **Never use** zwo-workout-builder's workout library data (third-party content).

### D-06 · Bluetooth through `tauri-plugin-blec` — Accepted (2026-11-20)
- **Decision:** `tauri-plugin-blec` 0.20 (MIT/Apache) handles Bluetooth. It uses btleplug on desktop and its own Kotlin backend on Android.
- **Why:** it supports several devices connected at once, and it has a mock feature we can use for a simulator.
- **Consequence:** Android `minSdk` must be 26 (Android 8.0) or higher.
- **Fallback:** write our own Kotlin Tauri plugin if the spike shows the plugin is unreliable.

### D-07 · Protocol code has no I/O — Accepted (2026-11-20)
- **Decision:** `crates/velo-ble` only converts between bytes and values. All Bluetooth I/O lives in `src-tauri/src/devices.rs`.
- **Why:** the protocols can be unit-tested without hardware.

### D-08 · Garmin Connect through the unofficial API, natively — Accepted (2026-11-20)
- **Decision:** log in through an embedded webview using the OAuth flow from zwo-trainer's `garmin.rs`, behind a `GarminSource` trait. Manual FIT import/export is always available as a fallback.
- **Why:** Garmin offers no official API for personal use. Dreeve's approach (a Python container) would need a server, which we don't want.
- **Open question:** whether these tokens also give access to the wellness and calendar endpoints. To be checked in Phase 7.

### D-09 · WebDAV sync with one JSON file per entity — Accepted (2026-11-20)
- **Decision:** each entity is stored as `velo-app/{type}/{id}.json` on WebDAV, with FIT files stored separately. Each record carries `updated_at` and a deleted flag (tombstone). Conflicts are resolved per entity: the newest record wins.
- **Why:** there's no server, and the user edits from both the tablet and the computer.

### D-10 · App identity — Accepted (2026-11-20)
- **Decision:** the product is named **BikeTo** and the app ID is `com.biketo.app`. Repository and crate names keep `velo-*`.
- **Why:** the app ID is permanent once the app is installed on a device.

### D-11 · Brand: indigo `#818CF8` and a geometric SVG logo — Accepted (2026-11-20)
- **Accent:** `#818CF8` in dark mode, `#4F46E5` in light mode for contrast. The theme is dark first.
- **Logo:** rebuilt as SVG geometry from `assets/logo.PNG`. The saddle was straightened.
- **Icons:** generated from `assets/icon.svg` with `npx tauri icon`.

### D-12 · Toolchain locations on the dev machine — Accepted (2026-11-20)
- **Locations:** everything lives under `~/.local/share/` to keep the home folder tidy: the Android SDK (`android/sdk`, with `ANDROID_USER_HOME` in `android/user`), Cargo and rustup, and the Gradle cache in `~/.cache/gradle`.
- **JDK:** Java 25, because Fedora 45 no longer ships 21.
- **Android project:** compileSdk/targetSdk 37, Gradle 9.6.1.

### D-13 · APK installed by hand; signed release builds — Accepted (2026-11-20)
- **Decision:** the user copies the APK to the tablet and installs it by hand, without adb.
- **Signing:** release APKs are signed with a dedicated keystore at `~/.local/share/biketo/biketo-release.jks`. The gitignored `src-tauri/gen/android/keystore.properties` points to it.
- **Why:** release APKs are much smaller, and builds signed with the same key update in place.
- **Warning:** if the keystore is lost, the next build can't update the installed app. It has to be uninstalled first, and its local data is lost with it.

### D-14 · Screen stays on in the foreground — Accepted (2026-11-20)
- **Decision:** `FLAG_KEEP_SCREEN_ON` is set in `MainActivity.kt`, which is a hand-edited generated file.
- **Why:** the tablet sits on the handlebars during rides, so it must not sleep.

### D-15 · Vendor and patch `tauri-plugin-blec` for indications — Accepted (2026-11-20)
- **Problem:** on Android, the plugin always writes `ENABLE_NOTIFICATION_VALUE` to the CCCD. On indicate-only characteristics, such as the FTMS Control Point (0x2AD9), indications therefore stay off. The trainer sent data but ignored ERG commands during the first tablet test.
- **Decision:** copy the plugin into `vendor/tauri-plugin-blec`, wired in through `[patch.crates-io]`. `subscribe()` now writes `ENABLE_INDICATION_VALUE` when a characteristic supports indications but not notifications. Details are in `vendor/README.md`.
- **Exit:** drop the copy once upstream (MnlPhlp/tauri-plugin-blec) fixes the bug. Reporting it upstream needs the user's OK first.

### D-16 · No trainer calibration feature for now — Accepted (2026-11-20)
- **Decision:** BikeTo has no calibration feature for now.
- **Why:** the user's trainer is a **Wahoo KICKR CORE 2**, which calibrates itself in firmware while riding. Wahoo's only manual option is the "factory spindown", a last resort that runs from Wahoo's own app.
- **Revisit if needed:** the standard FTMS spindown (op code 0x13, offered only if the trainer lists "Spin Down Control" in its Target Setting Features at 0x2ACC) could be added later for other trainers.

### D-17 · Zwift Ride Z button is bit 0x80 — Accepted (2026-11-20)
- **Decision:** the Z button is bit `0x80` of the Ride bitmap.
- **Why:** captured on the user's Zwift Ride. zwo-trainer's `0x100` is wrong, and the capture is now a unit test.
- **Battery:** read from Zwift message type `0x19` (`{1: percent}`), plus the standard Battery service (0x180F/0x2A19) if present.

### D-18 · Android adaptive icon built by our own script — Accepted (2026-11-20)
- **Decision:** `scripts/android-icons.sh` regenerates every icon.
- **How:** it runs `tauri icon` from `assets/icon.svg` for desktop and legacy icons. It then replaces the Android adaptive-icon foreground with `assets/icon-foreground.svg` (transparent, logo at 52% width so it stays inside the safe zone) and sets the background color to `#16181D`.
- **Why:** `tauri icon` uses the full icon as the foreground on a white background, which clips under round launcher masks. It also only writes Android icons if the Android project already exists.

### D-19 · Project folder renamed to `~/Projets/biketo` — Accepted (2026-11-20)
- **Decision:** the user renamed the folder to `~/Projets/biketo`. The Rust crates keep their `velo-*` names (`velo-ble`, `velo-app` / `velo_app_lib`); this is cosmetic and they can be renamed later.
- **Note:** Claude's project memory is stored by folder path, and has been copied to the new location.
