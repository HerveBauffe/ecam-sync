//! Battery service (0x180F).

use crate::uuid16;
use uuid::Uuid;

pub const SERVICE: Uuid = uuid16(0x180f);
pub const LEVEL: Uuid = uuid16(0x2a19);

/// Battery Level (0x2A19): one byte, percent. `None` if empty or above 100.
pub fn parse(v: &[u8]) -> Option<u8> {
    v.first().copied().filter(|l| *l <= 100)
}

#[cfg(test)]
mod tests {
    #[test]
    fn level() {
        assert_eq!(super::parse(&[87]), Some(87));
        assert_eq!(super::parse(&[200]), None);
        assert_eq!(super::parse(&[]), None);
    }
}
