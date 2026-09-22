"""Strictly read-only live API probe for eero-api 8.0.1.

This module answers the shape questions in the 4.0.0 migration plan (§7.0) by
walking a fixed allowlist of documented **read** endpoints against a real mesh
and emitting a *redacted key tree* for every response: structure, types, array
lengths, booleans, numbers, timestamps and a small set of bounded enum values —
never a value that identifies a person, a device or a secret.

Safety design (all four layers are independent):

1. **Write guard.** Every non-``GET`` path in ``eero.api.base.BaseAPI`` is
   patched before the client is built, so a misclassified step raises
   :class:`ProbeWriteBlocked` *before* a request object is constructed. The
   low-level dispatcher ``_request`` is patched too, so nothing can bypass the
   verb helpers.
2. **Allowlist.** Only the methods named in :data:`PROBE_STEPS` are ever
   called; each is a documented read in the SDK's ``wiki/API-Reference.md``.
   :func:`iter_probe_methods` exposes the list so the test suite can assert
   that every entry exists on ``EeroClient`` and that none matches a write
   name pattern.
3. **Budget and rate limit.** A :class:`RequestMeter` hooks the SDK's GET path,
   caps the total number of GETs and spaces them out. The run stops cleanly on
   budget exhaustion, on the first rate-limit response and on any
   authentication failure.
4. **Redaction.** :func:`redact` is applied to every response before anything
   is written or logged. Redaction is deliberately over-eager: an unknown key
   holding a string yields only its length.

The probe never opens the caller's session file for writing: it works on a
0600 copy inside a private temporary directory, and reports only the copy's
schema version and whether a token key is present — never the token.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from eero import EeroClient, classify_error_code
from eero.api import base as _eero_base
from eero.exceptions import (
    EeroAPIException,
    EeroAuthenticationException,
    EeroException,
    EeroRateLimitException,
)

from . import __version__

__all__ = [
    "ENUM_KEYS",
    "PROBE_STEPS",
    "ProbeBudgetExhausted",
    "ProbeContext",
    "ProbeOptions",
    "ProbeStep",
    "ProbeWriteBlocked",
    "RequestMeter",
    "StepResult",
    "build_markdown_summary",
    "inspect_session_file",
    "install_write_guard",
    "iter_probe_methods",
    "redact",
    "run_probe_cli",
    "write_guard",
]

_LOGGER = logging.getLogger(__name__)

#: SDK version the probe actually ran against (installed distribution), recorded
#: in the report and its file name. The allowlist was written against 8.0.1.
try:
    TARGET_SDK_VERSION = importlib.metadata.version("eero-api")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev checkouts
    TARGET_SDK_VERSION = "8.0.1"

#: Default number of GET requests the probe is allowed to issue.
DEFAULT_BUDGET = 80

#: Default maximum request rate, in requests per second.
DEFAULT_RATE = 1.0

#: Default output directory for the report pair.
DEFAULT_OUT_DIR = Path("probes")


# ---------------------------------------------------------------------------
# Layer 1 — write guard
# ---------------------------------------------------------------------------


class ProbeWriteBlocked(RuntimeError):  # noqa: N818 - reads better than ...Error here
    """Raised when anything attempts a non-``GET`` request under the guard.

    The probe is read-only by construction; this exception means a bug (a
    misclassified step, or an SDK read helper that issues a write internally),
    never a user error.
    """


class ProbeBudgetExhausted(RuntimeError):  # noqa: N818 - matches ProbeWriteBlocked
    """Raised by :class:`RequestMeter` when the GET budget is used up."""


#: Verb helpers on ``BaseAPI`` that must never fire. ``BaseAPI`` exposes no
#: ``patch`` helper in 8.0.1; it is included defensively so a future release
#: that adds one is still covered (the guard skips names that do not exist).
_WRITE_VERB_METHODS = ("post", "put", "delete", "patch")

#: Method-dispatching entry points that carry an explicit HTTP method string.
#: ``_request`` is the single place the SDK touches ``aiohttp``
#: (``base.py:535`` — ``self.session.request(method, url, ...)``), so guarding
#: it closes every bypass around the verb helpers above.
_DISPATCH_METHODS = ("_request", "_request_with_get_retry")


def _guarded_verb(name: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a replacement for a write verb helper that always refuses."""

    async def _refuse(_self: Any, url: str = "", *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ProbeWriteBlocked(
            f"read-only probe blocked a {name.upper()} request before it was built"
        )

    return _refuse


def _guarded_dispatch(
    name: str, original: Callable[..., Awaitable[dict[str, Any]]]
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a replacement dispatcher that refuses any method other than GET."""

    async def _checked(
        _self: Any, method: str, url: str = "", *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        if str(method).upper() != "GET":
            raise ProbeWriteBlocked(
                f"read-only probe blocked a {str(method).upper()} request "
                f"at BaseAPI.{name} before it was built"
            )
        return await original(_self, method, url, *args, **kwargs)

    return _checked


def install_write_guard() -> Callable[[], None]:
    """Patch every non-GET path on ``BaseAPI`` and return an uninstaller.

    Note:
        This also blocks the SDK's server-driven session refresh, which is a
        ``POST`` (``base.py:597-662``). That is deliberate: a refresh rewrites
        the credential record. If a probe run hits it, the run aborts with
        :class:`ProbeWriteBlocked` and the maintainer should re-login and try
        again rather than have the probe mutate a session.

    Returns:
        A zero-argument callable that restores the original attributes. Calling
        it more than once is harmless.
    """
    target = _eero_base.BaseAPI
    saved: dict[str, Any] = {}

    for name in _WRITE_VERB_METHODS:
        if not hasattr(target, name):
            continue
        saved[name] = getattr(target, name)
        setattr(target, name, _guarded_verb(name))

    for name in _DISPATCH_METHODS:
        if not hasattr(target, name):
            continue
        original = cast(Callable[..., Awaitable[dict[str, Any]]], getattr(target, name))
        saved[name] = original
        setattr(target, name, _guarded_dispatch(name, original))

    _LOGGER.debug("write guard installed on %s", ", ".join(sorted(saved)))

    def _uninstall() -> None:
        while saved:
            name, original = saved.popitem()
            setattr(target, name, original)

    return _uninstall


@contextmanager
def write_guard() -> Iterator[None]:
    """Context manager wrapper around :func:`install_write_guard`."""
    uninstall = install_write_guard()
    try:
        yield
    finally:
        uninstall()


# ---------------------------------------------------------------------------
# Layer 3 — budget and rate limiting
# ---------------------------------------------------------------------------


class RequestMeter:
    """Counts GETs, enforces the budget and spaces requests out.

    Args:
        budget: Maximum number of GET requests allowed for the whole run.
        rate: Maximum requests per second. Non-positive disables pacing.
        sleep: Injected sleep coroutine function (for tests).
        clock: Injected monotonic clock (for tests).
    """

    def __init__(
        self,
        budget: int = DEFAULT_BUDGET,
        rate: float = DEFAULT_RATE,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.budget = budget
        self.rate = rate
        self.gets = 0
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.monotonic
        self._last: float | None = None

    @property
    def min_interval(self) -> float:
        """Minimum seconds between two requests, ``0.0`` when unpaced."""
        return 1.0 / self.rate if self.rate > 0 else 0.0

    @property
    def remaining(self) -> int:
        """GETs still allowed by the budget."""
        return max(self.budget - self.gets, 0)

    async def acquire(self) -> None:
        """Account for one GET, sleeping first if the rate cap requires it.

        Raises:
            ProbeBudgetExhausted: If the budget is already used up.
        """
        if self.gets >= self.budget:
            raise ProbeBudgetExhausted(f"GET budget of {self.budget} exhausted")
        interval = self.min_interval
        if interval > 0.0 and self._last is not None:
            wait = interval - (self._clock() - self._last)
            if wait > 0.0:
                await self._sleep(wait)
        self._last = self._clock()
        self.gets += 1


def install_get_meter(meter: RequestMeter) -> Callable[[], None]:
    """Route every SDK GET through ``meter``; return an uninstaller."""
    target = _eero_base.BaseAPI
    original = cast(Callable[..., Awaitable[dict[str, Any]]], target.get)

    async def _metered(
        _self: Any, url: str, auth_token: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        await meter.acquire()
        return await original(_self, url, auth_token, **kwargs)

    target.get = _metered  # type: ignore[assignment]

    def _uninstall() -> None:
        target.get = original  # type: ignore[assignment]

    return _uninstall


# ---------------------------------------------------------------------------
# Layer 4 — redaction
# ---------------------------------------------------------------------------

#: Keys whose *value* may be kept verbatim when it also matches
#: :data:`_ENUM_VALUE_RE`. Everything outside this set becomes a length.
ENUM_KEYS = frozenset(
    {
        "band",
        "bands",
        "cadence",
        "connection_mode",
        "connection_type",
        "cadence_unit",
        "frequency",
        "gateway_type",
        "granularity_unit",
        "health",
        "insight_type",
        "interface",
        "kind",
        "level",
        "mlo_mode",
        "mode",
        "power_source",
        "protocol",
        "role",
        "schema_version",
        "severity",
        "source",
        "speed",
        "state",
        "status",
        "subnet_kind",
        "type",
        "unit",
        "units",
        "update_status",
        "wan_type",
        "wifi_generation",
        "wireless_mode",
    }
)

#: Exact key names that are never exported in any form. Matching is done on a
#: snake_case-normalised, separator-stripped form (see :func:`_normalise_key`)
#: so that camelCase surface forms (``segmentId``) and flat lower forms
#: (``segmentid``) both hit the same rule as their snake_case spelling.
_NEVER_EXPORT_EXACT = frozenset(
    {
        "active_operational_dataset",
        "bssid",
        "bssids",
        "bssids_with_bands",
        "chassisid",
        "domain",
        "domains",
        "email",
        "emails",
        "gateway",
        "host",
        "hostname",
        "id",
        "ip",
        "ipv4",
        "ipv6",
        "ips",
        "key",
        "keys",
        "latitude",
        "location",
        "longitude",
        "mac",
        "macs",
        "mask",
        "name",
        "nickname",
        "owner",
        "passphrase",
        "password",
        "phone",
        "portid",
        "prefix",
        "psk",
        "resources",
        "router",
        "secret",
        "segmentid",
        "serial",
        "ssid",
        "ssids",
        "subdomain",
        "systemdescription",
        "token",
        "url",
        "urls",
        "uuid",
    }
)

#: Substrings that force redaction wherever they appear in a key name.
_NEVER_EXPORT_SUBSTRINGS = (
    "address",
    "api_key",
    "apikey",
    "bssid",
    "cookie",
    "credential",
    "email",
    "iccid",
    "imei",
    "msisdn",
    "passphrase",
    "password",
    "phone",
    "postal",
    "psk",
    "secret",
    "serial",
    "ssid",
    "subdomain",
    "token",
    "username",
)

#: Key suffixes that force redaction.
_NEVER_EXPORT_SUFFIXES = (
    "_id",
    "_ids",
    "_ip",
    "_ips",
    "_key",
    "_mac",
    "_macs",
    "_name",
    "_names",
    "_url",
    "_urls",
    "etag",
)

#: The only child of a ``geo_ip`` object that may be described at all.
_GEO_IP_ALLOWED = frozenset({"isp"})

#: Container keys that would otherwise match a never-export rule but are worth
#: descending into, because a stricter per-child rule applies below them (or,
#: for ``name_servers``, because its only child of interest -- ``mode`` -- is
#: not itself sensitive).
_TRAVERSE_KEYS = frozenset({"geo_ip", "name_servers"})

_ENUM_VALUE_RE = re.compile(r"^[A-Za-z0-9_./-]{1,32}$")

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}" r"(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)

#: Values that look like an identifier are never kept, even under an enum key.
_IDENTIFIER_RE = re.compile(
    r"^(?:"
    r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}"  # MAC
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # UUID
    r"|\d{1,3}(?:\.\d{1,3}){3}"  # IPv4
    r"|[0-9a-fA-F]{12,}"  # long hex blob
    r"|\d{6,}"  # long numeric id
    r")$"
)

#: A dict key is structural metadata, but some payloads key objects *by* a MAC
#: or an id. Keys that do not look like identifiers are kept verbatim.
_SAFE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\- ]{0,48}$")

_REDACTED = "<redacted>"

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalise_key(key: str) -> str:
    """Fold camelCase and snake_case spellings of a key onto one form.

    ``segmentId``, ``segment_id`` and ``segmentid`` (an already-flat key, as
    LLDP-style payloads use) all normalise to ``segmentid`` so a single
    exact-match entry covers every surface form the API uses.
    """
    text = _CAMEL_BOUNDARY_RE.sub("_", str(key)).lower()
    return _NON_ALNUM_RE.sub("", text)


#: :data:`_NEVER_EXPORT_EXACT`, pre-normalised once for exact-key lookups.
_NEVER_EXPORT_EXACT_NORM = frozenset(_normalise_key(entry) for entry in _NEVER_EXPORT_EXACT)


def _is_never_export(key: str, path: Sequence[str]) -> bool:
    """Return True when ``key`` must never have its value described."""
    lowered = key.lower()
    if lowered in _TRAVERSE_KEYS:
        return False
    if _normalise_key(key) in _NEVER_EXPORT_EXACT_NORM:
        return True
    if any(token in lowered for token in _NEVER_EXPORT_SUBSTRINGS):
        return True
    if lowered.endswith(_NEVER_EXPORT_SUFFIXES):
        return True
    # geo_ip: everything except `isp`, at any depth below a geo_ip parent.
    if "geo_ip" in {part.lower() for part in path} and lowered not in _GEO_IP_ALLOWED:
        return True
    return False


def _type_name(value: Any) -> str:
    """Short, stable type label used in the key tree."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, Mapping):
        return "dict"
    if isinstance(value, (list, tuple)):
        return "list"
    if value is None:
        return "null"
    return "unknown"


def _safe_key(key: Any) -> str:
    """Return a key name that is safe to print, or a length placeholder."""
    text = str(key)
    if _SAFE_KEY_RE.match(text) and not _IDENTIFIER_RE.match(text):
        return text
    return f"<key:{len(text)}>"


def _redact_string(key: str, value: str) -> Any:
    """Describe a string: kept only for timestamps and bounded enums."""
    if _ISO8601_RE.match(value):
        return value
    if key.lower() in ENUM_KEYS and _ENUM_VALUE_RE.match(value) and not _IDENTIFIER_RE.match(value):
        return value
    return {"_type": "str", "_len": len(value)}


#: Cap on how many distinct enum values :func:`_merge_trees` will keep in a
#: merged ``_values`` list before giving up and reporting the type alone.
_MAX_MERGED_VALUES = 16


def _is_marker_dict(value: Any) -> bool:
    """Return True when ``value`` is a type-descriptor dict, not a real object."""
    return isinstance(value, Mapping) and bool(value) and all(str(k).startswith("_") for k in value)


def _as_descriptor(value: Any) -> Mapping[str, Any]:
    """Wrap a raw scalar as a bare ``{"_type": ...}`` marker; pass dicts through."""
    if isinstance(value, Mapping):
        return value
    return {"_type": _type_name(value)}


def _collect_kept_values(value: Any) -> set[str]:
    """Return the raw enum strings ``value`` represents, if any."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return set(value.get("_values", []))
    return set()


def _merge_scalar_markers(
    left_raw: Any, right_raw: Any, left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge two same-type, non-list marker dicts, keeping only stable fields.

    ``left_raw``/``right_raw`` are the pre-descriptor values (a raw kept
    string, or an already-merged marker carrying ``_values``); the enum
    values they represent are collected from these, not from ``left``/
    ``right``, which have already been wrapped into bare ``{"_type": ...}``
    markers and would otherwise lose that information.
    """
    type_name = left.get("_type")
    if type_name == "str":
        values = sorted(_collect_kept_values(left_raw) | _collect_kept_values(right_raw))
        merged: dict[str, Any] = {"_type": "str"}
        if values and all(_ISO8601_RE.match(item) for item in values):
            # Per-item timestamps (e.g. device last_active) are behavioural data;
            # across a list only the fact that the field is a timestamp matters.
            merged["_iso8601"] = True
        elif values and len(values) <= _MAX_MERGED_VALUES:
            merged["_values"] = values
        if "_value" in left and left.get("_value") == right.get("_value"):
            merged["_value"] = left["_value"]
        return merged
    merged = {"_type": type_name}
    if "_value" in left and left.get("_value") == right.get("_value"):
        merged["_value"] = left["_value"]
    if "_keys" in left and left.get("_keys") == right.get("_keys"):
        merged["_keys"] = left["_keys"]
    return merged


def _merge_list_markers(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Merge two ``_type: list`` markers, recursing into ``_item``."""
    merged: dict[str, Any] = {"_type": "list"}
    left_len, right_len = left.get("_len"), right.get("_len")
    if left_len is not None and left_len == right_len:
        merged["_len"] = left_len
    left_item, right_item = left.get("_item"), right.get("_item")
    if left_item is not None or right_item is not None:
        merged["_item"] = _merge_trees(
            left_item if left_item is not None else {"_type": "null"},
            right_item if right_item is not None else {"_type": "null"},
        )
    values = sorted(set(left.get("_values", [])) | set(right.get("_values", [])))
    if values and all(_ISO8601_RE.match(item) for item in values):
        merged["_iso8601"] = True
    elif values and len(values) <= _MAX_MERGED_VALUES:
        merged["_values"] = values
    if "_value" in left and left.get("_value") == right.get("_value"):
        merged["_value"] = left["_value"]
    return merged


def _merge_markers(
    left_raw: Any, right_raw: Any, left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge two marker dicts of possibly different ``_type``."""
    left_type, right_type = left.get("_type"), right.get("_type")
    if left_type != right_type:
        return {"_type": "mixed", "_types": sorted({str(left_type), str(right_type)})}
    if left_type == "list":
        return _merge_list_markers(left, right)
    return _merge_scalar_markers(left_raw, right_raw, left, right)


def _merge_trees(left: Any, right: Any, *, top: bool = False) -> Any:
    """Merge two redacted item trees into one that covers both shapes.

    Real objects (dicts with actual field names) are merged key by key, and a
    per-key type clash is recorded as a sibling ``_note: "mixed"`` rather than
    replacing the object -- one divergent field must never erase an otherwise
    well-known shape. At the top of a list (``top=True``), where there is no
    dominant shape to protect, a dict/scalar clash collapses to a single
    ``{"_type": "mixed", "_types": [...]}`` marker instead.

    Args:
        left: A previously merged (or freshly redacted) item tree.
        right: The next item tree to fold in.
        top: True when merging whole list items (as opposed to merging the
            subtree found under one shared key of two list-item objects).

    Returns:
        The merged tree.
    """
    if left == right:
        return left

    left_desc, right_desc = _as_descriptor(left), _as_descriptor(right)
    left_marker, right_marker = _is_marker_dict(left_desc), _is_marker_dict(right_desc)

    if not left_marker and not right_marker:
        merged: dict[str, Any] = dict(left_desc)
        for key, value in right_desc.items():
            merged[key] = _merge_trees(merged[key], value) if key in merged else value
        return merged

    if left_marker and right_marker:
        return _merge_markers(left, right, left_desc, right_desc)

    # One side is a real object, the other a type marker (a genuine shape clash).
    real = right_desc if left_marker else left_desc
    marker = left_desc if left_marker else right_desc
    if top:
        return {"_type": "mixed", "_types": sorted({"dict", str(marker.get("_type"))})}
    merged = dict(real)
    merged["_note"] = "mixed"
    return merged


def _never_export_marker(value: Any) -> dict[str, Any]:
    """Describe a never-export value: type only, plus shape metadata.

    Lists keep their length and dicts keep their key count -- neither reveals
    a value, only how big the redacted thing was.
    """
    if isinstance(value, (list, tuple)):
        return {"_type": "list", "_len": len(value), "_value": _REDACTED}
    if isinstance(value, Mapping):
        return {"_type": "dict", "_keys": len(value), "_value": _REDACTED}
    return {"_type": _type_name(value), "_value": _REDACTED}


def _redact_list(items: Sequence[Any], *, key: str, path: Sequence[str]) -> dict[str, Any]:
    """Redact a list, merging every item's tree into one ``_item`` shape.

    A list of scalars keeps its item type in ``_item`` and, when the items
    are enum-kept strings, moves the accumulated values up to a sibling
    ``_values`` -- so ``_item`` stays a bare type descriptor, matching the
    shape of a list of objects.
    """
    values = list(items)
    tree: dict[str, Any] = {"_type": "list", "_len": len(values)}
    if not values:
        return tree

    redacted_items = [redact(item, key=key, path=path) for item in values]
    merged = redacted_items[0]
    for later in redacted_items[1:]:
        merged = _merge_trees(merged, later, top=True)
    item_descriptor = dict(_as_descriptor(merged))
    kept_values = item_descriptor.pop("_values", None)
    tree["_item"] = item_descriptor
    if kept_values:
        tree["_values"] = kept_values
    return tree


def redact(value: Any, *, key: str = "", path: Sequence[str] = ()) -> Any:
    """Turn an API response into a redacted key tree.

    Booleans always survive, regardless of the key they were found under --
    a flag is not an identifying value. Numbers, ``None``, ISO-8601
    timestamps and allowlisted enum strings survive everywhere else. Every
    other string becomes ``{"_type": "str", "_len": N}``. Anything under a
    never-export key (other than a boolean) is reduced to its type and shape
    (length or key count) alone.

    Args:
        value: The value to describe.
        key: The key ``value`` was found under (``""`` at the root).
        path: The chain of ancestor keys, used for the ``geo_ip`` rule.

    Returns:
        A JSON-serialisable tree containing no identifying value.
    """
    if isinstance(value, bool):
        return value

    if key and _is_never_export(key, path):
        return _never_export_marker(value)

    if isinstance(value, Mapping):
        child_path = (*path, key) if key else tuple(path)
        return {
            _safe_key(child_key): redact(child_value, key=str(child_key), path=child_path)
            for child_key, child_value in value.items()
        }

    if isinstance(value, (list, tuple)):
        return _redact_list(value, key=key, path=path)

    if value is None or isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        return _redact_string(key, value)

    return {"_type": _type_name(value)}


# ---------------------------------------------------------------------------
# Layer 2 — the read allowlist
# ---------------------------------------------------------------------------


@dataclass
class ProbeContext:
    """Values discovered by earlier steps and consumed by later ones.

    Every field here holds a raw identifier. The context is kept in memory
    only: nothing in it is ever written to the report or to a log line.
    """

    start: str
    end: str
    network_id: str | None = None
    eero_id: str | None = None
    eero_serial: str | None = None
    eero_os_version: str | None = None
    device_id: str | None = None
    device_mac: str | None = None
    profile_id: str | None = None


StepRunner = Callable[[EeroClient, ProbeContext], Awaitable[dict[str, Any]]]
StepExtractor = Callable[[ProbeContext, Any], None]
StepGuard = Callable[[ProbeContext], bool]


@dataclass(frozen=True)
class ProbeStep:
    """One allowlisted read.

    Attributes:
        label: Stable identifier used in the report and by ``--only``.
        method: The ``EeroClient`` method the step calls. Asserted by the test
            suite to exist on the SDK and to not match a write name pattern.
        run: Coroutine factory issuing the call.
        requires: Context attributes that must be set for the step to run.
        extract: Optional hook that pulls identifiers out of the response.
        guard: Optional extra predicate deciding whether the step applies.
    """

    label: str
    method: str
    run: StepRunner
    requires: tuple[str, ...] = ()
    extract: StepExtractor | None = None
    guard: StepGuard | None = None

    def is_applicable(self, ctx: ProbeContext) -> bool:
        """Return True when every prerequisite for this step is satisfied."""
        if any(getattr(ctx, name, None) in (None, (), "") for name in self.requires):
            return False
        return self.guard(ctx) if self.guard else True


def _as_items(payload: Any, *keys: str) -> list[Any]:
    """Pull a list out of any of the shapes the eero API uses.

    The API returns ``{"data": {"data": [...]}}``, ``{"data": [...]}``,
    ``{"data": {"<key>": [...]}}`` or a bare list depending on the endpoint
    (see the SDK wiki, ``Raw-Response-Format.md``).
    """
    data = payload.get("data", payload) if isinstance(payload, Mapping) else payload
    for _ in range(3):
        if isinstance(data, list):
            return list(data)
        if not isinstance(data, Mapping):
            return []
        for key in (*keys, "data"):
            if key in data:
                data = data[key]
                break
        else:
            return []
    return list(data) if isinstance(data, list) else []


def _id_from_url(value: Any) -> str | None:
    """Extract the trailing identifier from an API resource URL."""
    if not isinstance(value, str) or not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1] or None


def _first_mapping(payload: Any, *keys: str) -> Mapping[str, Any] | None:
    """Return the first mapping in a list-shaped payload, if any."""
    for item in _as_items(payload, *keys):
        if isinstance(item, Mapping):
            return item
    return None


def _extract_network(ctx: ProbeContext, payload: Any) -> None:
    """Record the first network's id from ``get_networks()``."""
    item = _first_mapping(payload, "networks")
    if item is not None:
        ctx.network_id = _id_from_url(item.get("url")) or ctx.network_id


def _extract_eero(ctx: ProbeContext, payload: Any) -> None:
    """Record the first eero's id, serial and OS version."""
    item = _first_mapping(payload, "eeros")
    if item is None:
        return
    ctx.eero_id = _id_from_url(item.get("url")) or ctx.eero_id
    serial = item.get("serial")
    if isinstance(serial, str) and serial:
        ctx.eero_serial = serial
    version = item.get("os_version") or item.get("os")
    if isinstance(version, str) and version:
        ctx.eero_os_version = version


def _extract_device(ctx: ProbeContext, payload: Any) -> None:
    """Record the first device's id and MAC (MAC is needed by data usage)."""
    item = _first_mapping(payload, "devices")
    if item is None:
        return
    ctx.device_id = _id_from_url(item.get("url")) or ctx.device_id
    mac = item.get("mac")
    if isinstance(mac, str) and mac:
        ctx.device_mac = mac


def _extract_profile(ctx: ProbeContext, payload: Any) -> None:
    """Record the first profile's id."""
    item = _first_mapping(payload, "profiles")
    if item is not None:
        ctx.profile_id = _id_from_url(item.get("url")) or ctx.profile_id


_NET = ("network_id",)

#: The complete read allowlist, in execution order. Every ``method`` below is
#: documented as a read in the SDK's ``wiki/API-Reference.md``; no write-named
#: method appears anywhere in this module.
PROBE_STEPS: tuple[ProbeStep, ...] = (
    ProbeStep("account", "get_account", lambda c, x: c.get_account()),
    ProbeStep("networks", "get_networks", lambda c, x: c.get_networks(), extract=_extract_network),
    ProbeStep("network", "get_network", lambda c, x: c.get_network(x.network_id), requires=_NET),
    ProbeStep(
        "eeros",
        "get_eeros",
        lambda c, x: c.get_eeros(x.network_id),
        requires=_NET,
        extract=_extract_eero,
    ),
    ProbeStep(
        "devices",
        "get_devices",
        lambda c, x: c.get_devices(x.network_id),
        requires=_NET,
        extract=_extract_device,
    ),
    ProbeStep(
        "devices-thread",
        "get_devices",
        lambda c, x: c.get_devices(x.network_id, thread=True),
        requires=_NET,
    ),
    ProbeStep(
        "devices-proxied-node",
        "get_devices",
        lambda c, x: c.get_devices(x.network_id, proxied_node=True),
        requires=_NET,
    ),
    ProbeStep(
        "profiles",
        "get_profiles",
        lambda c, x: c.get_profiles(x.network_id),
        requires=_NET,
        extract=_extract_profile,
    ),
    ProbeStep(
        "guest-network",
        "get_guest_network",
        lambda c, x: c.get_guest_network(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "speed-tests",
        "get_speed_tests",
        lambda c, x: c.get_speed_tests(x.network_id, limit=5),
        requires=_NET,
    ),
    # --- data usage family, `day` window -----------------------------------
    ProbeStep(
        "data-usage-network",
        "get_data_usage",
        lambda c, x: c.get_data_usage(x.network_id, start=x.start, end=x.end, cadence="daily"),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-breakdown",
        "get_data_usage_breakdown",
        lambda c, x: c.get_data_usage_breakdown(
            x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-devices",
        "get_devices_data_usage",
        lambda c, x: c.get_devices_data_usage(
            x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-eeros-summary",
        "get_eeros_data_usage_summary",
        lambda c, x: c.get_eeros_data_usage_summary(
            x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-unprofiled-devices",
        "get_unprofiled_devices_data_usage",
        lambda c, x: c.get_unprofiled_devices_data_usage(
            x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-unprofiled-summary",
        "get_unprofiled_data_usage_summary",
        lambda c, x: c.get_unprofiled_data_usage_summary(
            x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-report-settings",
        "get_data_usage_report_settings",
        lambda c, x: c.get_data_usage_report_settings(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "data-usage-profile",
        "get_profile_data_usage",
        lambda c, x: c.get_profile_data_usage(
            str(x.profile_id), x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=("network_id", "profile_id"),
    ),
    ProbeStep(
        "data-usage-device",
        "get_device_data_usage",
        lambda c, x: c.get_device_data_usage(
            str(x.device_mac), x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=("network_id", "device_mac"),
    ),
    ProbeStep(
        "data-usage-eero",
        "get_eero_data_usage",
        lambda c, x: c.get_eero_data_usage(
            str(x.eero_id), x.network_id, start=x.start, end=x.end, cadence="daily"
        ),
        requires=("network_id", "eero_id"),
    ),
    # --- insights -----------------------------------------------------------
    ProbeStep(
        "insights-network-adblock",
        "get_insights",
        lambda c, x: c.get_insights(
            x.network_id, start=x.start, end=x.end, insight_type="adblock", cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "insights-network-blocked",
        "get_insights",
        lambda c, x: c.get_insights(
            x.network_id, start=x.start, end=x.end, insight_type="blocked", cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "insights-network-inspected",
        "get_insights",
        lambda c, x: c.get_insights(
            x.network_id, start=x.start, end=x.end, insight_type="inspected", cadence="daily"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "insights-devices",
        "get_devices_insights",
        lambda c, x: c.get_devices_insights(
            x.network_id, start=x.start, end=x.end, cadence="daily", insight_type="blocked"
        ),
        requires=_NET,
    ),
    ProbeStep(
        "insights-profiles",
        "get_profiles_insights",
        lambda c, x: c.get_profiles_insights(
            x.network_id, start=x.start, end=x.end, cadence="daily", insight_type="blocked"
        ),
        requires=_NET,
    ),
    # --- entitlements and premium ------------------------------------------
    ProbeStep(
        "entitlement-features",
        "get_entitlement_features",
        lambda c, x: c.get_entitlement_features(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "upsell-features",
        "get_upsell_features",
        lambda c, x: c.get_upsell_features(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "model-capabilities",
        "get_model_capabilities",
        lambda c, x: c.get_model_capabilities(x.network_id),
        requires=_NET,
    ),
    ProbeStep("premium-customer", "get_premium_customer", lambda c, x: c.get_premium_customer()),
    # --- backup internet and cellular --------------------------------------
    ProbeStep(
        "backup-internet",
        "get_backup_internet",
        lambda c, x: c.get_backup_internet(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "cellular-backup-usage",
        "get_cellular_backup_usage",
        lambda c, x: c.get_cellular_backup_usage(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "cellular-backup-events",
        "get_cellular_backup_events",
        lambda c, x: c.get_cellular_backup_events(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "backup-access-points",
        "list_backup_access_points",
        lambda c, x: c.list_backup_access_points(x.network_id),
        requires=_NET,
    ),
    # --- radio and roaming settings ----------------------------------------
    ProbeStep(
        "wpa3-per-band",
        "get_wpa3_per_band",
        lambda c, x: c.get_wpa3_per_band(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "fast-transition",
        "get_fast_transition",
        lambda c, x: c.get_fast_transition(x.network_id),
        requires=_NET,
    ),
    # --- access control -----------------------------------------------------
    ProbeStep(
        "permissions",
        "get_permissions",
        lambda c, x: c.get_permissions(x.network_id),
        requires=_NET,
    ),
    ProbeStep("members", "get_members", lambda c, x: c.get_members(x.network_id), requires=_NET),
    # --- notifications ------------------------------------------------------
    ProbeStep(
        "notification-settings",
        "get_notification_settings",
        lambda c, x: c.get_notification_settings(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "notifications-has-unread",
        "has_unread_notifications",
        lambda c, x: c.has_unread_notifications(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "notification-history",
        "get_notification_history",
        lambda c, x: c.get_notification_history(x.network_id),
        requires=_NET,
    ),
    # --- DNS policy ---------------------------------------------------------
    ProbeStep(
        "dns-advanced-content-filter",
        "get_advanced_content_filter",
        lambda c, x: c.get_advanced_content_filter(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "dns-policy-applications",
        "get_dns_policy_applications",
        lambda c, x: c.get_dns_policy_applications(str(x.profile_id), x.network_id),
        requires=("network_id", "profile_id"),
    ),
    # --- network configuration ---------------------------------------------
    ProbeStep(
        "subnets-config",
        "get_subnets_config",
        lambda c, x: c.get_subnets_config(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "multistaticip",
        "get_multistaticip",
        lambda c, x: c.get_multistaticip(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "power-saving-schedules",
        "get_power_saving_schedules",
        lambda c, x: c.get_power_saving_schedules(x.network_id),
        requires=_NET,
    ),
    ProbeStep("thread", "get_thread", lambda c, x: c.get_thread(x.network_id), requires=_NET),
    ProbeStep("updates", "get_updates", lambda c, x: c.get_updates(x.network_id), requires=_NET),
    ProbeStep(
        "diagnostics",
        "get_diagnostics",
        lambda c, x: c.get_diagnostics(x.network_id),
        requires=_NET,
    ),
    ProbeStep("routing", "get_routing", lambda c, x: c.get_routing(x.network_id), requires=_NET),
    ProbeStep("support", "get_support", lambda c, x: c.get_support(x.network_id), requires=_NET),
    ProbeStep(
        "ac-compat", "get_ac_compat", lambda c, x: c.get_ac_compat(x.network_id), requires=_NET
    ),
    # --- transfer statistics ------------------------------------------------
    ProbeStep(
        "transfer-network",
        "get_transfer_stats",
        lambda c, x: c.get_transfer_stats(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "transfer-device",
        "get_transfer_stats",
        lambda c, x: c.get_transfer_stats(x.network_id, str(x.device_mac)),
        requires=("network_id", "device_mac"),
    ),
    # --- channel utilisation: `band` is optional and, live, returned every
    # band for every eero in one call -- the per-band vocabulary is visible
    # instead on each eero's `radio_channel_stats` keys (band_2_4GHz,
    # band_5GHz_low, band_5GHz_high, band_5GHz_full, band_6GHz), so no
    # per-band fan-out is needed here.
    ProbeStep(
        "channel-utilization",
        "get_channel_utilization",
        lambda c, x: c.get_channel_utilization(x.network_id, start=x.start, end=x.end),
        requires=_NET,
    ),
    # --- misc network reads -------------------------------------------------
    ProbeStep(
        "network-scan",
        "get_network_scan",
        lambda c, x: c.get_network_scan(x.network_id),
        requires=_NET,
    ),
    ProbeStep(
        "app-events",
        "get_app_events",
        lambda c, x: c.get_app_events(x.network_id, page_size=20),
        requires=_NET,
    ),
    # --- per-eero, per-device, per-profile reads ----------------------------
    ProbeStep(
        "eero-nightlight",
        "get_nightlight",
        lambda c, x: c.get_nightlight(str(x.eero_id), x.network_id),
        requires=("network_id", "eero_id"),
    ),
    ProbeStep(
        "eero-connections",
        "get_connections",
        lambda c, x: c.get_connections(str(x.eero_id), x.network_id),
        requires=("network_id", "eero_id"),
    ),
    ProbeStep(
        "eero-ouicheck",
        "get_ouicheck",
        lambda c, x: c.get_ouicheck(
            x.network_id, serial=str(x.eero_serial), version=str(x.eero_os_version)
        ),
        requires=("network_id", "eero_serial", "eero_os_version"),
    ),
    ProbeStep(
        "device-labels",
        "get_device_labels",
        lambda c, x: c.get_device_labels(str(x.device_id), x.network_id),
        requires=("network_id", "device_id"),
    ),
    ProbeStep(
        "profile-schedules",
        "get_schedules",
        lambda c, x: c.get_schedules(str(x.profile_id), x.network_id),
        requires=("network_id", "profile_id"),
    ),
)

#: Coverage items from plan §7.0 that have no read method in eero-api 8.0.1.
#: Recorded in the report instead of being guessed at.
NOT_AVAILABLE: tuple[tuple[str, str], ...] = ()


def iter_probe_methods() -> tuple[str, ...]:
    """Return the distinct ``EeroClient`` method names the probe may call."""
    return tuple(sorted({step.method for step in PROBE_STEPS}))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """The redacted outcome of a single probe step."""

    label: str
    method: str
    outcome: str
    elapsed_ms: float = 0.0
    gets: int = 0
    exception: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    error_group: str | None = None
    top_level_keys: list[str] = field(default_factory=list)
    tree: Any = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of the result."""
        return {
            "label": self.label,
            "method": self.method,
            "outcome": self.outcome,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "gets": self.gets,
            "exception": self.exception,
            "status_code": self.status_code,
            "error_code": self.error_code,
            "error_group": self.error_group,
            "top_level_keys": self.top_level_keys,
            "tree": self.tree,
        }


def _describe_exception(exc: BaseException, result: StepResult) -> None:
    """Fill the error fields of ``result`` without copying any message body."""
    result.exception = type(exc).__name__
    status = getattr(exc, "status_code", None)
    result.status_code = status if isinstance(status, int) else None
    code = getattr(exc, "error_code", None)
    result.error_code = code if isinstance(code, str) else None
    group = classify_error_code(result.error_code)
    result.error_group = group.value if group is not None else None


async def execute_steps(
    client: Any,
    ctx: ProbeContext,
    meter: RequestMeter,
    *,
    steps: Sequence[ProbeStep] = PROBE_STEPS,
    only: str | None = None,
) -> list[StepResult]:
    """Run the allowlist against ``client`` and return redacted results.

    The loop stops early — cleanly, keeping everything collected so far — on
    budget exhaustion, on the first rate-limit response and on an
    authentication failure.

    Args:
        client: An entered ``EeroClient`` (or any object exposing the same
            read methods; the test suite passes a fake).
        ctx: Mutable context carrying identifiers between steps.
        meter: Budget and rate accounting, already hooked onto the GET path.
        steps: The allowlist to execute.
        only: When set, run just the step with this label.

    Returns:
        One :class:`StepResult` per step, in execution order.
    """
    results: list[StepResult] = []
    stop_reason: str | None = None

    for step in steps:
        if only is not None and step.label != only:
            continue
        if stop_reason is not None:
            results.append(StepResult(step.label, step.method, outcome=stop_reason))
            continue
        if not step.is_applicable(ctx):
            _LOGGER.info("step %s: skipped (prerequisite missing)", step.label)
            results.append(StepResult(step.label, step.method, outcome="skipped"))
            continue

        result = StepResult(step.label, step.method, outcome="ok")
        before = meter.gets
        started = time.monotonic()
        try:
            payload = await step.run(client, ctx)
        except ProbeWriteBlocked:
            raise
        except ProbeBudgetExhausted:
            result.outcome = "budget-exhausted"
            stop_reason = "not-run-budget"
        except EeroRateLimitException as exc:
            result.outcome = "rate-limited"
            _describe_exception(exc, result)
            stop_reason = "not-run-rate-limited"
        except EeroAuthenticationException as exc:
            result.outcome = "auth-failed"
            _describe_exception(exc, result)
            stop_reason = "not-run-auth-failed"
        except (EeroAPIException, EeroException) as exc:
            result.outcome = "error"
            _describe_exception(exc, result)
        else:
            if isinstance(payload, Mapping):
                result.top_level_keys = sorted(_safe_key(key) for key in payload)
            result.tree = redact(payload)
            if step.extract is not None:
                try:
                    step.extract(ctx, payload)
                except Exception:  # pragma: no cover - defensive
                    _LOGGER.warning("step %s: could not extract identifiers", step.label)
        finally:
            result.elapsed_ms = (time.monotonic() - started) * 1000.0
            result.gets = meter.gets - before

        _LOGGER.info("step %s: %s (%d GET)", result.label, result.outcome, result.gets)
        results.append(result)

    if stop_reason is not None:
        _LOGGER.warning("probe stopped early: %s", stop_reason.removeprefix("not-run-"))
    return results


# ---------------------------------------------------------------------------
# Session handling
# ---------------------------------------------------------------------------

#: Keys that may hold a session token in a credential record. Only their
#: *presence* is ever reported.
_TOKEN_KEYS = ("session_id", "user_token")


def inspect_session_file(path: Path) -> dict[str, Any]:
    """Describe a credential file without revealing its token.

    Args:
        path: Credential file to inspect. Opened read-only.

    Returns:
        ``{"exists", "schema_version", "token_key", "token_present", "mode"}``.
        ``token_key`` is a key *name*, never a value.
    """
    info: dict[str, Any] = {
        "exists": path.exists(),
        "schema_version": None,
        "token_key": None,
        "token_present": False,
        "mode": None,
    }
    if not info["exists"]:
        return info
    info["mode"] = oct(path.stat().st_mode & 0o777)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info["schema_version"] = "unreadable"
        return info
    if not isinstance(record, Mapping):
        info["schema_version"] = "unexpected"
        return info
    version = record.get("schema_version")
    info["schema_version"] = version if isinstance(version, (int, str)) else None
    for key in _TOKEN_KEYS:
        if record.get(key):
            info["token_key"] = key
            info["token_present"] = True
            break
    return info


def copy_session_file(source: Path) -> tuple[Path, Path]:
    """Copy ``source`` into a private 0700 temp dir as a 0600 file.

    The original is opened read-only and never written to; the SDK's schema
    migration therefore lands on the copy.

    Args:
        source: The caller's real session file.

    Returns:
        ``(temp_dir, copy_path)``. The caller owns cleanup of ``temp_dir``.

    Raises:
        FileNotFoundError: If ``source`` does not exist.
    """
    if not source.exists():
        raise FileNotFoundError(str(source))
    temp_dir = Path(tempfile.mkdtemp(prefix="eero-probe-"))
    os.chmod(temp_dir, 0o700)
    copy_path = temp_dir / "session.json"
    payload = source.read_bytes()
    handle = os.open(copy_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)
    os.chmod(copy_path, 0o600)
    return temp_dir, copy_path


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _window() -> tuple[str, str]:
    """Return the ISO-8601 24-hour window used by the time-series reads."""
    end = datetime.now(tz=UTC).replace(microsecond=0)
    start = end - timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def build_report(
    results: Sequence[StepResult],
    *,
    meter: RequestMeter,
    session_before: Mapping[str, Any],
    session_after: Mapping[str, Any],
    window: tuple[str, str],
) -> dict[str, Any]:
    """Assemble the machine-readable report."""
    outcomes: dict[str, int] = {}
    for result in results:
        outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
    return {
        "metadata": {
            "exporter_version": __version__,
            "eero_api_version": TARGET_SDK_VERSION,
            "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
            "window_start": window[0],
            "window_end": window[1],
            "budget": meter.budget,
            "budget_used": meter.gets,
            "rate_limit_per_second": meter.rate,
            "steps_total": len(results),
            "outcomes": outcomes,
            "not_available": [{"item": item, "reason": reason} for item, reason in NOT_AVAILABLE],
        },
        "session": {
            "note": "values below describe the working COPY; the original is never written",
            "before": dict(session_before),
            "after": dict(session_after),
        },
        "steps": [result.as_dict() for result in results],
    }


def build_markdown_summary(report: Mapping[str, Any]) -> str:
    """Render the human-readable sibling of the JSON report."""
    meta = report.get("metadata", {})
    session = report.get("session", {})
    lines = [
        f"# eero API probe — {meta.get('date', 'unknown')}",
        "",
        f"- exporter: `{meta.get('exporter_version')}`",
        f"- eero-api: `{meta.get('eero_api_version')}`",
        f"- window: `{meta.get('window_start')}` .. `{meta.get('window_end')}`",
        f"- GET budget: {meta.get('budget_used')} / {meta.get('budget')}"
        f" at <= {meta.get('rate_limit_per_second')} req/s",
        f"- steps: {meta.get('steps_total')} ({meta.get('outcomes')})",
        "",
        "## Session copy",
        "",
        f"- before: `{session.get('before')}`",
        f"- after: `{session.get('after')}`",
        "",
        "## Endpoints",
        "",
        "| Step | Method | Outcome | GETs | ms | Top-level keys |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for step in report.get("steps", []):
        keys = ", ".join(f"`{key}`" for key in step.get("top_level_keys", [])) or "—"
        outcome = step.get("outcome", "")
        detail = step.get("error_code") or step.get("exception")
        if detail:
            outcome = f"{outcome} (`{detail}`)"
        lines.append(
            f"| `{step.get('label')}` | `{step.get('method')}` | {outcome} "
            f"| {step.get('gets')} | {step.get('elapsed_ms')} | {keys} |"
        )
    not_available = meta.get("not_available") or []
    if not_available:
        lines += ["", f"## No read method in eero-api {meta.get('eero_api_version')}", ""]
        lines += [f"- `{entry['item']}` — {entry['reason']}" for entry in not_available]
    lines.append("")
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """Write the JSON report and its Markdown summary; return both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['metadata']['date']}-eero-api-{report['metadata']['eero_api_version']}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_path.write_text(build_markdown_summary(report), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass
class ProbeOptions:
    """Everything the ``probe`` CLI command passes down to this module."""

    session_file: Path
    out_dir: Path = DEFAULT_OUT_DIR
    budget: int = DEFAULT_BUDGET
    rate: float = DEFAULT_RATE
    only: str | None = None
    dry_run: bool = False
    keep_copy: bool = False


def _planned_steps(only: str | None) -> list[ProbeStep]:
    """Return the steps ``--only`` selects, or the whole allowlist."""
    if only is None:
        return list(PROBE_STEPS)
    return [step for step in PROBE_STEPS if step.label == only]


def _print_plan(steps: Sequence[ProbeStep], options: ProbeOptions) -> None:
    """Print the dry-run plan. Makes no request."""
    print(
        f"probe plan — {len(steps)} step(s), budget {options.budget} GET(s) "
        f"at <= {options.rate} req/s, output {options.out_dir}"
    )
    for index, step in enumerate(steps, start=1):
        requires = ",".join(step.requires) or "-"
        print(f"{index:3d}. {step.label:34s} {step.method:34s} requires={requires}")
    for item, reason in NOT_AVAILABLE:
        print(f"  (not available in eero-api {TARGET_SDK_VERSION}: {item} — {reason})")


async def run_probe(options: ProbeOptions) -> dict[str, Any]:
    """Run the probe end to end against a copy of the session file.

    Raises:
        FileNotFoundError: If the session file does not exist.
    """
    temp_dir, copy_path = copy_session_file(options.session_file)
    session_before = inspect_session_file(copy_path)
    start, end = _window()
    ctx = ProbeContext(start=start, end=end)
    meter = RequestMeter(budget=options.budget, rate=options.rate)

    uninstall_guard = install_write_guard()
    uninstall_meter = install_get_meter(meter)
    try:
        client = EeroClient(cookie_file=str(copy_path), use_keyring=False)
        async with client:
            results = await execute_steps(client, ctx, meter, only=options.only)
    finally:
        uninstall_meter()
        uninstall_guard()
        session_after = inspect_session_file(copy_path)
        if options.keep_copy:
            _LOGGER.info("session copy kept at %s", copy_path)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return build_report(
        results,
        meter=meter,
        session_before=session_before,
        session_after=session_after,
        window=(start, end),
    )


def run_probe_cli(options: ProbeOptions) -> int:
    """Synchronous entry point used by the ``probe`` CLI command.

    Returns:
        A process exit code: ``0`` on success, ``1`` on a usage or session
        error, ``2`` if a write was blocked (which would be a probe bug).
    """
    steps = _planned_steps(options.only)
    if options.only is not None and not steps:
        print(f"unknown step label: {options.only}")
        print("known labels: " + ", ".join(step.label for step in PROBE_STEPS))
        return 1

    if options.dry_run:
        _print_plan(steps, options)
        return 0

    try:
        report = asyncio.run(run_probe(options))
    except FileNotFoundError:
        print(f"session file not found: {options.session_file}")
        print("run `eero-exporter login` first, then point --session-file at the result")
        return 1
    except ProbeWriteBlocked as exc:
        print(f"probe aborted: {exc}")
        return 2

    json_path, md_path = write_report(report, options.out_dir)
    meta = report["metadata"]
    print(f"probe complete: {meta['steps_total']} step(s), {meta['budget_used']} GET(s)")
    print(f"  {json_path}")
    print(f"  {md_path}")
    return 0
