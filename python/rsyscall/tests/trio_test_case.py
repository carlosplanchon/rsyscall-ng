"A trio-enabled variant of unittest.TestCase"
import trio
import unittest
import contextlib
import functools
import sys
import types
import warnings
from rsyscall import local_process, Process

@contextlib.contextmanager
def raise_unraisables():
    """Re-raise "unraisable" exceptions (e.g. raised in __del__) seen inside the block

    A single unraisable exception is re-raised as-is, as trio.MultiError([x]) used to
    collapse to x; several are raised together as a BaseExceptionGroup.

    """
    unraisables = []
    try:
        orig_unraisablehook, sys.unraisablehook = sys.unraisablehook, unraisables.append
        yield
    finally:
        sys.unraisablehook = orig_unraisablehook
        if unraisables:
            excs = [unr.exc_value if unr.exc_value is not None
                    else RuntimeError(unr.err_msg or "unraisable exception", unr.object)
                    for unr in unraisables]
            if len(excs) == 1:
                raise excs[0]
            raise BaseExceptionGroup("unraisable exceptions during test", excs)

def _unwrap_single(exn: BaseException) -> BaseException:
    "Strip BaseExceptionGroup wrappers around exactly one exception (trio >= 0.25 strict nurseries)"
    while isinstance(exn, BaseExceptionGroup) and len(exn.exceptions) == 1:
        exn = exn.exceptions[0]
    return exn

class TrioTestCase(unittest.TestCase):
    "A trio-enabled variant of unittest.TestCase"
    nursery: trio.Nursery
    process: Process = local_process

    async def asyncSetUp(self) -> None:
        "Asynchronously set up resources for tests in this TestCase"
        pass

    async def asyncTearDown(self) -> None:
        "Asynchronously clean up resources for tests in this TestCase"
        pass

    @classmethod
    async def asyncSetUpClass(cls) -> None:
        "Asynchronously set up class-level resources for tests in this TestCase"
        pass

    @classmethod
    async def asyncTearDownClass(cls) -> None:
        "Asynchronously clean up class-level resources for tests in this TestCase"
        pass

    @classmethod
    def setUpClass(cls) -> None:
        trio.run(cls.asyncSetUpClass)

    @classmethod
    def tearDownClass(cls) -> None:
        trio.run(cls.asyncTearDownClass)

    def __init__(self, methodName='runTest') -> None:
        test = getattr(type(self), methodName)
        @functools.wraps(test)
        async def test_with_setup() -> None:
            async with trio.open_nursery() as nursery:
                self.nursery = nursery
                await self.asyncSetUp()
                try:
                    await test(self)
                finally:
                    await self.asyncTearDown()
                nursery.cancel_scope.cancel()
        @functools.wraps(test_with_setup)
        def sync_test_with_setup(self) -> None:
            # Throw an exception if there were any "coroutine was never awaited" warnings, to fail the test.
            # See https://github.com/python-trio/pytest-trio/issues/86
            # We also need raise_unraisables, otherwise the exception is suppressed, since it's in __del__
            with raise_unraisables():
                # Restore the old warning filter after the test.
                with warnings.catch_warnings():
                    warnings.filterwarnings('error', message='.*was never awaited', category=RuntimeWarning)
                    try:
                        trio.run(test_with_setup)
                    except BaseExceptionGroup as eg:
                        # trio >= 0.25 nurseries wrap even a single exception in an
                        # ExceptionGroup; unwrap it so tests see the original exception type.
                        exn = _unwrap_single(eg)
                        if exn is eg:
                            raise
                        raise exn from None
        setattr(self, methodName, types.MethodType(sync_test_with_setup, self))
        super().__init__(methodName)

class Test(unittest.TestCase):
    def test_coro_warning(self) -> None:
        class Test(TrioTestCase):
            async def test(self):
                trio.sleep(0)
        with self.assertRaises(RuntimeWarning):
            Test('test').test()
