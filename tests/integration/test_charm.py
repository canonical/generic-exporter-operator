#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

import jubilant
import pytest
import yaml
from helpers import (
    COS_ENDPOINT,
    GRAFANA_AGENT_APP,
    GRAFANA_AGENT_CHANNEL,
    JUJU_INFO_ENDPOINT,
    NODE_EXPORTER_EXPORTER_PORT,
    NODE_EXPORTER_SNAP_NAME,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_CHANNEL,
    get_app_unit,
    get_snap_revision,
    get_snap_revision_by_channel,
)

logger = logging.getLogger(__name__)

def test_deploy(juju: jubilant.Juju, charm: str, app_name: str, base: str) -> None:
    """Test that the charm deploys and relates correctly."""
    juju.deploy(
        charm,
        app=app_name,
        base=base,
        config={},
    )
    juju.deploy(GRAFANA_AGENT_APP, channel=GRAFANA_AGENT_CHANNEL, base=base)
    juju.deploy(UBUNTU_APP_NAME, channel=UBUNTU_CHANNEL, base=base)
    juju.integrate(f"{app_name}:{COS_ENDPOINT}", f"{GRAFANA_AGENT_APP}:{COS_ENDPOINT}")
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")

    juju.wait(
        lambda status: jubilant.all_blocked(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )
    juju.wait(
        lambda status: jubilant.all_active(status, UBUNTU_APP_NAME),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_config_basic(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm handles configuration changes."""
    juju.config(
        app_name,
        {
            "snap-name": SMARTCTL_SNAP_NAME,
            "exporter-port": SMARTCTL_EXPORTER_PORT,
        }
    )

    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

@pytest.mark.parametrize(
    "config_changes",
    [
        {
            "snap-channel": "latest/edge",
        },
        {
            "snap-revision": 76,
        },
    ],
)
def test_config_snap_source(juju: jubilant.Juju, app_name: str, config_changes: dict) -> None:
    """Test that the charm handles configuration changes."""
    juju.config(
        app_name,
        config_changes,
    )

    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    app = juju.status().apps[app_name]
    assert app.version != "unknown", (
        "Expected workload version to be set after changing snap source"
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        f"snap info {SMARTCTL_SNAP_NAME}",
        unit=principal_unit
    )
    snap_info = yaml.safe_load(task.stdout.strip())
    installed_revision = get_snap_revision(snap_info)
    assert installed_revision is not None, "Could not determine installed snap revision"

    if "snap-channel" in config_changes:
        expected_revision = get_snap_revision_by_channel(
            snap_info,
            config_changes["snap-channel"]
        )
        assert installed_revision == expected_revision, (
            f"Expected snap revision {expected_revision} for channel "
            f"{config_changes['snap-channel']}, but found {installed_revision}"
        )
    if "snap-revision" in config_changes:
        expected_revision = str(config_changes["snap-revision"])
        assert installed_revision == expected_revision, (
            f"Expected snap revision {expected_revision}, but found {installed_revision}"
        )

    juju.config(
        app_name,
        reset=list(config_changes.keys())
    )
    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_config_snap_config(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm handles configuration changes."""
    secret_id = juju.add_secret(
        "test-secret",
        {
            "config": json.dumps({"log": {"level": "debug"}})
        }
    )
    juju.grant_secret(secret_id, app_name)

    juju.config(
        app_name,
        {
            "snap-config": json.dumps({"web": {"listen-address": ":10200"}}),
            "snap-config-secret": secret_id,
            "exporter-port": 10200,
        }
    )
    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        f"snap get {SMARTCTL_SNAP_NAME}",
        unit=principal_unit
    )
    snap_config = json.loads(task.stdout.strip())
    assert snap_config.get("web", {}).get("listen-address") == ":10200", (
        "Expected snap configuration 'web.listen-address' to be set to ':10200'"
    )
    assert snap_config.get("log", {}).get("level") == "debug", (
        "Expected snap configuration 'log.level' to be set to 'debug'"
    )

    juju.config(
        app_name,
        {
            "exporter-port": SMARTCTL_EXPORTER_PORT
        },
        reset=["snap-config", "snap-config-secret"]
    )
    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

@pytest.mark.parametrize(
    "config_changes,expected_message",
    [
        (
            {"snap-channel": "invalid/channel"},
            "Could not determine revision for snap smartctl-exporter on channel invalid/channel."
        ),
        (
            {"snap-revision": 999999},
            "Failed to configure snap: smartctl-exporter. See juju debug-log for details."
        ),
        (
            {"snap-channel": "latest/stable", "snap-revision": 76},
            "Invalid configuration: snap-channel and snap-revision cannot both be set"
        ),
    ],
)
def test_config_invalid(
    juju: jubilant.Juju,
    app_name: str,
    config_changes: dict,
    expected_message: str
) -> None:
    """Test that the charm handles invalid configuration."""
    juju.config(
        app_name,
        config_changes,
    )
    juju.wait(
        lambda status: (
            jubilant.all_blocked(status, app_name) and
            jubilant.all_agents_idle(status, app_name)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )
    current_status_message = juju.status().apps[app_name].app_status.message
    assert current_status_message == expected_message, (
        f"Expected blocked message '{expected_message}', found '{current_status_message}'"
    )
    juju.config(
        app_name,
        reset=list(config_changes.keys())
    )
    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_config_invalid_snap(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm handles invalid snap name."""
    juju.config(app_name, {"snap-name": "non-existent-snap"})
    juju.wait(
        lambda status: (
            jubilant.all_blocked(status, app_name) and
            jubilant.all_agents_idle(status, app_name)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    current_status_message = juju.status().apps[app_name].app_status.message
    assert current_status_message == (
        "Could not fetch info for snap non-existent-snap. See juju debug-log for details."
    ), (
        f"Expected blocked message for non-existent snap, found '{current_status_message}'"
    )

def test_config_change_exporter(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can change the exporter snap."""
    juju.config(
        app_name,
        {
            "snap-name": NODE_EXPORTER_SNAP_NAME,
            "exporter-port": NODE_EXPORTER_EXPORTER_PORT,
            "snap-channel": "latest/beta",
            "snap-plugs": "hardware-observe,mount-observe,network-observe,system-observe",
        }
    )

    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        f"snap list {NODE_EXPORTER_SNAP_NAME}",
        unit=principal_unit
    )
    assert NODE_EXPORTER_SNAP_NAME in task.stdout.strip(), (
        f"Expected snap {NODE_EXPORTER_SNAP_NAME} to be installed on the machine"
    )
    assert SMARTCTL_SNAP_NAME not in task.stdout.strip(), (
        f"Expected snap {SMARTCTL_SNAP_NAME} to be removed from the machine"
    )

def test_unset_snap(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm removes the installed snap when snap-name is unset."""
    juju.config(
        app_name,
        reset=["snap-name"],
    )

    juju.wait(
        lambda status: jubilant.all_blocked(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        "snap list",
        unit=principal_unit
    )
    assert NODE_EXPORTER_SNAP_NAME not in task.stdout.strip(), (
        f"Expected {NODE_EXPORTER_SNAP_NAME} snap to be removed from the machine"
    )

    # Restore for cleanup
    juju.config(
        app_name,
        {
            "snap-name": SMARTCTL_SNAP_NAME,
            "exporter-port": SMARTCTL_EXPORTER_PORT,
            "snap-channel": "latest/stable"
        }
    )
    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_remove(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can be removed cleanly."""
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)

    juju.remove_application(app_name)
    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )

    task = juju.exec(
        "snap list",
        unit=principal_unit
    )
    assert SMARTCTL_SNAP_NAME not in task.stdout.strip(), (
        f"Expected {SMARTCTL_SNAP_NAME} snap to be removed from the machine"
    )
    juju.remove_application(GRAFANA_AGENT_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)
