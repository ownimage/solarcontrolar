import logging
from datetime import date, datetime, timedelta
from collections import defaultdict
from dateutil import parser

from common.json_store import JsonStore
from filenames import Filenames
from settings import Settings
from solarcontrolar.givenergy import GivEnergy

logger = logging.getLogger(__name__)


class UsageActuals:
    def __init__(self,
                 usage_store=JsonStore(Filenames.USAGE_ACTUALS.value),
                 timezone=Settings().timezone(),
                 days: int = 28
                 ):
        self.usage_store = usage_store
        self.timezone = timezone
        self.days = days

    def summarize(self, data_points):
        entries = sorted([
            (parser.parse(ts), value)
            for ts, value in data_points.items()
        ])

        # Initialize nested dictionary for the summary
        summary = defaultdict(dict)

        for i in range(1, len(entries)):
            current_dt, current_val = entries[i]
            _, previous_val = entries[i - 1]
            delta = round(current_val - previous_val, 3)
            delta = delta if delta > 0 else 0  # sometimes the data regresses and should not

            # Round to nearest half hour
            minute = current_dt.minute
            rounded_minute = 0 if minute < 30 else 30
            rounded_dt = current_dt.replace(
                minute=rounded_minute, second=0, microsecond=0
            )

            date_str = rounded_dt.strftime("%Y-%m-%d")
            time_str = rounded_dt.strftime("%H:%M")

            # Accumulate deltas into their half-hour bins
            summary[date_str][time_str] = summary[date_str].get(time_str, 0) + delta
        return summary

    def fetch(self, date_str):
        logger.info('Fetching usage actuals for date: %s', date_str)
        data = GivEnergy().get_meter_data(date_str)
        summary = {
            datetime.fromisoformat(entry["time"])
            .astimezone(self.timezone)
            .strftime("%Y-%m-%d %H:%M:%S %Z%z"): float(entry["today"]["consumption"])
            for entry in data["data"]
        }
        summary[min(summary)] = 0.0  # this is to fix a data problem where sometimes the api returns bad data, the day should always start at zero
        return dict(sorted(summary.items()))

    def run(self):
        usage_actuals = self.usage_store.read()
        today = date.today()
        date_strs = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, self.days + 1)]
        missing_days = [date_str for date_str in date_strs if date_str not in usage_actuals]
        for date_str in missing_days:
            data = self.fetch(date_str)
            hh_summary = self.summarize(data)
            usage_actuals.update(hh_summary)

        self.usage_store.write(dict(sorted(usage_actuals.items())))


if __name__ == '__main__':
    ua = UsageActuals()
    ua.run()
