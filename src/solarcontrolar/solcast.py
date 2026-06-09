import requests

class SolCast:
    def __init__(self, api_key, site_id):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("Please supply api_key")

        self.site_id = site_id
        if not self.site_id:
            raise ValueError("Please supply site_id")

        self.base_url = "https://api.solcast.com.au/rooftop_sites/"

    def get(self, url):
        # Set up headers with authorization
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Make the GET request
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            raise BaseException(response.status_code, response.text)

    def forecast(self):
        return self.get(f"{self.base_url}{self.site_id}/forecasts?format=json")

    def actuals(self):
        return self.get(f"{self.base_url}{self.site_id}/estimated_actuals?format=json")

