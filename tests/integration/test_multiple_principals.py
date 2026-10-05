#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for relating one generic-exporter app to multiple principals.

Scenario: one generic-exporter app is related to two separate principal applications
each deployed on their own machine. Each principal should receive its own subordinate
unit and both should reach active/idle.

This validates that the charm works without a `limit: 1` constraint on the juju-info
relation endpoint, and that with `label-principal-unit` enabled each subordinate unit's
published scrape job is labelled with its own co-located principal, not the other one.
"""

import json
import logging

import jubilant
from helpers import (
    COS_ENDPOINT,
    JUJU_INFO_ENDPOINT,
    OTCOL_APP,
    OTCOL_CHANNEL,
    SMARTCTL_EXPORTER_PORT,
    SMARTCTL_SNAP_NAME,
    TIMEOUT,
    UBUNTU_APP_NAME,
    UBUNTU_APP_NAME_2,
    UBUNTU_CHANNEL,
    get_unit_relation_data,
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
            "label-principal-unit": True,
        },
    )
    juju.deploy(OTCOL_APP, channel=OTCOL_CHANNEL, base=base)
    juju.deploy(UBUNTU_APP_NAME, channel=UBUNTU_CHANNEL, base=base)
    juju.deploy(app=UBUNTU_APP_NAME_2, charm="ubuntu", channel=UBUNTU_CHANNEL, base=base)

    juju.integrate(f"{app_name}:{COS_ENDPOINT}", f"{OTCOL_APP}:{COS_ENDPOINT}")
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")
    juju.integrate(f"{app_name}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME_2}:{JUJU_INFO_ENDPOINT}")
    # opentelemetry-collector is itself a subordinate: it needs its own juju-info relation
    # to spawn a unit at all. Relate it to both principals so it lands co-located with each
    # generic-exporter unit, making its published scrape-job relation data inspectable.
    juju.integrate(f"{OTCOL_APP}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME}:{JUJU_INFO_ENDPOINT}")
    juju.integrate(
        f"{OTCOL_APP}:{JUJU_INFO_ENDPOINT}", f"{UBUNTU_APP_NAME_2}:{JUJU_INFO_ENDPOINT}"
    )

    juju.wait(
        lambda status: (
            jubilant.all_active(status, app_name, UBUNTU_APP_NAME, UBUNTU_APP_NAME_2)
            # opentelemetry-collector has no configured telemetry destination in this
            # scenario (no send-remote-write/grafana-dashboards/etc.), so it legitimately
            # stays "blocked" forever; just wait for its agent to settle so its cos-agent
            # relation data is populated.
            and jubilant.all_agents_idle(status, OTCOL_APP)
        ),
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


def test_labels_identify_each_principal_unit(juju: jubilant.Juju, app_name: str) -> None:
    """Assert each subordinate's scrape job is labelled with its own principal, not the other."""
    status = juju.status()
    exporter_units = status.get_units(app_name)
    otcol_units = status.get_units(OTCOL_APP)

    seen_principal_apps = set()
    for exporter_unit_name, exporter_unit in exporter_units.items():
        otcol_unit_name = next(
            (name for name, unit in otcol_units.items() if unit.machine == exporter_unit.machine),
            None,
        )
        assert otcol_unit_name, (
            f"No {OTCOL_APP} unit co-located with {exporter_unit_name} "
            f"on machine {exporter_unit.machine}"
        )

        relation_data = get_unit_relation_data(
            juju,
            OTCOL_APP,
            app_name,
            COS_ENDPOINT,
            app_unit=exporter_unit_name,
            target_unit=otcol_unit_name,
        )
        config = json.loads(relation_data.get("config", "{}"))
        scrape_jobs = config.get("metrics_scrape_jobs", [])
        assert scrape_jobs, f"No scrape jobs found for {exporter_unit_name}"
        scrape_job = next(job for job in scrape_jobs if app_name in job["job_name"])
        labels = scrape_job["static_configs"][0]["labels"]

        principal_app = labels.get("juju_principal_application")
        principal_unit = labels.get("juju_principal_unit")
        principal_unit_number = labels.get("juju_principal_unit_number")

        assert principal_app in (UBUNTU_APP_NAME, UBUNTU_APP_NAME_2), (
            f"Unit {exporter_unit_name} reports unexpected principal application {principal_app!r}"
        )
        assert principal_unit == f"{principal_app}/{principal_unit_number}", (
            f"Unit {exporter_unit_name} labels are inconsistent: "
            f"juju_principal_unit={principal_unit!r}, "
            f"juju_principal_unit_number={principal_unit_number!r}"
        )
        seen_principal_apps.add(principal_app)

    assert seen_principal_apps == {UBUNTU_APP_NAME, UBUNTU_APP_NAME_2}, (
        f"Expected each subordinate to report a distinct principal, "
        f"covering both {{{UBUNTU_APP_NAME}, {UBUNTU_APP_NAME_2}}}, "
        f"got {seen_principal_apps}"
    )


def test_remove_multiple_principals(juju: jubilant.Juju, app_name: str) -> None:
    """Clean up all applications deployed in this module."""
    juju.remove_application(app_name)
    juju.remove_application(OTCOL_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME_2, destroy_storage=True)

    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )
