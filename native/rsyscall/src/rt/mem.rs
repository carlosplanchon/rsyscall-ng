//! Freestanding `mem*` symbols the compiler may emit calls to (native-abi.md §9).
//!
//! Defined in `global_asm!` so they stay *local* to the cdylib (rustc keeps
//! globals it does not recognise out of the dynamic symbol table), which is why the
//! `.so` exports exactly the five documented symbols and nothing else. They are
//! `.weak` so they never clash with the weak `compiler_builtins` versions.
//!
//! Intel syntax (the default for Rust inline/global asm).

core::arch::global_asm!(
    ".text",

    // void *memcpy(void *dst, const void *src, size_t n)
    ".weak memcpy",
    ".p2align 4",
    "memcpy:",
    "mov rax, rdi",   // return dst
    "mov rcx, rdx",
    "rep movsb",
    "ret",

    // void *memmove(void *dst, const void *src, size_t n)
    ".weak memmove",
    ".p2align 4",
    "memmove:",
    "mov rax, rdi",   // return dst
    "cmp rdi, rsi",
    "jbe 2f",         // dst <= src: forward copy is safe
    // dst > src: copy backward to handle overlap
    "lea rdi, [rdi + rdx - 1]",
    "lea rsi, [rsi + rdx - 1]",
    "mov rcx, rdx",
    "std",
    "rep movsb",
    "cld",
    "ret",
    "2:",
    "mov rcx, rdx",
    "rep movsb",
    "ret",

    // void *memset(void *dst, int c, size_t n)
    ".weak memset",
    ".p2align 4",
    "memset:",
    "mov r8, rdi",    // save dst
    "mov rax, rsi",   // byte value in al
    "mov rcx, rdx",
    "rep stosb",
    "mov rax, r8",    // return dst
    "ret",

    // int memcmp(const void *a, const void *b, size_t n)
    ".weak memcmp",
    ".p2align 4",
    "memcmp:",
    "xor eax, eax",
    "mov rcx, rdx",
    "test rcx, rcx",
    "je 5f",
    "4:",
    "movzx r8d, byte ptr [rdi]",
    "movzx r9d, byte ptr [rsi]",
    "sub r8d, r9d",
    "jne 6f",
    "inc rdi",
    "inc rsi",
    "dec rcx",
    "jne 4b",
    "5:",
    "ret",
    "6:",
    "mov eax, r8d",   // nonzero signed difference of the first differing bytes
    "ret",

    // int bcmp(const void *a, const void *b, size_t n) -- zero iff equal
    ".weak bcmp",
    ".p2align 4",
    "bcmp:",
    "jmp memcmp",

    // size_t strlen(const char *s) -- LLVM's loop-idiom recognition turns a
    // hand-written NUL scan (rsyscall_core::cstr::strlen) into a call to this
    // symbol, so the freestanding artefacts must define it.
    ".weak strlen",
    ".p2align 4",
    "strlen:",
    "mov rax, rdi",
    "7:",
    "cmp byte ptr [rax], 0",
    "je 8f",
    "inc rax",
    "jmp 7b",
    "8:",
    "sub rax, rdi",
    "ret",
);
