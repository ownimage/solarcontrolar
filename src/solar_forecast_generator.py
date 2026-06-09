import os
from datetime import datetime, timedelta

import pytz

from solarcontrolar.solcast import SolCast
from common.json_store import JsonStore
from filenames import Filenames
from settings import Settings


class SolarForecastGenerator:
    LOCAL_TZ = pytz.timezone('Europe/London')

    def __init__(self, api_key: str = None, site_id: str = None,
                 forecast_history_store=JsonStore(Filenames.SOLAR_FORECAST_FILE.value),
                 settings=Settings(),
                 os=os,
                 datetime=datetime,
                 timedelta=timedelta
                 ):
        self.api_key = api_key or os.getenv("SOLCAST_API_KEY")
        self.site_id = site_id or os.getenv("SOLCAST_SITE_ID")
        self.tomorrow = (datetime.now(settings.timezone()) + timedelta(days=1)).date()
        self.tomorrow_key = self.tomorrow.isoformat()
        self.forecast_history_store = forecast_history_store

    # TODO need to be able to inject SolCast
    def fetch_forecast(self):
        solcast = SolCast(self.api_key, self.site_id)
        return solcast.forecast()

    def check_already_exists(self, forecast) -> bool:
        return self.tomorrow_key in forecast

    def half_hourly_forecast(self, data):
        hh = {}
        for entry in data['forecasts']:
            dt = datetime.fromisoformat(entry['period_end'].split('.')[0]) - timedelta(minutes=30)
            if dt.date() == self.tomorrow:
                hh[dt.strftime("%H:%M")] = {
                    'pv_estimate': entry['pv_estimate'],
                    'pv_estimate10': entry['pv_estimate10'],
                    'pv_estimate90': entry['pv_estimate90'],
                }
        return {self.tomorrow_key: hh}

    def run(self):
        forecast_history = self.forecast_history_store.read()
        if not self.check_already_exists(forecast_history):
            new_forecast = self.fetch_forecast()
            tomorrow_hh = self.half_hourly_forecast(new_forecast)
            self.forecast_history_store.write({**forecast_history, **tomorrow_hh})


if __name__ == '__main__':
    manager = SolarForecastGenerator()
    manager.run()
