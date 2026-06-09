import os
from datetime import datetime, time
from common.json_store import JsonStore
from filenames import Filenames
from solarcontrolar.givenergy import GivEnergy


class SolarActualsUpdater:
    def __init__(self, days=7):
        self.days = days
        self.api_key = os.getenv("GIVENERGY_API_KEY")
        self.inverter_id = os.getenv("GIVENERGY_INVERTER_ID")
        self.givenergy = GivEnergy(self.api_key, self.inverter_id)
        self.store = JsonStore(Filenames.SOLAR_ACTUALS.value)

    def get_end_date(self):
        return datetime.combine(datetime.today(), time.min).date()

    def fetch_generation_actuals(self):
        end_date = self.get_end_date()
        return self.givenergy.get_generation_actuals_hh(end_date, self.days)

    def run(self):
        existing = self.store.read()
        new_data = self.fetch_generation_actuals()
        merged = {**existing, **new_data}
        self.store.write(merged)
        return merged


if __name__ == "__main__":
    updater = SolarActualsUpdater()
    updater.run()