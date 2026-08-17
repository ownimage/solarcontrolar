import logging
from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from settings import Settings

logger = logging.getLogger(__name__)


class CalcError:
    def __init__(
            self,
            forecast_store=JsonStore(Filenames.SOLAR_FORECAST_FILE.value),
            actuals_store=JsonStore(Filenames.SOLAR_ACTUALS.value),
            settings_store=Settings(),
            days = 2
    ):
        self._days = days
        self.forecast_data = forecast_store.read()
        self.actuals_data = actuals_store.read()
        self.settings_store = settings_store
        today = datetime.now(settings_store.timezone())
        self.start_date = (today - timedelta(days=self._days + 1)).date()
        self.end_date = (today - timedelta(days=1)).date()
        logger.debug("Comparing window: %s to %s (timezone %s)",
                     self.start_date, self.end_date, settings_store.timezone())
        logger.debug("Forecast store has %d days, actuals store has %d days",
                     len(self.forecast_data), len(self.actuals_data))

    def calculate_forecast_total(self, data):
        total = 0
        count = 0
        for date_str, entries in data.items():
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            if self.start_date <= d <= self.end_date:
                # Compatible with both list and dict formats
                iterable = entries.values() if isinstance(entries, dict) else entries
                day_total = 0
                for period in iterable:
                    day_total += 0.5 * period["pv_estimate"]
                    count += 1
                total += day_total
                logger.debug("Forecast %s: %.2f kWh over %d periods", date_str, day_total, len(iterable))
            else:
                logger.debug("Forecast %s outside window, skipped", date_str)
        return total, count

    def calculate_actual_total(self, actuals):
        total = 0
        count = 0
        for date_str, entries in actuals.items():
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            if self.start_date <= d <= self.end_date:
                day_total = 0
                day_periods = 0
                # Compatible with both list and dict formats
                print("entries: ", entries)
                print("entries.values(): ", entries.values())
                iterable = entries.values() if isinstance(entries, dict) else entries
                for period in iterable:
                    if isinstance(period, dict):
                        day_total += sum(period.values())
                    else:
                        day_total += period
                    day_periods += 1
                total += day_total
                count += day_periods
                logger.debug("Actuals %s: %.2f kWh over %d periods", date_str, day_total, day_periods)
            else:
                logger.debug("Actuals %s outside window, skipped", date_str)
        return total, count

    def update_settings(self, multiplier):
        settings = self.settings_store.read()
        settings["solar_forecast_multiplier"] = multiplier
        self.settings_store.write(settings)
        logger.debug("Wrote solar_forecast_multiplier=%s to %s", multiplier, Filenames.SETTINGS.value)

    def _missing_window_days(self, data):
        missing = []
        total_days = 0
        d = self.start_date
        while d <= self.end_date:
            total_days += 1
            if d.isoformat() not in data:
                missing.append(d.isoformat())
            d += timedelta(days=1)
        return missing, total_days

    def _latest_date(self, data):
        try:
            return datetime.strptime(sorted(data.keys())[-1], '%Y-%m-%d').date()
        except (ValueError, KeyError, IndexError):
            return None

    def check_data_staleness(self):
        missing_actuals, expected_days = self._missing_window_days(self.actuals_data)
        if missing_actuals:
            logger.warning("DATA STALENESS: %d/%d actuals days missing in %s..%s: %s",
                           len(missing_actuals), expected_days,
                           self.start_date, self.end_date, ", ".join(missing_actuals))
        missing_forecasts, expected_days = self._missing_window_days(self.forecast_data)
        if missing_forecasts:
            logger.warning("DATA STALENESS: %d/%d forecast history days missing in %s..%s: %s",
                           len(missing_forecasts), expected_days,
                           self.start_date, self.end_date, ", ".join(missing_forecasts))

        latest_actual = self._latest_date(self.actuals_data)
        if latest_actual is not None and latest_actual < self.start_date:
            logger.warning("DATA STALENESS: solar_actuals.json latest entry is %s, "
                           "older than window start %s",
                           latest_actual, self.start_date)
        if not self.actuals_data:
            logger.warning("DATA STALENESS: solar_actuals.json is empty")

    def run(self):
        self.check_data_staleness()

        forecast_total, forecast_count = self.calculate_forecast_total(self.forecast_data)
        actual_total, actual_count = self.calculate_actual_total(self.actuals_data)

        print(f"forecast total: {forecast_total} ({forecast_count})")
        print(f"actual total: {actual_total} ({actual_count})")
        logger.debug("window %s..%s, forecast %.3f kWh (%d periods), actual %.3f kWh (%d periods)",
                     self.start_date, self.end_date, forecast_total, forecast_count,
                     actual_total, actual_count)

        if actual_count == 0 and forecast_count > 0:
            logger.warning("actual total is zero: solar_actuals.json has no data in window %s..%s "
                           "(latest entry %s) — check minute_poller is writing half-hour summaries",
                           self.start_date, self.end_date, self._latest_date(self.actuals_data))

        if forecast_total > 0:
            multiplier = actual_total / forecast_total
            print(f"solar forecast multiplier: {multiplier}")
            logger.debug("Raw multiplier actual/forecast = %.4f", multiplier)

            expected_count = (self._days + 1) * 48
            complete = actual_count == expected_count and forecast_count == expected_count
            in_range = 0.5 <= multiplier <= 1.5
            logger.debug("Data complete (192 periods each side): %s, multiplier in 0.5..1.5 range: %s",
                         complete, in_range)

            if complete and in_range:
                self.update_settings(multiplier)
                print(f"solar forecast multiplier: {multiplier} written to settings")
            else:
                logger.warning("Multiplier NOT written: complete=%s, in_range=%s "
                               "(forecast periods=%d, actual periods=%d, expected count=%d)",
                               complete, in_range, forecast_count, actual_count, expected_count)
        else:
            print("⚠️ Forecast total is zero — cannot calculate multiplier.")
            logger.warning("Forecast total is zero, cannot calculate multiplier")


# Example usage
if __name__ == "__main__":
    from common.logging_setup import setup_logging
    setup_logging()
    calcError = CalcError()
    calcError.run()