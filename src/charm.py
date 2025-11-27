#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Generic Exporter Operator Charm."""

import logging
import socket
from pathlib import Path
from typing import List, Optional, Union

import ops
import yaml
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from pydantic import ValidationError

from config import CharmConfig
from snap_manager import SnapClient
from snap_singleton import SingletonSnapManager
from utils import (
    Confinement,
    check_metrics_endpoint,
    decode_secret_with_retry,
    flatten_dict,
    get_snap_info,
    merge_dicts,
)

logger = logging.getLogger(__name__)


CONFIG_PARENT_DIR = "/run"
ALERTS_RESOURCE_NAME = "alerts"
ALERTS_TARGET_FILE = "alerts.yaml"
COS_AGENT_RELATION_NAME = "cos-agent"

class CharmError(Exception):
    """Base class for all charm errors."""


class CharmConfigError(CharmError):
    """Raised when charm config is invalid."""


class CharmInstallError(CharmError):
    """Raised when charm installation fails."""


class CharmStatusError(CharmError):
    """Raised when charm status check fails."""


class CharmUninstallError(CharmError):
    """Raised when charm uninstallation fails."""


class GenericExporterOperatorCharm(ops.CharmBase):
    """Charm the service."""

    stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.conf = CharmConfig()
        self.stored.set_default(installed_snap_name=None)

        self.framework.observe(self.on.install, self.reconcile)
        self.framework.observe(self.on.config_changed, self.reconcile)
        self.framework.observe(self.on.update_status, self.reconcile)
        self.framework.observe(self.on.remove, self.remove)
        self.framework.observe(self.on.secret_changed, self.reconcile)
        self.framework.observe(self.on[COS_AGENT_RELATION_NAME].relation_changed, self.reconcile)

        self.framework.observe(self.on.dump_alerts_action, self.dump_alerts)

        self.cos = self._configure_cos_relation()

    # PROPERTIES

    @property
    def rules_dir(self) -> Path:
        """Path to the directory where alerting rules are stored."""
        unit_id = self.unit.name.split("/")[1]
        return Path(f"{CONFIG_PARENT_DIR}/{self.app.name}-{unit_id}/")

    @property
    def snap_client(self) -> Optional[SnapClient]:
        """Return the snap client."""
        if self.conf.snap_name:
            return SnapClient(self.conf.snap_name)
        return None

    @property
    def cos_agent_related(self) -> bool:
        """Return whether the cos-agent relation is present."""
        return bool(self.model.relations.get(COS_AGENT_RELATION_NAME))

    # EVENT HANDLERS

    def reconcile(self, event: ops.EventBase) -> None:
        """Reconcile the charm state."""
        try:
            self._validate_config()

            if self.stored.installed_snap_name != self.conf.snap_name:
                self._log_and_set_status(ops.MaintenanceStatus("Installing charm resources"))
                self._remove()
                self._install()

            if isinstance(event, ops.ConfigChangedEvent):
                self._log_and_set_status(ops.MaintenanceStatus("Updating configuration"))
                self._configure()

            self._check_status()
            self._log_and_set_status(ops.ActiveStatus())
        except CharmError as ce:
            self._log_and_set_status(ops.BlockedStatus(str(ce)))

    def remove(self, event: ops.RemoveEvent) -> None:
        """Handle the remove event."""
        self._log_and_set_status(ops.MaintenanceStatus("Removing charm resources"))
        if Path.exists(self.rules_dir):
            for file in self.rules_dir.iterdir():
                file.unlink()
            self.rules_dir.rmdir()

        self._remove()

    # ACTION HANDLERS

    def dump_alerts(self, event: ops.ActionEvent) -> None:
        """Handle the dump-alerts action."""
        path = self.rules_dir / ALERTS_TARGET_FILE
        if path.exists():
            content = path.read_text().strip()
            event.log(f"Configured Alerts:\n{content}")
            event.set_results({"status": "success", "path": str(path)})
        else:
            event.set_results({"status": "no alerts configured"})

    # HELPER METHODS

    def _install(self) -> None:
        """Handle the install event.

        Raises:
            CharmInstallError: If the installation fails
        """
        if self.snap_client is None or self.conf.snap_revision is None:
            logger.info("No snap to install; skipping installation.")
            return

        manager = SingletonSnapManager(self.unit.name)
        manager.register(self.snap_client.name)

        if not self.snap_client.install(self.conf.snap_revision, self.conf.snap_classic):
            raise CharmInstallError(
                f"Failed to install snap: {self.conf.snap_name}. "
                "See juju debug-log for details."
            )

        self.stored.installed_snap_name = self.conf.snap_name
        if not self.snap_client.enable_and_start():
            raise CharmInstallError(
                f"Failed to start snap services for: {self.conf.snap_name}. "
                "See juju debug-log for details."
                )

    def _check_status(self) -> None:
        """Check the status of the snap exporter.

        Raises:
            CharmStatusError: If the snap services are not active
        """
        if missing := self.conf.check_required_fields():
            raise CharmStatusError(
                f"Missing required configuration fields: {', '.join(missing)}"
            )

        if self.snap_client is not None and not self.snap_client.check():
            raise CharmStatusError(f"Snap services for {self.conf.snap_name} are not active.")

        url = f"http://localhost:{self.conf.exporter_port}/{self.conf.metrics_path}"
        if not check_metrics_endpoint(url):
            raise CharmStatusError(
                f"Metrics endpoint for {self.conf.snap_name} is not reachable."
            )

        if not self.cos_agent_related:
            raise CharmStatusError(f"Missing relation: [{COS_AGENT_RELATION_NAME}]")

    def _configure(self) -> None:
        """Configure the snap exporter.

        Raises:
            CharmConfigError: If the configuration fails
        """
        self._set_workload_version()
        self._configure_alerts()

        if self.snap_client is None or self.conf.snap_revision is None:
            logger.info("No snap to configure; skipping configuration.")
            return

        self.snap_client.disable_and_stop()
        if not self.snap_client.ensure(self.conf.snap_revision, self.conf.snap_classic):
            raise CharmConfigError(
                (
                    f"Failed to configure snap: {self.conf.snap_name}. "
                    "See juju debug-log for details."
                )
            )

        keys_to_unset = self._get_snap_config_diff()
        if keys_to_unset:
            if not self.snap_client.unset(keys_to_unset):
                raise CharmConfigError(
                    f"Failed to unset config keys {keys_to_unset} for snap: "
                    f"{self.conf.snap_name}. See juju debug-log for details."
                )
        if self.conf.snap_config and not self.snap_client.set(self.conf.snap_config):
            raise CharmConfigError(
                f"Failed to set config for snap: {self.conf.snap_name}. "
                "See juju debug-log for details."
            )

        if self.conf.snap_plugs:
            if not self.snap_client.connect(self.conf.snap_plugs):
                raise CharmConfigError(
                    (
                        f"Failed to connect plugs {self.conf.snap_plugs} for snap: "
                        f"{self.conf.snap_name}. See juju debug-log for details."
                    )
                )

        if not self.snap_client.enable_and_start():
            raise CharmConfigError(
                (
                    f"Failed to restart snap services for: {self.conf.snap_name}. "
                    "See juju debug-log for details."
                )
            )

    def _remove(self) -> None:
        """Remove the snap exporter.

        Raises:
            CharmUninstallError: If the removal fails
        """
        if self.stored.installed_snap_name is None:
            return

        snap_name = str(self.stored.installed_snap_name)
        manager = SingletonSnapManager(self.unit.name)
        snap_client = SnapClient(snap_name)

        manager.unregister(snap_name)
        if not manager.is_used_by_other_units(snap_name):
            if not snap_client.remove():
                logger.error(
                    "Failed to uninstall snap: %s", snap_name
                )
                raise CharmUninstallError(
                    f"Failed to uninstall snap: {snap_name}. "
                    "See juju debug-log for details."
                )

        self.stored.installed_snap_name = None

    def _configure_alerts(self) -> None:
        """Configure the alerts for the exporter."""
        try:
            resource_path = self.model.resources.fetch(ALERTS_RESOURCE_NAME)
        except (ops.ModelError, NameError): # pragma: no cover
            logger.info("No alerts resource provided; skipping alerts configuration.")
            return

        try:
            content = resource_path.read_text().strip()
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(
                "Failed to read resource '%s': %s; skipping alerts configuration.",
                ALERTS_RESOURCE_NAME,
                e,
            )
            return

        if not content:
            logger.info("Alerts resource is empty; skipping configuration.")
            return

        if not self._validate_alerts_yaml(content):
            logger.warning(
                "Alerts resource '%s' is not valid YAML; skipping alerts configuration.",
                ALERTS_RESOURCE_NAME,
            )
            return

        self.rules_dir.mkdir(parents=True, exist_ok=True)
        destination =  self.rules_dir / ALERTS_TARGET_FILE
        destination.write_text(content)

    def _configure_cos_relation(self) -> Optional[COSAgentProvider]:
        """Configure the COS relation databag."""
        try:
            config = self.load_config(CharmConfig)
        except ValidationError:
            return None

        if not config.exporter_port:
            return None

        return COSAgentProvider(
            self,
            scrape_configs=[
                {
                    "metrics_path": f"/{config.metrics_path}",
                    "static_configs": [
                        {
                            "targets": [f"localhost:{config.exporter_port}"],
                            "labels": {"instance": socket.getfqdn()},
                        }
                    ],
                }
            ],
            metrics_rules_dir=str(self.rules_dir),
            refresh_events=[self.on.config_changed],
        )

    def _set_workload_version(self) -> None:
        """Set the workload version based on the snap version."""
        client = self.snap_client
        if client is not None:
            self.unit.set_workload_version(client.snap_version or "unknown")
        else:
            self.unit.set_workload_version("") # Nothing

    def _get_snap_config_diff(self) -> List[str]:
        """Returns the diff list of keys between new and old snap config.

        Returns:
            List of keys that are not present in the new config
        """
        snap_client = self.snap_client
        old_config = {} if not snap_client else snap_client.get_config()
        new_config = self.conf.snap_config or {}

        old_keys = set(flatten_dict(old_config).keys())
        new_keys = set(flatten_dict(new_config).keys())
        return list(old_keys - new_keys)

    def _log_and_set_status(
        self,
        status: Union[
            ops.ActiveStatus, ops.MaintenanceStatus, ops.BlockedStatus
        ],
    ) -> None:
        """Set the status of the charm and logs the status message.

        Args:
            status: The status to set
        """
        if isinstance(status, ops.ActiveStatus):
            logger.info(status.message)
        elif isinstance(status, ops.MaintenanceStatus):
            logger.info(status.message)
        elif isinstance(status, ops.BlockedStatus):
            logger.warning(status.message)
        else:  # pragma: no cover
            raise ValueError(f"Unknown status type: {status}")

        self.unit.status = status

    def _validate_alerts_yaml(self, content: str) -> bool:
        """Validate the alerts YAML content.

        Args:
            content: The YAML content to validate

        Returns:
            True if the content is valid YAML, False otherwise
        """
        try:
            result = yaml.safe_load(content)
            return isinstance(result, (dict, list))
        except yaml.YAMLError as e:
            logger.warning(
                "YAML parsing error for alerts resource '%s': %s",
                ALERTS_RESOURCE_NAME,
                e,
            )
        return False

    def _validate_config(self) -> None:
        """Check the charm configs and raise error if they are not correct.

        Raises:
            CharmConfigError: If any of the charm configs is not correct
        """
        try:
            config = self.load_config(CharmConfig)
        except ValidationError as ve:
            logger.info(ve)
            messages = [err["msg"].removeprefix("Value error, ") for err in ve.errors()]
            raise CharmConfigError(
                f"Invalid configuration: {', '.join(messages)}"
            )

        if config.snap_name:
            snap_info = get_snap_info(config.snap_name, config.snap_channel)
            if snap_info is None:
                raise CharmConfigError(
                    f"Could not fetch info for snap {config.snap_name}. "
                    "See juju debug-log for details."
                )

            config.snap_revision = snap_info.revision or config.snap_revision
            if config.snap_channel is not None and config.snap_revision is None:
                raise CharmConfigError(
                    (
                        f"Could not determine revision for snap {config.snap_name} "
                        f"on channel {config.snap_channel}."
                    )
                )
            if snap_info.confinement == Confinement.CLASSIC and not config.snap_classic:
                raise CharmConfigError(
                    (
                        f"Snap {config.snap_name} requires classic confinement. "
                        "Please enable 'snap-classic'."
                    )
                )

        if config.snap_config_secret:
            try:
                secret_config = decode_secret_with_retry(self.model, config.snap_config_secret)
                config.snap_config = merge_dicts(secret_config, config.snap_config or {})
            except Exception as e:
                raise CharmConfigError(str(e))

        self.conf = config


if __name__ == "__main__":  # pragma: nocover
    ops.main(GenericExporterOperatorCharm)
