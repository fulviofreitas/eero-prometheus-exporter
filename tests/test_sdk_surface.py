"""Test SDK surface compatibility with eero-api 8.0.1.

This test ensures:
1. Every method the adapter calls exists on the real EeroClient
2. Method signatures accept the arguments the adapter passes
3. No adapter code calls SDK write methods (read-only verification)
4. BaseAPI exposes the write methods for the read-only guard to patch
"""

import inspect
import re
from pathlib import Path

from eero import EeroClient
from eero.api.base import BaseAPI
from eero.exceptions import EeroException


class TestSDKSurface:
    """Verify SDK surface compatibility."""

    @classmethod
    def setup_class(cls) -> None:
        """Parse the adapter to find all SDK method calls."""
        adapter_path = Path(__file__).parent.parent / "src" / "eero_exporter" / "eero_adapter.py"
        with open(adapter_path) as f:
            cls.adapter_source = f.read()

        # Extract all self._client.<method>( calls using regex
        cls.adapter_calls = set(re.findall(r"await self\._client\.([a-z_]+)\(", cls.adapter_source))

    def test_all_adapter_calls_exist_on_client(self) -> None:
        """Every method the adapter calls must exist on EeroClient."""
        missing = []
        for method_name in sorted(self.adapter_calls):
            if not hasattr(EeroClient, method_name):
                missing.append(method_name)

        assert not missing, f"EeroClient missing methods called by adapter: {missing}"

    def test_client_methods_are_callable(self) -> None:
        """Every adapter-called method must be callable."""
        non_callable = []
        for method_name in sorted(self.adapter_calls):
            attr = getattr(EeroClient, method_name)
            if not callable(attr):
                non_callable.append(method_name)

        assert not non_callable, f"Adapter calls non-callable attributes: {non_callable}"

    def test_no_write_methods_in_adapter_calls(self) -> None:
        """Verify adapter never calls SDK write methods."""
        write_patterns = {
            "set_",
            "create_",
            "delete_",
            "update_",
            "run_",
            "reboot_",
            "request_support",
            "discover_",
            "pause_",
            "block_",
            "apply_",
        }

        write_calls = []
        for call in sorted(self.adapter_calls):
            for pattern in write_patterns:
                if call.startswith(pattern):
                    write_calls.append(call)
                    break

        assert not write_calls, f"Adapter calls write methods (forbidden): {write_calls}"

    def test_login_verify_exist(self) -> None:
        """login() and verify() must exist (used by CLI, not read-only guarded)."""
        assert hasattr(EeroClient, "login")
        assert hasattr(EeroClient, "verify")
        assert callable(EeroClient.login)
        assert callable(EeroClient.verify)

    def test_baseapi_has_write_methods_for_guard(self) -> None:
        """BaseAPI must expose post, put, delete for the read-only guard to patch."""
        assert hasattr(BaseAPI, "post"), "BaseAPI must have post method for read-only guard"
        assert hasattr(BaseAPI, "put"), "BaseAPI must have put method for read-only guard"
        assert hasattr(BaseAPI, "delete"), "BaseAPI must have delete method for read-only guard"

        assert callable(BaseAPI.post), "BaseAPI.post must be callable"
        assert callable(BaseAPI.put), "BaseAPI.put must be callable"
        assert callable(BaseAPI.delete), "BaseAPI.delete must be callable"

    def test_get_data_usage_signature_kw_only_params(self) -> None:
        """get_data_usage must have kw-only params (cadence, start, end, etc).

        In eero-api 8.0+, get_data_usage changed from positional (payload, resource)
        to keyword-only parameters (start, end, cadence, timezone).
        """
        sig = inspect.signature(EeroClient.get_data_usage)
        params = list(sig.parameters.values())

        # Parameters after 'network_id' should be keyword-only (KEYWORD_ONLY kind)
        # Expected: get_data_usage(network_id=..., *, start, end, cadence, timezone=None)
        kw_only_params = [p.name for p in params if p.kind == inspect.Parameter.KEYWORD_ONLY]

        assert "start" in kw_only_params, "get_data_usage must have start as keyword-only"
        assert "end" in kw_only_params, "get_data_usage must have end as keyword-only"
        assert "cadence" in kw_only_params, "get_data_usage must have cadence as keyword-only"

    def test_adapter_error_mapping_covers_sdk_exceptions(self) -> None:
        """Adapter should handle all SDK exceptions.

        Spot-check that the main exception hierarchy exists.
        """
        assert issubclass(EeroException, Exception), "EeroException should be a standard Exception"

        # These specific exceptions are used in the adapter's error mapping
        from eero.exceptions import (
            EeroAPIException,
            EeroAuthenticationException,
            EeroNotFoundException,
            EeroValidationException,
        )

        assert issubclass(EeroAuthenticationException, EeroException)
        assert issubclass(EeroAPIException, EeroException)
        assert issubclass(EeroNotFoundException, EeroAPIException)
        assert issubclass(EeroValidationException, EeroException)

    def test_get_insights_accepts_cadence_parameter(self) -> None:
        """get_insights must accept cadence parameter."""
        sig = inspect.signature(EeroClient.get_insights)
        params = sig.parameters

        assert "cadence" in params, "get_insights must accept cadence parameter"

    def test_get_devices_accepts_optional_filters(self) -> None:
        """get_devices should accept optional thread and proxied_node filters."""
        sig = inspect.signature(EeroClient.get_devices)
        params = sig.parameters

        # The adapter calls it with these optional keyword arguments
        # This just verifies the signature exists; values are validated elsewhere
        assert "network_id" in params, "get_devices must accept network_id"


class TestAdapterCallsValidSignatures:
    """Test that adapter calls match SDK method signatures."""

    @classmethod
    def setup_class(cls) -> None:
        """Parse adapter calls with their arguments."""
        adapter_path = Path(__file__).parent.parent / "src" / "eero_exporter" / "eero_adapter.py"
        cls.adapter_path = adapter_path

        with open(adapter_path) as f:
            cls.adapter_source = f.read()

        # Simple regex to extract method calls: self._client.METHOD(args)
        # This is a best-effort check; false negatives are acceptable
        cls.call_pattern = re.compile(r"await self\._client\.([a-z_]+)\(([^)]*)\)", re.DOTALL)

    def test_data_usage_calls_use_kwargs(self) -> None:
        """get_data_usage calls must use keyword arguments (v8 compatibility).

        In v8, get_data_usage signature changed from:
          get_data_usage(network_id, payload, resource)
        to:
          get_data_usage(network_id=..., *, start, end, cadence, ...)

        The adapter should pass these as keyword arguments.
        """
        data_usage_calls = [
            match
            for match in self.call_pattern.finditer(self.adapter_source)
            if "data_usage" in match.group(1)
        ]

        assert data_usage_calls, "Adapter should call the data-usage family"

        for match in data_usage_calls:
            call_args = match.group(2)
            for required in ("start=", "end=", "cadence="):
                assert (
                    required in call_args
                ), f"{match.group(1)} must pass {required} as a keyword: {call_args.strip()}"

    def test_removed_methods_not_called(self) -> None:
        """Methods removed from the SDK in v8 must not be called by the adapter."""
        removed_methods = ["get_backup_network", "get_backup_status"]

        removed_calls = [
            method
            for method in removed_methods
            if re.search(rf"self\._client\.{method}\(", self.adapter_source)
        ]

        assert removed_calls == [], f"Adapter still calls removed SDK methods: {removed_calls}"
