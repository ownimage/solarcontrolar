from enum import Enum


class Filenames(Enum):
    CONFIG = "config.json"
    SETTINGS = "settings.json"
    SOLAR_ACTUALS = "solar_actuals.json"
    SOLAR_FORECAST_FILE = "solar_forecast_history.json"
    USAGE_ACTUALS = "usage_actuals.json"
    USAGE_BASELINE_FILE = "usage_baseline.json"
    USAGE_FORECAST_FILE = "usage_forecast.json"
    MINUTE_TOTALS_FILE = "minute_totals.json"
    MINUTE_POLLER_STATE_FILE = "minute_poller_state.json"
    MINUTE_POWER_FILE = "minute_power.json"

