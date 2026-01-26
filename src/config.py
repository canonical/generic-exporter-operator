# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Configuration for the charm."""

import json
from typing import Any, Dict, List, Optional

from ops.model import Secret
from pydantic import BaseModel, field_validator, model_validator

REQUIRED_FIELDS = ["snap_name", "exporter_port"]

class CharmConfig(BaseModel):
    """Manager for the user configuration of the charm."""

    snap_name: Optional[str] = None
    exporter_port: Optional[int] = None
    snap_classic: bool = False
    snap_channel: Optional[str] = None
    snap_revision: Optional[int] = None
    snap_config: Optional[Dict[str, Any]] = None
    metrics_path: str = "metrics"
    snap_plugs: Optional[List[str]] = None
    snap_config_secret: Optional[str] = None

    def check_required_fields(self) -> Optional[List[str]]:
        """Ensure that required fields are present."""
        missing_fields = []
        for field in REQUIRED_FIELDS:
            if getattr(self, field, None) is None:
                missing_fields.append(field.replace('_', '-'))
        if missing_fields:
            return missing_fields
        return None

    @field_validator("exporter_port", mode="before")
    @classmethod
    def validate_port(cls, v):
        """Ensure that exporter_port is within valid range."""
        if v is None:
            return v
        if not isinstance(v, int) or not (1 <= v <= 65535):
            raise ValueError("exporter-port must be between 1 and 65535")
        return v

    @field_validator("snap_name", mode="before")
    @classmethod
    def validate_snap_name(cls, v):
        """Ensure that snap_name is a non-empty string."""
        if v is None:
            return v
        if not isinstance(v, str) or not v.strip():
            raise ValueError("snap-name must be a non-empty string")
        return v.strip()

    @field_validator("snap_revision", mode="before")
    @classmethod
    def validate_revision(cls, v):
        """Ensure that snap_revision is a positive integer if set."""
        if v is None:
            return None
        if not isinstance(v, int) or v <= 0:
            raise ValueError("snap-revision must be a positive integer")
        return v

    @field_validator("snap_channel", mode="before")
    @classmethod
    def validate_channel(cls, v):
        """Ensure that snap_channel is either None or a non-empty string."""
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError("snap-channel must be a non-empty string")
        return v.strip()

    @field_validator("metrics_path", mode="after")
    @classmethod
    def normalize_metrics_path(cls, v: str):
        """Ensure no leading forward slash in metrics path."""
        return v.strip().lstrip('/')

    @field_validator("snap_plugs", mode="before")
    @classmethod
    def validate_snap_plug(cls, v):
        """Ensure that snap_plugs is either None or a non-empty string."""
        if v is None:
            return None
        plugs = [plug.strip() for plug in v.split(",") if plug.strip()]
        if not plugs:
            raise ValueError("snap-plugs must contain at least one valid plug name")
        return plugs

    @field_validator("snap_config", mode="before")
    @classmethod
    def validate_snap_config(cls, v):
        """Ensure that snap_config is a JSON string or dict."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, dict):
                    raise ValueError("snap-config JSON must decode to a dictionary")
                return parsed
            except json.JSONDecodeError:
                raise ValueError("snap-config must be valid JSON")
        else:
            return None

    @field_validator("snap_config_secret", mode="before")
    @classmethod
    def normalize_snap_config_secret(cls, v: Secret):
        """Extract id from Secret object."""
        return v.id

    @model_validator(mode="after")
    def check_channel_revision(self):
        """Ensure that snap_channel and snap_revision are not both set or both unset."""
        if self.snap_channel and self.snap_revision is not None:
            raise ValueError("snap-channel and snap-revision cannot both be set")

        if self.snap_channel is None and self.snap_revision is None:
            self.snap_channel = "latest/stable"

        return self
