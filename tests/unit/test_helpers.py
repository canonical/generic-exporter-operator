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
    SnapNotFoundError,
    SnapStoreUnavailableError,
    _fetch_snap_information,
    check_metrics_endpoint,
    decode_secret,
    get_snap_info,
)


@pytest.fixture()
def mock_snap_client():
    """Mock the snapd client used for store lookups, without sleeping between retries."""
    client = MagicMock()
    with patch("utils.snap.SnapClient", return_value=client):
        with patch.object(_fetch_snap_information.retry, "sleep"):
            yield client


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
        "channels": {snap_channel: {"revision": str(expected_revision)}},
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
    mock_snap_client.get_snap_information.return_value = {"confinement": "classic"}

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
        "channels": {snap_channel: {}},
    }

    with patch("utils.snap.SnapClient", return_value=mock_snap_client):
        info = get_snap_info(snap_name, snap_channel)
        assert info is not None
        assert info.name == snap_name
        assert info.revision is None
        assert info.confinement == Confinement.CLASSIC


def test_get_snap_info_retries_transient_error(mock_snap_client):
    """Test that a transient store failure is retried instead of reported."""
    mock_snap_client.get_snap_information.side_effect = [
        snap.SnapAPIError({"message": "too many requests"}, 429, "Too Many Requests", ""),
        {"confinement": "strict", "channels": {"latest/stable": {"revision": "7"}}},
    ]

    info = get_snap_info("test-snap", "latest/stable")

    assert info.revision == 7
    assert mock_snap_client.get_snap_information.call_count == 2


def test_get_snap_info_store_unavailable(mock_snap_client):
    """Test that a persistent store failure is reported with the details of the API error."""
    mock_snap_client.get_snap_information.side_effect = snap.SnapAPIError(
        {"message": "too many requests"}, 429, "Too Many Requests", ""
    )

    with pytest.raises(SnapStoreUnavailableError, match="code=429.*too many requests"):
        get_snap_info("test-snap", "latest/stable")

    assert mock_snap_client.get_snap_information.call_count == 3


@pytest.mark.parametrize(
    "side_effect",
    [
        snap.SnapAPIError({"kind": "snap-not-found"}, 404, "Not Found", ""),
        IndexError("list index out of range"),
    ],
)
def test_get_snap_info_not_found(side_effect, mock_snap_client):
    """Test that a snap the store does not know is reported as not found, after retrying."""
    mock_snap_client.get_snap_information.side_effect = side_effect

    with pytest.raises(SnapNotFoundError):
        get_snap_info("test-snap", "latest/stable")

    assert mock_snap_client.get_snap_information.call_count == 3


def test_get_snap_info_invalid_channels():
    """Test retrieval of snap revision when channels data is invalid."""
    snap_name = "test-snap"
    snap_channel = "latest/stable"

    mock_snap_client = MagicMock()
    mock_snap_client.get_snap_information.return_value = {"channels": "invalid_data"}

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
        "channels": {snap_channel: "invalid_data"},
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
