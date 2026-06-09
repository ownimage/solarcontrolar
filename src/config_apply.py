import os
import datetime
import logging
import json

import pytz
from tenacity import retry, stop_after_attempt, wait_fixed

from common.json_store import JsonStore
from solarcontrolar.givenergyfactory import GivEnergyFactory

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


class ConfigApply:
    def __init__(self, config=JsonStore("config.json"), os=os, json=json, GivEnergyFactory=GivEnergyFactory(), pytz=pytz, datetime=datetime, logger=logger):
        self.__config = config
        self.__os = os
        self.__json = json
        self.__GivEnergyFactory = GivEnergyFactory
        self.__pytz = pytz
        self.__datetime = datetime
        self.__logger = logger

    def get_settings(self):
        with open("settings.json", "r") as file:
            return self.__json.load(file)

    def get_givenergy(self):
        return self.__GivEnergyFactory.instance()

    def get_current_time(self, timezone_str="Europe/London"):
        local_tz = self.__pytz.timezone(timezone_str)
        now = self.__datetime.datetime.now(local_tz)
        return now, now.strftime("%Y-%m-%d %H:%M:%S")

    # @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def charge_to_percentage(self, givenergy, tolerance, formatted_date):
        target_percentage = self.__config.read()["charge_to_percentage"]
        battery_level = givenergy.battery_level()
        enabled = battery_level <= target_percentage

        if abs(battery_level - target_percentage) > tolerance:
            result = givenergy.set_timed_charge(enabled)
            if result:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} CHANGE set_timed_charge({enabled})"
            else:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} set_timed_charge({enabled})"
        else:
            msg = f"{formatted_date} battery_level={battery_level} is within tolerance={tolerance} of target_percentage={target_percentage} NO CHANGE"

        self.__logger.info(msg)
        return msg  # Allows assertion in unit tests

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def limit_timed_export(self, givenergy, target_percentage, tolerance, formatted_date):
        battery_level = givenergy.battery_level()
        enabled = battery_level >= target_percentage

        if abs(battery_level - target_percentage) > tolerance:
            result = givenergy.set_timed_export(enabled)
            if result:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} CHANGE set_timed_export({enabled})"
            else:
                msg = f"{formatted_date} battery_level={battery_level} target_percentage={target_percentage} set_timed_export({enabled})"
        else:
            msg = f"{formatted_date} battery_level={battery_level} is within tolerance={tolerance} of target_percentage={target_percentage} NO CHANGE"

        self.__logger.info(msg)
        return msg  # Allows assertion in unit tests

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def full_discharge(self, givenergy, formatted_date):
        battery_level = givenergy.battery_level()

        result = givenergy.set_timed_export(True)
        if result:
            msg = f"{formatted_date} battery_level={battery_level} target_percentage=0 CHANGE set_timed_export(True)"
        else:
            msg = f"{formatted_date} battery_level={battery_level} target_percentage=0 set_timed_export(True)"

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

    # Main function for better testability
    def main(self):
        givenergy = self.get_givenergy()
        settings = self.get_settings()
        tolerance = settings["tolerance_percent"]
        start_discharge_target = settings["start_discharge_target"]
        last_30mins_discharge_target = settings["last_30mins_discharge_target"]

        now, formatted_date = self.get_current_time()
        hour = now.hour
        minute = now.minute

        if 2 <= hour < 5:
            return self.charge_to_percentage(givenergy, tolerance, formatted_date)
        elif 16 <= hour < 19:
            if hour < 18 or minute < 30:  # not last half-hour drain immediately to init_discharge_target
                target = self.calc_limited_discharge_target(start_discharge_target, last_30mins_discharge_target, hour, minute)
                return self.limit_timed_export(givenergy, target, tolerance, formatted_date)
            else:  # last half-hour drain to floor
                return self.full_discharge(givenergy, formatted_date)

        else:
            msg = f"{formatted_date} no action"
            self.__logger.info(msg)
            return msg


if __name__ == "__main__":
    ConfigApply().main()
