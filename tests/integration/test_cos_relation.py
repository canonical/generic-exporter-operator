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
    JUJU_INFO_ENDPOINT,
    SMARTCTL_EXPORTER_METRICS_PATH,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_CHANNEL,
    VALID_ALERTS_YAML,
    assert_alerts_rules,
    assert_metrics_endpoint,
    assert_scrape_job,
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
    juju.deploy(UBUNTU_APP_NAME, channel=UBUNTU_CHANNEL, base=base)
    juju.deploy(GRAFANA_AGENT_APP, channel=GRAFANA_AGENT_CHANNEL, base=base)
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")
    juju.integrate(
        f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}",
        f"{GRAFANA_AGENT_APP}:{JUJU_INFO_ENDPOINT}"
    )

    juju.wait(
        lambda status: jubilant.all_blocked(status, app_name, GRAFANA_AGENT_APP),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )
    juju.wait(
        lambda status: jubilant.all_active(status, UBUNTU_APP_NAME),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_cos_relation(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm enters active state when Grafana Agent is related."""
    juju.integrate(f"{app_name}:{COS_ENDPOINT}", f"{GRAFANA_AGENT_APP}:{COS_ENDPOINT}")

    juju.wait(
        lambda status: jubilant.all_active(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

def test_relation_data(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the relation data is set correctly."""
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

    target = f"localhost:{SMARTCTL_EXPORTER_PORT}"
    assert_scrape_job(juju, app_name, target, SMARTCTL_EXPORTER_METRICS_PATH, {"instance"})
    assert_alerts_rules(juju, app_name, {"ExampleAlert"})

def test_metrics_endpoint(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the metrics endpoint is reachable and returns valid metrics."""
    principal_unit = get_app_unit(juju, UBUNTU_APP_NAME)
    assert_metrics_endpoint(
        juju,
        principal_unit,
        SMARTCTL_EXPORTER_PORT,
        SMARTCTL_EXPORTER_METRICS_PATH
    )

def test_config_exporter(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm handles configuration changes and update COS relation data."""
    juju.config(
        app_name,
        {
            "snap-name": "smartctl-exporter",
            "exporter-port": 9644,
            "metrics-path": "custom-metrics",
        }
    )

    # Will block as the endpoint is unreachable
    juju.wait(
        lambda status: jubilant.all_blocked(status, app_name),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )

    target = "localhost:9644"
    assert_scrape_job(juju, app_name, target, "/custom-metrics", {"instance"})

def test_remove(juju: jubilant.Juju, app_name: str) -> None:
    """Test that the charm can be removed cleanly."""
    juju.remove_application(app_name)
    juju.remove_application(GRAFANA_AGENT_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)

    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )
