# Features

This is the list of everything BikeTo should do, grouped by area. Each feature has a status and the roadmap phase it belongs to (see `ROADMAP.md`). Update the status when a feature lands, and put the details of what happened in `PROGRESS.md`.

Status: ✅ done · 🟡 partial or untested · ⬜ not started · ❓ needs a decision · ❌ decided against

## Devices and Bluetooth
| Feature | Phase | Status |
|---|---|---|
| Scan, then classify each result as trainer (FTMS), Zwift controller or heart-rate strap | 0 | ✅ |
| FTMS trainer: take control, ERG target clamped to the trainer's power range, free ride (flat-road simulation), live power/cadence/speed/HR | 0 | ✅ on the KICKR CORE 2 (with the D-15 patch) |
| Zwift Ride / Click / Play: "RideOn" handshake, button decoding, one event per press; the left Ride only, since it relays the right one | 0 | ✅ (Z = 0x80, D-17) |
| Separate heart-rate strap connection | 1 | ⬜ (scanning works, connecting doesn't yet) |
| Power meter as a separate source (Cycling Power 0x1818), PowerMatch | 1 | ⬜ |
| Automatic reconnect when a device drops | 1 | ⬜ |
| Simulator: fake trainer, heart rate and controller for developing without hardware | 1 | ⬜ |
| Zwift Ride analog paddles and keepalive (pedalcraft notes) | later | ❓ only if needed on hardware |
| Controller battery level (Zwift message 0x19 and the Battery service) | 0 | ✅ |
| Trainer calibration | — | ❌ not needed for the KICKR CORE 2 (D-16) |

## Riding
| Feature | Phase | Status |
|---|---|---|
| Ride engine in Rust (ticks every 250 ms, 1 s samples), target power = workout × intensity × FTP | 1 | ⬜ |
| Ride page modeled on zwoTrainer: workout chart, gauges, play/pause, skip forward/back, intensity 50–150% | 1 | ⬜ |
| Everything usable with controller buttons only | 1 | ⬜ |
| Virtual shifting in free ride (24 gears; port of zwo-trainer's `vshift.js`) | 1 | ⬜ |
| ERG soft start and protection against cadence collapse (Apex `velo-erg.js`) | 1 | ⬜ |
| Recorder with crash recovery, FIT export, summary screen | 1 | ⬜ |
| FTP and ramp tests | 2 | ⬜ |

## Workouts and plans
| Feature | Phase | Status |
|---|---|---|
| Workout model: steps, ramps, repeats, cadence, text cues | 1 | ⬜ |
| `.zwo` import and export | 1 | ⬜ |
| Text editor using intervals.icu-style syntax, with round-tripping | 2 | ⬜ |
| Drag-and-drop block editor | 2 | ⬜ |
| Workout generator (our own design; ideas from zwo-workout-builder, no copied code or data), seeded, three options per request | 2 | ⬜ |
| Home page library in suffer.online style (categories, filters, cards) | 2 | ⬜ |
| Plan generator: periodization, 3:1 load-to-recovery weeks, load ramp, taper, placement of key days | 5 | ⬜ |
| Adaptive week: move, skip or ride a session differently, and the rest of the week rebalances (Apex block-planner math) | 5 | ⬜ |
| Calendar (week and month views) with drag-to-move | 5 | ⬜ |
| Plan export as `WeekNN_DayNN_Title.zwo` folders | 5 | ⬜ |

## Analytics
| Feature | Phase | Status |
|---|---|---|
| NP, IF and TSS; hrTSS for rides without power | 4 | ⬜ |
| CTL (42 days), ATL (7 days) and TSB, with form bands and ACWR | 4 | ⬜ |
| Monotony and strain, rest days | 4 | ⬜ |
| Polarization (Seiler PI and three-zone targets) | 4 | ⬜ |
| Power curve, CP/W′, W′bal | 4 | ⬜ |
| Readiness from HRV, resting HR and sleep, falling back to TSB | 4 | ⬜ |
| Rolling 7-day distance and time goals | 4 | ⬜ |
| Dashboard | 4 | ⬜ |

## Bikes and wear
| Feature | Phase | Status |
|---|---|---|
| Bikes and nested components with install/remove history | 6 | ⬜ |
| Maintenance tasks by km, hours, days or days used; due at 98%, overdue when past | 6 | ⬜ |
| Bike assigned per activity (indoor default; chosen per outdoor ride) | 6 | ⬜ |

## Sync and integrations
| Feature | Phase | Status |
|---|---|---|
| WebDAV sync: one JSON file per entity, ETags, newest wins, tombstones | 3 | ⬜ |
| FIT import (files and a WebDAV inbox folder) | 4 | ⬜ |
| Garmin: login, pull activities and wellness data, push activities and workouts to the calendar | 7 | ⬜ (see D-08) |
| intervals.icu upload (optional) | 7 | ⬜ |

## App and UI
| Feature | Phase | Status |
|---|---|---|
| BikeTo branding: logo, icons (Android adaptive icon, D-18), indigo accent | 0 | ✅ |
| Dark-first theme with a light toggle | 0 | 🟡 tokens exist, toggle not built |
| Screen stays on while riding | 0 | ✅ (Android) |
| Settings page: FTP, zones, weight, devices, button mapping, theme | 2 | ⬜ |
| SQLite storage | 1–2 | ⬜ |
