"""Like the stdlib codeop module, but returning an AST instead.

This is useful because we can properly deal with `await`s at the AST level.

We lack functionality precisely equivalent to `codeop.Compile` or `codeop.CommandCompiler`,
because the AST object returned from `compile(ONLY_AST)` doesn't expose the information to
us about what `__future__` statements the compile process has seen. To properly implement
those classes, either the return value of `compile(ONLY_AST)` needs to contain that
information, or we need to reimplement the simple `__future__` statement scanner contained
in the Python core.

The detection of incomplete input follows `codeop.compile_command`, but only through the
public `compile` builtin and codeop's flag constants: codeop's private helper changed its
signature in Python 3.12 and again in 3.14.

"""
import ast
import codeop
import typing as t
import warnings

# Parse only, without implying a dedent at the end of the source, and report input that may
# still be completed by more lines as "incomplete input" rather than as a plain syntax error.
_FLAGS_INCOMPLETE_OK = (ast.PyCF_ONLY_AST | codeop.PyCF_DONT_IMPLY_DEDENT  # type: ignore
                        | codeop.PyCF_ALLOW_INCOMPLETE_INPUT)  # type: ignore

def _is_incomplete(err: SyntaxError) -> bool:
    "Whether this error means that more lines may complete the source (Python 3.12 and later)"
    return getattr(err, "msg", None) == "incomplete input"

def ast_compile_command(source: str, filename="<input>", symbol="single") -> t.Any:
    """Like codeop.compile_command, but returns an AST instead.

    Returns the AST if the source is complete, None if more lines may complete it, and raises
    SyntaxError (or OverflowError, ValueError) if it is invalid.
    """
    if symbol != "eval" and all(not line.strip() or line.strip().startswith("#")
                                for line in source.split("\n")):
        source = "pass"  # only blank lines and comments: an empty statement
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", (SyntaxWarning, DeprecationWarning))
        try:
            compile(source, filename, symbol, _FLAGS_INCOMPLETE_OK)
        except SyntaxError:
            try:
                compile(source + "\n", filename, symbol, _FLAGS_INCOMPLETE_OK)
                return None  # one more line makes it valid: wait for it
            except SyntaxError as err:
                if _is_incomplete(err):
                    return None
                # otherwise it is a real syntax error, raised by the final compile below
    return compile(source, filename, symbol, ast.PyCF_ONLY_AST)

def ast_compile_interactive(source: str) -> t.Optional[ast.Interactive]:
    "Compiles this single interactive statement into an AST"
    return ast_compile_command(source, "<input>", "single")
