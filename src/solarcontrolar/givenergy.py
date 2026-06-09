import requests
import os
from datetime import date, datetime, timedelta
from collections import defaultdict


class GivEnergy:
    def __init__(self, api_key=None, inverter_id=None, requests=requests, os=os):

        self.api_key = api_key if api_key is not None else os.getenv('GIVENERGY_API_KEY')
        self.inverter_id = inverter_id if inverter_id is not None else os.getenv('GIVENERGY_INVERTER_ID')

        self.requests = requests

        self.base_url = "https://api.givenergy.cloud/v1"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

    def get(self, url, payload=None):
        # Set up headers with authorization
        response = self.requests.request("GET", url, headers=self.headers, json=payload)

        if response.status_code == 200:
            return response.json()
        else:
            raise BaseException(response.status_code, response.text)

    def post(self, url, payload=None):
        response = self.requests.post(url, headers=self.headers, json=payload)

        if response.status_code == 200 or response.status_code == 201:
            return response.json()
        else:
            raise BaseException(response.status_code, response.text)

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

    def setting_write_validate(self, setting_id, value, function_name):
        current_value = self.setting_read(setting_id)['data']['value']
        if current_value == value:
            return False
        else:
            print(f'{function_name} current_value {current_value} being set to {value}')
            self.setting_write(setting_id, value)
            updated_value = self.setting_read(setting_id)['data']['value']
            if isinstance(value, bool):
                updated_value = bool(updated_value)
            if updated_value != value:
                raise RuntimeError(f'Givnergy::{function_name}({value}) failed, updated_value={updated_value} != value={value}')
            print(f'{function_name} updated_value {updated_value}')
            return True

    def get_timed_charge(self):
        return self.setting_read(66)

    def set_timed_charge(self, value):
        return self.setting_write_validate(66, value, 'set_enable_ac_charge')

    def get_timed_export(self):
        return self.setting_read(56)

    def set_timed_export(self, value):
        return self.setting_write_validate(56, value, 'set_enable_dc_discharge')

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
        for days_ago in range(1, 8):
            daily_data = self.get_day_usage(days_ago)  # Get usage for the given day
            date_obj = datetime.today() - timedelta(days=days_ago)
            day_of_week = date_obj.strftime("%A")  # Convert to full weekday name

            daily_usage_sum = sum(entry["data"].get("0", 0) for entry in daily_data["data"].values())
            daily_usage_sum += sum(entry["data"].get("3", 0) for entry in daily_data["data"].values())
            daily_usage_sum += sum(entry["data"].get("5", 0) for entry in daily_data["data"].values())
            weekly_usage[day_of_week] += daily_usage_sum

        return dict(weekly_usage)

    def battery_level(self):
        return self.get(f"{self.base_url}/inverter/{self.inverter_id}/system-data/latest")['data']['battery']['percent']
