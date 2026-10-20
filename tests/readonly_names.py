"""The one definition of "which SDK method names are reads".

Shared by the three read-only guards so they cannot drift apart:

- ``tests/test_sdk_surface.py`` -- every ``self._client.<name>(`` call in the adapter
- ``tests/test_collector_readonly.py`` -- every name a full collection cycle invokes
- ``tests/test_probe.py`` -- every step on the probe allowlist

This is an allow-list, not a deny-list. A deny-list of write prefixes has to be
extended every time eero-api adds a verb (8.4.0 added ``add_``, ``remove_``,
``clear_`` and ``resend_`` helpers that the old list did not know about); an
allow-list rejects any new name by default. Authentication (``login``/``verify``)
is the only sanctioned non-GET and is listed explicitly.
"""

import re

#: Method-name prefixes that denote a read on ``EeroClient``.
READ_NAME_RE = re.compile(r"^(get_|list_|has_)")

#: The only non-read SDK calls the exporter may make (authentication).
AUTH_NAMES = frozenset({"login", "verify"})


def is_read_only_name(name: str) -> bool:
    """Return ``True`` when ``name`` is a read or a sanctioned auth call."""
    return name in AUTH_NAMES or READ_NAME_RE.match(name) is not None


def is_read_name(name: str) -> bool:
    """Return ``True`` only for reads; auth calls are *not* reads."""
    return READ_NAME_RE.match(name) is not None


#: A sample of real eero-api write helpers, used to self-test the allow-list.
#: Includes the four 8.4.0 additions the old prefix deny-list missed.
KNOWN_SDK_WRITES = (
    "add_to_blacklist",
    "remove_from_blacklist",
    "clear_auth_data",
    "resend_verification_code",
    "create_burst_reporter",
    "reboot_network",
    "request_support",
    "set_ipv6_upstream",
    "set_network_ad_block",
    "set_weekday_bedtime",
    "block_device",
    "unblock_device",
    "run_speed_test",
    "logout",
)
