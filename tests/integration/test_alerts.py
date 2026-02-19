#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import pathlib
import tempfile

import jubilant
from helpers import (
    COS_ENDPOINT,
    GRAFANA_AGENT_APP,
    GRAFANA_AGENT_CHANNEL,
    INVALID_ALERTS_YAML,
    JUJU_INFO_ENDPOINT,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_CHANNEL,
    VALID_ALERTS_YAML,
    get_app_unit,
)

logger = logging.getLogger(__name__)
TEMP_DIR = pathlib.Path(__file__).parent.resolve()

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

def test_dump_alerts_empty(juju: jubilant.Juju, app_name: str) -> None:
    """Test that dumping alerts when none are configured."""
    app_unit = get_app_unit(juju, app_name)
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)

    task = juju.run(app_unit, "dump-alerts")
    assert task.results["status"] == "no alerts configured", "Expected no alerts to be configured"

    app_unit_id = app_unit.split("/")[1]
    task = juju.exec(
        f"test -e /run/{app_name}-{app_unit_id}/alerts.yaml || echo 'not found'",
        unit=principal_unit
    )
    assert task.stdout.strip() == "not found", (
        "Expected alerts.yaml to not exist when no alerts are configured"
    )

def test_invalid_alerts(juju: jubilant.Juju, app_name: str) -> None:
    """Test that invalid alerts configuration is handled."""
    app_unit = get_app_unit(juju, app_name)
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)

    with tempfile.NamedTemporaryFile(
        delete=False, mode='w', newline='', encoding='utf-8', dir=TEMP_DIR, suffix='.yaml'
    ) as alerts_file:
        alerts_file.write(INVALID_ALERTS_YAML)
        alerts_file_path = alerts_file.name

    juju.cli("attach-resource", app_name, f"alerts={alerts_file_path}")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, app_name, UBUNTU_APP_NAME) and
            jubilant.all_agents_idle(status, app_name)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    app_unit_id = app_unit.split("/")[1]
    task = juju.exec(
        f"test -e /run/{app_name}-{app_unit_id}/alerts.yaml || echo 'not found'",
        unit=principal_unit
    )
    assert task.stdout.strip() == "not found", (
        "Expected alerts.yaml to not exist after attaching invalid alerts"
    )

def test_valid_alerts(juju: jubilant.Juju, app_name: str) -> None:
    """Test that valid alerts configuration is handled."""
    app_unit = get_app_unit(juju, app_name)
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)

    with tempfile.NamedTemporaryFile(
        delete=False, mode='w', newline='', encoding='utf-8', dir=TEMP_DIR, suffix='.yaml'
    ) as alerts_file:
        alerts_file.write(VALID_ALERTS_YAML)
        alerts_file_path = alerts_file.name

    juju.cli("attach-resource", app_name, f"alerts={alerts_file_path}")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, app_name, UBUNTU_APP_NAME) and
            jubilant.all_agents_idle(status, app_name)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    app_unit_id = app_unit.split("/")[1]
    task = juju.exec(
        f"test -e /run/{app_name}-{app_unit_id}/alerts.yaml || echo 'not found'",
        unit=principal_unit
    )
    assert task.stdout.strip() != "not found", (
        "Expected alerts.yaml to exist after attaching valid alerts"
    )

def test_dump_alerts(juju: jubilant.Juju, app_name: str) -> None:
    """Test that dumping alerts works correctly."""
    app_unit = get_app_unit(juju, app_name)

    with tempfile.NamedTemporaryFile(
        delete=False, mode='w', newline='', encoding='utf-8', dir=TEMP_DIR, suffix='.yaml'
    ) as alerts_file:
        alerts_file.write(VALID_ALERTS_YAML)
        alerts_file_path = alerts_file.name

    juju.cli("attach-resource", app_name, f"alerts={alerts_file_path}")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, app_name, UBUNTU_APP_NAME) and
            jubilant.all_agents_idle(status, app_name)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    app_unit_id = app_unit.split("/")[1]
    task = juju.run(app_unit, "dump-alerts")
    assert task.results["status"] == "success", "Expected alerts to be dumped successfully"
    assert task.results["path"] == f"/run/{app_name}-{app_unit_id}/alerts.yaml", (
        "Expected correct path for dumped alerts"
    )
    assert len(task.log) == 1, "Expected single line log output for dump-alerts"
    assert VALID_ALERTS_YAML.strip() in task.log[0], (
        "Expected dumped alerts content to match the valid alerts YAML"
    )

def test_remove(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can be removed cleanly."""
    app_unit = get_app_unit(juju, app_name)
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)

    juju.remove_application(app_name)
    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )

    app_unit_id = app_unit.split("/")[1]
    task = juju.exec(
        f"test -e /run/{app_name}-{app_unit_id}/alerts.yaml || echo 'not found'",
        unit=principal_unit
    )
    assert task.stdout.strip() == "not found", (
        "Expected alerts.yaml to be removed after application removal"
    )
    juju.remove_application(GRAFANA_AGENT_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)


