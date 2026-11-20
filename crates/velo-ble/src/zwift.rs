//! Zwift Ride / Click / Play controllers.
//!
//! Adapted from zwo-trainer's `shifter.rs` (MIT, Copyright (c) 2026 SteffenR), which follows the
//! publicly reverse-engineered protocol:
//!  - advertises manufacturer data with Zwift's company id 0x094A; byte 0 = device type
//!  - service `00000001-19ca-4651-86e5-fa29dcdd09d1` (the Ride advertises 16-bit 0xFC82 instead):
//!    …0002 async notify (button events) · …0003 sync RX (write) · …0004 sync TX (indicate)
//!  - handshake: subscribe to async + sync TX, write `"RideOn"` to sync RX → unencrypted
//!    button notifications
//!  - notification = 1 type byte + protobuf:
//!    0x37 Click `{1: plus, 2: minus}` (0 = pressed) · 0x07 Play `{1: side, 2..7: buttons}` ·
//!    0x23 Ride `{1: button bitmap}` (bit cleared = pressed)
//!
//!    0x19 battery `{1: percent}`
//!
//! Only the LEFT Zwift Ride controller needs a connection: it relays the right one.

use crate::uuid16;
use serde::Serialize;
use uuid::Uuid;

pub const COMPANY_ID: u16 = 0x094a;
pub const SERVICE: Uuid = Uuid::from_u128(0x00000001_19ca_4651_86e5_fa29dcdd09d1);
pub const SERVICE_RIDE: Uuid = uuid16(0xfc82);
pub const ASYNC: Uuid = Uuid::from_u128(0x00000002_19ca_4651_86e5_fa29dcdd09d1);
pub const SYNC_RX: Uuid = Uuid::from_u128(0x00000003_19ca_4651_86e5_fa29dcdd09d1);
pub const SYNC_TX: Uuid = Uuid::from_u128(0x00000004_19ca_4651_86e5_fa29dcdd09d1);
pub const RIDE_ON: &[u8] = b"RideOn";

// Zwift Ride bitmap (bit cleared = pressed)
const RIDE_LEFT: u32 = 0x1;
const RIDE_UP: u32 = 0x2;
const RIDE_RIGHT: u32 = 0x4;
const RIDE_DOWN: u32 = 0x8;
const RIDE_A: u32 = 0x10;
const RIDE_B: u32 = 0x20;
const RIDE_Y: u32 = 0x40;
// 0x80, confirmed on a Zwift Ride (2026-11-20); zwo-trainer had 0x100
const RIDE_Z: u32 = 0x80;
const RIDE_SHIFT_UP_L: u32 = 0x0200;
const RIDE_SHIFT_DN_L: u32 = 0x0400;
const RIDE_POWERUP_L: u32 = 0x0800;
const RIDE_ONOFF_L: u32 = 0x1000;
const RIDE_SHIFT_UP_R: u32 = 0x2000;
const RIDE_SHIFT_DN_R: u32 = 0x4000;
const RIDE_POWERUP_R: u32 = 0x10000;
const RIDE_ONOFF_R: u32 = 0x20000;

/// A logical button, the same on every controller model.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum Button {
    ShiftUp,
    ShiftDown,
    Up,
    Down,
    Left,
    Right,
    A,
    B,
    Y,
    Z,
    PowerUp,
    OnOff,
}

impl Button {
    pub const ALL: [Button; 12] = [
        Button::ShiftUp,
        Button::ShiftDown,
        Button::Up,
        Button::Down,
        Button::Left,
        Button::Right,
        Button::A,
        Button::B,
        Button::Y,
        Button::Z,
        Button::PowerUp,
        Button::OnOff,
    ];

    /// This button's bit in a [`Buttons`] mask.
    pub const fn bit(self) -> u32 {
        1 << self as u32
    }
}

/// A set of pressed buttons, as a bitmask of [`Button::bit`]s.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Buttons(pub u32);

impl Buttons {
    pub fn contains(self, b: Button) -> bool {
        self.0 & b.bit() != 0
    }

    pub fn iter(self) -> impl Iterator<Item = Button> {
        Button::ALL.into_iter().filter(move |b| self.contains(*b))
    }
}

/// Which controller a scan result is, from byte 0 of its Zwift manufacturer data.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum Model {
    Click,
    ClickV2,
    PlayLeft,
    PlayRight,
    RideLeft,
    RideRight,
    Unknown,
}

impl Model {
    pub fn from_type_byte(b: Option<u8>) -> Self {
        match b {
            Some(0x09) => Model::Click,
            Some(0x0a | 0x0b) => Model::ClickV2,
            Some(0x02) => Model::PlayRight,
            Some(0x03) => Model::PlayLeft,
            Some(0x07) => Model::RideRight,
            Some(0x08) => Model::RideLeft,
            _ => Model::Unknown,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Model::Click => "Zwift Click",
            Model::ClickV2 => "Zwift Click v2",
            Model::PlayLeft => "Zwift Play (L)",
            Model::PlayRight => "Zwift Play (R)",
            Model::RideLeft => "Zwift Ride (L)",
            Model::RideRight => "Zwift Ride (R)",
            Model::Unknown => "Zwift controller",
        }
    }

    /// Whether to offer this device for connection: the right Ride is relayed by the left one.
    pub fn connectable(self) -> bool {
        self != Model::RideRight
    }
}

/// Whether a scanned device is a Zwift controller.
pub fn is_controller(services: &[Uuid], has_zwift_manufacturer_data: bool) -> bool {
    has_zwift_manufacturer_data || services.contains(&SERVICE) || services.contains(&SERVICE_RIDE)
}

/// Write types to try for the handshake, preferred first: (with response?).
/// The Ride rejects write-with-response on some platforms, so without-response comes first.
pub fn handshake_with_response(write: bool, write_without_response: bool) -> Vec<bool> {
    match (write, write_without_response) {
        (false, true) => vec![false],
        (true, false) => vec![true],
        _ => vec![false, true],
    }
}

/// Minimal protobuf reader: (field number, varint value) pairs; other wire types skipped.
pub fn proto_varints(b: &[u8]) -> Vec<(u32, u64)> {
    let mut out = vec![];
    let mut i = 0;
    let varint = |i: &mut usize| -> Option<u64> {
        let mut v = 0u64;
        let mut shift = 0;
        while *i < b.len() {
            let byte = b[*i];
            *i += 1;
            v |= ((byte & 0x7f) as u64) << shift;
            if byte & 0x80 == 0 {
                return Some(v);
            }
            shift += 7;
            if shift > 63 {
                return None;
            }
        }
        None
    };
    while i < b.len() {
        let Some(key) = varint(&mut i) else { break };
        let (field, wire) = ((key >> 3) as u32, key & 7);
        // lengths come from the device: checked, so a huge one can't wrap `i` back to the start
        let skip = match wire {
            0 => match varint(&mut i) {
                Some(v) => {
                    out.push((field, v));
                    continue;
                }
                None => break,
            },
            1 => 8,
            2 => match varint(&mut i).and_then(|len| usize::try_from(len).ok()) {
                Some(len) => len,
                None => break,
            },
            5 => 4,
            _ => break,
        };
        match i.checked_add(skip) {
            Some(next) => i = next,
            None => break,
        }
    }
    out
}

/// Buttons held down in one notification; `None` for non-button messages.
pub fn decode(msg: &[u8]) -> Option<Buttons> {
    use Button::*;
    let (&kind, body) = msg.split_first()?;
    let f = proto_varints(body);
    let get = |n: u32| f.iter().find(|(k, _)| *k == n).map(|(_, v)| *v);
    let on = |cond: bool, b: Button| if cond { b.bit() } else { 0 };
    let mask = match kind {
        // Click: {1: plus, 2: minus}, 0 = pressed
        0x37 => on(get(1) == Some(0), ShiftUp) | on(get(2) == Some(0), ShiftDown),
        // Play: {1: pad (0 right, 1 left), 2: Y/up, 3: Z/left, 4: A/right, 5: B/down, 6: shift, 7: on}
        0x07 => {
            let right = get(1).unwrap_or(0) == 0;
            let p = |n: u32| get(n) == Some(0);
            if right {
                on(p(2), Y) | on(p(3), Z) | on(p(4), A) | on(p(5), B) | on(p(6), ShiftUp) | on(p(7), PowerUp)
            } else {
                on(p(2), Up) | on(p(3), Left) | on(p(4), Right) | on(p(5), Down) | on(p(6), ShiftDown) | on(p(7), OnOff)
            }
        }
        // Ride (and Click v2): {1: button bitmap, bit cleared = pressed}
        0x23 => {
            let map = get(1)? as u32;
            let d = |m: u32| map & m == 0;
            on(d(RIDE_SHIFT_UP_L) || d(RIDE_SHIFT_UP_R), ShiftUp)
                | on(d(RIDE_SHIFT_DN_L) || d(RIDE_SHIFT_DN_R), ShiftDown)
                | on(d(RIDE_UP), Up)
                | on(d(RIDE_DOWN), Down)
                | on(d(RIDE_LEFT), Left)
                | on(d(RIDE_RIGHT), Right)
                | on(d(RIDE_A), A)
                | on(d(RIDE_B), B)
                | on(d(RIDE_Y), Y)
                | on(d(RIDE_Z), Z)
                | on(d(RIDE_POWERUP_L) || d(RIDE_POWERUP_R), PowerUp)
                | on(d(RIDE_ONOFF_L) || d(RIDE_ONOFF_R), OnOff)
        }
        _ => return None,
    };
    Some(Buttons(mask))
}

/// Battery level in percent from a Zwift battery notification (type 0x19), `None` otherwise.
pub fn battery(msg: &[u8]) -> Option<u8> {
    let (&0x19, body) = msg.split_first()? else { return None };
    let level = proto_varints(body).into_iter().find(|(k, _)| *k == 1)?.1;
    u8::try_from(level).ok().filter(|l| *l <= 100)
}

/// The raw Zwift Ride button bitmap (bit cleared = pressed), for diagnostics.
pub fn ride_bitmap(msg: &[u8]) -> Option<u32> {
    let (&0x23, body) = msg.split_first()? else { return None };
    proto_varints(body).into_iter().find(|(k, _)| *k == 1).map(|(_, v)| v as u32)
}

/// Turns "buttons held" notifications into presses: each press is reported once, when the
/// button goes down, however many notifications repeat it while held.
#[derive(Default, Debug)]
pub struct PressDetector {
    held: Buttons,
}

impl PressDetector {
    /// Feed one notification; returns the buttons newly pressed by it.
    pub fn feed(&mut self, msg: &[u8]) -> Buttons {
        let Some(now) = decode(msg) else { return Buttons::default() };
        let pressed = Buttons(now.0 & !self.held.0);
        self.held = now;
        pressed
    }
}

#[cfg(test)]
mod tests {
    use super::Button::*;
    use super::*;

    fn bits(bs: &[Button]) -> Option<Buttons> {
        Some(Buttons(bs.iter().fold(0, |m, b| m | b.bit())))
    }

    fn ride(v: u32) -> Vec<u8> {
        let mut out = vec![0x23, 0x08];
        let mut v = v as u64;
        loop {
            let b = (v & 0x7f) as u8;
            v >>= 7;
            if v == 0 {
                out.push(b);
                break;
            }
            out.push(b | 0x80);
        }
        out
    }

    #[test]
    fn handshake_types() {
        assert_eq!(handshake_with_response(false, true), vec![false]);
        assert_eq!(handshake_with_response(true, false), vec![true]);
        assert_eq!(handshake_with_response(true, true), vec![false, true]);
    }

    #[test]
    fn click_plus_minus() {
        assert_eq!(decode(&[0x37, 0x08, 0x00, 0x10, 0x01]), bits(&[ShiftUp]));
        assert_eq!(decode(&[0x37, 0x08, 0x01, 0x10, 0x00]), bits(&[ShiftDown]));
        assert_eq!(decode(&[0x37, 0x08, 0x01, 0x10, 0x01]), bits(&[]));
    }

    #[test]
    fn ride_bitmap() {
        assert_eq!(decode(&ride(0xFFFF_FFFF)), bits(&[]));
        assert_eq!(decode(&ride(!RIDE_SHIFT_UP_R)), bits(&[ShiftUp]));
        assert_eq!(decode(&ride(!RIDE_SHIFT_DN_L)), bits(&[ShiftDown]));
        assert_eq!(decode(&ride(!RIDE_LEFT)), bits(&[Left]));
        assert_eq!(decode(&ride(!(RIDE_A | RIDE_RIGHT))), bits(&[A, Right]));
        assert_eq!(decode(&ride(!RIDE_POWERUP_R)), bits(&[PowerUp]));
        assert_eq!(decode(&ride(!RIDE_ONOFF_L)), bits(&[OnOff]));
    }

    #[test]
    fn play_pads() {
        assert_eq!(
            decode(&[0x07, 0x08, 0x00, 0x10, 0x01, 0x18, 0x01, 0x20, 0x00, 0x28, 0x01, 0x30, 0x01]),
            bits(&[A])
        );
        assert_eq!(decode(&[0x07, 0x08, 0x01, 0x30, 0x00]), bits(&[ShiftDown]));
        assert_eq!(decode(&[0x07, 0x08, 0x00, 0x30, 0x00]), bits(&[ShiftUp]));
    }

    #[test]
    fn controller_detection() {
        assert!(is_controller(&[], true));
        assert!(is_controller(&[SERVICE_RIDE], false));
        assert!(is_controller(&[SERVICE], false));
        assert!(!is_controller(&[crate::ftms::SERVICE], false));
    }

    #[test]
    fn models() {
        assert_eq!(Model::from_type_byte(Some(0x08)), Model::RideLeft);
        assert!(Model::RideLeft.connectable());
        assert!(!Model::from_type_byte(Some(0x07)).connectable());
        assert_eq!(Model::from_type_byte(None), Model::Unknown);
    }

    #[test]
    fn non_button() {
        assert_eq!(decode(&[0x19, 0x08, 0x64]), None);
        assert_eq!(decode(&[]), None);
    }

    #[test]
    fn malformed_messages_terminate() {
        // length-delimited field whose length wraps the index back to 0
        let mut wrap = vec![0x0a, 0xF5];
        wrap.extend([0xFF; 8]);
        wrap.push(0x01);
        assert_eq!(proto_varints(&wrap), vec![]);
        let mut msg = vec![0x23];
        msg.extend(&wrap);
        assert_eq!(decode(&msg), None);
        // truncated inputs: varint without end, fixed64 / fixed32 / bytes past the end
        assert_eq!(proto_varints(&[0x08, 0x80]), vec![]);
        assert_eq!(proto_varints(&[0x08, 0x01, 0x09, 0x01]), vec![(1, 1)]);
        assert_eq!(proto_varints(&[0x0d, 0x01, 0x10, 0x02]), vec![]);
        assert_eq!(proto_varints(&[0x0a, 0x05, 0x01]), vec![]);
        // over-long varint (more than 64 bits)
        assert_eq!(
            proto_varints(&[0x08, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01]),
            vec![]
        );
    }

    #[test]
    fn ride_without_bitmap() {
        assert_eq!(decode(&[0x23]), None);
        assert_eq!(decode(&[0x23, 0x10, 0x00]), None);
        assert_eq!(decode(&[0x23, 0x08]), None);
        // analog paddle data (field 2, nested) before the bitmap: its inner field 1 isn't the bitmap
        let mut msg = vec![0x23, 0x12, 0x04, 0x08, 0x00, 0x10, 0x00];
        msg.extend(&ride(!RIDE_SHIFT_UP_L)[1..]);
        assert_eq!(decode(&msg), bits(&[ShiftUp]));
    }

    #[test]
    fn presses_are_reported_once_while_held() {
        let mut p = PressDetector::default();
        assert_eq!(p.feed(&ride(!RIDE_A)), Buttons(A.bit()), "A goes down");
        assert_eq!(p.feed(&ride(!RIDE_A)), Buttons(0), "still held");
        assert_eq!(p.feed(&ride(!(RIDE_A | RIDE_UP))), Buttons(Up.bit()), "Up added while A held");
        assert_eq!(p.feed(&ride(0xFFFF_FFFF)), Buttons(0), "all released");
        assert_eq!(p.feed(&ride(!RIDE_A)), Buttons(A.bit()), "A pressed again");
        assert_eq!(p.feed(&[0x19, 0x08, 0x64]), Buttons(0), "non-button message changes nothing");
        assert_eq!(p.feed(&ride(!RIDE_A)), Buttons(0));
    }

    #[test]
    fn ride_z_from_real_capture() {
        // captured from a Zwift Ride: Z pressed, then released (with the 4 analog paddle fields)
        let tail = "1a04080010001a04080110001a04080210001a0408031000";
        let hex = |s: &str| (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect::<Vec<_>>();
        let pressed = hex(&format!("2308fffeffff0f{tail}"));
        let released = hex(&format!("2308ffffffff0f{tail}"));
        assert_eq!(decode(&pressed), bits(&[Z]));
        assert_eq!(decode(&released), bits(&[]));
        let mut p = PressDetector::default();
        assert_eq!(p.feed(&pressed), Buttons(Z.bit()));
        assert_eq!(p.feed(&released), Buttons(0));
    }

    #[test]
    fn battery_level() {
        assert_eq!(battery(&[0x19, 0x08, 0x64]), Some(100));
        assert_eq!(battery(&[0x19, 0x08, 0x2a]), Some(42));
        assert_eq!(battery(&[0x19, 0x08, 0xc8, 0x01]), None, "over 100 is not a percentage");
        assert_eq!(battery(&[0x19]), None);
        assert_eq!(battery(&[0x23, 0x08, 0x64]), None);
    }

    #[test]
    fn raw_ride_bitmap() {
        assert_eq!(super::ride_bitmap(&ride(!RIDE_Z)), Some(!RIDE_Z));
        assert_eq!(super::ride_bitmap(&[0x37, 0x08, 0x00]), None);
        assert_eq!(super::ride_bitmap(&[]), None);
    }

    #[test]
    fn buttons_iterate_in_order() {
        let b = Buttons(A.bit() | ShiftUp.bit());
        assert_eq!(b.iter().collect::<Vec<_>>(), vec![ShiftUp, A]);
    }
}
