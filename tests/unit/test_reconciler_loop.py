from __future__ import annotations

import logging

import pytest

from reconciler import run_reconciler_forever


class _StopTest(BaseException):
    """Breaks out of the loop without being caught by the reconciler's except Exception."""


class _FakeSession:
    def __init__(self, *, raise_on_call: int | None = None) -> None:
        self.calls: list[str] = []
        self._raise_on_call = raise_on_call

    def authenticate(self) -> None:
        self.calls.append("authenticate")
        if self._raise_on_call is not None and len(self.calls) == self._raise_on_call:
            raise RuntimeError("auth failed")


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
        run_reconciler_forever(_FailOnce(), _FakeSession(), _FakeClock(), logging.getLogger("test"))

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
        run_reconciler_forever(_CountingUseCase(), _FakeSession(), _FakeClock(), logging.getLogger("test"))

    assert all(s == 60 for s in slept)
    assert len(slept) == 2


def test_reconciler_authenticates_before_each_execute():
    events: list[str] = []
    cycles = 0

    class _TrackingSession:
        def authenticate(self) -> None:
            events.append("auth")

    class _TrackingUseCase:
        def execute(self) -> None:
            nonlocal cycles
            events.append("execute")
            cycles += 1
            if cycles >= 2:
                raise _StopTest("stop")

    class _FakeClock:
        def sleep(self, seconds: float) -> None:
            pass

    with pytest.raises(_StopTest):
        run_reconciler_forever(_TrackingUseCase(), _TrackingSession(), _FakeClock(), logging.getLogger("test"))

    assert events == ["auth", "execute", "auth", "execute"]


def test_reconciler_skips_execute_when_authenticate_raises():
    execute_calls = 0

    class _TrackingUseCase:
        def execute(self) -> None:
            nonlocal execute_calls
            execute_calls += 1
            raise _StopTest("stop after first success")

    class _FakeClock:
        def sleep(self, seconds: float) -> None:
            pass

    with pytest.raises(_StopTest):
        run_reconciler_forever(
            _TrackingUseCase(),
            _FakeSession(raise_on_call=1),
            _FakeClock(),
            logging.getLogger("test"),
        )

    assert execute_calls == 1
