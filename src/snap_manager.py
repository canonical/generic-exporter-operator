# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The snap management for the Generic Exporter Operator Charm."""

import logging
from typing import List, Optional, Union

from charms.operator_libs_linux.v2 import snap
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

class SnapClient:
    """A class representing a snap exporter service."""

    name: str

    def __init__(
        self, name: str,
    ):
        self.name = name

    @property
    def snap_client(self) -> snap.Snap:
        """Return the snap client."""
        return snap.SnapCache()[self.name]

    @property
    def snap_version(self) -> Optional[str]:
        """Return the snap version if installed."""
        client = self.snap_client
        if client.present:
            return client.version
        return None

    def install(self, revision: Union[str, int], classic: bool = False) -> bool:
        """Install the snap exporter."""
        try:
            snap.add(self.name, revision=str(revision), classic=classic)
            logger.info(
                "Installed snap %s from revision: %s",
                self.name,
                revision,
            )
            self.snap_client.hold()
            return self.snap_client.present is True
        except snap.SnapError as err:
            logger.error(
                "Failed to install %s from revision: %s %s",
                self.name,
                revision,
                err
            )
        return False

    def remove(self) -> bool:
        """Remove the snap exporter."""
        try:
            snap.remove(self.name)
            logger.info("Removed %s", self.name)
            return self.snap_client.present is False
        except snap.SnapError as err:
            logger.error("Failed to remove %s: %s", self.name, err)
        return False

    def set(self, config: dict) -> bool:
        """Set the configuration for the snap exporter."""
        try:
            self.snap_client.set(config, typed=True)
            self.snap_client.restart()
            logger.info("Set config for %s: %s", self.name, config)
            return True
        except snap.SnapError as err:
            logger.error("Failed to set config for %s: %s", self.name, err)
        return False

    def unset(self, keys: List[str]) -> bool:
        """Unset the configuration for the snap exporter."""
        try:
            for key in keys:
                self.snap_client.unset(key)
            self.snap_client.restart()
            logger.info("Unset config keys %s for %s", keys, self.name)
            return True
        except snap.SnapError as err:
            logger.error("Failed to unset config keys %s for %s: %s", keys, self.name, err)
        return False

    def get_config(self) -> dict:
        """Get the configuration for the snap exporter."""
        try:
            return self.snap_client.get(None, typed=True)
        except snap.SnapError as err:
            logger.error("Failed to get config for %s: %s", self.name, err)
        return {}

    def connect(self, plugs: List[str]) -> bool:
        """Connect the specified interfaces for the snap exporter."""
        for plug in plugs:
            full_plug = f"{self.name}:{plug}"
            try:
                self.snap_client.connect(plug)
                logger.info("Connected plug %s for %s", full_plug, self.name)
            except snap.SnapError as err:
                logger.error("Failed to connect plug %s for %s: %s", full_plug, self.name, err)
                return False
        return True

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_fixed(2),
        retry=retry_if_result(lambda x: x is False),
        retry_error_callback=(lambda state: state.outcome.result()), # type: ignore
    )
    def check(self) -> bool:
        """Check if the snap services are active."""
        return all(service.get("active", False) for service in self.snap_client.services.values())

    def enable_and_start(self) -> bool:
        """Enable and start the exporter services."""
        try:
            self.snap_client.start(enable=True)
            logger.info("Enabled and started services for %s", self.name)
            return True
        except snap.SnapError as err:
            logger.error("Failed to enable and start services for %s: %s", self.name, err)
        return False

    def disable_and_stop(self) -> bool:
        """Disable and stop the services."""
        try:
            self.snap_client.stop(disable=True)
            logger.info("Disabled and stopped services for %s", self.name)
            return True
        except snap.SnapError as err:
            logger.error("Failed to disable and stop services for %s: %s", self.name, err)
        return False

    def ensure(self, revision: Union[str, int], classic: bool = False) -> bool:
        """Ensure the snap is configured correctly."""
        try:
            self.snap_client.ensure(
                snap.SnapState.Present,
                revision=str(revision),
                classic=classic,
            )
            logger.info(
                "Configured %s to revision: %s",
                self.name,
                revision
            )
            return True
        except snap.SnapError as err:
            logger.error("Failed to configure %s: %s", self.name, err)
        return False
