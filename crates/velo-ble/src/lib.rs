//! Bluetooth LE protocol logic for velo-app: byte formats only, no I/O.
//!
//! The Bluetooth transport lives in `src-tauri` (via `tauri-plugin-blec`); this crate turns
//! notification bytes into values and values into command bytes, so all of it is unit-testable.
//!
//! FTMS and Zwift controller handling is adapted from zwo-trainer
//! (<https://github.com/steffenr/zwo-trainer>, MIT, Copyright (c) 2026 SteffenR).

pub mod battery;
pub mod ftms;
pub mod hr;
pub mod zwift;

use uuid::Uuid;

/// A 16-bit Bluetooth SIG UUID expanded onto the base UUID.
pub const fn uuid16(short: u16) -> Uuid {
    Uuid::from_u128(((short as u128) << 96) | 0x0000_0000_0000_1000_8000_0080_5f9b_34fb)
}

pub(crate) fn u16le(v: &[u8], o: usize) -> Option<u16> {
    v.get(o..o + 2).map(|b| u16::from_le_bytes([b[0], b[1]]))
}

pub(crate) fn i16le(v: &[u8], o: usize) -> Option<i16> {
    v.get(o..o + 2).map(|b| i16::from_le_bytes([b[0], b[1]]))
}

#[cfg(test)]
mod tests {
    #[test]
    fn uuid16_expands_onto_the_base_uuid() {
        assert_eq!(super::uuid16(0x1826).to_string(), "00001826-0000-1000-8000-00805f9b34fb");
    }
}
