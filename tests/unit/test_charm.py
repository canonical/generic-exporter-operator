# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ops import testing

from charm import GenericExporterOperatorCharm
from utils import Confinement, SnapInfo

CHARM_NAME = "generic-exporter"
STORED_STATE_NAME = "stored"
STORED_SNAP_NAME_KEY = "installed_snap_name"
DEFAULT_SNAP_INFO = SnapInfo(
    name="test-snap",
    revision=1,
    confinement=Confinement.STRICT
)
COS_AGENT_ENDPOINT_NAME = "cos-agent"

@pytest.fixture()
def mock_snap_client():
    """Mock the Velero class in charm.py."""
    mock_snap_client = MagicMock()
    mock_snap_client.snap_version = "1.0.0"
    with patch("charm.SnapClient", return_value=mock_snap_client):
        yield mock_snap_client

@pytest.fixture()
def mock_check_metrics_endpoint():
    """Mock the check_metrics_endpoint function in charm.py."""
    with patch("charm.check_metrics_endpoint") as mock_check:
        yield mock_check

@pytest.fixture()
def mock_get_snap_info():
    """Mock the get_snap_info function in charm.py."""
    with patch("charm.get_snap_info") as mock_get_revision:
        yield mock_get_revision

@pytest.fixture()
def mock_singleton_snap_manager():
    """Mock the SingletonSnapManager class in charm.py."""
    mock_manager = MagicMock()
    with patch("charm.SingletonSnapManager", return_value=mock_manager):
        yield mock_manager

@pytest.mark.parametrize(
    "config,bad_fields",
    [
        ({}, ["snap-name", "exporter-port"]),
        ({"snap-name": "test", "metrics-path": ""}, ["exporter-port"]),
        ({"snap-name": "", "exporter-port": 9090}, ["snap-name"]),
        ({"snap-name": "test", "exporter-port": 70000}, ["exporter-port"]),
        ({"snap-name": "test", "exporter-port": -1}, ["exporter-port"]),
        (
            {"snap-name": "test", "snap-channel": "", "exporter-port": 9090}
            ,["snap-channel"]
        ),
        (
            {"snap-name": "test", "exporter-port": 8080, "snap-config": "not-a-json"},
            ["snap-config"]
        ),
        (
            {"snap-name": "test", "exporter-port": 8080, "snap-config": "123"},
            ["snap-config"]
        ),
        (
            {"snap-name": "test", "exporter-port": 8080, "snap-plugs": ""},
            ["snap-plugs"]
        ),
        (
            {"snap-name": "test", "exporter-port": 8080, "snap-plugs": "   ,  , "},
            ["snap-plugs"]
        ),
        (
            {
                "snap-name": "test",
                "exporter-port": 8080,
                "snap-channel": "test",
                "snap-revision": 1
            },
            ["snap-channel", "snap-revision"]
        ),
        (
            {
                "snap-name": "test",
                "exporter-port": 8080,
                "snap-revision": -1
            },
            ["snap-revision"]
        )
    ],
)
def test_invalid_config(
    config, bad_fields,
    mock_snap_client,
    mock_singleton_snap_manager,
    mock_get_snap_info
):
    """Check that charm sets BlockedStatus on install event with invalid config."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(config=config))
    # Assert
    for field in bad_fields:
        assert field in state_out.unit_status.message

@pytest.mark.parametrize(
    "config",
    [
        {"snap-name": "test-snap", "exporter-port": 10000, "snap-channel": "stable"},
        {"snap-name": "test-snap", "exporter-port": 10000, "snap-revision": 42},
    ]
)
def test_snap_channel_revision_config(
    config,
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Check that charm will try to resolve snap revision."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = (
        DEFAULT_SNAP_INFO
        if "snap-channel" in config
        else SnapInfo(
            name="test-snap",
            revision=None,
            confinement=Confinement.STRICT
        )
    )

    # Act:
    with ctx(
        ctx.on.update_status(),
        testing.State(
            config=config,
            stored_states={
                testing.StoredState(
                    STORED_STATE_NAME,
                    owner_path="GenericExporterOperatorCharm",
                    content={STORED_SNAP_NAME_KEY: "test-snap"}
                )
            }
        )
    ) as mgr:
        pass

    # Assert
    if "snap-channel" in config:
        assert mgr.charm.conf.snap_revision == DEFAULT_SNAP_INFO.revision
        mock_get_snap_info.assert_called_once_with(
            "test-snap",
            config["snap-channel"]
        )
    else:
        assert mgr.charm.conf.snap_revision == config["snap-revision"]
        mock_get_snap_info.assert_called_once_with(
            "test-snap",
            None
        )


def test_snap_not_found(mock_get_snap_info):
    """Check that charm sets BlockedStatus on install event when snap not found."""
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = None

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-channel": "stable",
        }
    ))

    # Assert
    mock_get_snap_info.assert_called_once_with(
        "test-snap",
        "stable"
    )
    assert state_out.unit_status == testing.BlockedStatus(
        (
            "Could not fetch info for snap test-snap. "
            "See juju debug-log for details."
        )
    )

def test_snap_revision_not_found(mock_get_snap_info):
    """Check that charm sets BlockedStatus on install event when snap revision not found."""
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = SnapInfo(
        name="test-snap",
        revision=None,
        confinement=Confinement.STRICT
    )

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-channel": "stable",
        }
    ))

    # Assert
    mock_get_snap_info.assert_called_once_with(
        "test-snap",
        "stable"
    )
    assert state_out.unit_status == testing.BlockedStatus(
        "Could not determine revision for snap test-snap on channel stable."
    )

def test_snap_classic_not_allowed(mock_get_snap_info):
    """Check that charm sets BlockedStatus on install when snap requires classic."""
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = SnapInfo(
        name="test-snap",
        revision=1,
        confinement=Confinement.CLASSIC
    )

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-channel": "stable",
            "snap-classic": False,
        }
    ))

    # Assert
    mock_get_snap_info.assert_called_once_with(
        "test-snap",
        "stable"
    )
    assert state_out.unit_status == testing.BlockedStatus(
        (
            "Snap test-snap requires classic confinement. "
            "Please enable 'snap-classic'."
        )
    )

def test_on_install_no_snap(mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test install event handling when no snap is configured."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "old-snap"})
        },
        config={
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.install.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Missing required configuration fields: snap-name"
    )

@pytest.mark.parametrize(
    "stored_snap_name",
    [
        None,
        "test-snap",
        "another-snap",
    ]
)
def test_on_install(
    stored_snap_name,
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test install event handling."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    snap_name = "test-snap"
    mock_snap_client.install.return_value = True
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    mock_singleton_snap_manager.is_used_by_other_units.return_value = False

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        relations=[
            testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: stored_snap_name})
        },
        config={
            "snap-name": snap_name,
            "exporter-port": 10000,
        }
    ))

    # Assert
    if stored_snap_name != snap_name:
        if stored_snap_name is not None:
            mock_snap_client.remove.assert_called_once_with()
        else:
            mock_snap_client.remove.assert_not_called()
        mock_snap_client.install.assert_called_once()
    else:
        mock_snap_client.install.assert_not_called()
    assert state_out.unit_status == testing.ActiveStatus()

def test_on_install_snap_remove_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test install event handling when snap removal fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.install.return_value = True
    mock_snap_client.remove.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    mock_singleton_snap_manager.is_used_by_other_units.return_value = False

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "old-snap"})
        },
        config={
            "snap-name": "new-snap",
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.remove.assert_called_once_with()
    mock_snap_client.install.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to uninstall snap: old-snap. See juju debug-log for details."
    )

def test_on_install_snap_start_service_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test install event handling when snap service start fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.enable_and_start.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: None,
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.enable_and_start.assert_called_once_with()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to start snap services for: test-snap. See juju debug-log for details."
    )

def test_on_install_snap_install_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test install event handling when snap installation fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.install.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: None,
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.install.assert_called_once()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to install snap: test-snap. See juju debug-log for details."
    )

@pytest.mark.parametrize(
    "snap_services_ok,metrics_endpoint_ok,cos_related,expected_status",
    [
        (True, True, True, testing.ActiveStatus()),
        (False, True, True, testing.BlockedStatus("Snap services for test-snap are not active.")),
        (
            True,
            False,
            True,
            testing.BlockedStatus("Metrics endpoint for test-snap is not reachable.")
        ),
        (False, False, True, testing.BlockedStatus("Snap services for test-snap are not active.")),
        (True, True, False, testing.BlockedStatus("Missing relation: [cos-agent]")),
    ]
)
def test_on_update_status(
    snap_services_ok,
    metrics_endpoint_ok,
    cos_related,
    expected_status,
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test update-status event handling."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.check.return_value = snap_services_ok
    mock_check_metrics_endpoint.return_value = metrics_endpoint_ok
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    relations = [
        testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
    ] if cos_related else []

    # Act:
    state_out = ctx.run(ctx.on.install(), testing.State(
        relations=relations,
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
        }
    ))

    assert state_out.unit_status == expected_status

@pytest.mark.parametrize(
    "snap_installed,snap_used_by_others,alerts_exists",
    [
        (None, False, False),
        ("test-snap", False, False),
        ("test-snap", False, True),
        (None, True, False),
        ("test-snap", True, False),
        ("test-snap", True, True),
    ]
)
def test_on_remove(
    snap_installed,
    snap_used_by_others,
    alerts_exists,
    mock_snap_client,
    mock_get_snap_info,
    mock_singleton_snap_manager
):
    """Test remove event handling."""
    # Arrange:
    unit_id = 1
    ctx = testing.Context(GenericExporterOperatorCharm, unit_id=unit_id, app_name=CHARM_NAME)
    mock_snap_client.remove.return_value = True
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    mock_singleton_snap_manager.is_used_by_other_units.return_value = snap_used_by_others

    with tempfile.TemporaryDirectory() as config_parent_dir:
        alerts_dir = Path(config_parent_dir) / f"{CHARM_NAME}-{unit_id}"

        if alerts_exists:
            alerts_dir.mkdir(parents=True, exist_ok=True)
            (alerts_dir / "alerts.yaml").write_text("test alerts content")

        with patch("charm.CONFIG_PARENT_DIR", new=config_parent_dir):
            # Act:
            state_out = ctx.run(ctx.on.remove(), testing.State(
                stored_states={
                    testing.StoredState(
                        STORED_STATE_NAME,
                        owner_path="GenericExporterOperatorCharm",
                        content={STORED_SNAP_NAME_KEY: snap_installed})
                },
                config={
                    "snap-name": "test-snap",
                    "exporter-port": 10000,
                }
            ))

            # Assert
            if snap_installed is not None:
                if snap_used_by_others is False:
                    mock_snap_client.remove.assert_called_once_with()
                else:
                    mock_snap_client.remove.assert_not_called()
            else:
                mock_snap_client.remove.assert_not_called()

            if alerts_exists:
                assert not (alerts_dir / "alerts.yaml").exists()
                assert not alerts_dir.exists()

            assert state_out.unit_status == testing.MaintenanceStatus("Removing charm resources")

@pytest.mark.parametrize(
    "config",
    [
        {"snap-name": "test-snap", "exporter-port": 10000},
        {"snap-name": "test-snap", "exporter-port": 9090, "snap-config": '{"key": "value"}'},
        {"snap-name": "test-snap", "exporter-port": 8080, "snap-plugs": "network, home"},
    ],
)
def test_on_config_changed(
    config,
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.set.return_value = True
    mock_snap_client.connect.return_value = True
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        relations=[
           testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
        ],
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config=config
    ))

    # Assert
    mock_snap_client.disable_and_stop.assert_called_once_with()
    if "snap-config" in config:
        mock_snap_client.set.assert_called_once_with({"key": "value"})
    else:
        mock_snap_client.set.assert_not_called()
    if "snap-plugs" in config:
        mock_snap_client.connect.assert_called_once_with(["network", "home"])
    else:
        mock_snap_client.connect.assert_not_called()
    mock_snap_client.enable_and_start.assert_called_once_with()

    assert state_out.unit_status == testing.ActiveStatus()
    assert state_out.workload_version == "1.0.0"

def test_on_config_changed_snap_ensure_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap ensure fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.ensure.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.ensure.assert_called_once()
    mock_snap_client.enable_and_start.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to configure snap: test-snap. See juju debug-log for details."
    )

def test_on_config_no_snap(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap is not set."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.set.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        config={
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.disable_and_stop.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Missing required configuration fields: snap-name"
    )

def test_on_config_changed_snap_set_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap set fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.set.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config": '{"key": "value"}',
        }
    ))

    # Assert
    mock_snap_client.set.assert_called_once_with({"key": "value"})
    mock_snap_client.enable_and_start.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to set config for snap: test-snap. See juju debug-log for details."
    )

def test_on_config_changed_updated_snap_config(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap config is updated."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.get_config.return_value = {
        "key": "old-value",
        "other-key": { "sub-key": 123 }
    }
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        relations=[
            testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
        ],
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config": '{"key": "new-value"}',
        }
    ))

    # Assert
    mock_snap_client.unset.assert_called_once_with(["other-key.sub-key"])
    mock_snap_client.set.assert_called_once_with({"key": "new-value"})
    mock_snap_client.enable_and_start.assert_called_once_with()
    assert state_out.unit_status == testing.ActiveStatus()

def test_on_config_changed_snap_unset_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap connect fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.unset.return_value = False
    mock_snap_client.get_config.return_value = {"other-key": "old-value"}
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config": '{"key": "new-value"}',
        }
    ))

    # Assert
    mock_snap_client.unset.assert_called_once_with(["other-key"])
    mock_snap_client.enable_and_start.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to unset config keys ['other-key'] for snap: "
        "test-snap. See juju debug-log for details."
    )


def test_on_config_changed_snap_connect_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap connect fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.connect.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-plugs": "network, home",
        }
    ))

    # Assert
    mock_snap_client.connect.assert_called_once_with(["network", "home"])
    mock_snap_client.enable_and_start.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to connect plugs ['network', 'home'] for snap: test-snap. "
        "See juju debug-log for details."
    )


def test_on_config_changed_snap_start_failed(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling when snap start fails."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.enable_and_start.return_value = False
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={
                    STORED_SNAP_NAME_KEY: "test-snap",
                })
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
        }
    ))

    # Assert
    mock_snap_client.enable_and_start.assert_called_once_with()
    assert state_out.unit_status == testing.BlockedStatus(
        "Failed to restart snap services for: test-snap. See juju debug-log for details."
    )


@pytest.mark.parametrize(
    "alerts_content,valid",
    [
        ("", False),
        ("invalid: yaml: ::", False),
        ("invalid yaml", False),
        ("groups:\n  - name: test-alerts\n    rules: []", True)
    ],
)
def test_on_config_changed_alerts_setup(
    alerts_content,
    valid,
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info
):
    """Test config-changed event handling for alerts file setup."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm, unit_id=1, app_name=CHARM_NAME)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    with tempfile.TemporaryDirectory() as alerts_dir:
        with patch(
            "charm.CONFIG_PARENT_DIR",
            new=Path(alerts_dir)
        ):
            with tempfile.NamedTemporaryFile(
                delete=False, mode='w', newline='', encoding='utf-8'
            ) as alerts_file:
                alerts_file.write(alerts_content)
                alerts_file_path = alerts_file.name

            # Act:
            state_out = ctx.run(ctx.on.config_changed(), testing.State(
                relations=[
                   testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
                ],
                resources=[
                    testing.Resource(name="alerts", path=alerts_file_path)
                ],
                stored_states={
                    testing.StoredState(
                        STORED_STATE_NAME,
                        owner_path="GenericExporterOperatorCharm",
                        content={
                            STORED_SNAP_NAME_KEY: "test-snap",
                        })
                },
                config={
                    "snap-name": "test-snap",
                    "exporter-port": 10000,
                }
            ))

            # Assert
            alerts_dest_file = f"{alerts_dir}/{CHARM_NAME}-1/alerts.yaml"
            if valid:
                assert os.path.exists(alerts_dest_file)
                with open(alerts_dest_file, 'r', encoding='utf-8') as dest_file:
                    assert dest_file.read() == alerts_content
                assert state_out.unit_status == testing.ActiveStatus()
            else:
                assert not os.path.exists(alerts_dest_file)

            assert state_out.unit_status == testing.ActiveStatus()

@pytest.mark.parametrize(
    "alerts_content",
    [
        "groups:\n  - name: test-alerts\n    rules: []",
        None,
    ],
)
def test_action_dump_alerts(alerts_content, mock_get_snap_info):
    """Test dump-alerts action handling."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm, unit_id=1, app_name=CHARM_NAME)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO

    with tempfile.TemporaryDirectory() as config_parent_dir:
        with patch(
            "charm.CONFIG_PARENT_DIR",
            new=Path(config_parent_dir)
        ):
            alerts_dir = Path(config_parent_dir) / f"{CHARM_NAME}-1"
            alerts_dir.mkdir(parents=True, exist_ok=True)
            alerts_file_path = Path(alerts_dir) / "alerts.yaml"
            if alerts_content is not None:
                with open(alerts_file_path, 'w', encoding='utf-8') as alerts_file:
                    alerts_file.write(alerts_content)

            # Act:
            ctx.run(ctx.on.action("dump-alerts"), testing.State(
                config={
                    "snap-name": "test-snap",
                    "exporter-port": 10000,
                }
            ))

            # Assert
            assert type(ctx.action_results) is dict
            if alerts_content is not None:
                assert ctx.action_results.get("status") == "success"
                assert ctx.action_results.get("path") == str(alerts_file_path)
            else:
                assert ctx.action_results.get("status") == "no alerts configured"
                assert "path" not in ctx.action_results

def test_on_config_changed_snap_config_secret_success(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test config-changed with snap-config-secret successfully decoded."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.set.return_value = True
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={"config": '{"secret-key": "secret-value"}'},
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        relations=[
            testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
        ],
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_called_once_with({"secret-key": "secret-value"})
    assert state_out.unit_status == testing.ActiveStatus()


def test_on_config_changed_snap_config_secret_merged_with_snap_config(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that snap-config-secret is merged with snap-config."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_snap_client.set.return_value = True
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={
            "config": json.dumps({
                "secret-key": "secret-value",
                "other-key": {"sub-key": 42}
            })
        },
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        relations=[
            testing.SubordinateRelation(endpoint=COS_AGENT_ENDPOINT_NAME)
        ],
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config": json.dumps({
                "public-key": "public-value",
                "other-key": {"another-sub-key": 99}
            }),
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_called_once_with(
        {
            "public-key": "public-value",
            "secret-key": "secret-value",
            "other-key": {
                "another-sub-key": 99,
                "sub-key": 42
            }
        }
    )
    assert state_out.unit_status == testing.ActiveStatus()


def test_on_config_changed_snap_config_secret_merge_conflict(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that merge conflict between snap-config-secret and snap-config raises error."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={"config": '{"conflict-key": "secret-value"}'},
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config": '{"conflict-key": "public-value"}',
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_not_called()
    assert state_out.unit_status == testing.BlockedStatus(
        "The configs conflict at key: conflict-key"
    )


def test_on_config_changed_snap_config_secret_missing_config_field(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that secret without 'config' field raises appropriate error."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={"other-field": "value"},
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_not_called()
    assert "config field is missing" in state_out.unit_status.message


def test_on_config_changed_snap_config_secret_invalid_json(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that secret with invalid JSON in config field raises error."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={"config": "not-valid-json{"},
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_not_called()
    assert "must be valid JSON" in state_out.unit_status.message


def test_on_config_changed_snap_config_secret_json_not_dict(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that secret with JSON that is not a dict raises error."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret = testing.Secret(
        tracked_content={"config": '["list", "not", "dict"]'},
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        secrets={secret},
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config-secret": secret.id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_not_called()
    assert "must decode to dict" in state_out.unit_status.message


def test_on_config_changed_snap_config_secret_not_found(
    mock_snap_client,
    mock_check_metrics_endpoint,
    mock_get_snap_info,
):
    """Test that missing secret raises appropriate error."""
    # Arrange:
    ctx = testing.Context(GenericExporterOperatorCharm)
    mock_get_snap_info.return_value = DEFAULT_SNAP_INFO
    secret_id = "secret:abcdefghij1234567890"

    state_out = ctx.run(ctx.on.config_changed(), testing.State(
        resources=[
            testing.Resource(name="alerts", path="alerts.yaml"),
        ],
        stored_states={
            testing.StoredState(
                STORED_STATE_NAME,
                owner_path="GenericExporterOperatorCharm",
                content={STORED_SNAP_NAME_KEY: "test-snap"})
        },
        config={
            "snap-name": "test-snap",
            "exporter-port": 10000,
            "snap-config-secret": secret_id,
        }
    ))

    # Assert
    mock_snap_client.set.assert_not_called()
    assert "does not exist" in state_out.unit_status.message
