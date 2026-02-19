# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import re
from typing import Any, Dict, Optional, Set

import jubilant
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

TIMEOUT = 10 * 60

UBUNTU_CHANNEL = "latest/stable"
UBUNTU_APP_NAME = "ubuntu"
GRAFANA_AGENT_APP = "grafana-agent"
GRAFANA_AGENT_CHANNEL = "1/stable"

SMARTCTL_SNAP_NAME = "smartctl-exporter"
SMARTCTL_EXPORTER_PORT = 9633
SMARTCTL_EXPORTER_METRICS_PATH = "/metrics"

NODE_EXPORTER_SNAP_NAME = "node-exporter"
NODE_EXPORTER_EXPORTER_PORT = 9100

COS_ENDPOINT = "cos-agent"
JUJU_INFO_ENDPOINT = "juju-info"

PROVIDES = "provides"

VALID_ALERTS_YAML = """groups:
  - name: example-group
    rules:
      - alert: ExampleAlert
        expr: up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
            summary: "Instance is down"
"""

INVALID_ALERTS_YAML = "invalid yaml"


def get_snap_revision(snap_info: Dict[str, Any]) -> Optional[str]:
    """Extract the installed revision from snap info dictionary.

    Args:
        snap_info: Dictionary parsed from `snap info` YAML output

    Returns:
        The revision number as a string, or None if not found
    """
    installed = snap_info.get("installed", "")
    if not installed:
        return None

    match = re.search(r"\((\d+)\)", installed)
    if match:
        return match.group(1)
    return None


def get_snap_revision_by_channel(snap_info: Dict[str, Any], channel: str) -> Optional[str]:
    """Extract the revision for a specific channel from snap info dictionary.

    Args:
        snap_info: Dictionary parsed from `snap info` YAML output
        channel: The channel name (e.g., "latest/stable", "latest/edge")

    Returns:
        The revision number as a string, or None if not found
    """
    channels = snap_info.get("channels", {})
    channel_info = channels.get(channel, "")
    if not channel_info:
        return None

    match = re.search(r"\((\d+)\)", channel_info)
    if match:
        return match.group(1)
    return None


def get_unit_relation_data(
    juju: jubilant.Juju,
    target_app_name: str,
    app_name: str,
    endpoint: str,
) -> Dict[str, Any]:
    """Get unit relation data from endpoint name between two applications.

    Args:
        juju: The Juju instance
        target_app_name: The target application name
        app_name: The application name related to the target
        endpoint: The relation endpoint name
    Returns:
        The relation data dictionary

    Raises:
        AssertionError: If the relation or application is not found
    """
    app_unit = get_app_unit(juju, app_name)
    target_unit = get_app_unit(juju, target_app_name)

    result = juju.cli("show-unit", target_unit, f"--related-unit={app_unit}")
    relations = yaml.safe_load(result).get(target_unit, {}).get("relation-info", [])

    assert relations, f"No relations found between {app_name} and {target_app_name}"
    for relation in relations:
        if relation.get("endpoint") == endpoint:
            return relation.get("related-units", {}).get(app_unit, {}).get("data", {})
    return {}

def get_app_unit(juju: jubilant.Juju, app_name: str, id: int = 0) -> str:
    """Get the unit name for a given application and unit id.

    Args:
        juju: The Juju instance
        app_name: The application name
        id: The unit id (default is 0)

    Returns:
        The unit name as a string

    Raises:
        AssertionError: If the application or unit is not found
    """
    status = juju.status()
    units = status.get_units(app_name)
    unit_names = list(units.keys())
    assert unit_names, f"No units found for application {app_name}"
    assert id < len(unit_names), f"Unit id {id} out of range for application {app_name}"
    return unit_names[id]

def assert_scrape_job(
    juju: jubilant.Juju,
    app_name: str,
    metrics_target: str,
    metrics_path: str,
    labels: Set[str] = set(),
) -> None:
    """Check the endpoint in the relation data bag.

    Args:
        juju: The Juju instance
        app_name: The application name
        metrics_target: The expected metrics target
        metrics_path: The expected metrics path
        labels: The expected set of labels in the scrape job

    Raises:
        AssertionError: If the endpoint is not accessible or does not match expectations
    """
    relation_data = get_unit_relation_data(juju, GRAFANA_AGENT_APP, app_name, COS_ENDPOINT)
    config = json.loads(relation_data.get("config", "{}"))

    scrape_jobs = config.get("metrics_scrape_jobs", [])
    assert scrape_jobs, "No scrape jobs found in relation data"

    for job in scrape_jobs:
        if app_name in job.get("job_name"):
            scrape_job = job
            break
    else:
        assert False, f"No scrape job found for application {app_name}"

    assert job.get("metrics_path") == metrics_path, (
        f"Expected metrics path {metrics_path}, found {job.get('metrics_path')}"
    )

    static_configs = scrape_job.get("static_configs", [])
    assert static_configs, "No static configs found in scrape job"

    targets = static_configs[0].get("targets", [])
    assert targets, "No targets found in static config"

    target = targets[0]
    assert target == metrics_target, (
        f"Expected metrics endpoint {metrics_target}, found {target}"
    )

    config_labels = static_configs[0].get("labels", {})
    for label in labels:
        assert label in config_labels.keys(), (
            f"Expected label {label} not found in scrape job labels {config_labels}"
        )

@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(10),
    reraise=True,
)
def assert_metrics_endpoint(
    juju: jubilant.Juju,
    unit_name: str,
    metrics_port: int,
    metrics_path: str,
) -> None:
    """Assert that the metrics endpoint is accessible.

    Args:
        juju: The Juju instance
        unit_name: The application name
        metrics_port: The expected metrics port
        metrics_path: The expected metrics path

    Raises:
        AssertionError: If the metrics endpoint is not correctly set or accessible
    """
    task = juju.exec(
        f"curl -s http://localhost:{metrics_port}{metrics_path} || echo 'failed'",
        unit=unit_name,
    )
    assert task.stdout.strip() != "failed", (
        f"Metrics endpoint http://localhost:{metrics_port}{metrics_path} is not accessible"
    )

def assert_alerts_rules(
    juju: jubilant.Juju,
    app_name: str,
    alert_rules: Set[str],
):
    """Assert that the alerting rules are correctly provided in the relation data.

    Relation is between the given app and the grafana-agent with cos-agent endpoint.

    Args:
        juju: The Juju instance
        app_name: The application name
        alert_rules: The expected set of alerting rules

    Raises:
        AssertionError: If the alerting rules are not correctly set
    """
    relation_data = get_unit_relation_data(juju, GRAFANA_AGENT_APP, app_name, COS_ENDPOINT)
    config = json.loads(relation_data.get("config", "{}"))

    alerts = config.get("metrics_alert_rules", {})
    assert alerts, "No alerting rules found in relation data"

    groups = alerts.get("groups", [])
    assert groups, "No alerting groups found in relation data"
    relation_alert_rules =  {
        rule["alert"] for group in groups for rule in group["rules"]
    }
    assert alert_rules.issubset(
        relation_alert_rules
    ), (
        f"Provided alert rules: {alert_rules} "
        f"are not included in the relation alert rules: {relation_alert_rules}"
    )
