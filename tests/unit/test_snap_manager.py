# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charms.operator_libs_linux.v2 import snap

from snap_manager import SnapClient


@pytest.fixture
def mock_snap_cache():
    """Mock the snap.SnapCache."""
    with patch("utils.snap.SnapCache") as mock_cache:
        yield mock_cache

@pytest.fixture
def mock_snap_add():
    """Mock the snap.add function."""
    with patch("utils.snap.add") as mock_add:
        yield mock_add

@pytest.fixture
def mock_snap_remove():
    """Mock the snap.remove function."""
    with patch("utils.snap.remove") as mock_remove:
        yield mock_remove

def test_snap_version_installed(mock_snap_cache):
    """Test retrieving snap version when installed."""
    mock_snap = MagicMock()
    mock_snap.present = True
    mock_snap.version = "1.2.3"
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    version = client.snap_version

    assert version == "1.2.3"

def test_snap_version_not_installed(mock_snap_cache):
    """Test retrieving snap version when not installed."""
    mock_snap = MagicMock()
    mock_snap.present = False
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    version = client.snap_version

    assert version is None

def test_install_success(mock_snap_cache, mock_snap_add):
    """Test successful snap installation."""
    mock_snap = MagicMock()
    mock_snap.present = True
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.install(1, classic=False)

    mock_snap_add.assert_called_once_with("test-snap", revision="1", classic=False)
    assert result is True

def test_install_failure_snap_not_present(mock_snap_cache, mock_snap_add):
    """Test snap installation failure when snap is not present after installation."""
    mock_snap = MagicMock()
    mock_snap.present = False
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.install(1, classic=False)

    assert result is False

def test_install_failure_snap_error(mock_snap_cache, mock_snap_add):
    """Test snap installation failure with SnapError exception."""
    mock_snap_add.side_effect = snap.SnapError("Installation failed")
    mock_snap_cache.return_value.__getitem__.return_value = MagicMock()

    client = SnapClient("test-snap")
    result = client.install(1, classic=False)

    assert result is False

def test_remove_success(mock_snap_cache, mock_snap_remove):
    """Test successful snap removal."""
    mock_snap = MagicMock()
    mock_snap.present = False
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.remove()

    mock_snap_remove.assert_called_once_with("test-snap")
    assert result is True

def test_remove_failure_snap_still_present(mock_snap_cache, mock_snap_remove):
    """Test snap removal failure when snap is still present after removal."""
    mock_snap = MagicMock()
    mock_snap.present = True
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.remove()

    assert result is False

def test_remove_failure_snap_error(mock_snap_cache, mock_snap_remove):
    """Test snap removal failure with SnapError exception."""
    mock_snap_remove.side_effect = snap.SnapError("Removal failed")
    mock_snap_cache.return_value.__getitem__.return_value = MagicMock()

    client = SnapClient("test-snap")
    result = client.remove()

    assert result is False

def test_set_success(mock_snap_cache):
    """Test successful snap configuration setting."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    config = {"key": "value", "port": 9090}
    result = client.set(config)

    mock_snap.set.assert_called_once_with(config, typed=True)
    assert result is True

def test_set_failure(mock_snap_cache):
    """Test snap configuration setting failure."""
    mock_snap = MagicMock()
    mock_snap.set.side_effect = snap.SnapError("Config set failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.set({"key": "value"})

    assert result is False

def test_unset_success(mock_snap_cache):
    """Test successful snap unset config."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    config = ["key", "other-key"]
    result = client.unset(config)

    mock_snap.unset.assert_any_call("key")
    mock_snap.unset.assert_any_call("other-key")
    assert result is True

def test_unset_failure(mock_snap_cache):
    """Test snap unset config failure."""
    mock_snap = MagicMock()
    mock_snap.unset.side_effect = snap.SnapError("Config unset failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.unset(["key"])

    assert result is False

def test_get_config_success(mock_snap_cache):
    """Test successful retrieval of snap configuration."""
    mock_snap = MagicMock()
    mock_snap.get.return_value = {"key": "value", "port": 9090}
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    config = client.get_config()

    mock_snap.get.assert_called_once_with(None, typed=True)
    assert config == {"key": "value", "port": 9090}

def test_get_config_failure(mock_snap_cache):
    """Test snap configuration retrieval failure."""
    mock_snap = MagicMock()
    mock_snap.get.side_effect = snap.SnapError("Get config failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    config = client.get_config()

    assert config == {}

def test_connect_success_single_plug(mock_snap_cache):
    """Test successful connection of a single plug."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.connect(["network"])

    mock_snap.connect.assert_called_once_with("network")
    assert result is True

def test_connect_success_multiple_plugs(mock_snap_cache):
    """Test successful connection of multiple plugs."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.connect(["network", "home", "removable-media"])

    assert mock_snap.connect.call_count == 3
    mock_snap.connect.assert_any_call("network")
    mock_snap.connect.assert_any_call("home")
    mock_snap.connect.assert_any_call("removable-media")
    assert result is True

def test_connect_failure_first_plug(mock_snap_cache):
    """Test plug connection failure on the first plug."""
    mock_snap = MagicMock()
    mock_snap.connect.side_effect = snap.SnapError("Connection failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.connect(["network", "home"])

    mock_snap.connect.assert_called_once_with("network")
    assert result is False

def test_connect_failure_second_plug(mock_snap_cache):
    """Test plug connection failure on the second plug."""
    mock_snap = MagicMock()
    mock_snap.connect.side_effect = [None, snap.SnapError("Connection failed")]
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.connect(["network", "home"])

    assert mock_snap.connect.call_count == 2
    assert result is False

def test_check_all_services_active(mock_snap_cache):
    """Test check method when all services are active."""
    mock_snap = MagicMock()
    mock_snap.services = {
        "service1": {"active": True},
        "service2": {"active": True},
    }
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.check()

    assert result is True

def test_check_some_services_inactive(mock_snap_cache):
    """Test check method when some services are inactive."""
    mock_snap = MagicMock()
    mock_snap.services = {
        "service1": {"active": True},
        "service2": {"active": False},
    }
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.check()

    assert result is False

def test_check_no_active_key(mock_snap_cache):
    """Test check method when services don't have active key."""
    mock_snap = MagicMock()
    mock_snap.services = {
        "service1": {},
        "service2": {"enabled": True},
    }
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.check()

    assert result is False

def test_check_empty_services(mock_snap_cache):
    """Test check method with empty services dictionary."""
    mock_snap = MagicMock()
    mock_snap.services = {}
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.check()

    assert result is True

def test_enable_and_start(mock_snap_cache):
    """Test enabling and starting snap services."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    client.enable_and_start()

    mock_snap.start.assert_called_once_with(enable=True)

def test_enable_and_start_failure(mock_snap_cache):
    """Test enabling and starting snap services failure."""
    mock_snap = MagicMock()
    mock_snap.start.side_effect = snap.SnapError("Start failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    resutl = client.enable_and_start()

    mock_snap.start.assert_called_once_with(enable=True)
    assert resutl is False

def test_disable_and_stop(mock_snap_cache):
    """Test disabling and stopping snap services."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    client.disable_and_stop()

    mock_snap.stop.assert_called_once_with(disable=True)

def test_disable_and_stop_failure(mock_snap_cache):
    """Test disabling and stopping snap services failure."""
    mock_snap = MagicMock()
    mock_snap.stop.side_effect = snap.SnapError("Stop failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.disable_and_stop()

    mock_snap.stop.assert_called_once_with(disable=True)
    assert result is False

def test_ensure_success(mock_snap_cache):
    """Test successful snap ensure operation."""
    mock_snap = MagicMock()
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.ensure(1, classic=True)

    mock_snap.ensure.assert_called_once_with(
        snap.SnapState.Present, revision="1", classic=True
    )
    assert result is True

def test_ensure_failure(mock_snap_cache):
    """Test snap ensure operation failure."""
    mock_snap = MagicMock()
    mock_snap.ensure.side_effect = snap.SnapError("Ensure failed")
    mock_snap_cache.return_value.__getitem__.return_value = mock_snap

    client = SnapClient("test-snap")
    result = client.ensure(1, classic=True)

    assert result is False
