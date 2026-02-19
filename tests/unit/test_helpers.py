# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charms.operator_libs_linux.v2 import snap
from ops.model import ModelError
from requests import RequestException

from utils import (
    Confinement,
    SecretAccessError,
    check_metrics_endpoint,
    decode_secret,
    get_snap_info,
)


def test_check_metrics_endpoint_success():
    """Test successful metrics endpoint check."""
    url = "http://example.com/metrics"
    with patch("utils.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = check_metrics_endpoint(url)
        assert result is True

def test_check_metrics_endpoint_failure():
    """Test failed metrics endpoint check."""
    url = "http://example.com/metrics"
    with patch("utils.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = check_metrics_endpoint(url)
        assert result is False

def test_check_metrics_endpoint_exception():
    """Test metrics endpoint check with exception."""
    url = "http://example.com/metrics"
    with patch("utils.requests.get", side_effect=RequestException("Network error")):
        result = check_metrics_endpoint(url)
        assert result is False


def test_get_snap_info_success_with_channel():
    """Test successful retrieval of snap info."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"
    expected_revision = 1234

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {
        "confinement": "strict",
        "channels": {
            snap_channel: {"revision": str(expected_revision)}
        }
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is not None
        assert info.name == snap_name
        assert info.revision == expected_revision
        assert info.confinement == Confinement.STRICT

def test_get_snap_info_success_without_channel():
    """Test successful retrieval of snap info without channel."""
    snap_name = "test-snap"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {
        "confinement": "classic"
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name)
        assert info is not None
        assert info.name == snap_name
        assert info.revision is None
        assert info.confinement == Confinement.CLASSIC

def test_get_snap_info_no_revision():
    """Test retrieval of snap revision when no revision is found."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {
        "confinement": "classic",
        "channels": {
            snap_channel: {}
        }
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is not None
        assert info.name == snap_name
        assert info.revision is None
        assert info.confinement == Confinement.CLASSIC

def test_get_snap_info_api_error():
    """Test retrieval of snap revision when SnapAPIError is raised."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.side_effect = snap.SnapAPIError({}, 404, "Err", "Err")

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is None

def test_get_snap_info_invalid_channels():
    """Test retrieval of snap revision when channels data is invalid."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {
        "channels": "invalid_data"
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is not None
        assert info.revision is None
        assert info.name == snap_name
        assert info.confinement == Confinement.STRICT

def test_get_snap_info_invalid_channel_info():
    """Test retrieval of snap revision when channel info data is invalid."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {
        "confinement": "classic",
        "channels": {
            snap_channel: "invalid_data"
        }
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is not None
        assert info.revision is None
        assert info.name == snap_name
        assert info.confinement == Confinement.CLASSIC


def test_decode_secret_permission_denied():
    """Test secret decoding when permission is denied."""
    secret_id = "secret:abcdefghij1234567890"

    mock_model = MagicMock()
    mock_model.get_secret.side_effect = ModelError("permission denied for secret")

    with pytest.raises(SecretAccessError) as exc_info:
        decode_secret(mock_model, secret_id)

    assert f"Permission for secret '{secret_id}' has not been granted" in str(exc_info.value)


def test_decode_secret_model_error():
    """Test secret decoding when a generic ModelError is raised."""
    secret_id = "secret:abcdefghij1234567890"

    mock_model = MagicMock()
    mock_model.get_secret.side_effect = ModelError("some other model error")

    with pytest.raises(SecretAccessError) as exc_info:
        decode_secret(mock_model, secret_id)

    assert f"Could not decode secret '{secret_id}'" in str(exc_info.value)


def test_decode_secret_unexpected_exception():
    """Test secret decoding when an unexpected exception is raised."""
    secret_id = "secret:abcdefghij1234567890"

    mock_model = MagicMock()
    mock_model.get_secret.side_effect = RuntimeError("unexpected error")

    with pytest.raises(SecretAccessError) as exc_info:
        decode_secret(mock_model, secret_id)

    assert f"Could not decode secret '{secret_id}'" in str(exc_info.value)
