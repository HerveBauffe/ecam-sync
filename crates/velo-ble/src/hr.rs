//! Heart Rate service (0x180D).

use crate::{u16le, uuid16};
use uuid::Uuid;

pub const SERVICE: Uuid = uuid16(0x180d);
pub const MEASUREMENT: Uuid = uuid16(0x2a37);

/// Heart Rate Measurement (0x2A37) in bpm. `None` for a malformed value or 0 bpm (no skin
/// contact), so the UI lets the last value go stale instead of recording zeros.
pub fn parse(v: &[u8]) -> Option<u16> {
    let flags = *v.first()?;
    let hr = if flags & 1 != 0 { u16le(v, 1)? } else { u16::from(*v.get(1)?) };
    (hr > 0).then_some(hr)
}

#[cfg(test)]
mod tests {
    use super::parse;

    #[test]
    fn heart_rate_formats() {
        assert_eq!(parse(&[0x00, 0x8c]), Some(140), "uint8");
        assert_eq!(parse(&[0x01, 0x2c, 0x01]), Some(300), "uint16");
        assert_eq!(parse(&[0x00, 0x00]), None, "no contact");
        assert_eq!(parse(&[0x01, 0x2c]), None, "truncated");
        assert_eq!(parse(&[]), None);
    }
}
