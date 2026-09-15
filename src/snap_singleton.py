# # Copyright 2026 Canonical Ltd.
# # See LICENSE file for licensing details.

"""File-based registration for singleton snap operations."""

import errno
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SnapRegistrationFile:
    """Registration file for tracking snap registrations by units.

    The files are stored in the lock directory and follow a specific naming convention.
    The configuration fingerprint, if any, is stored as the file's content rather than
    in the filename.

    The filename format is: LCK..<snap_name>--rev<revision>__<unit_name>
    Example: LCK..node-exporter--rev1__unit-0

    Attributes:
        unit_name: Name of the unit registering the snap
        snap_name: Name of the snap being registered
        snap_revision: Revision of the snap being registered
        config_fingerprint: The configuration this unit applies to the snap, used to
            detect conflicts between co-located units of the same application sharing
            this snap. None if unknown (e.g. written by an older charm revision).
    """

    unit_name: str
    snap_name: str
    snap_revision: int
    config_fingerprint: Optional[Dict[str, Any]] = field(default=None, compare=False)

    PREFIX = "LCK.."
    SEPARATOR_REVISION = "--rev"
    SEPARATOR_UNIT = "__"

    @property
    def filename(self):
        """Assemble the filename."""
        return (
            f"{self.PREFIX}"
            f"{self.snap_name}"
            f"{self.SEPARATOR_REVISION}"
            f"{str(self.snap_revision)}"
            f"{self.SEPARATOR_UNIT}"
            f"{SnapRegistrationFile._normalize_name(self.unit_name)}"
        )

    @staticmethod
    def from_filename(filename: str):
        """Build a SnapRegistrationFile by parsing its filename."""
        _, filename = filename.split(SnapRegistrationFile.PREFIX)
        snap_name, filename = filename.split(SnapRegistrationFile.SEPARATOR_REVISION)
        snap_revision, unit_name = filename.split(SnapRegistrationFile.SEPARATOR_UNIT)
        return SnapRegistrationFile(
            unit_name=unit_name,
            snap_name=snap_name,
            snap_revision=int(snap_revision),
        )

    @classmethod
    def _normalize_name(cls, name: str) -> str:
        """Normalize names to contain only alphanumerics, _ and -."""
        return re.sub(r"[^\w-]", "_", name)


class SingletonSnapManager:
    """Manages exclusive access to singleton snaps and configuration files using file-based locks.

    Uses a combination of file-based reference counting for unit tracking and
    file locks for exclusive operations.

    manager = SingletonSnapManager("unit-1")

    Usage:

    .. code-block:: python
        # For unit tracking
        manager.register("snap-one", 1)
        # Use the snap...

        # For unregistering
        manager.unregister("snap-two", 1)

    Raises:
        TimeoutError: If a lock could not be acquired within the specified timeout.
        OSError: on I/O related errors.
    """

    LOCK_DIR: Path = Path("/opt/singleton_snaps")

    def __init__(self, unit_name: str):
        """Initialize the manager with a normalized unit name.

        Args:
            unit_name: Identifier for the current unit
        """
        self.unit_name = unit_name
        self._ensure_lock_dir_exists()

    @classmethod
    def _ensure_lock_dir_exists(cls) -> None:
        """Ensure the lock directory exists with correct permissions."""
        try:
            os.makedirs(cls.LOCK_DIR, exist_ok=True)
            os.chown(cls.LOCK_DIR, os.geteuid(), os.getegid())
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    @classmethod
    def _list_registration_files(cls) -> list:
        """List all valid SnapRegistrationFile objects in the lock directory.

        Returns:
            List of SnapRegistrationFile with all valid registration files in the lock directory.

        Raises:
            OSError: If there's an error accessing the lock directory
        """
        result = []
        cls._ensure_lock_dir_exists()

        for filename in os.listdir(cls.LOCK_DIR):
            try:
                registration_file = SnapRegistrationFile.from_filename(filename)
            except ValueError:
                logger.debug(
                    "Ignoring file in singleton snap registry with unexpected format: %s",
                    filename,
                )
                continue

            try:
                content = cls.LOCK_DIR.joinpath(filename).read_text()
                registration_file.config_fingerprint = json.loads(content) if content else None
            except (OSError, json.JSONDecodeError):
                registration_file.config_fingerprint = None

            result.append(registration_file)

        return result

    @classmethod
    def _get_units(cls, snap_name: str) -> Set[str]:
        """Get all units currently registered for a snap (atomic with directory lock).

        Args:
            snap_name: Name of the snap to get units for

        Returns:
            Set of unit names associated with the snap

        Raises:
            OSError: If there's an error accessing the lock directory
        """
        units = set()

        for registration_file in cls._list_registration_files():
            if registration_file.snap_name == snap_name:
                units.add(registration_file.unit_name)

        return units

    def register(
        self,
        snap_name: str,
        snap_revision: int,
        config_fingerprint: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register current unit as using the specified snap and revision.

        Args:
            snap_name: Name of the snap.
            snap_revision: Revision of the snap to register.
            config_fingerprint: The configuration this unit applies to the snap, used
                to detect conflicts with co-located units of the same application
                sharing this snap. Omit if not relevant.

        Raises:
            OSError: if there is an I/O related error creating the lock file.
        """
        registration_file = SnapRegistrationFile(
            unit_name=self.unit_name,
            snap_name=snap_name,
            snap_revision=snap_revision,
        )
        content = json.dumps(config_fingerprint, sort_keys=True) if config_fingerprint else ""
        with open(self.LOCK_DIR.joinpath(registration_file.filename), "w") as f:
            f.write(content)

    def update_registration(
        self,
        snap_name: str,
        new_revision: int,
        config_fingerprint: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update the registration for the specified snap with a new revision.

        This is useful when the snap revision changes is updated by the charm.

        Args:
            snap_name: Name of the snap.
            new_revision: New revision to update in the lock file.
            config_fingerprint: The configuration this unit applies to the snap, used
                to detect conflicts with co-located units of the same application
                sharing this snap. Omit if not relevant.
        """
        snaps = self.get_snaps()
        if (snap_name, new_revision) in snaps:
            self.register(snap_name, new_revision, config_fingerprint)
            return

        for existing_snap_name, existing_revision in snaps:
            if existing_snap_name == snap_name:
                self.unregister(snap_name, existing_revision)
                break

        self.register(snap_name, new_revision, config_fingerprint)

    def unregister(self, snap_name: str, snap_revision: int) -> None:
        """Unregister current unit from using the specified snap.

        Args:
            snap_name: Name of the snap.
            snap_revision: Revision of the snap to unregister.

        Raises:
            OSError: if there is an I/O related error removing the lock file.
        """
        registration_file = SnapRegistrationFile(
            unit_name=self.unit_name,
            snap_name=snap_name,
            snap_revision=snap_revision,
        )
        os.remove(self.LOCK_DIR.joinpath(registration_file.filename))

    def get_snaps(self) -> Set[Tuple[str, int]]:
        """Get all snaps currently registered for a unit (atomic with directory lock).

        Returns:
            Set of tuples containing snap names and revisions associated with the unit
        """
        snaps = set()

        for registration_file in self._list_registration_files():
            if registration_file.unit_name == SnapRegistrationFile._normalize_name(self.unit_name):
                snaps.add((registration_file.snap_name, registration_file.snap_revision))

        return snaps

    def is_used_by_other_units(self, snap_name: str) -> bool:
        """Check if the specified snap is being used by other units."""
        return any(unit != self.unit_name for unit in self._get_units(snap_name))

    def find_conflicting_colocated_unit(
        self, snap_name: str, app_name: str, config_fingerprint: Dict[str, Any]
    ) -> Optional[Tuple[str, str]]:
        """Find a co-located unit of the same application with a conflicting configuration.

        Two principals of the same subordinate application can be co-located on one
        machine (e.g. two different principal applications sharing a machine, both
        related to this subordinate application). They then share a single snap
        instance, so their configuration must match exactly: only one exporter-port,
        snap-config etc. can be applied to it.

        Note: this only guards against same-app co-location. If two *different*
        generic-exporter apps request the same snap name on the same machine they
        may conflict on snap revision.

        Args:
            snap_name: Name of the snap to check.
            app_name: Juju application name of the current unit.
            config_fingerprint: The configuration this unit would apply to the snap.

        Returns:
            A tuple of (conflicting unit name, human-readable description of the
            differing fields), or None if there is no co-located unit of the same
            application, or all of them share this exact configuration.
        """
        normalized_app_prefix = SnapRegistrationFile._normalize_name(app_name) + "_"
        normalized_self = SnapRegistrationFile._normalize_name(self.unit_name)
        for registration_file in self._list_registration_files():
            if (
                registration_file.snap_name != snap_name
                or registration_file.unit_name == normalized_self
                or not registration_file.unit_name.startswith(normalized_app_prefix)
            ):
                continue

            diff = _describe_config_diff(registration_file.config_fingerprint, config_fingerprint)
            if diff:
                return registration_file.unit_name, diff

        return None


def _describe_config_diff(other: Optional[Dict[str, Any]], mine: Dict[str, Any]) -> Optional[str]:
    """Describe the fields that differ between two configuration fingerprints.

    Args:
        other: The other unit's configuration fingerprint, or None if it could not be
            read (e.g. registered by an older charm revision).
        mine: This unit's configuration fingerprint.

    Returns:
        A human-readable description of the differing fields, or None if they match.
    """
    if other is None:
        return "its configuration could not be verified (registered by an older charm revision)"

    diffs = [
        f"{key} ({other.get(key)!r} vs {mine.get(key)!r})"
        for key in sorted(set(other) | set(mine))
        if other.get(key) != mine.get(key)
    ]
    return ", ".join(diffs) if diffs else None
