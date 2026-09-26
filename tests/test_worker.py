import pytest

from worker.worker import Worker


def test_worker_scan_is_stub():
    with pytest.raises(NotImplementedError):
        Worker().scan("/tmp")


def test_worker_parse_is_stub():
    with pytest.raises(NotImplementedError):
        Worker().parse("deadbeef")


def test_worker_index_is_stub():
    with pytest.raises(NotImplementedError):
        Worker().index("deadbeef")
