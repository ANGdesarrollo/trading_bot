from __future__ import annotations

import logging

import pytest

from reconciler import run_reconciler_forever


class _StopTest(BaseException):
    """Breaks out of the loop without being caught by the reconciler's except Exception."""


def test_reconciler_loop_catches_exception_and_continues():
    call_count = 0

    class _FailOnce:
        def execute(self) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("use case exploded")
            raise _StopTest("stop")

    slept: list[float] = []

    class _FakeClock:
        def sleep(self, seconds: float) -> None:
            slept.append(seconds)

    with pytest.raises(_StopTest):
        run_reconciler_forever(_FailOnce(), _FakeClock(), logging.getLogger("test"))

    assert call_count == 2


def test_reconciler_loop_sleeps_before_each_cycle():
    iterations = 0

    class _CountingUseCase:
        def execute(self) -> None:
            nonlocal iterations
            iterations += 1
            if iterations >= 2:
                raise _StopTest("stop")

    slept: list[float] = []

    class _FakeClock:
        def sleep(self, seconds: float) -> None:
            slept.append(seconds)

    with pytest.raises(_StopTest):
        run_reconciler_forever(_CountingUseCase(), _FakeClock(), logging.getLogger("test"))

    assert all(s == 60 for s in slept)
    assert len(slept) == 2
