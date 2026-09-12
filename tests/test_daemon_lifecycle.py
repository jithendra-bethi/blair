from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from blair.config import _atomic_json_write
from blair.daemon import _remove_daemon_record, daemon_pid


def write_record(home: Path, **values) -> Path:
    path = home / "runtime" / "daemon.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, {"pid": os.getpid(), "instance_id": "old", **values})
    return path


def test_shutdown_waits_until_status_reader_closes_file(tmp_path, monkeypatch):
    path = write_record(tmp_path)
    opened, release, cleaning = threading.Event(), threading.Event(), threading.Event()
    errors, statuses = [], []
    original_read = Path.read_text

    def held_read(candidate, *args, **kwargs):
        if candidate == path and threading.current_thread().name == "status-reader":
            with candidate.open("r", encoding="utf-8") as stream:
                opened.set()
                assert release.wait(timeout=5)
                return stream.read()
        return original_read(candidate, *args, **kwargs)

    def read_status():
        try:
            statuses.append(daemon_pid(tmp_path))
        except BaseException as exc:
            errors.append(exc)

    def cleanup():
        cleaning.set()
        try:
            _remove_daemon_record(tmp_path, "old")
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(Path, "read_text", held_read)
    reader = threading.Thread(target=read_status, name="status-reader")
    cleaner = threading.Thread(target=cleanup)
    reader.start()
    try:
        assert opened.wait(timeout=3)
        cleaner.start()
        assert cleaning.wait(timeout=3)
        cleaner.join(timeout=0.1)
        assert cleaner.is_alive(), "Cleanup must wait for the open status reader"
        assert path.exists()
    finally:
        release.set()
        reader.join(timeout=3)
        if cleaner.ident is not None:
            cleaner.join(timeout=3)
    assert not reader.is_alive() and not cleaner.is_alive()
    assert errors == []
    assert statuses == [os.getpid()]
    assert not path.exists()


def test_old_service_cleanup_preserves_replacement_with_same_pid(tmp_path):
    path = write_record(tmp_path, instance_id="replacement")
    _remove_daemon_record(tmp_path, "old")
    assert json.loads(path.read_text())["instance_id"] == "replacement"
    _remove_daemon_record(tmp_path, "replacement")
    assert not path.exists()


def test_repeated_cleanup_is_harmless(tmp_path):
    write_record(tmp_path)
    _remove_daemon_record(tmp_path, "old")
    _remove_daemon_record(tmp_path, "old")
    assert daemon_pid(tmp_path) is None


@pytest.mark.parametrize("content", ['{"pid": -1}', "{invalid", "[]"])
def test_status_cleans_invalid_or_dead_records(tmp_path, content):
    path = write_record(tmp_path)
    path.write_text(content)
    assert daemon_pid(tmp_path) is None
    assert not path.exists()


def test_unreadable_record_is_not_deleted_or_reported_as_stopped(tmp_path, monkeypatch):
    path = write_record(tmp_path)
    original = Path.read_text

    def unreadable(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("Temporary read failure")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(PermissionError, match="Temporary read failure"):
        daemon_pid(tmp_path)
    assert path.exists()
