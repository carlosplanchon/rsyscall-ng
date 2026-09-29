//! Freestanding C-string helpers for argv/envp (bootstrap-handshakes.md §0, §2-§4).
//!
//! No allocation, no `core::fmt`; every function is a thin, bounds-conscious walk
//! over NUL-terminated strings the kernel placed on the initial stack.

use core::marker::PhantomData;

/// Length of a NUL-terminated string.
///
/// # Safety
/// `p` must point to a readable NUL-terminated byte string.
pub unsafe fn strlen(p: *const u8) -> usize {
    let mut n = 0usize;
    // SAFETY: the caller guarantees a NUL terminator within the allocation.
    while unsafe { *p.add(n) } != 0 {
        n += 1;
    }
    n
}

/// The bytes of a NUL-terminated string, without the NUL.
///
/// # Safety
/// As for [`strlen`]; the string must stay valid for `'a`.
pub unsafe fn cstr<'a>(p: *const u8) -> &'a [u8] {
    // SAFETY: `strlen` found the terminator, so `n` bytes are readable.
    unsafe { core::slice::from_raw_parts(p, strlen(p)) }
}

/// Iterator over a NULL-terminated array of C strings (argv or envp).
pub struct CStrArray<'a> {
    p: *const *const u8,
    _m: PhantomData<&'a [u8]>,
}

impl<'a> CStrArray<'a> {
    /// # Safety
    /// `p` must be NULL or point to a NULL-terminated array of valid C strings
    /// that stay alive for `'a`.
    pub unsafe fn new(p: *const *const u8) -> CStrArray<'a> {
        CStrArray { p, _m: PhantomData }
    }
}

impl<'a> Iterator for CStrArray<'a> {
    type Item = &'a [u8];

    fn next(&mut self) -> Option<&'a [u8]> {
        if self.p.is_null() {
            return None;
        }
        // SAFETY: `new`'s contract: the array is NULL-terminated and readable.
        let s = unsafe { *self.p };
        if s.is_null() {
            return None;
        }
        // SAFETY: not at the terminator yet, so the next slot exists.
        self.p = unsafe { self.p.add(1) };
        // SAFETY: each non-NULL entry is a valid C string.
        Some(unsafe { cstr(s) })
    }
}

/// True for a well-formed `KEY=value` entry (bootstrap-handshakes.md §0: every
/// reported envp entry MUST contain `=`).
pub fn has_eq(e: &[u8]) -> bool {
    e.iter().any(|&b| b == b'=')
}

/// The reportable environment entries: those containing `=`, verbatim, in order.
///
/// # Safety
/// As for [`CStrArray::new`].
pub unsafe fn env_entries<'a>(envp: *const *const u8) -> impl Iterator<Item = &'a [u8]> {
    // SAFETY: forwarded contract.
    unsafe { CStrArray::new(envp) }.filter(|e| has_eq(e))
}

/// Number of reportable environment entries (`envp_count`).
///
/// # Safety
/// As for [`CStrArray::new`].
pub unsafe fn count_env(envp: *const *const u8) -> usize {
    // SAFETY: forwarded contract.
    unsafe { env_entries(envp) }.count()
}

/// The value of the first entry starting with `prefix` (e.g.
/// `b"RSYSCALL_UNIX_STUB_SOCK_PATH="`). The returned slice is the tail of that
/// entry, so the byte after it is the entry's NUL terminator.
///
/// # Safety
/// As for [`CStrArray::new`].
pub unsafe fn env_lookup<'a>(envp: *const *const u8, prefix: &[u8]) -> Option<&'a [u8]> {
    // SAFETY: forwarded contract.
    unsafe { CStrArray::new(envp) }
        .find(|e| e.starts_with(prefix))
        .map(|e| &e[prefix.len()..])
}

/// Decimal representation of `n` in `buf` (20 digits suffice for `u64::MAX`).
pub fn fmt_decimal(mut n: u64, buf: &mut [u8; 20]) -> &[u8] {
    let mut i = buf.len();
    loop {
        i -= 1;
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
        if n == 0 {
            break;
        }
    }
    &buf[i..]
}

/// The part of `path` after its last `/` (the program name for diagnostics,
/// bootstrap-handshakes.md §6).
pub fn basename(path: &[u8]) -> &[u8] {
    let mut start = 0;
    let mut i = 0;
    while i < path.len() {
        if path[i] == b'/' {
            start = i + 1;
        }
        i += 1;
    }
    &path[start..]
}
