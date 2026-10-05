#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for two principal applications co-located on the same machine.

Scenario: two different principal applications are placed on the *same* machine (e.g.
via an explicit placement directive, or by coincidence of the model's placement
policy), and both are related to the *same* generic-exporter application over
juju-info. This produces two generic-exporter subordinate units sharing one machine,
which in turn share a single installed snap instance.

This must not permanently block: every unit of a Juju application always receives the
exact same application config, so co-located units of this application can only ever
disagree transiently (e.g. mid-rollout of a config change before every unit's hook has
fired) -- see test_charm.py::test_blocked_when_colocated_units_conflict and
test_active_when_colocated_units_match for the corresponding unit-level coverage. Once
settled, both units must reach active, and each must still report its own principal.
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


def test_deploy_colocated_principals(
    juju: jubilant.Juju, charm: str, app_name: str, base: str
) -> None:
    """Deploy two principal apps onto the same machine, both related to one exporter."""
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

    # Co-locate the second principal on the exact same machine as the first.
    juju.wait(
        lambda status: jubilant.all_agents_idle(status, UBUNTU_APP_NAME),
        timeout=TIMEOUT,
    )
    machine = juju.status().get_units(UBUNTU_APP_NAME)[f"{UBUNTU_APP_NAME}/0"].machine
    juju.deploy(
        app=UBUNTU_APP_NAME_2, charm="ubuntu", channel=UBUNTU_CHANNEL, base=base, to=machine
    )

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
            # scenario, so it legitimately stays "blocked" forever; just wait for its
            # agent to settle so its cos-agent relation data is populated.
            and jubilant.all_agents_idle(status, OTCOL_APP)
        ),
        error=jubilant.any_error,
        timeout=TIMEOUT,
    )


def test_principals_are_colocated(juju: jubilant.Juju) -> None:
    """Sanity check that both principals actually landed on the same machine."""
    status = juju.status()
    ubuntu_units = status.get_units(UBUNTU_APP_NAME)
    ubuntu_two_units = status.get_units(UBUNTU_APP_NAME_2)

    machines = {unit.machine for unit in ubuntu_units.values()} | {
        unit.machine for unit in ubuntu_two_units.values()
    }
    assert len(machines) == 1, f"Expected both principals on the same machine, got {machines}"


def test_two_subordinate_units_created(juju: jubilant.Juju, app_name: str) -> None:
    """Assert that co-location produced one exporter unit per principal, neither blocked."""
    status = juju.status()
    exporter_units = status.get_units(app_name)

    assert len(exporter_units) == 2, (
        f"Expected 2 generic-exporter subordinate units (one per co-located principal), "
        f"got {len(exporter_units)}: {list(exporter_units.keys())}"
    )
    for unit_name, unit in exporter_units.items():
        assert unit.workload_status.current == "active", (
            f"Unit {unit_name} is not active: {unit.workload_status}"
        )


def test_labels_identify_each_colocated_principal(juju: jubilant.Juju, app_name: str) -> None:
    """Assert each co-located subordinate's scrape job is labelled with its own principal."""
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
        f"Expected each co-located subordinate to report a distinct principal, "
        f"covering both {{{UBUNTU_APP_NAME}, {UBUNTU_APP_NAME_2}}}, "
        f"got {seen_principal_apps}"
    )


def test_remove_colocated_principals(juju: jubilant.Juju, app_name: str) -> None:
    """Clean up all applications deployed in this module."""
    juju.remove_application(app_name)
    juju.remove_application(OTCOL_APP, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME, destroy_storage=True)
    juju.remove_application(UBUNTU_APP_NAME_2, destroy_storage=True)

    juju.wait(
        lambda status: app_name not in status.apps,
        timeout=TIMEOUT,
    )
