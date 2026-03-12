"""Tests for service_call.py exception handling."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.climate_group_helper.service_call import (
    BaseServiceCallHandler,
    ClimateCallHandler,
)
from custom_components.climate_group_helper.state import GroupContext, TargetState


class TestServiceValidationErrorHandling:
    """Test ServiceValidationError fail-fast behavior in _execute_calls."""

    def _create_mock_group(self):
        """Create a mock ClimateGroup for testing with fully mocked hass."""
        mock_hass = MagicMock()
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        group = MagicMock()
        group.hass = mock_hass
        group.entity_id = "climate.test_group"
        group.debounce_delay = 0
        group.retry_attempts = 2
        group.retry_delay = 0.1
        group.climate_entity_ids = ["climate.member_1", "climate.member_2"]
        group.shared_target_state = TargetState()
        group.group_context = GroupContext()
        group.config = {}
        return group

    @pytest.mark.asyncio
    async def test_service_validation_error_is_reraised_immediately(self):
        """Test that ServiceValidationError is re-raised without retries."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        # Mock _generate_calls to return a call
        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_hvac_mode",
            "entity_ids": ["climate.member_1"],
            "kwargs": {"hvac_mode": "heat"},
        }])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1
            raise ServiceValidationError(
                translation_domain="climate",
                translation_key="invalid_mode",
                translation_placeholders={"mode": "heat"},
            )

        group.hass.services.async_call = mock_async_call

        with pytest.raises(ServiceValidationError) as exc_info:
            await handler._execute_calls(data={"hvac_mode": "heat"})

        # Verify: Only 1 call attempt (no retries for validation errors)
        assert call_count[0] == 1
        assert exc_info.value.translation_key == "invalid_mode"

    @pytest.mark.asyncio
    async def test_service_validation_error_stops_processing_other_calls(self):
        """Test that ServiceValidationError stops processing remaining calls."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        # Mock _generate_calls to return multiple calls
        handler._generate_calls = MagicMock(return_value=[
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_1"],
                "kwargs": {"hvac_mode": "heat"},
            },
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_2"],
                "kwargs": {"hvac_mode": "heat"},
            },
        ])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1
            raise ServiceValidationError(
                translation_domain="climate",
                translation_key="invalid_mode",
            )

        group.hass.services.async_call = mock_async_call

        with pytest.raises(ServiceValidationError):
            await handler._execute_calls(data={"hvac_mode": "heat"})

        # Only first call attempted - second call was never made
        assert call_count[0] == 1


class TestAllMembersFailedError:
    """Test HomeAssistantError with all_members_failed translation key."""

    def _create_mock_group(self):
        """Create a mock ClimateGroup for testing."""
        mock_hass = MagicMock()
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        group = MagicMock()
        group.hass = mock_hass
        group.entity_id = "climate.test_group"
        group.debounce_delay = 0
        group.retry_attempts = 0  # No retries for simpler testing
        group.retry_delay = 0
        group.climate_entity_ids = ["climate.member_1", "climate.member_2"]
        group.shared_target_state = TargetState()
        group.group_context = GroupContext()
        group.config = {}
        return group

    @pytest.mark.asyncio
    async def test_all_members_failed_raises_error(self):
        """Test that HomeAssistantError is raised when ALL members fail."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_hvac_mode",
            "entity_ids": ["climate.member_1", "climate.member_2"],
            "kwargs": {"hvac_mode": "heat"},
        }])

        async def mock_async_call(*args, **kwargs):
            raise Exception("Connection failed")

        group.hass.services.async_call = mock_async_call

        with pytest.raises(HomeAssistantError) as exc_info:
            await handler._execute_calls(data={"hvac_mode": "heat"})

        assert exc_info.value.translation_key == "all_members_failed"
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))
        assert "Connection failed" in str(exc_info.value.translation_placeholders.get("failed_members", ""))

    @pytest.mark.asyncio
    async def test_all_members_failed_after_retries(self):
        """Test that HomeAssistantError is raised after all retry attempts fail."""
        group = self._create_mock_group()
        group.retry_attempts = 2  # 3 total attempts
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_temperature",
            "entity_ids": ["climate.member_1"],
            "kwargs": {"temperature": 22.0},
        }])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1
            raise Exception("Timeout")

        group.hass.services.async_call = mock_async_call

        with pytest.raises(HomeAssistantError) as exc_info:
            await handler._execute_calls(data={"temperature": 22.0})

        # 3 attempts (1 + 2 retries)
        assert call_count[0] == 3
        assert exc_info.value.translation_key == "all_members_failed"

    @pytest.mark.asyncio
    async def test_all_members_failed_includes_error_details(self):
        """Test that error details are included in the error message."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        # Two separate calls, each targeting one member
        handler._generate_calls = MagicMock(return_value=[
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_1"],
                "kwargs": {"hvac_mode": "heat"},
            },
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_2"],
                "kwargs": {"hvac_mode": "heat"},
            },
        ])

        call_errors = {
            "climate.member_1": "Device offline",
            "climate.member_2": "Authentication failed",
        }

        async def mock_async_call(*args, **kwargs):
            service_data = kwargs.get("service_data", {})
            entity_ids = service_data.get("entity_id", [])
            entity_id = entity_ids[0] if isinstance(entity_ids, list) else entity_ids
            raise Exception(call_errors.get(entity_id, "Unknown error"))

        group.hass.services.async_call = mock_async_call

        with pytest.raises(HomeAssistantError) as exc_info:
            await handler._execute_calls(data={"hvac_mode": "heat"})

        failed_members = str(exc_info.value.translation_placeholders.get("failed_members", ""))
        assert "climate.member_1" in failed_members
        assert "climate.member_2" in failed_members
        assert "Device offline" in failed_members
        assert "Authentication failed" in failed_members


class TestPartialFailureLogging:
    """Test partial failure behavior (some succeed, some fail)."""

    def _create_mock_group(self):
        """Create a mock ClimateGroup for testing."""
        mock_hass = MagicMock()
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        group = MagicMock()
        group.hass = mock_hass
        group.entity_id = "climate.test_group"
        group.debounce_delay = 0
        group.retry_attempts = 0
        group.retry_delay = 0
        group.climate_entity_ids = ["climate.member_1", "climate.member_2"]
        group.shared_target_state = TargetState()
        group.group_context = GroupContext()
        group.config = {}
        return group

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_raise(self, caplog):
        """Test that partial failure logs warning but does not raise."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        # Two separate calls
        handler._generate_calls = MagicMock(return_value=[
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_1"],
                "kwargs": {"hvac_mode": "heat"},
            },
            {
                "service": "set_hvac_mode",
                "entity_ids": ["climate.member_2"],
                "kwargs": {"hvac_mode": "heat"},
            },
        ])

        call_index = [0]

        async def mock_async_call(*args, **kwargs):
            call_index[0] += 1
            if call_index[0] == 1:
                # First call succeeds
                return None
            else:
                # Second call fails
                raise Exception("Member 2 failed")

        group.hass.services.async_call = mock_async_call

        with caplog.at_level(logging.WARNING):
            # Should not raise
            await handler._execute_calls(data={"hvac_mode": "heat"})

        # Verify warning logged
        assert "Partial failure" in caplog.text
        assert "1 of 2 members failed" in caplog.text

    @pytest.mark.asyncio
    async def test_all_succeed_no_error(self, caplog):
        """Test that successful calls do not raise or log warnings."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_hvac_mode",
            "entity_ids": ["climate.member_1", "climate.member_2"],
            "kwargs": {"hvac_mode": "heat"},
        }])

        async def mock_async_call(*args, **kwargs):
            return None  # Success

        group.hass.services.async_call = mock_async_call

        with caplog.at_level(logging.WARNING):
            await handler._execute_calls(data={"hvac_mode": "heat"})

        # No error or partial failure warnings
        assert "Partial failure" not in caplog.text
        assert "all_members_failed" not in caplog.text


class TestRetryBehavior:
    """Test retry behavior with different error types."""

    def _create_mock_group(self):
        """Create a mock ClimateGroup for testing."""
        mock_hass = MagicMock()
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        group = MagicMock()
        group.hass = mock_hass
        group.entity_id = "climate.test_group"
        group.debounce_delay = 0
        group.retry_attempts = 2
        group.retry_delay = 0  # No delay for tests
        group.climate_entity_ids = ["climate.member_1"]
        group.shared_target_state = TargetState()
        group.group_context = GroupContext()
        group.config = {}
        return group

    @pytest.mark.asyncio
    async def test_regular_exception_retries(self):
        """Test that regular exceptions trigger retries."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_temperature",
            "entity_ids": ["climate.member_1"],
            "kwargs": {"temperature": 22.0},
        }])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Temporary failure")
            # Succeed on 3rd attempt
            return None

        group.hass.services.async_call = mock_async_call

        # Should not raise (succeeds on 3rd attempt)
        await handler._execute_calls(data={"temperature": 22.0})

        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_service_validation_error_no_retry(self):
        """Test that ServiceValidationError does NOT retry."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_hvac_mode",
            "entity_ids": ["climate.member_1"],
            "kwargs": {"hvac_mode": "invalid"},
        }])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1
            raise ServiceValidationError(
                translation_domain="climate",
                translation_key="invalid_hvac_mode",
            )

        group.hass.services.async_call = mock_async_call

        with pytest.raises(ServiceValidationError):
            await handler._execute_calls(data={"hvac_mode": "invalid"})

        # Only 1 attempt - no retries for validation errors
        assert call_count[0] == 1


class TestBlockingModeWithExceptions:
    """Test exception behavior when blocking mode is active."""

    def _create_mock_group(self):
        """Create a mock ClimateGroup for testing."""
        mock_hass = MagicMock()
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        group = MagicMock()
        group.hass = mock_hass
        group.entity_id = "climate.test_group"
        group.debounce_delay = 0
        group.retry_attempts = 0
        group.retry_delay = 0
        group.climate_entity_ids = ["climate.member_1"]
        group.shared_target_state = TargetState()
        group.group_context = GroupContext(is_blocked=True)
        group.config = {}
        return group

    @pytest.mark.asyncio
    async def test_blocked_calls_do_not_reach_service(self):
        """Test that blocked calls don't reach the service at all."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1

        group.hass.services.async_call = mock_async_call

        # Temperature change should be blocked
        await handler._execute_calls(data={"temperature": 22.0})

        # No calls should be made
        assert call_count[0] == 0

    @pytest.mark.asyncio
    async def test_turning_off_bypasses_block(self):
        """Test that turning group OFF bypasses blocking mode."""
        group = self._create_mock_group()
        handler = ClimateCallHandler(group)

        handler._generate_calls = MagicMock(return_value=[{
            "service": "set_hvac_mode",
            "entity_ids": ["climate.member_1"],
            "kwargs": {"hvac_mode": "off"},
        }])

        call_count = [0]

        async def mock_async_call(*args, **kwargs):
            call_count[0] += 1

        group.hass.services.async_call = mock_async_call

        # Turn OFF should bypass block
        await handler._execute_calls(data={"hvac_mode": "off"})

        assert call_count[0] == 1
