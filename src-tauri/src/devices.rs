//! Bluetooth devices: scanning, the FTMS trainer and the Zwift controller.
//!
//! Byte formats come from `velo-ble`; this module only moves bytes through
//! `tauri-plugin-blec` (btleplug on desktop, its own Kotlin backend on Android) and turns
//! notifications into events for the UI:
//!  - `trainer:data`      [`velo_ble::ftms::BikeData`]
//!  - `controller:button` `{ button }` once per press
//!  - `controller:raw`    `{ hex, bitmap }` every notification (for the button tester)
//!  - `controller:battery` `{ percent }` from the Zwift battery message or the Battery service
//!  - `trainer:control`   `{ op, reply }` every control point answer (diagnostics)
//!  - `trainer:status`    `{ text }` every Fitness Machine Status notification (diagnostics)
//!  - `device:status`     [`Status`]

use serde::Serialize;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};
use tauri_plugin_blec::models::{BleDevice, CharProps, ScanFilter, WriteType};
use tauri_plugin_blec::{Handler, OnDisconnectHandler};
use tokio::sync::{mpsc, Mutex};
use velo_ble::ftms::{self, PowerRange, Reply, Target};
use velo_ble::zwift::{self, Model, PressDetector};
use velo_ble::{battery, hr};

/// How long to wait for the trainer to answer a control point write while connecting.
const REPLY_CONNECT: Duration = Duration::from_millis(1500);
/// How long to wait for the answer to a target during a ride.
const REPLY_RIDE: Duration = Duration::from_millis(600);

#[derive(Serialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "camelCase")]
pub enum Kind {
    Trainer,
    Controller,
    HeartRate,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Found {
    address: String,
    name: String,
    kind: Kind,
    rssi: Option<i16>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    kind: Kind,
    connected: bool,
    name: String,
    /// Trainer only: whether the trainer refused control (another app may hold it).
    denied: bool,
}

struct Trainer {
    address: String,
    range: PowerRange,
    replies: mpsc::UnboundedReceiver<(u8, Reply)>,
}

#[derive(Default)]
pub struct Devices {
    trainer: Mutex<Option<Trainer>>,
    controller: Mutex<Option<String>>,
}

/// The BLE handler. On Android it is set up only once the app is ready, so wait for it.
async fn handler() -> Result<&'static Handler, String> {
    for _ in 0..50 {
        if let Ok(h) = tauri_plugin_blec::get_handler() {
            return Ok(h);
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    tauri_plugin_blec::get_handler().map_err(|e| e.to_string())
}

fn classify(d: &BleDevice) -> Option<(Kind, String)> {
    let zwift_data = d.manufacturer_data.get(&zwift::COMPANY_ID);
    if zwift::is_controller(&d.services, zwift_data.is_some()) {
        let model = Model::from_type_byte(zwift_data.and_then(|m| m.first().copied()));
        if !model.connectable() {
            return None;
        }
        let name = if model == Model::Unknown && !d.name.is_empty() { d.name.clone() } else { model.label().into() };
        return Some((Kind::Controller, name));
    }
    let name = if d.name.is_empty() { d.address.clone() } else { d.name.clone() };
    if d.services.contains(&ftms::SERVICE) {
        Some((Kind::Trainer, name))
    } else if d.services.contains(&hr::SERVICE) {
        Some((Kind::HeartRate, name))
    } else {
        None
    }
}

fn status(app: &AppHandle, kind: Kind, connected: bool, name: &str, denied: bool) {
    let _ = app.emit("device:status", Status { kind, connected, name: name.into(), denied });
}

fn on_disconnect(app: &AppHandle, kind: Kind, name: String) -> OnDisconnectHandler {
    let app = app.clone();
    OnDisconnectHandler::from_sync(move || {
        log::warn!("{kind:?} {name} disconnected");
        status(&app, kind, false, &name, false);
    })
}

/// Scan for trainers, heart rate straps and Zwift controllers.
#[tauri::command]
pub async fn ble_scan(seconds: u64) -> Result<Vec<Found>, String> {
    if !tauri_plugin_blec::check_permissions(true).await.map_err(|e| e.to_string())? {
        return Err("Bluetooth permission denied".into());
    }
    let h = handler().await?;
    let (tx, mut rx) = mpsc::channel(4);
    h.discover(Some(tx), seconds.clamp(1, 30) * 1000, ScanFilter::None, false)
        .await
        .map_err(|e| e.to_string())?;
    // each message is the full list so far; the channel closes when the scan ends
    let mut latest = vec![];
    while let Some(devices) = rx.recv().await {
        latest = devices;
    }
    let mut found: Vec<Found> = latest
        .iter()
        .filter_map(|d| {
            classify(d).map(|(kind, name)| Found { address: d.address.clone(), name, kind, rssi: d.rssi })
        })
        .collect();
    found.sort_by_key(|f| std::cmp::Reverse(f.rssi.unwrap_or(i16::MIN)));
    Ok(found)
}

/// Write to the control point and wait (at most `wait`) for the trainer's answer.
async fn command(
    h: &'static Handler,
    address: &str,
    replies: &mut mpsc::UnboundedReceiver<(u8, Reply)>,
    bytes: &[u8],
    wait: Duration,
) -> Result<Reply, String> {
    while replies.try_recv().is_ok() {} // drop stale replies
    h.send_data_to(address, ftms::CONTROL_POINT, Some(ftms::SERVICE), bytes, WriteType::WithResponse)
        .await
        .map_err(|e| e.to_string())?;
    let deadline = tokio::time::Instant::now() + wait;
    loop {
        match tokio::time::timeout_at(deadline, replies.recv()).await {
            Ok(Some((op, reply))) if op == bytes[0] => return Ok(reply),
            Ok(Some(_)) => {} // answer to an earlier command
            Ok(None) | Err(_) => return Ok(Reply::Silent),
        }
    }
}

/// Connect an FTMS trainer, take control and stream its data.
#[tauri::command]
pub async fn trainer_connect(app: AppHandle, devices: State<'_, Devices>, address: String, name: String) -> Result<bool, String> {
    let h = handler().await?;
    let mut slot = devices.trainer.lock().await;
    if let Some(old) = slot.take() {
        let _ = h.disconnect_device(&old.address).await;
    }
    h.connect(&address, on_disconnect(&app, Kind::Trainer, name.clone()), false)
        .await
        .map_err(|e| e.to_string())?;

    // control point answers arrive as indications; they must be enabled before writing
    let (tx, mut replies) = mpsc::unbounded_channel();
    let cp_app = app.clone();
    h.subscribe_to(&address, ftms::CONTROL_POINT, Some(ftms::SERVICE), move |v: Vec<u8>| {
        if let Some((op, reply)) = ftms::parse_cp_response(&v) {
            let _ = cp_app.emit("trainer:control", serde_json::json!({ "op": format!("0x{op:02x}"), "reply": reply }));
            let _ = tx.send((op, reply));
        }
    })
    .await
    .map_err(|e| format!("FTMS control point unavailable: {e}"))?;

    // machine status confirms targets ("target power changed to …"); optional, diagnostics only
    let status_app = app.clone();
    if let Err(e) = h
        .subscribe_to(&address, ftms::MACHINE_STATUS, Some(ftms::SERVICE), move |v: Vec<u8>| {
            let _ = status_app.emit("trainer:status", serde_json::json!({ "text": ftms::describe_status(&v) }));
        })
        .await
    {
        log::info!("no fitness machine status: {e}");
    }

    // any answer keeps ERG: some firmware says "not permitted" and follows targets anyway
    let mut denied = command(h, &address, &mut replies, &[ftms::OP_REQUEST_CONTROL], REPLY_CONNECT).await?
        == Reply::Denied;
    denied |= command(h, &address, &mut replies, &[ftms::OP_START], REPLY_CONNECT).await? == Reply::Denied;
    if denied {
        log::warn!("trainer refused control; another app may hold it");
    }

    let range = match h.recv_data_from(&address, ftms::SUPPORTED_POWER_RANGE, Some(ftms::SERVICE)).await {
        Ok(v) => PowerRange::parse(&v).unwrap_or_default(),
        Err(_) => PowerRange::default(),
    };
    log::info!("trainer {name}: power range {range:?}");

    let data_app = app.clone();
    h.subscribe_to(&address, ftms::INDOOR_BIKE_DATA, Some(ftms::SERVICE), move |v: Vec<u8>| {
        if let Some(d) = ftms::parse_bike_data(&v) {
            let _ = data_app.emit("trainer:data", d);
        }
    })
    .await
    .map_err(|e| e.to_string())?;

    *slot = Some(Trainer { address, range, replies });
    status(&app, Kind::Trainer, true, &name, denied);
    Ok(denied)
}

/// Send a target and return the trainer's answer. If the trainer refuses because it no longer
/// grants us control, request control once more and retry.
async fn write_target(devices: &Devices, target: Target) -> Result<Reply, String> {
    let h = handler().await?;
    let mut slot = devices.trainer.lock().await;
    let t = slot.as_mut().ok_or("No trainer connected")?;
    let target = match target {
        Target::Watts(w) => Target::Watts(t.range.clamp(w)),
        free => free,
    };
    let bytes = target.bytes();
    let reply = command(h, &t.address, &mut t.replies, &bytes, REPLY_RIDE).await?;
    if reply != Reply::Denied {
        return Ok(reply);
    }
    log::warn!("target refused; requesting control again");
    command(h, &t.address, &mut t.replies, &[ftms::OP_REQUEST_CONTROL], REPLY_CONNECT).await?;
    command(h, &t.address, &mut t.replies, &bytes, REPLY_RIDE).await
}

/// ERG: hold `watts` (clamped to the trainer's range). Returns the trainer's answer.
#[tauri::command]
pub async fn trainer_set_power(devices: State<'_, Devices>, watts: i32) -> Result<Reply, String> {
    write_target(&devices, Target::Watts(watts)).await
}

/// Leave ERG for a flat-road simulation. Returns the trainer's answer.
#[tauri::command]
pub async fn trainer_free_ride(devices: State<'_, Devices>) -> Result<Reply, String> {
    write_target(&devices, Target::Free).await
}

/// Connect a Zwift controller and stream its button presses.
#[tauri::command]
pub async fn controller_connect(app: AppHandle, devices: State<'_, Devices>, address: String, name: String) -> Result<(), String> {
    let h = handler().await?;
    let mut slot = devices.controller.lock().await;
    if let Some(old) = slot.take() {
        let _ = h.disconnect_device(&old).await;
    }
    let conn = h
        .connect(&address, on_disconnect(&app, Kind::Controller, name.clone()), false)
        .await
        .map_err(|e| e.to_string())?;

    let presses = Arc::new(StdMutex::new(PressDetector::default()));
    let button_app = app.clone();
    h.subscribe_to(&address, zwift::ASYNC, None, move |v: Vec<u8>| {
        let hex: String = v.iter().map(|b| format!("{b:02x}")).collect();
        if let Some(percent) = zwift::battery(&v) {
            let _ = button_app.emit("controller:battery", serde_json::json!({ "percent": percent }));
        }
        let bitmap = zwift::ride_bitmap(&v).map(|b| format!("{b:08x}"));
        let _ = button_app.emit("controller:raw", serde_json::json!({ "hex": hex, "bitmap": bitmap }));
        let pressed = presses.lock().map(|mut p| p.feed(&v)).unwrap_or_default();
        for button in pressed.iter() {
            let _ = button_app.emit("controller:button", serde_json::json!({ "button": button }));
        }
    })
    .await
    .map_err(|e| format!("controller button channel unavailable: {e}"))?;
    if let Err(e) = h.subscribe_to(&address, zwift::SYNC_TX, None, |_: Vec<u8>| {}).await {
        log::warn!("controller sync channel unavailable: {e}");
    }

    // handshake: "RideOn" on sync RX, trying the write types the characteristic offers
    let props = conn
        .services()
        .await
        .map_err(|e| e.to_string())?
        .iter()
        .flat_map(|s| &s.characteristics)
        .find(|c| c.uuid == zwift::SYNC_RX)
        .map(|c| c.properties)
        .ok_or("controller has no handshake characteristic")?;
    let mut result = Err("no write type to try".to_string());
    for with_response in zwift::handshake_with_response(props.contains(CharProps::Write), props.contains(CharProps::WriteWithoutResponse)) {
        let wt = if with_response { WriteType::WithResponse } else { WriteType::WithoutResponse };
        result = h.send_data_to(&address, zwift::SYNC_RX, None, zwift::RIDE_ON, wt).await.map_err(|e| e.to_string());
        if result.is_ok() {
            break;
        }
    }
    result.map_err(|e| format!("controller handshake failed: {e}"))?;

    // standard Battery service, if the controller has one: read now, then follow notifications
    if let Ok(v) = h.recv_data_from(&address, battery::LEVEL, Some(battery::SERVICE)).await
        && let Some(percent) = battery::parse(&v)
    {
        let _ = app.emit("controller:battery", serde_json::json!({ "percent": percent }));
    }
    let battery_app = app.clone();
    let _ = h
        .subscribe_to(&address, battery::LEVEL, Some(battery::SERVICE), move |v: Vec<u8>| {
            if let Some(percent) = battery::parse(&v) {
                let _ = battery_app.emit("controller:battery", serde_json::json!({ "percent": percent }));
            }
        })
        .await;

    *slot = Some(address);
    status(&app, Kind::Controller, true, &name, false);
    Ok(())
}

/// Disconnect every device.
#[tauri::command]
pub async fn ble_disconnect_all(devices: State<'_, Devices>) -> Result<(), String> {
    devices.trainer.lock().await.take();
    devices.controller.lock().await.take();
    handler().await?.disconnect_all().await.map_err(|e| e.to_string())
}
