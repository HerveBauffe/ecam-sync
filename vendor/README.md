# Vendored dependencies

## tauri-plugin-blec 0.20.0 (MIT OR Apache-2.0)
Copied from crates.io and wired in through `[patch.crates-io]` in the root `Cargo.toml`.

Patch: `android/src/main/java/com/plugin/blec/Peripheral.kt`, in `subscribe()`. Characteristics that only support indications now get `ENABLE_INDICATION_VALUE` written to their CCCD. Upstream always writes the notification value. On Android that leaves indications off on indicate-only characteristics such as the FTMS Control Point (0x2AD9), and trainers then ignore ERG commands. See D-15 in `docs/DECISIONS.md`.

Drop this copy once upstream fixes the bug.
