//! The wire codec: request struct and response encoding (wire-protocol.md §2, §4).
//!
//! All integers are little-endian two's complement (native-abi.md §1). Parsing and
//! encoding use fixed constant indices only, so no bounds check can panic in the
//! freestanding server path.

/// Length of a request on the wire (`sizeof(struct rsyscall_syscall)` = 56).
pub const REQUEST_LEN: usize = 56;
/// Length of a response on the wire (`sizeof(long)` = 8).
pub const RESPONSE_LEN: usize = 8;

/// `struct rsyscall_syscall` (abi-layouts.generated.md): a syscall number followed
/// by six 64-bit arguments.
#[repr(C)]
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Request {
    pub sys: i64,
    pub args: [i64; 6],
}

#[inline]
fn le_i64(b: &[u8; REQUEST_LEN], o: usize) -> i64 {
    i64::from_le_bytes([
        b[o], b[o + 1], b[o + 2], b[o + 3], b[o + 4], b[o + 5], b[o + 6], b[o + 7],
    ])
}

impl Request {
    /// Parse the 56 request bytes (wire-protocol.md §2).
    #[inline]
    pub fn from_bytes(b: &[u8; REQUEST_LEN]) -> Request {
        Request {
            sys: le_i64(b, 0),
            args: [
                le_i64(b, 8),
                le_i64(b, 16),
                le_i64(b, 24),
                le_i64(b, 32),
                le_i64(b, 40),
                le_i64(b, 48),
            ],
        }
    }

    /// Serialise back to 56 bytes (used by the vectors test for a round-trip check).
    #[inline]
    pub fn to_bytes(&self) -> [u8; REQUEST_LEN] {
        let mut b = [0u8; REQUEST_LEN];
        b[0..8].copy_from_slice(&self.sys.to_le_bytes());
        b[8..16].copy_from_slice(&self.args[0].to_le_bytes());
        b[16..24].copy_from_slice(&self.args[1].to_le_bytes());
        b[24..32].copy_from_slice(&self.args[2].to_le_bytes());
        b[32..40].copy_from_slice(&self.args[3].to_le_bytes());
        b[40..48].copy_from_slice(&self.args[4].to_le_bytes());
        b[48..56].copy_from_slice(&self.args[5].to_le_bytes());
        b
    }
}

/// Encode the raw kernel return value as the 8-byte response (wire-protocol.md §4).
#[inline]
pub fn encode_response(v: i64) -> [u8; RESPONSE_LEN] {
    v.to_le_bytes()
}

/// `struct rsyscall_trampoline_stack` (abi-layouts.generated.md; native-abi.md §4):
/// the six argument-register slots followed by the target function pointer. Present
/// here so the vectors test can confirm the image layout the client builds; native
/// code never writes it (the client does).
#[repr(C)]
pub struct TrampolineStack {
    pub rdi: i64,
    pub rsi: i64,
    pub rdx: i64,
    pub rcx: i64,
    pub r8: i64,
    pub r9: i64,
    pub function: u64,
}
