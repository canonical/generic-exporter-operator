#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
from helpers import (
    COS_ENDPOINT,
    GRAFANA_AGENT_APP,
    GRAFANA_AGENT_CHANNEL,
    JUJU_INFO_ENDPOINT,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_CHANNEL,
    get_app_unit,
)

logger = logging.getLogger(__name__)

def test_deploy(juju: jubilant.Juju, charm: str, app_name: str, base: str) -> None:
    """Test that the charm deploys and relates correctly."""
    juju.deploy(
        charm,
        app=app_name,
        base=base,
        config={"snap-name": SMARTCTL_SNAP_NAME, "exporter-port": SMARTCTL_EXPORTER_PORT},
    )
    juju.deploy(GRAFANA_AGENT_APP, channel=GRAFANA_AGENT_CHANNEL, base=base)
    juju.deploy(UBUNTU_APP_NAME, channel=UBUNTU_CHANNEL, base=base)
    juju.integrate(f"{app_name}:{COS_ENDPOINT}", f"{GRAFANA_AGENT_APP}:{COS_ENDPOINT}")
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")

    juju.wait(
        lambda status: jubilant.all_active(status, app_name, UBUNTU_APP_NAME),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_scale_up(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can scale up and down."""
    juju.add_unit(UBUNTU_APP_NAME, to="0")

    juju.wait(
        lambda status: jubilant.all_active(status, app_name, UBUNTU_APP_NAME),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        "ls /opt/singleton_snaps | wc -l",
        unit=principal_unit
    )
    assert task.stdout.strip() == "2", "Expected 2 files in /opt/singleton_snaps"

def test_scale_down(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can scale down."""
    juju.remove_unit(f"{UBUNTU_APP_NAME}/1")

    juju.wait(
        lambda status: jubilant.all_active(status, app_name, UBUNTU_APP_NAME),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    task = juju.exec(
        "ls /opt/singleton_snaps | wc -l",
        unit=principal_unit
    )
    assert task.stdout.strip() == "1", "Expected 1 file in /opt/singleton_snaps"

    task = juju.exec(
        "snap list",
        unit=principal_unit
    )
    assert SMARTCTL_SNAP_NAME in task.stdout.strip(), (
        f"Expected snap {SMARTCTL_SNAP_NAME} to still be installed on the machine"
    )

def test_remove(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can be removed cleanly."""
    juju.remove_application(app_name)
    juju.remove_application(GRAFANA_AGENT_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)

    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )
