import logging
import os
from datetime import datetime, timedelta

import pytz

from solarcontrolar.solcast import SolCast
from common.json_store import JsonStore
from filenames import Filenames
from settings import Settings

logger = logging.getLogger(__name__)


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
        logger.debug("Fetching SolCast forecast, site_id=%s", self.site_id)
        solcast = SolCast(self.api_key, self.site_id)
        forecast = solcast.forecast()
        if isinstance(forecast, dict) and "forecasts" in forecast:
            logger.debug("SolCast returned %d forecast entries", len(forecast["forecasts"]))
        else:
            logger.debug("SolCast response did not contain a forecasts list: %r", type(forecast).__name__)
        return forecast

    def check_already_exists(self, forecast) -> bool:
        exists = self.tomorrow_key in forecast
        logger.debug("Forecast for %s already exists: %s", self.tomorrow_key, exists)
        return exists

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
        logger.debug("Extracted %d half-hour periods for %s", len(hh), self.tomorrow_key)
        if hh:
            daily_total = sum(period["pv_estimate"] for period in hh.values())
            logger.debug("Raw pv_estimate total for %s: %.2f kW (kWh/day = %.2f)",
                         self.tomorrow_key, daily_total, daily_total * 0.5)
        return {self.tomorrow_key: hh}

    def run(self):
        forecast_history = self.forecast_history_store.read()
        logger.debug("Forecast history contains %d days: %s",
                     len(forecast_history), ", ".join(sorted(forecast_history.keys())))
        if not self.check_already_exists(forecast_history):
            logger.debug("No forecast for %s yet, fetching from SolCast", self.tomorrow_key)
            new_forecast = self.fetch_forecast()
            tomorrow_hh = self.half_hourly_forecast(new_forecast)
            if not tomorrow_hh.get(self.tomorrow_key):
                logger.warning("Forecast for %s is empty (no periods for that date)", self.tomorrow_key)
            self.forecast_history_store.write({**forecast_history, **tomorrow_hh})
            logger.info("Wrote forecast for %s to %s",
                        self.tomorrow_key, Filenames.SOLAR_FORECAST_FILE.value)
        else:
            logger.debug("Skipping SolCast fetch, forecast for %s already stored", self.tomorrow_key)


if __name__ == '__main__':
    from common.logging_setup import setup_logging
    setup_logging()
    manager = SolarForecastGenerator()
    manager.run()
