//! Exercise the real `trampoline` and `futex_helper` by cloning children with a
//! stack image built exactly as native-abi.md §4-§6 describe, then driving the
//! futex EOF mechanism by hand. Uses raw syscalls only (no libc clone wrapper),
//! which is the model the client itself uses.

use core::ffi::c_void;
use core::sync::atomic::{AtomicU32, Ordering};
use rsyscall_core::arch::x86_64::{futex_helper, raw_syscall7, trampoline};

// x86-64 syscall numbers for the harness (public kernel ABI).
const SYS_CLONE: i64 = 56;
const SYS_WAIT4: i64 = 61;
const SYS_KILL: i64 = 62;
const SYS_FUTEX: i64 = 202;

// clone flags (vectors/v0.json clone_args.constants; native-abi.md §5).
const CLONE_VM: i64 = 0x100;
const CLONE_FILES: i64 = 0x400;
const SIGCHLD: i64 = 17;

// signals / futex ops / wait options.
const SIGCONT: i64 = 18;
const SIGSTOP: i32 = 19;
const FUTEX_WAIT: i64 = 0;
const FUTEX_WAKE: i64 = 1;
const WUNTRACED: i64 = 2;

#[repr(align(16))]
struct Arena([u8; 8192]);

/// Write the 64-byte stack image at `image` (native-abi.md §4): trampoline address,
/// six register slots, then the target function address.
unsafe fn write_image(image: *mut u8, tramp: u64, regs: [u64; 6], func: u64) {
    let w = image as *mut u64;
    unsafe {
        w.write(tramp);
        for i in 0..6 {
            w.add(1 + i).write(regs[i]);
        }
        w.add(7).write(func); // offset 56
    }
}

fn wait_for(pid: i64, options: i64) -> (i64, i32) {
    let mut status: i32 = 0;
    loop {
        let r = raw_syscall7(
            pid,
            (&mut status as *mut i32) as usize as i64,
            options,
            0, // rusage
            0,
            0,
            SYS_WAIT4,
        );
        if r == -4 {
            continue; // EINTR
        }
        return (r, status);
    }
}

fn wifexited(s: i32) -> bool {
    (s & 0x7f) == 0
}
fn wexitstatus(s: i32) -> i32 {
    (s >> 8) & 0xff
}
fn wifstopped(s: i32) -> bool {
    (s & 0xff) == 0x7f
}
fn wstopsig(s: i32) -> i32 {
    (s >> 8) & 0xff
}

extern "C" fn returns_42() -> i32 {
    42
}

#[test]
fn trampoline_enters_target_and_exits_with_its_status() {
    let mut arena = Box::new(Arena([0u8; 8192]));
    let base = arena.0.as_mut_ptr();
    // 16-byte-aligned image near the top; the child's stack grows down into the
    // 4096 bytes below it (native-abi.md §4).
    let image = unsafe { base.add(4096) };

    let tramp = trampoline as extern "C" fn() as usize as u64;
    let func = returns_42 as extern "C" fn() -> i32 as usize as u64;
    unsafe { write_image(image, tramp, [0; 6], func) };

    let pid = raw_syscall7(
        CLONE_VM | SIGCHLD, // flags
        image as usize as i64, // child_stack
        0,                     // ptid
        0,                     // ctid
        0,                     // newtls
        0,
        SYS_CLONE,
    );
    assert!(pid > 0, "clone failed: {pid}");

    let (r, status) = wait_for(pid, 0);
    assert_eq!(r, pid);
    assert!(wifexited(status), "expected WIFEXITED, status={status:#x}");
    assert_eq!(wexitstatus(status), 42, "trampoline must exit_group(ret & 0xff)");

    drop(arena);
}

#[test]
fn futex_helper_stops_waits_and_exits() {
    // Shared futex word (CLONE_VM makes it visible to the helper).
    let word = Box::new(AtomicU32::new(1));
    let word_addr = (&*word as *const AtomicU32) as usize as i64;

    let mut arena = Box::new(Arena([0u8; 8192]));
    let base = arena.0.as_mut_ptr();
    let image = unsafe { base.add(4096) };

    let tramp = trampoline as extern "C" fn() as usize as u64;
    let func = futex_helper as extern "C" fn(*mut c_void) as usize as u64;
    // rdi = &futex word, rsi = expected value (1) (native-abi.md §3.4).
    unsafe { write_image(image, tramp, [word_addr as u64, 1, 0, 0, 0, 0], func) };

    let pid = raw_syscall7(
        CLONE_VM | CLONE_FILES | SIGCHLD, // helper flags (0x511; native-abi.md §5)
        image as usize as i64,
        0,
        0,
        0,
        0,
        SYS_CLONE,
    );
    assert!(pid > 0, "clone failed: {pid}");

    // 1. The helper stops itself with SIGSTOP before touching the futex.
    let (r1, s1) = wait_for(pid, WUNTRACED);
    assert_eq!(r1, pid);
    assert!(wifstopped(s1), "expected WIFSTOPPED, status={s1:#x}");
    assert_eq!(wstopsig(s1), SIGSTOP, "must stop with SIGSTOP");

    // 2. Continue it; it will FUTEX_WAIT on the word (still == 1).
    let rc = raw_syscall7(pid, SIGCONT, 0, 0, 0, 0, SYS_KILL);
    assert_eq!(rc, 0, "kill(SIGCONT) failed: {rc}");

    // 3. Emulate the kernel's CLONE_CHILD_CLEARTID wake: clear the word, then wake.
    word.store(0, Ordering::SeqCst);
    let woken = raw_syscall7(word_addr, FUTEX_WAKE, 1, 0, 0, 0, SYS_FUTEX);
    assert!(woken >= 0, "FUTEX_WAKE failed: {woken}");

    // 4. The helper re-checks (word 0 != expected 1) and exits 0.
    let (r2, s2) = wait_for(pid, 0);
    assert_eq!(r2, pid);
    assert!(wifexited(s2), "expected WIFEXITED, status={s2:#x}");
    assert_eq!(wexitstatus(s2), 0, "helper must exit 0");

    // FUTEX_WAIT with the current op value must be 0 (no FUTEX_PRIVATE_FLAG),
    // matching the op the helper issues.
    assert_eq!(FUTEX_WAIT, 0);

    drop(arena);
    drop(word);
}
