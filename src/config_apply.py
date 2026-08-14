import asyncio
import datetime
import json
import logging
import os
import sys

import pytz

from common.json_store import JsonStore
from common.logging_setup import setup_logging
from solarcontrolar.givenergymodbus import GivenergyModbus, PlantWrapper

logger = logging.getLogger(__name__)


class ConfigApply:
    def __init__(self, config=JsonStore("config.json"), os=os, json=json, pytz=pytz, datetime=datetime, logger=logger):
        self.__config = config
        self.__os = os
        self.__json = json
        self.__pytz = pytz
        self.__datetime = datetime
        self.__logger = logger

    def get_settings(self):
        with open("settings.json", "r") as file:
            return self.__json.load(file)

    def get_current_time(self, timezone_str="Europe/London"):
        local_tz = self.__pytz.timezone(timezone_str)
        now = self.__datetime.datetime.now(local_tz)
        return now, now.strftime("%Y-%m-%d %H:%M:%S")

    async def charge_to_percentage(self, tolerance, formatted_date):
        target_percentage = self.__config.read()["charge_to_percentage"]
        data = await GivenergyModbus().read_data_direct()
        battery_level = data.battery_percentage
        enabled = battery_level <= target_percentage

        if abs(battery_level - target_percentage) > tolerance:
            changed = await GivenergyModbus().set_enable_charge(enabled)
            if changed:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} CHANGE set_timed_charge({enabled})"
            else:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} set_timed_charge({enabled})"
        else:
            msg = f"{formatted_date} battery_level={battery_level} is within tolerance={tolerance} of target_percentage={target_percentage} NO CHANGE"

        self.__logger.info(msg)
        return msg  # Allows assertion in unit tests

    async def limit_timed_export(self,  target_percentage, tolerance, formatted_date):
        data = await GivenergyModbus().read_data_direct()
        battery_level = data.battery_soc
        enabled = battery_level >= target_percentage

        if abs(battery_level - target_percentage) > tolerance:
            changed = await GivenergyModbus().set_enable_discharge(enabled)
            if changed:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} CHANGE set_timed_export({enabled})"
            else:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} set_timed_export({enabled})"
        else:
            msg = f"{formatted_date} battery_level={battery_level} is within tolerance={tolerance} of target_percentage={target_percentage} NO CHANGE"

        self.__logger.info(msg)
        return msg  # Allows assertion in unit tests


    @staticmethod
    def calc_limited_discharge_target(start_discharge_target, last_30mins_discharge_target, hour, minute):
        # for between 4 and 6:30
        if ((16 <= hour < 18) and (0 <= minute <= 59)) or (hour == 18 and 0 <= minute <= 30):
            f = ((hour - 16) * 60 + minute) / 150
            target = start_discharge_target + f * (last_30mins_discharge_target - start_discharge_target)
            return int(target)
        else:
            raise BaseException(f"Invalid hour={hour} or minute={minute}, or not in discharge window.")

    async def run(self):
        settings = self.get_settings()
        tolerance = settings["tolerance_percent"]
        start_discharge_target = settings["start_discharge_target"]
        last_30mins_discharge_target = settings["last_30mins_discharge_target"]

        now, formatted_date = self.get_current_time()
        hour = now.hour
        minute = now.minute

        if 2 <= hour < 5:
            return await self.charge_to_percentage(tolerance, formatted_date)
        elif 16 <= hour < 19:
            if hour < 18 or minute < 30:  # not last half-hour drain immediately to init_discharge_target
                target = self.calc_limited_discharge_target(start_discharge_target, last_30mins_discharge_target, hour, minute)
                return await self.limit_timed_export(target, tolerance, formatted_date)
            else:  # last half-hour drain to floor
                min_charge_percentage = 100.0 * settings["battery_min_kWh"] / settings["battery_capacity_kWh"]
                return await self.limit_timed_export(min_charge_percentage, 0, formatted_date)

        else:
            msg = f"{formatted_date} no action"
            self.__logger.info(msg)
            return msg


if __name__ == "__main__":
    setup_logging(stream=sys.stdout)

    class _ConfigApplyOnly(logging.Filter):
        def filter(self, record):
            return record.name == __name__

    for handler in logging.getLogger().handlers:
        handler.addFilter(_ConfigApplyOnly())

    asyncio.run(ConfigApply().run())
