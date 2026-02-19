# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import errno
import os

import pytest

from snap_singleton import SingletonSnapManager


@pytest.fixture(autouse=True)
def lock_dir(monkeypatch, tmp_path):
    """Fixture to set up a temporary lock directory for tests."""
    lock_dir = tmp_path / "lock_dir"
    lock_dir.mkdir()
    monkeypatch.setattr(SingletonSnapManager, "LOCK_DIR", lock_dir)
    yield lock_dir


def test_register_unregister():
    """Test registering and unregistering a unit."""
    unit_name = "unit-0"
    snap_name = "generic-exporter"
    manager = SingletonSnapManager(unit_name)

    manager.register(snap_name)
    assert unit_name in manager.get_units(snap_name)
    manager.unregister(snap_name)
    assert unit_name not in manager.get_units(snap_name)


def test_register_unregister_multiple_units():
    """Test registering and unregistering multiple units."""
    unit_one = "unit-0"
    unit_two = "unit-1"
    snap_name = "generic-exporter"
    manager_one = SingletonSnapManager(unit_one)
    manager_two = SingletonSnapManager(unit_two)

    manager_one.register(snap_name)
    manager_two.register(snap_name)
    assert unit_one in manager_one.get_units(snap_name)
    assert unit_two in manager_one.get_units(snap_name)
    assert unit_one in manager_two.get_units(snap_name)
    assert unit_two in manager_two.get_units(snap_name)

    manager_one.unregister(snap_name)
    assert unit_one not in manager_one.get_units(snap_name)
    assert unit_one not in manager_two.get_units(snap_name)


def test_unregister_without_register():
    """Test unregistering a unit that was not registered."""
    unit_name = "unit-0"
    snap_name = "generic-exporter"
    manager = SingletonSnapManager(unit_name)

    with pytest.raises(FileNotFoundError):
        manager.unregister(snap_name)


def test_is_used_by_other_units(lock_dir):
    """Test checking if a snap is used by other units."""
    unit_one = "unit-0"
    unit_two = "unit-1"
    snap_name = "generic-exporter"
    snap_name_other = "other-snap"
    manager_one = SingletonSnapManager(unit_one)
    manager_two = SingletonSnapManager(unit_two)

    manager_one.register(snap_name)
    manager_one.register(snap_name_other)
    assert manager_two.is_used_by_other_units(snap_name) is True
    manager_one.unregister(snap_name)
    assert manager_two.is_used_by_other_units(snap_name) is False


def test_ensure_lock_dir_exists_error(monkeypatch):
    """Test that an OSError other than EEXIST is raised."""
    def mock_makedirs(path, exist_ok):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "makedirs", mock_makedirs)

    with pytest.raises(OSError) as exc_info:
        SingletonSnapManager._ensure_lock_dir_exists()
    assert exc_info.value.errno == 13

def test_ensure_lock_dir_exists_eexist(monkeypatch):
    """Test that OSError with EEXIST is ignored."""
    def mock_makedirs(path, exist_ok):
        raise OSError(errno.EEXIST, "File exists")

    monkeypatch.setattr(os, "makedirs", mock_makedirs)

    # Should not raise an exception
    SingletonSnapManager._ensure_lock_dir_exists()
