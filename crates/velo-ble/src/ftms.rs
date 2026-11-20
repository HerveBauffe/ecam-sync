//! Fitness Machine Service (FTMS, 0x1826): smart trainer data and control.
//!
//! Adapted from zwo-trainer's `ble.rs` (MIT, Copyright (c) 2026 SteffenR).
//!
//! Taking control: enable indications on the control point, write [`OP_REQUEST_CONTROL`], then
//! [`OP_START`]. The trainer answers each write with `[0x80, op, result]` (see
//! [`parse_cp_response`]); many trainers never answer, and some answer "not permitted" yet
//! follow targets anyway, so a refusal is a warning, not a failure.

use crate::{i16le, u16le, uuid16};
use serde::Serialize;
use uuid::Uuid;

pub const SERVICE: Uuid = uuid16(0x1826);
pub const INDOOR_BIKE_DATA: Uuid = uuid16(0x2ad2);
pub const SUPPORTED_POWER_RANGE: Uuid = uuid16(0x2ad8);
pub const CONTROL_POINT: Uuid = uuid16(0x2ad9);
pub const MACHINE_STATUS: Uuid = uuid16(0x2ada);

pub const OP_REQUEST_CONTROL: u8 = 0x00;
pub const OP_START: u8 = 0x07;
pub const OP_RESPONSE: u8 = 0x80;

/// Our own limit for ERG targets; a trainer's Supported Power Range can only narrow it.
pub const MAX_TARGET: i32 = 2000;

/// What the trainer answered on the control point.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum Reply {
    Success,
    /// "Control not permitted": another app controls the trainer, or control was never granted.
    Denied,
    /// Any other result code (op code not supported, invalid parameter, operation failed).
    Failed(u8),
    /// No reply in time; many trainers never send one, so this is not an error.
    Silent,
}

impl Reply {
    pub fn from_result(code: u8) -> Self {
        match code {
            0x01 => Reply::Success,
            0x05 => Reply::Denied,
            c => Reply::Failed(c),
        }
    }
}

/// FTMS Control Point response indication: `[0x80, request op code, result code, …]`.
pub fn parse_cp_response(v: &[u8]) -> Option<(u8, Reply)> {
    match v {
        [OP_RESPONSE, op, result, ..] => Some((*op, Reply::from_result(*result))),
        _ => None,
    }
}

/// Power targets the trainer accepts (Supported Power Range, 0x2AD8), in watts.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize)]
pub struct PowerRange {
    pub min: i32,
    pub max: i32,
    pub step: i32,
}

impl Default for PowerRange {
    fn default() -> Self {
        PowerRange { min: 0, max: MAX_TARGET, step: 1 }
    }
}

impl PowerRange {
    /// `[min: sint16, max: sint16, increment: uint16]`, little endian. `None` for a missing or
    /// nonsensical range, so a bad value from the trainer never narrows ERG to something unusable.
    pub fn parse(v: &[u8]) -> Option<Self> {
        let min = i32::from(i16le(v, 0)?).max(0);
        let max = i32::from(i16le(v, 2)?).min(MAX_TARGET);
        let step = i32::from(u16le(v, 4)?).max(1);
        (max > min && step <= max - min).then_some(PowerRange { min, max, step })
    }

    /// Keep a target inside the range, on the trainer's increment (counted from `min`).
    pub fn clamp(self, watts: i32) -> i32 {
        let w = watts.clamp(self.min, self.max);
        let snapped = self.min + ((w - self.min) as f64 / self.step as f64).round() as i32 * self.step;
        // rounding up may pass a max that isn't on the grid: take the last step below it
        if snapped > self.max { snapped - self.step } else { snapped }
    }
}

/// What the trainer should do.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Target {
    /// ERG: hold this power whatever the cadence.
    Watts(i32),
    /// Flat-road simulation, for free ride.
    Free,
}

impl Target {
    /// Control point command for this target.
    pub fn bytes(self) -> Vec<u8> {
        match self {
            // Set Target Power: sint16 watts
            Target::Watts(w) => {
                let b = (w.clamp(0, MAX_TARGET) as i16).to_le_bytes();
                vec![0x05, b[0], b[1]]
            }
            // Indoor Bike Simulation, flat road: wind 0, grade 0 %, crr 0.004, cw 0.51
            Target::Free => vec![0x11, 0, 0, 0, 0, 40, 51],
        }
    }
}

/// Human-readable Fitness Machine Status (0x2ADA) notification, for diagnostics.
pub fn describe_status(v: &[u8]) -> String {
    match v {
        [0x01, ..] => "reset".into(),
        [0x02, ..] => "stopped or paused by user".into(),
        [0x04, ..] => "started or resumed by user".into(),
        [0x08, ..] => match i16le(v, 1) {
            Some(w) => format!("target power changed to {w} W"),
            None => "target power changed".into(),
        },
        [0x12, ..] => "indoor bike simulation parameters changed".into(),
        [0xff, ..] => "control permission lost".into(),
        [op, ..] => format!("status 0x{op:02x}"),
        [] => "empty".into(),
    }
}

/// One Indoor Bike Data notification. Fields the trainer didn't send are `None`.
#[derive(Clone, Copy, PartialEq, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BikeData {
    pub speed_kmh: Option<f32>,
    pub cadence_rpm: Option<f32>,
    pub power_w: Option<i16>,
    pub hr_bpm: Option<u8>,
}

/// FTMS Indoor Bike Data (0x2AD2). `None` if the value is too short for its own flags.
pub fn parse_bike_data(v: &[u8]) -> Option<BikeData> {
    let flags = u16le(v, 0)?;
    let mut o = 2;
    let mut out = BikeData::default();
    // bit 0 is "more data": instantaneous speed is present when it is *cleared*
    if flags & 0x0001 == 0 {
        out.speed_kmh = Some(f32::from(u16le(v, o)?) / 100.0);
        o += 2;
    }
    if flags & 0x0002 != 0 { o += 2; } // average speed
    if flags & 0x0004 != 0 {
        out.cadence_rpm = Some(f32::from(u16le(v, o)?) / 2.0);
        o += 2;
    }
    if flags & 0x0008 != 0 { o += 2; } // average cadence
    if flags & 0x0010 != 0 { o += 3; } // total distance
    if flags & 0x0020 != 0 { o += 2; } // resistance level
    if flags & 0x0040 != 0 {
        out.power_w = Some(i16le(v, o)?);
        o += 2;
    }
    if flags & 0x0080 != 0 { o += 2; } // average power
    if flags & 0x0100 != 0 { o += 5; } // expended energy
    if flags & 0x0200 != 0 {
        out.hr_bpm = v.get(o).copied().filter(|hr| *hr > 0);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn control_point_response() {
        assert_eq!(parse_cp_response(&[0x80, 0x00, 0x01]), Some((0x00, Reply::Success)));
        assert_eq!(parse_cp_response(&[0x80, 0x05, 0x05]), Some((0x05, Reply::Denied)));
        assert_eq!(parse_cp_response(&[0x80, 0x11, 0x01, 0xaa]), Some((0x11, Reply::Success)));
        assert_eq!(parse_cp_response(&[0x80, 0x07, 0x02]), Some((0x07, Reply::Failed(0x02))));
        assert_eq!(parse_cp_response(&[0x05, 0x64, 0x00]), None);
        assert_eq!(parse_cp_response(&[0x80, 0x00]), None);
        assert_eq!(parse_cp_response(&[]), None);
    }

    #[test]
    fn supported_power_range() {
        let r = PowerRange::parse(&[0x00, 0x00, 0xdc, 0x05, 0x01, 0x00]).unwrap();
        assert_eq!(r, PowerRange { min: 0, max: 1500, step: 1 });
        // 25–2500 W, 5 W steps: the maximum is capped at our own 2000 W
        let r = PowerRange::parse(&[0x19, 0x00, 0xc4, 0x09, 0x05, 0x00]).unwrap();
        assert_eq!(r, PowerRange { min: 25, max: 2000, step: 5 });
        // nonsense is ignored: max ≤ min, short value, step wider than the range
        assert_eq!(PowerRange::parse(&[0x64, 0x00, 0x64, 0x00, 0x01, 0x00]), None);
        assert_eq!(PowerRange::parse(&[0x00, 0x00, 0xdc]), None);
        assert_eq!(PowerRange::parse(&[0x00, 0x00, 0x0a, 0x00, 0x64, 0x00]), None);
        // a negative minimum counts as 0; a zero step as 1
        assert_eq!(
            PowerRange::parse(&[0xf6, 0xff, 0xe8, 0x03, 0x00, 0x00]),
            Some(PowerRange { min: 0, max: 1000, step: 1 })
        );
    }

    #[test]
    fn targets_stay_inside_the_power_range() {
        let r = PowerRange { min: 25, max: 1500, step: 5 };
        assert_eq!(r.clamp(10), 25);
        assert_eq!(r.clamp(1800), 1500);
        assert_eq!(r.clamp(152), 150);
        assert_eq!(r.clamp(153), 155);
        assert_eq!(PowerRange { min: 0, max: 1003, step: 5 }.clamp(1003), 1000);
        assert_eq!(PowerRange::default().clamp(-20), 0);
        assert_eq!(PowerRange::default().clamp(2500), 2000);
        assert_eq!(PowerRange::default().clamp(173), 173);
    }

    #[test]
    fn target_bytes() {
        assert_eq!(Target::Watts(150).bytes(), vec![0x05, 0x96, 0x00]);
        assert_eq!(Target::Watts(200).bytes(), vec![0x05, 0xc8, 0x00]);
        assert_eq!(Target::Watts(5000).bytes(), vec![0x05, 0xd0, 0x07], "capped at 2000 W");
        assert_eq!(Target::Free.bytes(), vec![0x11, 0, 0, 0, 0, 40, 51]);
    }

    #[test]
    fn bike_data_speed_cadence_power() {
        // flags 0x0044: speed (bit 0 cleared), cadence, power
        let d = parse_bike_data(&[0x44, 0x00, 0x10, 0x0e, 0xb4, 0x00, 0xc8, 0x00]).unwrap();
        assert_eq!(d.speed_kmh, Some(36.0));
        assert_eq!(d.cadence_rpm, Some(90.0));
        assert_eq!(d.power_w, Some(200));
        assert_eq!(d.hr_bpm, None);
    }

    #[test]
    fn bike_data_skips_unused_fields() {
        // flags 0x0241: more data (no speed), power, heart rate
        let d = parse_bike_data(&[0x41, 0x02, 0xfa, 0x00, 0x8c]).unwrap();
        assert_eq!((d.speed_kmh, d.power_w, d.hr_bpm), (None, Some(250), Some(140)));
        // flags 0x0054: speed, cadence, total distance (3 bytes, skipped), power
        let d = parse_bike_data(&[0x54, 0x00, 0x10, 0x0e, 0xb4, 0x00, 0x01, 0x02, 0x03, 0x2c, 0x01]).unwrap();
        assert_eq!(d.power_w, Some(300));
    }

    #[test]
    fn machine_status() {
        assert_eq!(describe_status(&[0x08, 0x96, 0x00]), "target power changed to 150 W");
        assert_eq!(describe_status(&[0xff]), "control permission lost");
        assert_eq!(describe_status(&[0x33]), "status 0x33");
    }

    #[test]
    fn bike_data_truncated() {
        assert_eq!(parse_bike_data(&[0x44, 0x00, 0x10, 0x0e, 0xb4]), None);
        assert_eq!(parse_bike_data(&[0x44]), None);
        // heart rate flag without the byte: no heart rate, rest still parsed
        assert_eq!(parse_bike_data(&[0x41, 0x02, 0xfa, 0x00]).unwrap().hr_bpm, None);
    }
}
