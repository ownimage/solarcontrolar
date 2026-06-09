import os
import time

import requests


class GivEnergyBase:
    def __init__(self, inverter_id, requests=requests):
        if inverter_id is None:
            raise ValueError(f"You must provide an inverter_id.")

        self.inverter_id = inverter_id
        self.requests = requests
        self.__sleep_time = 2

    def get(self, url, payload=None):
        # Set up headers with authorization
        response = self.requests.request("GET", url, headers=self.headers, json=payload)

        if response.status_code == 200:
            return response.json()
        else:
            raise BaseException(response.status_code, response.text)

    def post(self, url, payload=None):
        time.sleep(self.__sleep_time)
        response = self.requests.post(url, headers=self.headers, json=payload)

        if response.status_code == 200 or response.status_code == 201:
            return response.json()
        else:
            raise BaseException(response.status_code, response.text)

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
