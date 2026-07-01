from __future__ import annotations

from unittest.mock import MagicMock


class _TestExit(BaseException):
    """BaseException so it is NOT caught by 'except Exception' in run_ingestion_forever."""


def test_run_ingestion_forever_calls_run_once_in_loop():
    from ingestion import run_ingestion_forever

    ingester = MagicMock()
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise _TestExit

    ingester.run_once.side_effect = side_effect

    try:
        run_ingestion_forever(ingester)
    except _TestExit:
        pass

    assert ingester.run_once.call_count >= 3


def test_run_ingestion_forever_continues_on_exception():
    from ingestion import run_ingestion_forever

    ingester = MagicMock()
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")
        if call_count >= 3:
            raise _TestExit

    ingester.run_once.side_effect = side_effect

    try:
        run_ingestion_forever(ingester)
    except _TestExit:
        pass

    assert ingester.run_once.call_count >= 3


def test_ingestion_module_has_main_guard():
    import ast
    import pathlib

    src = pathlib.Path(__file__).parents[2] / "src" / "ingestion.py"
    tree = ast.parse(src.read_text())
    has_main = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in ast.walk(tree)
    )
    assert has_main, "ingestion.py must have an if __name__ == '__main__' guard"
