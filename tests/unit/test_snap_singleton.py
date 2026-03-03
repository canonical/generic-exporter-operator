# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import errno
import logging
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

    manager.register(snap_name, 1)
    assert unit_name in manager._get_units(snap_name)
    manager.unregister(snap_name, 1)
    assert unit_name not in manager._get_units(snap_name)


def test_register_unregister_multiple_units():
    """Test registering and unregistering multiple units."""
    unit_one = "unit-0"
    unit_two = "unit-1"
    snap_name = "generic-exporter"
    manager_one = SingletonSnapManager(unit_one)
    manager_two = SingletonSnapManager(unit_two)

    manager_one.register(snap_name, 1)
    manager_two.register(snap_name, 1)
    assert unit_one in manager_one._get_units(snap_name)
    assert unit_two in manager_one._get_units(snap_name)
    assert unit_one in manager_two._get_units(snap_name)
    assert unit_two in manager_two._get_units(snap_name)

    manager_one.unregister(snap_name, 1)
    assert unit_one not in manager_one._get_units(snap_name)
    assert unit_one not in manager_two._get_units(snap_name)


def test_unregister_without_register():
    """Test unregistering a unit that was not registered."""
    unit_name = "unit-0"
    snap_name = "generic-exporter"
    manager = SingletonSnapManager(unit_name)

    with pytest.raises(FileNotFoundError):
        manager.unregister(snap_name, 1)


def test_update_registration():
    """Test updating a registration."""
    unit_name = "unit-0"
    snap_name = "generic-exporter"
    snap_name_other = "other-snap"
    manager = SingletonSnapManager(unit_name)

    manager.register(snap_name, 1)
    manager.register(snap_name_other, 1)

    manager.update_registration(snap_name, 2)
    assert (snap_name, 2) in manager.get_snaps()
    assert (snap_name, 1) not in manager.get_snaps()
    assert len(manager.get_snaps()) == 2, "Expected two snap registrations after update"


def test_update_registration_no_change():
    """Test updating a registration with the same revision does not change it."""
    unit_name = "unit-0"
    snap_name = "generic-exporter"
    manager = SingletonSnapManager(unit_name)

    manager.register(snap_name, 1)

    manager.update_registration(snap_name, 1)
    assert (snap_name, 1) in manager.get_snaps()
    assert len(manager.get_snaps()) == 1, "Expected no change in snap registrations"


def test_update_registration_no_previous_registration():
    """Test updating a snap when other snaps exist but target snap is not yet registered."""
    unit_name = "unit-0"
    target_snap = "generic-exporter"
    other_snap_one = "other-snap-1"
    other_snap_two = "other-snap-2"

    manager = SingletonSnapManager(unit_name)

    manager.register(other_snap_one, 1)
    manager.register(other_snap_two, 2)

    manager.update_registration(target_snap, 3)

    snaps = manager.get_snaps()
    assert (other_snap_one, 1) in snaps
    assert (other_snap_two, 2) in snaps
    assert (target_snap, 3) in snaps
    assert len(snaps) == 3, "Expected three snap registrations after update"


def test_is_used_by_other_units(lock_dir):
    """Test checking if a snap is used by other units."""
    unit_one = "unit-0"
    unit_two = "unit-1"
    snap_name = "generic-exporter"
    snap_name_other = "other-snap"
    manager_one = SingletonSnapManager(unit_one)
    manager_two = SingletonSnapManager(unit_two)

    manager_one.register(snap_name, 1)
    manager_one.register(snap_name_other, 1)
    assert manager_two.is_used_by_other_units(snap_name) is True
    manager_one.unregister(snap_name, 1)
    assert manager_two.is_used_by_other_units(snap_name) is False


def test_get_snaps(lock_dir):
    """Test getting snaps for a unit."""
    unit_one = "unit-0"
    unit_two = "unit-1"
    snap_name_one = "generic-exporter"
    snap_name_two = "other-snap"
    snap_name_three = "third-snap"
    manager_one = SingletonSnapManager(unit_one)
    manager_two = SingletonSnapManager(unit_two)

    manager_one.register(snap_name_one, 1)
    manager_one.register(snap_name_two, 2)
    manager_two.register(snap_name_three, 1)
    snaps = manager_one.get_snaps()
    assert (snap_name_one, 1) in snaps
    assert (snap_name_two, 2) in snaps
    assert (snap_name_three, 1) not in snaps


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


def test_ignore_unexpected_files(lock_dir, caplog):
    """Test that unexpected files in the lock directory are ignored and logged."""
    snap_name = "generic-exporter"
    unit_one = "unit-0"
    manager = SingletonSnapManager(unit_one)

    manager.register(snap_name, snap_revision=1)

    (lock_dir / "unexpected-file").write_text("")
    with caplog.at_level(logging.DEBUG):
        units = manager._get_units(snap_name)

    assert unit_one in units
    assert len(units) == 1, "Expected only the valid unit to be returned"
    assert any(
        "unexpected format" in record.message and "unexpected-file" in record.message
        for record in caplog.records
    )
