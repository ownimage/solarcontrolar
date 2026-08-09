from collections import defaultdict
from datetime import datetime, timedelta

import os
import time

import requests

from .givenergybase import GivEnergyBase


class GivLocal(GivEnergyBase):
    def __init__(self, base_url, inverter_id, requests=requests):
        super().__init__(inverter_id, requests)
        if (base_url is None) or (inverter_id is None):
            raise ValueError(f"You must provide both an base_url and an inverter_id. \n base_url={base_url}\ninverter_id={inverter_id}")

        self.base_url = base_url

        self.headers = {
            "Accept": "application/json"
        }

    def events(self):
        return self.get(f"{self.base_url}/inverter/{self.inverter_id}/events")

    def data(self):
        return self.get(f"{self.base_url}/inverter/{self.inverter_id}/data-points/2025-04-25?page=1")

    def energy_flows(self):
        payload = {
            "start_time": "2025-04-25",
            "end_time": "2025-04-26",
            "grouping": 1
        }
        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/energy-flows", payload)

    def settings(self):
        return self.get(f"{self.base_url}/inverter/{self.inverter_id}/settings")

    def setting_read(self, setting_id):
        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/settings/{setting_id}/read")

    def setting_write(self, setting_id, value):
        payload = {"value": value}
        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/settings/{setting_id}/write", payload)

    def get_day_usage(self, days_ago):
        today = datetime.today()
        start_time = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        end_time = (today - timedelta(days=days_ago - 1)).strftime("%Y-%m-%d")
        payload = {"start_time": start_time, "end_time": end_time, "grouping": 0}
        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/energy-flows", payload)

    def get_meter_data(self, date_str):
        return self.get(f"{self.base_url}/inverter/{self.inverter_id}/data-points/{date_str}?pageSize=1000")

    def get_generation_actuals(self, end_date, days):
        start_date = end_date - timedelta(days=days)
        payload = {
            "start_time": start_date.strftime("%Y-%m-%d"),
            "end_time": end_date.strftime("%Y-%m-%d"),
            "grouping": 0,
            "types": [0, 1, 2]
        }

        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/energy-flows", payload)

    def get_generation_actuals_hh(self, end_date, days):
        hh = defaultdict(dict)
        raw_data = self.get_generation_actuals(end_date, days)
        for record in raw_data["data"].values():
            start_time = record["start_time"]
            dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            date_str = dt.date().isoformat()
            time_str = dt.strftime("%H:%M")
            hh[date_str][time_str] = record["data"]
        return {k: v for k, v in hh.items() if len(v) == 48}

    def get_usage_actuals(self, end_date, days):
        start_date = end_date - timedelta(days=days)
        payload = {
            "start_time": start_date.strftime("%Y-%m-%d"),
            "end_time": end_date.strftime("%Y-%m-%d"),
            "grouping": 0,
            # "types": [0, 3, 5]
        }

        return self.post(f"{self.base_url}/inverter/{self.inverter_id}/energy-flows", payload)

    def last_4_weeks_usage(self):
        weekly_usage = defaultdict(float)  # Dictionary to store sums per day of the week

        # Iterate over the last 28 days
        for days_ago in range(1, 28):
            daily_data = self.get_day_usage(days_ago)  # Get usage for the given day
            date_obj = datetime.today() - timedelta(days=days_ago)
            day_of_week = date_obj.strftime("%A")  # Convert to full weekday name

            daily_usage_sum = sum(entry["data"].get("0", 0) for entry in daily_data["data"].values())
            daily_usage_sum += sum(entry["data"].get("3", 0) for entry in daily_data["data"].values())
            daily_usage_sum += sum(entry["data"].get("5", 0) for entry in daily_data["data"].values())
            weekly_usage[day_of_week] += daily_usage_sum

        return dict(weekly_usage)

    def get_meter_data_latest(self):
        return self._get_meter_data_latest_fix_datetime()

    def _get_meter_data_latest_fix_datetime(self):
        result = self._fetch_with_date_retry(
            url=f"{self.base_url}/inverter/{self.inverter_id}/meter-data-latest",
            extract_date=self._extract_time,
            patch_date=self._patch_time,
        )
        raw = result["data"]

        # split timestamp
        dt = datetime.fromisoformat(raw["time"])
        date_str = dt.date().isoformat()
        time_str = dt.time().isoformat()

        # extract values
        solar_total = raw["total"]["solar"]
        usage_total = raw["total"]["consumption"]

        return date_str, time_str, solar_total, usage_total

    def _fetch_with_date_retry(self, url, extract_date, patch_date):
        result = self.get(url)
        if not self._is_bad_date(extract_date(result)):
            return result

        print(f"Bad date/time from {url}, retrying")
        for delay in get_retry_delays():
            time.sleep(delay)
            result = self.get(url)
            if not self._is_bad_date(extract_date(result)):
                return result

        print("Date and Time corrected")
        patch_date(result)
        return result

    def _is_bad_date(self, ts):
        if not isinstance(ts, str) or not ts:
            return True
        if ts.startswith("2000-01-01"):
            return True
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            return True
        return False

    def _extract_time(self, result):
        return result["data"].get("time", "")

    def _patch_time(self, result):
        result["data"]["time"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def _system_data_fix_datetime(self):
        return self._fetch_with_date_retry(
            url=f"{self.base_url}/inverter/{self.inverter_id}/system-data-latest",
            extract_date=self._extract_time,
            patch_date=self._patch_time,
        )

    def battery_level(self):
        return self._system_data_fix_datetime()['data']['battery']['percent']

    def system_data_latest(self):
        return self._system_data_fix_datetime()


def get_retry_delays():
    raw = os.getenv("GIVENERGY_RETRY_DELAYS", "1,2,5,10")
    delays = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            delays.append(float(part))
        except ValueError:
            pass
    return delays if delays else [1, 2, 5, 10]