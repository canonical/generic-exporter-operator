# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""SSDLC (Secure Software Development Lifecycle) Logging.

These events provide critical visibility into the asset's lifecycle and health, and can help
detect potential tampering or malicious activities aimed at altering system behavior.

Logging these events allows for the identification of unauthorized changes to system states,
such as unapproved restarts or unexpected shutdowns, which may indicate security incidents
or availability attacks, or changes to security settings.
"""
from datetime import datetime, timezone
from enum import Enum
from logging import getLogger

logger = getLogger(__name__)


class SSDLCSysEvent(str, Enum):
    """Constant event defined in SSDLC."""

    STARTUP = "sys_startup"
    SHUTDOWN = "sys_shutdown"
    RESTART = "sys_restart"
    CRASH = "sys_crash"

_EVENT_MESSAGE_MAPS = {
    SSDLCSysEvent.STARTUP: "generic-exporter start service %s",
    SSDLCSysEvent.SHUTDOWN: "generic-exporter shutdown service %s",
    SSDLCSysEvent.RESTART: "generic-exporter restart service %s",
    SSDLCSysEvent.CRASH: "generic-exporter service %s crash",
}


def log_ssdlc_system_event(event: SSDLCSysEvent, service: str, msg: str = ""):
    """Log system startup event in SSDLC required format.

    Args:
        event: The SSDLC system event type
        service: The name of the exporter service, e.g. node_exporter
        msg: Optional additional message
    """
    event_msg = _EVENT_MESSAGE_MAPS[event].format(service)

    now = datetime.now(timezone.utc).astimezone()
    logger.warning(
        {
            "datetime": now.isoformat(),
            "appid": f"service.{service}",
            "event": f"{event.value}:{service}",
            "level": "WARN",
            "description": f"{event_msg} {msg}".strip(),
        },
    )
