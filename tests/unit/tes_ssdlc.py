# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from datetime import datetime, timezone
from unittest import mock

import pytest

from ssdlc import SSDLCSysEvent, log_ssdlc_system_event


@pytest.fixture()
def mock_ssdlc_logger():
    with mock.patch("ssdlc.logger") as mock_ssdlc_logger:
        yield mock_ssdlc_logger

@pytest.fixture()
def mock_ssdlc_datetime():
    with mock.patch("ssdlc.datetime") as mock_ssdlc_datetime:
        yield mock_ssdlc_datetime


def test_log_ssdlc_system_event_with_service_name(self, mock_ssdlc_datetime, mock_ssdlc_logger):
    """Test logging with exporter_name string."""
    # Setup mock datetime
    mock_now = mock.MagicMock()
    mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
    mock_ssdlc_datetime.now.return_value.astimezone.return_value = mock_now

    # Call the function with exporter name
    log_ssdlc_system_event(SSDLCSysEvent.STARTUP, "node-exporter")

    # Verify logger was called correctly
    mock_ssdlc_logger.warning.assert_called_once()
    logged_data = mock_ssdlc_logger.warning.call_args[0][0]

    self.assertEqual(logged_data["datetime"], "2025-01-01T12:00:00+00:00")
    self.assertEqual(logged_data["appid"], "service.node-exporter")
    self.assertEqual(logged_data["event"], "sys_startup:node-exporter")
    self.assertEqual(logged_data["level"], "WARN")
    self.assertIn("generic-exporter start service", logged_data["description"])

@pytest.mark.parametrize(
    "event,service_name,msg",
    [
        (SSDLCSysEvent.STARTUP, "node-exporter", ""),
        (SSDLCSysEvent.SHUTDOWN, "smarctl-exporter", ""),
        (SSDLCSysEvent.RESTART, "node-exporter", ""),
        (
            SSDLCSysEvent.CRASH,
            "other-exporter",
            "Connection timeout",
        ),
    ]
)
def test_log_ssdlc_system_event_all_events(
    self, event, service_name, msg, mock_ssdlc_datetime, mock_ssdlc_logger
):
    """Test logging all event types."""
    # Setup mock datetime
    mock_now = mock.MagicMock()
    mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
    mock_ssdlc_datetime.now.return_value.astimezone.return_value = mock_now

    # Call the function
    log_ssdlc_system_event(event, service_name, msg)

    # Verify logger was called
    mock_ssdlc_logger.warning.assert_called_once()
    logged_data = mock_ssdlc_logger.warning.call_args[0][0]

    self.assertEqual(logged_data["datetime"], "2025-01-01T12:00:00+00:00")
    self.assertEqual(logged_data["appid"], f"service.{service_name}")
    self.assertEqual(logged_data["event"], f"{event.value}:{service_name}")
    self.assertEqual(logged_data["level"], "WARN")
    self.assertIsInstance(logged_data["description"], str)
    if msg:
        self.assertIn(msg, logged_data["description"])

def test_log_ssdlc_system_event_with_additional_message(
    self,
    mock_ssdlc_datetime,
    mock_ssdlc_logger
):
    """Test logging with additional message."""
    # Setup mock datetime
    mock_now = mock.MagicMock()
    mock_now.isoformat.return_value = "2025-01-01T12:00:00+00:00"
    mock_ssdlc_datetime.now.return_value.astimezone.return_value = mock_now

    # Call with additional message
    additional_msg = "Service failed due to network error"
    log_ssdlc_system_event(SSDLCSysEvent.CRASH, "node-exporter", additional_msg)

    # Verify the additional message is included
    logged_data = mock_ssdlc_logger.warning.call_args[0][0]
    self.assertIn(additional_msg, logged_data["description"])

def test_log_ssdlc_system_event_datetime_format(self, mock_ssdlc_datetime, mock_ssdlc_logger):
    """Test that datetime is in ISO 8601 format with timezone."""
    # Use a real datetime to test formatting
    test_time = datetime(2025, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
    mock_ssdlc_datetime.now.return_value.astimezone.return_value = test_time

    log_ssdlc_system_event(SSDLCSysEvent.STARTUP, "node-exporter")

    logged_data = mock_ssdlc_logger.warning.call_args[0][0]
    # Verify ISO 8601 format with timezone
    self.assertRegex(
        logged_data["datetime"],
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}",
    )
