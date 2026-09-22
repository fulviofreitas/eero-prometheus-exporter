"""Tests for the reorganised, tier-gated metrics registry (commit 4).

Verifies: every declared metric carries family/tier/source/evidence
provenance; every name in `REMOVED_IN_4_0_0` is gone from the module and was
never declared; no metric uses a forbidden identifying label; tier gating in
`register_metrics` only exposes enabled families; registering twice never
raises; and `describe_metrics()` enumerates every declared metric exactly
once.
"""

from prometheus_client import CollectorRegistry, generate_latest

from eero_exporter import metrics as m
from eero_exporter.config import ExporterConfig

# The exact forbidden-label contract from the commit brief.
_FORBIDDEN_LABELS = {
    "ip",
    "public_ip",
    "password",
    "ssid",
    "email",
    "phone",
    "bssid",
    "subdomain",
    "serial",
    "url",
    "mac_address",
}


def test_removed_metrics_are_not_declared() -> None:
    """Every REMOVED_IN_4_0_0 name must not exist as a declared metric."""
    declared_names = {p.name for p in m.describe_metrics()}
    overlap = declared_names & m.REMOVED_IN_4_0_0
    assert not overlap, f"removed metrics still declared: {sorted(overlap)}"


def test_removed_metrics_are_not_module_attributes() -> None:
    """No leftover module-level object should expose a removed metric name."""
    for name, obj in vars(m).items():
        metric_name = getattr(obj, "_name", None)
        if metric_name in m.REMOVED_IN_4_0_0:
            raise AssertionError(f"module attribute {name!r} still exposes {metric_name!r}")


def test_every_declared_metric_has_full_provenance() -> None:
    for prov in m.describe_metrics():
        assert prov.family, f"{prov.name} has no family"
        assert prov.tier, f"{prov.name} has no tier"
        assert prov.source, f"{prov.name} has no source"
        assert prov.evidence in ("verified", "documented", "inferred"), prov.name
        assert prov.family in m.FAMILY_TIER
        assert m.METRIC_FAMILY[prov.name] == prov.family


def test_no_forbidden_identifying_labels() -> None:
    for prov in m.describe_metrics():
        bad = set(prov.labels) & _FORBIDDEN_LABELS
        assert not bad, f"{prov.name} declares forbidden label(s) {bad}"


def test_describe_metrics_enumerates_every_declared_metric_once() -> None:
    provenances = m.describe_metrics()
    names = [p.name for p in provenances]
    assert len(names) == len(set(names))
    assert len(names) == len(m._METRIC_PROVENANCE)


def test_register_metrics_all_tiers_off_registers_only_core() -> None:
    config = ExporterConfig(
        include_extended=False,
        include_rf=False,
        include_per_profile=False,
        include_per_device=False,
        include_per_eero=False,
        include_unverified=False,
    )
    registry = CollectorRegistry(auto_describe=True)
    m.register_metrics(config, registry=registry)

    registered_names = {getattr(c, "_name", None) for c in registry._collector_to_names}
    for family, tier in m.FAMILY_TIER.items():
        if tier == "core":
            continue
        for metric in m._FAMILY_METRICS[family]:
            assert getattr(metric, "_name", None) not in registered_names


def test_register_metrics_core_family_flag_gates_registration() -> None:
    """A core family's own include_* flag can still turn it off."""
    config = ExporterConfig(include_devices=False)
    registry = CollectorRegistry(auto_describe=True)
    m.register_metrics(config, registry=registry)

    registered = set(registry._collector_to_names.keys())
    for metric in m._FAMILY_METRICS["devices"]:
        assert metric not in registered


def test_register_metrics_is_idempotent() -> None:
    config = ExporterConfig()
    registry = CollectorRegistry(auto_describe=True)
    m.register_metrics(config, registry=registry)
    # Calling again must not raise (duplicate registration is swallowed).
    m.register_metrics(config, registry=registry)


def test_generate_latest_omits_help_for_disabled_family() -> None:
    config = ExporterConfig(include_devices=False)
    registry = CollectorRegistry(auto_describe=True)
    m.register_metrics(config, registry=registry)

    output = generate_latest(registry).decode()
    for metric in m._FAMILY_METRICS["devices"]:
        name = getattr(metric, "_name", None)
        assert name is not None
        assert f"# HELP {name} " not in output


def test_generate_latest_includes_help_for_enabled_core_family() -> None:
    config = ExporterConfig()
    registry = CollectorRegistry(auto_describe=True)
    m.register_metrics(config, registry=registry)

    output = generate_latest(registry).decode()
    assert f"# HELP {m.EERO_UP._name} " in output
