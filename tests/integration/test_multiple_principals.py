#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for relating one generic-exporter app to multiple principals.

Scenario: one generic-exporter app is related to two separate principal applications
each deployed on their own machine. Each principal should receive its own subordinate
unit and both should reach active/idle.

This validates that the charm works without a `limit: 1` constraint on the juju-info
relation endpoint.
"""

import logging

import jubilant
from helpers import (
    JUJU_INFO_ENDPOINT,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_APP_NAME_2,
    UBUNTU_CHANNEL,
)

logger = logging.getLogger(__name__)


def test_deploy_multiple_principals(
    juju: jubilant.Juju, charm: str, app_name: str, base: str
) -> None:
    """Deploy one generic-exporter app related to two different principal apps."""
    juju.deploy(
        charm,
        app=app_name,
        base=base,
        config={
            "snap-name": SMARTCTL_SNAP_NAME,
            "exporter-port": SMARTCTL_EXPORTER_PORT,
        },
    )
    juju.deploy(UBUNTU_APP_NAME, channel=UBUNTU_CHANNEL, base=base)
    juju.deploy(app=UBUNTU_APP_NAME_2, charm="ubuntu", channel=UBUNTU_CHANNEL, base=base)

    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME_2}:{JUJU_INFO_ENDPOINT}")

    juju.wait(
        lambda status: jubilant.all_active(status, app_name, UBUNTU_APP_NAME, UBUNTU_APP_NAME_2),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )


def test_two_subordinate_units_created(juju: jubilant.Juju, app_name: str) -> None:
    """Assert that one subordinate unit exists on each principal machine."""
    status = juju.status()
    exporter_units = status.get_units(app_name)

    assert len(exporter_units) == 2, (
        f"Expected 2 generic-exporter subordinate units (one per principal), "
        f"got {len(exporter_units)}: {list(exporter_units.keys())}"
    )


def test_each_subordinate_active(juju: jubilant.Juju, app_name: str) -> None:
    """Assert that every subordinate unit is active/idle."""
    status = juju.status()
    exporter_units = status.get_units(app_name)

    for unit_name, unit in exporter_units.items():
        assert unit.workload_status.current == "active", (
            f"Unit {unit_name} is not active: {unit.workload_status}"
        )


def test_remove_multiple_principals(juju: jubilant.Juju, app_name: str) -> None:
    """Clean up all applications deployed in this module."""
    juju.remove_application(app_name)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME_2, destroy_storage=True)

    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )
