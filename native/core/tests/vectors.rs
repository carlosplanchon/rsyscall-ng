//! Byte-exact conformance against docs/spec/vectors/v0.json and the struct layouts
//! of abi-layouts.generated.md. Only the M1-relevant vectors are checked here;
//! describe-struct, cmsg-array and persistent-handshake vectors arrive with their
//! milestones.

use core::mem::{align_of, offset_of, size_of};
use rsyscall_core::sys::{Cmsghdr, FutexNode, Iovec, Msghdr, RobustList, SockaddrUn};
use rsyscall_core::wire::{encode_response, Request, TrampolineStack, REQUEST_LEN, RESPONSE_LEN};
use serde::Deserialize;

#[derive(Deserialize)]
struct VectorsFile {
    vectors: Vec<Vector>,
}

#[derive(Deserialize)]
struct Vector {
    name: String,
    hex: Option<String>,
}

fn load() -> VectorsFile {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../docs/spec/vectors/v0.json");
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {path}: {e}"));
    serde_json::from_str(&text).expect("parse v0.json")
}

/// Bytes of a vector, dropping the ` | ` field separators and spaces.
fn hex_of(vf: &VectorsFile, name: &str) -> Vec<u8> {
    let v = vf
        .vectors
        .iter()
        .find(|v| v.name == name)
        .unwrap_or_else(|| panic!("vector {name} not found"));
    let hex = v.hex.as_ref().unwrap_or_else(|| panic!("vector {name} has null hex"));
    hex.split_whitespace()
        .filter(|t| *t != "|")
        .map(|t| u8::from_str_radix(t, 16).unwrap_or_else(|_| panic!("bad hex token {t:?} in {name}")))
        .collect()
}

fn struct_bytes<T>(v: &T) -> Vec<u8> {
    // SAFETY: reading the initialised bytes of a `#[repr(C)]` value; callers zero
    // any padding first so every byte is defined.
    unsafe { core::slice::from_raw_parts((v as *const T) as *const u8, size_of::<T>()) }.to_vec()
}

#[test]
fn struct_layouts_match_abi() {
    // struct rsyscall_syscall: 56, args at 8.
    assert_eq!(size_of::<Request>(), 56);
    assert_eq!(offset_of!(Request, args), 8);
    assert_eq!(REQUEST_LEN, 56);
    assert_eq!(RESPONSE_LEN, 8);

    // struct rsyscall_trampoline_stack: 56, function at 48.
    assert_eq!(size_of::<TrampolineStack>(), 56);
    assert_eq!(offset_of!(TrampolineStack, function), 48);

    // struct iovec: 16.
    assert_eq!(size_of::<Iovec>(), 16);
    assert_eq!(offset_of!(Iovec, iov_len), 8);

    // struct msghdr: 56.
    assert_eq!(size_of::<Msghdr>(), 56);
    assert_eq!(offset_of!(Msghdr, msg_namelen), 8);
    assert_eq!(offset_of!(Msghdr, msg_iov), 16);
    assert_eq!(offset_of!(Msghdr, msg_iovlen), 24);
    assert_eq!(offset_of!(Msghdr, msg_control), 32);
    assert_eq!(offset_of!(Msghdr, msg_controllen), 40);
    assert_eq!(offset_of!(Msghdr, msg_flags), 48);

    // struct cmsghdr (mirror): 16.
    assert_eq!(size_of::<Cmsghdr>(), 16);
    assert_eq!(offset_of!(Cmsghdr, cmsg_level), 8);
    assert_eq!(offset_of!(Cmsghdr, cmsg_type), 12);

    // struct robust_list: 8; struct futex_node: 16, futex at 8.
    assert_eq!(size_of::<RobustList>(), 8);
    assert_eq!(size_of::<FutexNode>(), 16);
    assert_eq!(offset_of!(FutexNode, futex), 8);

    // struct sockaddr_un: family(2) + path(108) = 110.
    assert_eq!(size_of::<SockaddrUn>(), 110);
    assert_eq!(align_of::<SockaddrUn>(), 2);
}

#[test]
fn requests_parse_and_round_trip() {
    let vf = load();

    let check = |name: &str, sys: i64, args: [i64; 6]| {
        let bytes = hex_of(&vf, name);
        assert_eq!(bytes.len(), 56, "{name} length");
        let arr: [u8; 56] = bytes.clone().try_into().unwrap();
        let req = Request::from_bytes(&arr);
        assert_eq!(req.sys, sys, "{name} sys");
        assert_eq!(req.args, args, "{name} args");
        // round-trip: our encoder reproduces the exact bytes.
        assert_eq!(&req.to_bytes()[..], &bytes[..], "{name} round-trip");
    };

    check("request_write", 1, [1, 0x1000, 12, 0, 0, 0]);
    check("request_negative_arg", 257, [-100, 0x2000, 0, 0, 0, 0]);
    check("request_memory_write", 45, [14, 0x7f0000003000, 44, 0x100, 0, 0]);
    check("request_memory_read", 44, [14, 0x7f0000003000, 44, 0, 0, 0]);
}

#[test]
fn responses_encode() {
    let vf = load();
    assert_eq!(&encode_response(12)[..], &hex_of(&vf, "response_ok")[..]);
    assert_eq!(&encode_response(-2)[..], &hex_of(&vf, "response_enoent")[..]);
}

#[test]
fn image_layouts_match_vectors() {
    let vf = load();

    // struct rsyscall_trampoline_stack for rsyscall_server(7, 7).
    let mut ts: TrampolineStack = unsafe { core::mem::zeroed() };
    ts.rdi = 7;
    ts.rsi = 7;
    ts.function = 0x7f0000001000;
    assert_eq!(struct_bytes(&ts), hex_of(&vf, "trampoline_stack"));

    // The 64-byte stack image: trampoline address followed by the stack struct.
    let mut image = Vec::new();
    image.extend_from_slice(&0x7f0000002000u64.to_le_bytes());
    image.extend_from_slice(&struct_bytes(&ts));
    assert_eq!(image, hex_of(&vf, "stack_image"));

    // FutexNode(next=NULL, futex=1) with zero tail padding.
    let mut node: FutexNode = unsafe { core::mem::zeroed() };
    node.futex = 1;
    assert_eq!(struct_bytes(&node), hex_of(&vf, "futex_node"));

    // The cmsghdr that opens the client's SCM_RIGHTS message (first 16 bytes of
    // scm_rights_2fds): cmsg_len=24, level=SOL_SOCKET(1), type=SCM_RIGHTS(1).
    let mut cmsg: Cmsghdr = unsafe { core::mem::zeroed() };
    cmsg.cmsg_len = 24;
    cmsg.cmsg_level = 1;
    cmsg.cmsg_type = 1;
    let scm = hex_of(&vf, "scm_rights_2fds");
    assert_eq!(struct_bytes(&cmsg), &scm[..16]);
}
