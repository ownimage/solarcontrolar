import json
import logging
from datetime import datetime, timedelta

from common.dateHelper import DateHelper
from filenames import Filenames
from settings import Settings
from common.json_store import JsonStore

logger = logging.getLogger(__name__)


class ConfigGenerator:
    def __init__(self,
                 settings: Settings = Settings(),
                 solar_forecast_store: JsonStore = JsonStore(Filenames.SOLAR_FORECAST_FILE.value),
                 usage_forecast_store: JsonStore = JsonStore(Filenames.USAGE_FORECAST_FILE.value),
                 usage_actuals_store: JsonStore = JsonStore(Filenames.USAGE_ACTUALS.value),
                 config_store: JsonStore = JsonStore(Filenames.CONFIG.value),
                 datehelper=DateHelper(),
                 logging=logging
                 ):
        self.settings = settings
        self.solar_forecast = solar_forecast_store.read()
        self.usage_forecast = usage_forecast_store.read()
        self.usage_actuals = usage_actuals_store.read()
        self.config_store = config_store
        self.datehelper = datehelper
        self.logging = logging

        self.battery_min_percentage = 100.0 * self.settings.battery_min_kwh() / self.settings.battery_capacity_kwh()

        self.tomorrow = (datetime.now(self.settings.timezone()) + timedelta(days=1)).date()
        self.tomorrow_iso = self.tomorrow.isoformat()
        self.tomorrow_day = self.tomorrow.strftime('%A')

    def get_min_max_estimate(self):
        usage1 = self.usage_actuals[self.datehelper.offset_iso(-6)]
        usage2 = self.usage_actuals[self.datehelper.offset_iso(-13)]
        solar = self.solar_forecast[self.datehelper.tomorrow_iso()]
        min_level = self.settings.min_charge_to_bias_kwh()
        max_level = self.settings.max_charge_to_bias_kwh()
        min_total = self.settings.min_charge_to_bias_kwh()
        max_total = self.settings.max_charge_to_bias_kwh()
        for key, solar_value in sorted(solar.items()):
            if "05:00" <= key <= "16:00":
                usage = ((usage1[key] + usage2[key]) / 2) * self.settings.usage_multiplier()
                delta = solar_value["pv_estimate"] * self.settings.solar_forecast_multiplier() / 2 - usage
                min_total += delta
                max_total += delta
                min_level = min(min_level, min_total)
                max_level = max(max_level, max_total)
        return min_level, max_level

    def calculate_charge_to_percentage(self, min_level, max_level):
        kwh_for_100_peak = self.settings.battery_capacity_kwh() - max_level
        kwh_for_before_sun = self.settings.battery_min_kwh() - min_level
        kwh_requirement = max(kwh_for_100_peak, kwh_for_before_sun)

        percentage_unlimited = kwh_requirement * 100 / self.settings.battery_capacity_kwh()
        return int(max(self.battery_min_percentage, min(percentage_unlimited, 100)))

    def write_config(self, charge_to_percentage):
        config = self.config_store.read()
        config["charge_to_percentage"] = charge_to_percentage
        self.config_store.write(config)

    def run(self):
        min_level, max_level = self.get_min_max_estimate()
        charge_to_percentage = self.calculate_charge_to_percentage(min_level, max_level)
        self.write_config(charge_to_percentage)
        logger.info(f"minimum level: {min_level}, maximum level: {max_level}, charge to_percentage: {charge_to_percentage}")


# Example usage:
if __name__ == "__main__":
    config_generator = ConfigGenerator()
    config_generator.run()
