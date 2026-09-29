/*
 * rsyscall.h -- C ABI of the rsyscall native side (native-abi.md §2).
 *
 * Clean-room from docs/spec. Included by the cffi preamble (python/ffibuilder.py)
 * AFTER the system headers, in one translation unit; cffi API mode checks these
 * complete struct definitions against the C compiler's view. Field names, types
 * and order match the cdef exactly, so the layouts are those of
 * abi-layouts.generated.md.
 *
 * This header MUST NOT define linux_dirent64, kernel_sigset, kernel_sigaction,
 * fdpair, futex_node, robust_list or robust_list_head, and MUST NOT add macros or
 * typedefs that could collide with the system headers included before it
 * (native-abi.md §2).
 */
#ifndef RSYSCALL_H
#define RSYSCALL_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The trampoline stack image, minus the leading trampoline address
 * (native-abi.md §4). sizeof = 56. */
struct rsyscall_trampoline_stack {
	int64_t rdi;
	int64_t rsi;
	int64_t rdx;
	int64_t rcx;
	int64_t r8;
	int64_t r9;
	void *function;
};

/* A request on the syscall socket (wire-protocol.md §2). sizeof = 56. */
struct rsyscall_syscall {
	int64_t sys;
	int64_t args[6];
};

/* Absolute run-time addresses of the four entry points (native-abi.md §8).
 * sizeof = 32. */
struct rsyscall_symbol_table {
	void *rsyscall_server;
	void *rsyscall_persistent_server;
	void *rsyscall_futex_helper;
	void *rsyscall_trampoline;
};

/* Describe struct written by rsyscall-bootstrap (bootstrap-handshakes.md §2).
 * sizeof = 56. */
struct rsyscall_bootstrap {
	struct rsyscall_symbol_table symbols;
	pid_t pid;
	int listening_sock;
	int syscall_sock;
	int data_sock;
	size_t envp_count;
};

/* Describe struct written by rsyscall-stdin-bootstrap
 * (bootstrap-handshakes.md §3). sizeof = 64. */
struct rsyscall_stdin_bootstrap {
	struct rsyscall_symbol_table symbols;
	pid_t pid;
	int syscall_fd;
	int data_fd;
	int futex_memfd;
	int connecting_fd;
	size_t envp_count;
};

/* Describe struct written by rsyscall-unix-stub (bootstrap-handshakes.md §4).
 * sizeof = 80. */
struct rsyscall_unix_stub {
	struct rsyscall_symbol_table symbols;
	pid_t pid;
	int syscall_fd;
	int data_fd;
	int futex_memfd;
	int connecting_fd;
	size_t argc;
	size_t envp_count;
	uint64_t sigmask;
};

/* The five symbols (native-abi.md §3). rsyscall_raw_syscall is declared as a
 * function; the other four are used only as function pointers by the client, and
 * an ordinary prototype satisfies the const function-pointer cdef. */
long rsyscall_raw_syscall(long arg1, long arg2, long arg3, long arg4, long arg5, long arg6, long sys);
int rsyscall_server(int infd, int outfd);
int rsyscall_persistent_server(int infd, int outfd, int listensock);
void rsyscall_futex_helper(void *futex_addr);
void rsyscall_trampoline(void);

#ifdef __cplusplus
}
#endif

#endif /* RSYSCALL_H */
