import json
from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from settings import Settings


class CalcError:
    def __init__(
            self,
            forecast_store=JsonStore(Filenames.SOLAR_FORECAST_FILE.value),
            actuals_store=JsonStore(Filenames.SOLAR_ACTUALS.value),
            settings_store=Settings()
    ):
        self.forecast_data = forecast_store.read()
        self.actuals_data = actuals_store.read()
        self.settings_store = settings_store
        self.start_date = (datetime.today() - timedelta(days=4)).date()
        self.end_date = (datetime.today() - timedelta(days=1)).date()

    def calculate_forecast_total(self, data):
        total = 0
        count = 0
        for date_str, entries in data.items():
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            if self.start_date <= d <= self.end_date:
                # Compatible with both list and dict formats
                iterable = entries.values() if isinstance(entries, dict) else entries
                for period in iterable:
                    total += 0.5 * period["pv_estimate"]
                    count += 1
        return total, count

    def calculate_actual_total(self, actuals):
        total = 0
        count = 0
        for date_str, entries in actuals.items():
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            if self.start_date <= d <= self.end_date:
                # Compatible with both list and dict formats
                print("entries: ", entries)
                print("entries.values(): ", entries.values())
                iterable = entries.values() if isinstance(entries, dict) else entries
                for period in iterable:
                    if isinstance(period, dict):
                        total += sum(period.values())
                    else:
                        total += period
                
                count += 1
        return total, count

    def update_settings(self, multiplier):
        settings = self.settings_store.read()
        settings["solar_forecast_multiplier"] = multiplier
        self.settings_store.write(settings)

    def run(self):
        forecast_total, forecast_count = self.calculate_forecast_total(self.forecast_data)
        actual_total, actual_count = self.calculate_actual_total(self.actuals_data)

        print(f"forecast total: {forecast_total} ({forecast_count})")
        print(f"actual total: {actual_total} ({actual_count})")

        if forecast_total > 0:
            multiplier = actual_total / forecast_total
            print(f"solar forecast multiplier: {multiplier}")

            if actual_count == 192 and forecast_count == 192 and 0.5 <= multiplier <= 1.5:
                self.update_settings(multiplier)
                print(f"solar forecast multiplier: {multiplier} written to settings")
        else:
            print("⚠️ Forecast total is zero — cannot calculate multiplier.")


# Example usage
if __name__ == "__main__":
    calcError = CalcError()
    calcError.run()
