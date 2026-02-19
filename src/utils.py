# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The helper methods for the Generic Exporter Operator Charm."""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests
from charms.operator_libs_linux.v2 import snap
from ops.model import Model, ModelError, SecretNotFoundError
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_fixed,
)

logger = logging.getLogger(__name__)

class Confinement(Enum):
    """Snap confinement types."""

    STRICT = "strict"
    CLASSIC = "classic"

@dataclass
class SnapInfo:
    """Data class to hold snap information."""

    name: str
    revision: Optional[int]
    confinement: Confinement

class SecretInvalidContentError(ValueError):
    """A mandatory field is invalid in the secret content."""

class SecretAccessError(ModelError):
    """The secret access was not successful."""

@retry(
    stop=stop_after_attempt(5),
    wait=wait_fixed(2),
    retry=retry_if_result(lambda x: x is False),
    retry_error_callback=(lambda state: state.outcome.result()), # type: ignore
)
def check_metrics_endpoint(url: str) -> bool:
    """Check if the metrics endpoint is reachable.

    Returns:
        bool: True if the metrics endpoint is reachable, False otherwise.
    """
    try:
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        logger.warning("Metrics endpoint %s is not reachable yet.", url)
        return False

def flatten_dict(data: dict, parent_key: str = "") -> dict:
    """Flatten a nested dict to dot-notation keys.

    Args:
        data: The dictionary to flatten.
        parent_key: The base key string for recursion.

    Returns:
        A flattened dictionary with dot-notation keys.

    Example:
        {"web": {"port": 1922}} -> {"web.port": 1922}
    """
    sep = "."
    items = []

    for k, v in data.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key).items())
        else:
            items.append((new_key, v))

    return dict(items)

def merge_dicts(data_1: dict, data_2: dict, path: str = "") -> dict:
    """Deep-merge two dicts safely.

    Raises:
        ValueError: if two dicts have a field conflict.

    Returns:
        A merged dict.
    """
    result = dict(data_1)

    for key, value in data_2.items():
        current_path = f"{path}.{key}" if path else key

        if key not in result:
            result[key] = value
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value, current_path)
        else:
            raise ValueError(f"The configs conflict at key: {current_path}")

    return result

def get_snap_info(snap_name: str, snap_channel: Optional[str] = None) -> Optional[SnapInfo]:
    """Extract the revision from a snap channel string.

    Args:
        snap_name: Name of the snap.
        snap_channel: Optional snap channel (e.g., 'latest/stable', 'latest/edge').
            If provided, the revision for that channel will be fetched.

    Returns:
        Optional[SnapInfo]: SnapInfo object if snap found, None otherwise.
    """
    client = snap.SnapClient()

    try:
        response = client.get_snap_information(snap_name)
        if snap_channel:
            return SnapInfo(
                name=snap_name,
                revision=_get_revision_from_response(response, snap_channel),
                confinement=Confinement(response.get("confinement", "strict")),
            )
        else:
            return SnapInfo(
                name=snap_name,
                revision=None,
                confinement=Confinement(response.get("confinement", "strict")),
            )
    except snap.SnapAPIError as err:
        logger.error("Failed to get snap information for %s: %s", snap_name, err)
        return None

def _get_revision_from_response(response: dict, snap_channel: str) -> Optional[int]:
    """Helper function to extract revision from snap information response.

    Args:
        response: The snap information response dictionary.
        snap_channel: The snap channel string.

    Returns:
        Optional[int]: The revision number if found, None otherwise.
    """
    channels = response.get("channels", {})
    if not isinstance(channels, dict):
        return None
    channel_info = channels.get(snap_channel, {})
    if not isinstance(channel_info, dict):
        return None
    revision = channel_info.get("revision")
    if revision and isinstance(revision, str):
        return int(revision)
    return None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    retry=retry_if_exception_type(SecretAccessError),
    reraise=True,
)
def decode_secret_with_retry(model: Model, secret_id: str) -> dict:
    """Try to decode the secret key, retry for 3 times before failing."""
    return decode_secret(model, secret_id)


def decode_secret(model: Model, id: str) -> dict:
    """Decode the secret with given secret_id and return the config as a dict.

    Args:
        model: Juju model
        id: The ID (URI) of the secret that contains the config

    Raises:
        SecretAccessError: When the secret access failes.
        SecretInvalidContentError: When the secret's content is invalid.

    Returns:
        dict: The sensitive snap config
    """
    try:
        secret_content = model.get_secret(id=id).get_content(refresh=True)
        config = secret_content.get("config")

        if not config:
            raise SecretInvalidContentError(f"The config field is missing in secret '{id}'.")

        parsed = json.loads(config)
        if not isinstance(parsed, dict):
            raise SecretInvalidContentError(
                f"The config field must decode to dict in secret '{id}'."
            )
        return parsed
    except SecretInvalidContentError:
        raise
    except json.JSONDecodeError:
        raise SecretInvalidContentError(f"The config field must be valid JSON in secret '{id}'.")
    except SecretNotFoundError:
        raise SecretAccessError(f"Secret '{id}' does not exist.")
    except ModelError as me:
        if "permission denied" in str(me):
            raise SecretAccessError(f"Permission for secret '{id}' has not been granted.")
        raise SecretAccessError(f"Could not decode secret '{id}'.")
    except Exception:
        raise SecretAccessError(f"Could not decode secret '{id}'.")
