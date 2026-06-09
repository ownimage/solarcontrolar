import os

import requests

from .givcloud import GivCloud
from .givlocal import GivLocal


class GivEnergyFactory:
    def __init__(self, requests=requests, os=os):
        self.requests = requests
        self.os = os

        local_url = os.getenv('GIVENERGY_LOCAL_URL')
        inverter_id = os.getenv('GIVENERGY_INVERTER_ID')
        if local_url is not None:
            self.giv_instance = GivLocal(local_url, inverter_id, requests)
        else:
            api_key = os.getenv('GIVENERGY_API_KEY')
            self.giv_instance = GivCloud(api_key, inverter_id, requests)

    def instance(self):
        return self.giv_instance
