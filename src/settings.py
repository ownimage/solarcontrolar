from enum import Enum
import pytz

from filenames import Filenames
from common.json_store import JsonStore


class SettingsKeys(Enum):
    TIMEZONE = "timezone"
    BATTERY_CAPACITY_KWH = "battery_capacity_kWh"
    BATTERY_MIN_KWH = "battery_min_kWh"
    SOLAR_FORECAST_MULTIPLIER = "solar_forecast_multiplier"
    TOLERANCE_PERCENT = "tolerance_percent"
    START_DISCHARGE_TARGET = "start_discharge_target"
    LAST_30MINS_DISCHARGE_TARGET = "last_30mins_discharge_target"
    HOLIDAY_CUTOFF_KWH = "holiday_cutoff_kwh"
    MIN_CHARGE_TO_BIAS_KWH = "min_charge_to_bias_kwh"
    MAX_CHARGE_TO_BIAS_KWH = "max_charge_to_bias_kwh"
    USAGE_MULTIPLIER = "usage_multiplier"


class Settings(JsonStore):
    def __init__(self, filepath = Filenames.SETTINGS.value):
        super().__init__(filepath)
        self._settings = self.read()

    def battery_capacity_kwh(self):
        return self._settings[SettingsKeys.BATTERY_CAPACITY_KWH.value]

    def battery_min_kwh(self):
        return self._settings[SettingsKeys.BATTERY_MIN_KWH.value]

    def solar_forecast_multiplier(self):
        return self._settings[SettingsKeys.SOLAR_FORECAST_MULTIPLIER.value]

    def timezone(self):
        return pytz.timezone(self._settings[SettingsKeys.TIMEZONE.value])

    def start_discharge_target(self):
        return self._settings[SettingsKeys.START_DISCHARGE_TARGET.value]

    def last_30mins_discharge_target(self):
        return self._settings[SettingsKeys.LAST_30MINS_DISCHARGE_TARGET.value]

    def tolerance_percent(self):
        return self._settings[SettingsKeys.TOLERANCE_PERCENT.value]

    def holiday_cutoff_kwh(self):
        return self._settings[SettingsKeys.HOLIDAY_CUTOFF_KWH.value]

    def min_charge_to_bias_kwh(self):
        return self._settings[SettingsKeys.MIN_CHARGE_TO_BIAS_KWH.value]

    def max_charge_to_bias_kwh(self):
        return self._settings[SettingsKeys.MAX_CHARGE_TO_BIAS_KWH.value]

    def usage_multiplier(self):
        return self._settings[SettingsKeys.USAGE_MULTIPLIER.value]