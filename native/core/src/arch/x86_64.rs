//! x86-64 naked-assembly primitives (native-abi.md §3).
//!
//! Kernel syscall convention: `rax` = syscall number; arguments in
//! `rdi, rsi, rdx, r10, r8, r9` (`r10` replaces the C ABI's `rcx`). The `syscall`
//! instruction clobbers only `rax`, `rcx` and `r11`; every other register is
//! preserved by the kernel (a platform fact, not derived from docs/spec).
//!
//! Each primitive is emitted by a `macro_rules!` so the exact same body can be
//! instantiated twice: once here under a mangled, internal name used by the rest
//! of `rsyscall-core`, and once in the `rsyscall` cdylib under the exported C name
//! (native-abi.md §3, §9 — internal calls never go through the exported, and thus
//! interposable, symbol). The macros are `#[macro_export]`, hence reachable as
//! `rsyscall_core::define_*!` from the artefact crate.

/// `long rsyscall_raw_syscall(long a1, long a2, long a3, long a4, long a5, long a6, long sys)`
/// (native-abi.md §3.1).
///
/// The syscall number is the 7th System-V argument, passed on the stack just
/// above the return address (`[rsp+8]`). The instruction after `syscall` MUST be
/// `ret` and nothing may touch the stack after `syscall`: a `clone` child resumes
/// exactly there with `rsp` = its stack image and pops the trampoline address with
/// that `ret` (native-abi.md §3.1; wire-protocol.md §3).
#[macro_export]
macro_rules! define_raw_syscall {
    ($(#[$attr:meta])* $vis:vis $name:ident) => {
        $(#[$attr])*
        #[unsafe(naked)]
        $vis extern "C" fn $name(
            _a1: i64, _a2: i64, _a3: i64, _a4: i64, _a5: i64, _a6: i64, _sys: i64,
        ) -> i64 {
            core::arch::naked_asm!(
                "mov rax, [rsp + 8]", // sys: 7th arg, above the return address
                "mov r10, rcx",       // C's 4th arg (rcx) -> kernel's 4th arg (r10)
                "syscall",
                "ret",                // clone child resumes here; rsp = stack image
            )
        }
    };
}

/// `void rsyscall_trampoline(void)` (native-abi.md §3.5, §4).
///
/// Entered with `rsp` = image+8 (the raw-syscall `ret` already popped the
/// trampoline address at image+0). Loads the six argument registers from image
/// offsets +8..+48 and the target from +56, then enters the target as a C
/// function. After the seven pops `rsp` = image+64 (16-byte aligned), so the
/// `call` is ABI-conformant. When the target returns the process terminates with
/// `exit_group(ret & 0xff)` (status Unspecified in v0; native-abi.md §3.5
/// Recommended default).
#[macro_export]
macro_rules! define_trampoline {
    ($(#[$attr:meta])* $vis:vis $name:ident) => {
        $(#[$attr])*
        #[unsafe(naked)]
        $vis extern "C" fn $name() {
            core::arch::naked_asm!(
                "pop rdi",      // image+8
                "pop rsi",      // image+16
                "pop rdx",      // image+24
                "pop rcx",      // image+32
                "pop r8",       // image+40
                "pop r9",       // image+48
                "pop rax",      // image+56: target function address
                "call rax",     // rsp = image+64 (16-aligned): conformant
                "movzx edi, al", // exit_group(ret & 0xff)
                "mov eax, 231",
                "syscall",
                "ud2",
            )
        }
    };
}

/// `void rsyscall_futex_helper(void *futex_addr)` (native-abi.md §3.4).
///
/// Despite the one-parameter prototype it is entered (via a stack image, never a
/// direct call) with `rdi` = address of the 32-bit futex word and `rsi` = the
/// value the word is expected to hold. It stashes both in callee-saved registers,
/// stops itself with `SIGSTOP` **before** touching the futex word, and after
/// `SIGCONT` waits on the futex. It uses no stack after the stop (the client may
/// free its stack once it observes the stop). It exits when the word no longer
/// holds `expected` (kernel `CLONE_CHILD_CLEARTID` wake, or `EAGAIN`); on `EINTR`
/// or a wake with the word unchanged it re-checks and waits again
/// (native-abi.md §3.4 Recommended default). `FUTEX_WAIT` carries no
/// `FUTEX_PRIVATE_FLAG` because the kernel's CLEARTID wake is a shared wake.
#[macro_export]
macro_rules! define_futex_helper {
    ($(#[$attr:meta])* $vis:vis $name:ident) => {
        $(#[$attr])*
        #[unsafe(naked)]
        $vis extern "C" fn $name(_futex_addr: *mut core::ffi::c_void) {
            core::arch::naked_asm!(
                "mov rbx, rdi",     // rbx = &futex word (callee-saved: survives syscalls)
                "mov r12, rsi",     // r12 = expected value
                "mov eax, 186",     // gettid
                "syscall",
                "mov edi, eax",     // tid
                "mov esi, 19",      // SIGSTOP
                "mov eax, 200",     // tkill(tid, SIGSTOP) -- before touching the futex
                "syscall",
                "2:",               // re-check loop (no stack use past this point)
                "mov eax, [rbx]",   // *addr (u32)
                "cmp eax, r12d",    // still == expected?
                "jne 3f",           // no -> exit
                "mov rdi, rbx",     // futex(addr, FUTEX_WAIT, expected, NULL)
                "xor esi, esi",     // FUTEX_WAIT = 0 (no FUTEX_PRIVATE_FLAG)
                "mov edx, r12d",    // expected
                "xor r10d, r10d",   // timeout = NULL
                "mov eax, 202",     // futex
                "syscall",
                "test rax, rax",
                "je 2b",            // 0: woken -> re-check
                "cmp rax, -4",      // -EINTR
                "je 2b",            // interrupted -> re-check
                "3:",               // -EAGAIN or any other error -> exit_group(0)
                "xor edi, edi",
                "mov eax, 231",     // exit_group
                "syscall",
                "ud2",
            )
        }
    };
}

// Internal, mangled instantiations used throughout rsyscall-core (and by the
// core tests). The cdylib re-instantiates the same macros under the exported
// `rsyscall_*` names with `#[unsafe(no_mangle)]`.
define_raw_syscall!(pub raw_syscall7);
define_trampoline!(pub trampoline);
define_futex_helper!(pub futex_helper);
