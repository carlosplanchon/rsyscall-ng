//! The freestanding string helpers the helper executables rely on: C-string
//! walking, argv/envp iteration, the `=` rule for environment entries
//! (bootstrap-handshakes.md §0), decimal formatting, program names, errno texts,
//! the stderr diagnostic line (§6) and length-prefixed strings.

use core::ptr::null;
use rsyscall_core::cstr::{basename, count_env, cstr, env_entries, env_lookup, fmt_decimal, strlen, CStrArray};
use rsyscall_core::describe::write_lp_string;
use rsyscall_core::diag::{diag_to, errno_text};
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

/// A NULL-terminated array of NUL-terminated strings, like argv/envp.
struct CArray {
    _owned: Vec<Vec<u8>>,
    ptrs: Vec<*const u8>,
}

impl CArray {
    fn new(strs: &[&[u8]]) -> CArray {
        let owned: Vec<Vec<u8>> = strs
            .iter()
            .map(|s| {
                let mut v = s.to_vec();
                v.push(0);
                v
            })
            .collect();
        let mut ptrs: Vec<*const u8> = owned.iter().map(|v| v.as_ptr()).collect();
        ptrs.push(null());
        CArray { _owned: owned, ptrs }
    }
    fn ptr(&self) -> *const *const u8 {
        self.ptrs.as_ptr()
    }
}

fn read_exact_from(s: &mut UnixStream, n: usize) -> Vec<u8> {
    s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let mut b = vec![0u8; n];
    s.read_exact(&mut b).unwrap();
    b
}

#[test]
fn strlen_and_cstr() {
    assert_eq!(unsafe { strlen(b"hello\0".as_ptr()) }, 5);
    assert_eq!(unsafe { strlen(b"\0".as_ptr()) }, 0);
    assert_eq!(unsafe { cstr(b"arg two\0".as_ptr()) }, b"arg two");
    assert_eq!(unsafe { cstr(b"\0".as_ptr()) }, b"");
}

#[test]
fn cstr_array_iterates_until_null() {
    let a = CArray::new(&[b"a", b"bb", b""]);
    let items: Vec<&[u8]> = unsafe { CStrArray::new(a.ptr()) }.collect();
    assert_eq!(items, vec![&b"a"[..], &b"bb"[..], &b""[..]]);
    assert_eq!(unsafe { CStrArray::new(null()) }.count(), 0);
    let empty = CArray::new(&[]);
    assert_eq!(unsafe { CStrArray::new(empty.ptr()) }.count(), 0);
}

#[test]
fn env_entries_require_an_equals_sign() {
    let e = CArray::new(&[b"FOO=bar", b"NOEQ", b"EMPTY=", b"X=y=z", b"", b"PATH=/usr/bin"]);
    let got: Vec<&[u8]> = unsafe { env_entries(e.ptr()) }.collect();
    assert_eq!(got, vec![&b"FOO=bar"[..], &b"EMPTY="[..], &b"X=y=z"[..], &b"PATH=/usr/bin"[..]]);
    assert_eq!(unsafe { count_env(e.ptr()) }, 4);
}

#[test]
fn env_lookup_returns_the_nul_terminated_tail() {
    let e = CArray::new(&[b"FOO=bar", b"RSYSCALL_UNIX_STUB_SOCK_PATH=/tmp/x/stub.sock", b"BAR=1"]);
    let v = unsafe { env_lookup(e.ptr(), b"RSYSCALL_UNIX_STUB_SOCK_PATH=") }.unwrap();
    assert_eq!(v, b"/tmp/x/stub.sock");
    // the value is usable as a C string: the byte after it is the entry's NUL.
    assert_eq!(unsafe { *v.as_ptr().add(v.len()) }, 0);
    assert_eq!(unsafe { env_lookup(e.ptr(), b"MISSING=") }, None);
    let empty = CArray::new(&[b"RSYSCALL_UNIX_STUB_SOCK_PATH="]);
    assert_eq!(unsafe { env_lookup(empty.ptr(), b"RSYSCALL_UNIX_STUB_SOCK_PATH=") }, Some(&b""[..]));
}

#[test]
fn decimal_and_basename() {
    let mut b = [0u8; 20];
    assert_eq!(fmt_decimal(0, &mut b), b"0");
    assert_eq!(fmt_decimal(7, &mut b), b"7");
    assert_eq!(fmt_decimal(4242, &mut b), b"4242");
    assert_eq!(fmt_decimal(u64::MAX, &mut b), b"18446744073709551615");

    assert_eq!(basename(b"/a/b/rsyscall-unix-stub"), b"rsyscall-unix-stub");
    assert_eq!(basename(b"rsyscall-bootstrap"), b"rsyscall-bootstrap");
    assert_eq!(basename(b"./bootstrap"), b"bootstrap");
    assert_eq!(basename(b""), b"");
}

#[test]
fn errno_texts() {
    let mut b = [0u8; 40];
    assert_eq!(errno_text(2, &mut b), b"No such file or directory");
    assert_eq!(errno_text(13, &mut b), b"Permission denied");
    assert_eq!(errno_text(22, &mut b), b"Invalid argument");
    assert_eq!(errno_text(88, &mut b), b"Socket operation on non-socket");
    assert_eq!(errno_text(98, &mut b), b"Address already in use");
    assert_eq!(errno_text(111, &mut b), b"Connection refused");
    assert_eq!(errno_text(12345, &mut b), b"Unknown error 12345");
}

#[test]
fn diag_line_format() {
    let (a, mut b) = UnixStream::pair().unwrap();
    diag_to(a.as_raw_fd(), b"rsyscall-unix-stub", &[b"connect(".as_slice(), b"/x".as_slice(), b")".as_slice()], Some(2));
    let expect = b"rsyscall-unix-stub: connect(/x): No such file or directory\n";
    assert_eq!(read_exact_from(&mut b, expect.len()), expect);

    diag_to(a.as_raw_fd(), b"rsyscall-bootstrap", &[b"usage: <path> <type>".as_slice()], None);
    let expect = b"rsyscall-bootstrap: usage: <path> <type>\n";
    assert_eq!(read_exact_from(&mut b, expect.len()), expect);
}

#[test]
fn lp_string_round_trip() {
    let (a, mut b) = UnixStream::pair().unwrap();
    write_lp_string(a.as_raw_fd(), b"PATH=/bin").unwrap();
    write_lp_string(a.as_raw_fd(), b"").unwrap();
    let mut expect = Vec::new();
    expect.extend_from_slice(&9u64.to_le_bytes());
    expect.extend_from_slice(b"PATH=/bin");
    expect.extend_from_slice(&0u64.to_le_bytes());
    assert_eq!(read_exact_from(&mut b, expect.len()), expect);
}
