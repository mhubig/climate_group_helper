"""Tests for climate group helper exception handling."""

import logging
from unittest.mock import MagicMock

import pytest

from custom_components.climate_group_helper.climate import ClimateGroup
from custom_components.climate_group_helper.const import CalibrationMode


class TestDeviceCalibrationExceptionHandling:
    """Test _device_calibration exception handling."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        entity = object.__new__(ClimateGroup)

        # Core attributes
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity.config = {}

        # Calibration-related attributes
        entity._temp_update_target_entity_ids = []
        entity._humidity_update_target_entity_ids = []
        entity._temp_calibration_mode = CalibrationMode.ABSOLUTE
        entity._attr_current_temperature = 22.0
        entity._attr_current_humidity = 50.0
        entity._event_entity_id = None
        entity._temp_sensor_entity_ids = []
        entity._humidity_sensor_entity_ids = []
        entity._target_member_map = {}
        entity._member_temp_avg = None

        return entity

    def _create_mock_state(self, entity_id: str, state: str = "20.0"):
        """Create a mock state object."""
        mock_state = MagicMock()
        mock_state.entity_id = entity_id
        mock_state.state = state
        mock_state.attributes = {}
        return mock_state

    def test_exception_is_logged_and_processing_continues(self, hass, caplog):
        """Test that exceptions during service calls are logged and don't stop processing."""
        # Setup entity
        entity = self._create_mock_entity(hass)
        entity._temp_update_target_entity_ids = ["number.target_1", "number.target_2"]

        # Mock states for two target entities
        mock_state_1 = self._create_mock_state("number.target_1", "20.0")
        mock_state_2 = self._create_mock_state("number.target_2", "21.0")

        entity._get_valid_member_states = MagicMock(
            return_value=([mock_state_1, mock_state_2], True)
        )

        # Track service calls
        service_calls = []

        def mock_create_task(coro):
            """Mock async_create_task that tracks calls and raises on first."""
            coro.close()  # Properly close coroutine to avoid warning
            service_calls.append(True)
            if len(service_calls) == 1:
                raise Exception("Service call failed for target_1")

        hass.async_create_task = mock_create_task

        # Act
        with caplog.at_level(logging.ERROR):
            entity._device_calibration(domain="temperature", force=True)

        # Assert: Error was logged
        assert "Error updating target entity number.target_1" in caplog.text
        assert "Service call failed for target_1" in caplog.text

        # Assert: Processing continued to second entity (2 calls attempted)
        assert len(service_calls) == 2

    def test_exception_logs_full_traceback(self, hass, caplog):
        """Test that exception logging includes exc_info for debugging."""
        entity = self._create_mock_entity(hass)
        entity._temp_update_target_entity_ids = ["number.target_1"]

        mock_state = self._create_mock_state("number.target_1", "20.0")
        entity._get_valid_member_states = MagicMock(
            return_value=([mock_state], True)
        )

        def mock_create_task(coro):
            coro.close()
            raise ValueError("Detailed error message")

        hass.async_create_task = mock_create_task

        # Act
        with caplog.at_level(logging.ERROR):
            entity._device_calibration(domain="temperature", force=True)

        # Assert: Error message contains the exception details
        assert "Detailed error message" in caplog.text
        assert "number.target_1" in caplog.text

    def test_no_exception_when_service_succeeds(self, hass, caplog):
        """Test that no error is logged when service call succeeds."""
        entity = self._create_mock_entity(hass)
        entity._temp_update_target_entity_ids = ["number.target_1"]

        mock_state = self._create_mock_state("number.target_1", "20.0")
        entity._get_valid_member_states = MagicMock(
            return_value=([mock_state], True)
        )

        # Mock successful task creation (close coroutine to avoid warning)
        def mock_create_task(coro):
            coro.close()

        hass.async_create_task = mock_create_task

        # Act
        with caplog.at_level(logging.ERROR):
            entity._device_calibration(domain="temperature", force=True)

        # Assert: No error logged
        assert "Error updating target entity" not in caplog.text

    def test_humidity_calibration_exception_handling(self, hass, caplog):
        """Test exception handling for humidity domain calibration."""
        entity = self._create_mock_entity(hass)
        entity._humidity_update_target_entity_ids = ["number.humidity_target"]

        mock_state = self._create_mock_state("number.humidity_target", "45.0")
        entity._get_valid_member_states = MagicMock(
            return_value=([mock_state], True)
        )

        def mock_create_task(coro):
            coro.close()
            raise RuntimeError("Humidity service failed")

        hass.async_create_task = mock_create_task

        # Act
        with caplog.at_level(logging.ERROR):
            entity._device_calibration(domain="humidity", force=True)

        # Assert
        assert "Error updating target entity number.humidity_target" in caplog.text
        assert "Humidity service failed" in caplog.text

    def test_multiple_failures_all_logged(self, hass, caplog):
        """Test that multiple failures are all logged separately."""
        entity = self._create_mock_entity(hass)
        entity._temp_update_target_entity_ids = [
            "number.target_1",
            "number.target_2",
            "number.target_3",
        ]

        mock_states = [
            self._create_mock_state("number.target_1", "20.0"),
            self._create_mock_state("number.target_2", "21.0"),
            self._create_mock_state("number.target_3", "22.0"),
        ]
        entity._get_valid_member_states = MagicMock(
            return_value=(mock_states, True)
        )

        call_count = [0]

        def mock_create_task(coro):
            coro.close()
            call_count[0] += 1
            # All three fail
            raise Exception(f"Error {call_count[0]}")

        hass.async_create_task = mock_create_task

        # Act
        with caplog.at_level(logging.ERROR):
            entity._device_calibration(domain="temperature", force=True)

        # Assert: All three errors logged
        assert "number.target_1" in caplog.text
        assert "number.target_2" in caplog.text
        assert "number.target_3" in caplog.text
        assert call_count[0] == 3


class TestClimateGroupValidation:
    """Test input validation and ServiceValidationError handling."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        from homeassistant.components.climate import HVACMode

        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_set_hvac_mode_invalid_mode_raises_error(self, hass):
        """Test that setting an invalid HVAC mode raises ServiceValidationError."""
        from homeassistant.components.climate import HVACMode
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        # Act & Assert: AUTO is not in the allowed modes
        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_hvac_mode(HVACMode.AUTO)

        # Verify the error contains useful information
        assert exc_info.value.translation_key == "invalid_hvac_mode"
        assert "auto" in str(exc_info.value.translation_placeholders.get("mode", "")).lower()
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))

    @pytest.mark.asyncio
    async def test_set_hvac_mode_valid_mode_succeeds(self, hass):
        """Test that setting a valid HVAC mode does not raise an error."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import HVACMode

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        # Act: HEAT is in the allowed modes - should not raise
        await entity.async_set_hvac_mode(HVACMode.HEAT)

        # Assert: State manager and call handler were invoked
        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_empty_modes_list_allows_any(self, hass):
        """Test that when hvac_modes is empty/None, any mode is allowed."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import HVACMode

        entity = self._create_mock_entity(hass)
        entity._attr_hvac_modes = []  # Empty list
        entity.climate_call_handler.call_debounced = AsyncMock()

        # Act: Should not raise even with empty modes list
        await entity.async_set_hvac_mode(HVACMode.AUTO)

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()


class TestTemperatureValidation:
    """Test temperature validation in async_set_temperature."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        from homeassistant.components.climate import HVACMode

        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_min_temp = 10.0
        entity._attr_max_temp = 30.0
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_temperature_below_min_raises_error(self, hass):
        """Test that temperature below min_temp raises ServiceValidationError."""
        from homeassistant.const import ATTR_TEMPERATURE
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 5.0})

        assert exc_info.value.translation_key == "temperature_out_of_range"
        assert "5.0" in str(exc_info.value.translation_placeholders.get("temperature", ""))
        assert "10.0" in str(exc_info.value.translation_placeholders.get("min", ""))
        assert "30.0" in str(exc_info.value.translation_placeholders.get("max", ""))

    @pytest.mark.asyncio
    async def test_temperature_above_max_raises_error(self, hass):
        """Test that temperature above max_temp raises ServiceValidationError."""
        from homeassistant.const import ATTR_TEMPERATURE
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_temperature(**{ATTR_TEMPERATURE: 35.0})

        assert exc_info.value.translation_key == "temperature_out_of_range"
        assert "35.0" in str(exc_info.value.translation_placeholders.get("temperature", ""))

    @pytest.mark.asyncio
    async def test_target_temp_low_below_min_raises_error(self, hass):
        """Test that target_temp_low below min_temp raises ServiceValidationError."""
        from homeassistant.components.climate import ATTR_TARGET_TEMP_LOW
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_temperature(**{ATTR_TARGET_TEMP_LOW: 5.0})

        assert exc_info.value.translation_key == "temperature_out_of_range"

    @pytest.mark.asyncio
    async def test_target_temp_high_above_max_raises_error(self, hass):
        """Test that target_temp_high above max_temp raises ServiceValidationError."""
        from homeassistant.components.climate import ATTR_TARGET_TEMP_HIGH
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_temperature(**{ATTR_TARGET_TEMP_HIGH: 40.0})

        assert exc_info.value.translation_key == "temperature_out_of_range"

    @pytest.mark.asyncio
    async def test_valid_temperature_succeeds(self, hass):
        """Test that valid temperature does not raise an error."""
        from unittest.mock import AsyncMock

        from homeassistant.const import ATTR_TEMPERATURE

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        # 20.0 is within range [10, 30]
        await entity.async_set_temperature(**{ATTR_TEMPERATURE: 20.0})

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_temp_range_succeeds(self, hass):
        """Test that valid temperature range does not raise an error."""
        from unittest.mock import AsyncMock

        from homeassistant.components.climate import ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        # Both values within range
        await entity.async_set_temperature(**{
            ATTR_TARGET_TEMP_LOW: 15.0,
            ATTR_TARGET_TEMP_HIGH: 25.0
        })

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_boundary_temperatures_succeed(self, hass):
        """Test that temperatures at exact boundaries are valid."""
        from unittest.mock import AsyncMock

        from homeassistant.const import ATTR_TEMPERATURE

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        # Exact min value should be valid
        await entity.async_set_temperature(**{ATTR_TEMPERATURE: 10.0})
        entity.climate_state_manager.update.assert_called()

        # Exact max value should be valid
        await entity.async_set_temperature(**{ATTR_TEMPERATURE: 30.0})

    @pytest.mark.asyncio
    async def test_none_limits_skip_validation(self, hass):
        """Test that None limits skip validation."""
        from unittest.mock import AsyncMock

        from homeassistant.const import ATTR_TEMPERATURE

        entity = self._create_mock_entity(hass)
        entity._attr_min_temp = None
        entity._attr_max_temp = None
        entity.climate_call_handler.call_debounced = AsyncMock()

        # Any value should be allowed when limits are None
        await entity.async_set_temperature(**{ATTR_TEMPERATURE: -100.0})
        entity.climate_state_manager.update.assert_called()

        await entity.async_set_temperature(**{ATTR_TEMPERATURE: 1000.0})
        assert entity.climate_call_handler.call_debounced.call_count == 2


class TestFanModeValidation:
    """Test fan mode validation in async_set_fan_mode."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_fan_modes = ["auto", "low", "medium", "high"]
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_invalid_fan_mode_raises_error(self, hass):
        """Test that setting an invalid fan mode raises ServiceValidationError."""
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_fan_mode("turbo")

        assert exc_info.value.translation_key == "invalid_fan_mode"
        assert "turbo" in str(exc_info.value.translation_placeholders.get("mode", ""))
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))

    @pytest.mark.asyncio
    async def test_valid_fan_mode_succeeds(self, hass):
        """Test that setting a valid fan mode does not raise an error."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_fan_mode("high")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_fan_modes_list_allows_any(self, hass):
        """Test that when fan_modes is empty/None, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_fan_modes = []
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_fan_mode("any_mode")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_fan_modes_allows_any(self, hass):
        """Test that when fan_modes is None, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_fan_modes = None
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_fan_mode("silent")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()


class TestPresetModeValidation:
    """Test preset mode validation in async_set_preset_mode."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_preset_modes = ["home", "away", "eco", "boost"]
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_invalid_preset_mode_raises_error(self, hass):
        """Test that setting an invalid preset mode raises ServiceValidationError."""
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_preset_mode("vacation")

        assert exc_info.value.translation_key == "invalid_preset_mode"
        assert "vacation" in str(exc_info.value.translation_placeholders.get("mode", ""))
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))

    @pytest.mark.asyncio
    async def test_valid_preset_mode_succeeds(self, hass):
        """Test that setting a valid preset mode does not raise an error."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_preset_mode("eco")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_preset_modes_list_allows_any(self, hass):
        """Test that when preset_modes is empty, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_preset_modes = []
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_preset_mode("any_preset")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_preset_modes_allows_any(self, hass):
        """Test that when preset_modes is None, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_preset_modes = None
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_preset_mode("custom")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()


class TestSwingModeValidation:
    """Test swing mode validation in async_set_swing_mode."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_swing_modes = ["off", "on", "vertical", "horizontal", "both"]
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_invalid_swing_mode_raises_error(self, hass):
        """Test that setting an invalid swing mode raises ServiceValidationError."""
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_swing_mode("diagonal")

        assert exc_info.value.translation_key == "invalid_swing_mode"
        assert "diagonal" in str(exc_info.value.translation_placeholders.get("mode", ""))
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))

    @pytest.mark.asyncio
    async def test_valid_swing_mode_succeeds(self, hass):
        """Test that setting a valid swing mode does not raise an error."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_mode("vertical")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_swing_modes_list_allows_any(self, hass):
        """Test that when swing_modes is empty, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_swing_modes = []
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_mode("any_swing")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_swing_modes_allows_any(self, hass):
        """Test that when swing_modes is None, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_swing_modes = None
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_mode("custom_swing")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()


class TestSwingHorizontalModeValidation:
    """Test swing horizontal mode validation in async_set_swing_horizontal_mode."""

    def _create_mock_entity(self, hass):
        """Create a partially mocked ClimateGroup entity for testing."""
        entity = object.__new__(ClimateGroup)
        entity.hass = hass
        entity.entity_id = "climate.test_group"
        entity._attr_swing_horizontal_modes = ["off", "on", "left", "right", "center"]
        entity.climate_state_manager = MagicMock()
        entity.climate_call_handler = MagicMock()
        return entity

    @pytest.mark.asyncio
    async def test_invalid_swing_horizontal_mode_raises_error(self, hass):
        """Test that setting an invalid swing horizontal mode raises ServiceValidationError."""
        from homeassistant.exceptions import ServiceValidationError

        entity = self._create_mock_entity(hass)

        with pytest.raises(ServiceValidationError) as exc_info:
            await entity.async_set_swing_horizontal_mode("wide")

        assert exc_info.value.translation_key == "invalid_swing_horizontal_mode"
        assert "wide" in str(exc_info.value.translation_placeholders.get("mode", ""))
        assert "climate.test_group" in str(exc_info.value.translation_placeholders.get("entity_id", ""))

    @pytest.mark.asyncio
    async def test_valid_swing_horizontal_mode_succeeds(self, hass):
        """Test that setting a valid swing horizontal mode does not raise an error."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_horizontal_mode("left")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_swing_horizontal_modes_list_allows_any(self, hass):
        """Test that when swing_horizontal_modes is empty, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_swing_horizontal_modes = []
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_horizontal_mode("any_horizontal")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_swing_horizontal_modes_allows_any(self, hass):
        """Test that when swing_horizontal_modes is None, any mode is allowed."""
        from unittest.mock import AsyncMock

        entity = self._create_mock_entity(hass)
        entity._attr_swing_horizontal_modes = None
        entity.climate_call_handler.call_debounced = AsyncMock()

        await entity.async_set_swing_horizontal_mode("custom_horizontal")

        entity.climate_state_manager.update.assert_called_once()
        entity.climate_call_handler.call_debounced.assert_called_once()
