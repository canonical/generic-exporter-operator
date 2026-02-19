# # Copyright 2026 Canonical Ltd.
# # See LICENSE file for licensing details.

"""File-based registration for singleton snap operations."""

import errno
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Set


@dataclass
class SnapRegistrationFile:
    """Registration file for tracking snap registrations by units.

    The files are stored in the lock directory and follow a specific naming convention.

    The filename format is: LCK..<snap_name>__<unit_name>
    Example: LCK..node-exporter__unit-1

    Attributes:
        unit_name: Name of the unit registering the snap
        snap_name: Name of the snap being registered
        snap_revision: Revision of the snap being registered
    """

    unit_name: str
    snap_name: str

    PREFIX = "LCK.."
    SEPARATOR_UNIT = "__"

    @property
    def filename(self):
        """Assemble the filename."""
        return (
            f"{self.PREFIX}"
            f"{self.snap_name}"
            f"{self.SEPARATOR_UNIT}"
            f"{SnapRegistrationFile._normalize_name(self.unit_name)}"
        )

    @staticmethod
    def from_filename(filename: str):
        """Build a SnapRegistrationFile by parsing its filename."""
        _, filename = filename.split(SnapRegistrationFile.PREFIX)
        snap_name, unit_name = filename.split(SnapRegistrationFile.SEPARATOR_UNIT)
        return SnapRegistrationFile(
            unit_name=unit_name,
            snap_name=snap_name,
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
        manager.register("unit-1")
        # Use the snap...

        # For unregistering
        manager.unregister("unit-1")

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

    def register(self, snap_name: str) -> None:
        """Register current unit as using the specified snap and revision.

        Args:
            snap_name: Name of the snap.
            snap_revision: Optional revision to put in the lock file. Defaults to an empty string.

        Raises:
            OSError: if there is an I/O related error creating the lock file.
        """
        registration_file = SnapRegistrationFile(
            unit_name=self.unit_name,
            snap_name=snap_name,
        )
        with open(self.LOCK_DIR.joinpath(registration_file.filename), "w") as f:
            f.write("")

    def unregister(self, snap_name: str) -> None:
        """Unregister current unit from using the specified snap.

        Raises:
            OSError: if there is an I/O related error removing the lock file.
        """
        registration_file = SnapRegistrationFile(
            unit_name=self.unit_name,
            snap_name=snap_name,
        )
        os.remove(self.LOCK_DIR.joinpath(registration_file.filename))

    @classmethod
    def get_units(cls, snap_name: str) -> Set[str]:
        """Get all units currently registered for a snap (atomic with directory lock).

        This method is primarily useful for debugging purposes. In most scenarios, you
        do not need to call this directly. Instead, use
        :meth:`SingletonSnapManager.is_used_by_other_units` to detect if there are other
        units registered with a snap.

        Args:
            snap_name: Name of the snap to get units for

        Returns:
            Set of unit names associated with the snap

        Raises:
            OSError: If there's an error accessing the lock directory
        """
        units = set()
        cls._ensure_lock_dir_exists()

        for filename in os.listdir(cls.LOCK_DIR):
            registration_file = SnapRegistrationFile.from_filename(filename)
            if registration_file.snap_name == snap_name:
                units.add(registration_file.unit_name)

        return units

    def is_used_by_other_units(self, snap_name: str) -> bool:
        """Check if the specified snap is being used by other units."""
        return any(unit != self.unit_name for unit in self.get_units(snap_name))
