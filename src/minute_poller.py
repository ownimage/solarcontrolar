from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from solarcontrolar.givenergyfactory import GivEnergyFactory


class MinutePoller:
    def __init__(self):
        self.__state = JsonStore(Filenames.MINUTE_POLLER_STATE_FILE.value)

    def _store_minute_value(self, date_str, time_str, solar, usage):
        print("__store_minute_value", date_str, time_str, solar, usage)
        minute_store = JsonStore(Filenames.MINUTE_TOTALS_FILE.value)
        data = minute_store.read()

        if date_str not in data:
            data[date_str] = {}

        data[date_str][time_str] = {
            "solar": solar,
            "usage": usage
        }
        minute_store.write(data)
        return data

    def _store_power_data(self, date_str, time_str, status, solar, grid, inverter, home, battery):
        power_store = JsonStore(Filenames.MINUTE_POWER_FILE.value)
        data = power_store.read()

        if date_str not in data:
            data[date_str] = {}

        data[date_str][time_str] = {
            "status": status,
            "solar": solar,
            "grid": grid,
            "inverter": inverter,
            "home": home,
            "battery": battery
        }
        power_store.write(data)
        return data

    def run(self):
        print("============================================================================")
        print("Current time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        givenergy = GivEnergyFactory().instance()
        self._save_meter_data_latest(givenergy)
        self._save_power_data(givenergy)

    def _save_power_data(self, givenergy):
        raw = givenergy.system_data_latest()["data"]

        # Split timestamp
        dt = datetime.fromisoformat(raw["time"])
        date_str = dt.date().isoformat()
        time_str = dt.time().isoformat()

        # Extract fields
        battery = raw['battery']['percent']
        status = raw["status"]
        solar = raw["solar"]["power"]
        grid = raw["grid"]["power"]
        inverter = raw["inverter"]["power"]
        home = raw["consumption"]

        self._store_power_data(date_str, time_str, status, solar, grid, inverter, home, battery)

    def _save_meter_data_latest(self, givenergy) :
        date_str, time_str, solar, usage = givenergy.get_meter_data_latest()
        self._store_minute_value(date_str, time_str, solar, usage)

        now = datetime.fromisoformat(f"{date_str}T{time_str}")
        current_boundary = now.replace(
            minute=(now.minute // 30) * 30,
            second=0,
            microsecond=0
        )

        anchor = self.__state.read()
        if not anchor:  # First ever run: treat this as "end of previous window"
            self._save_anchor(current_boundary, solar, usage)
            return

        anchor_boundary = datetime.fromisoformat(anchor["boundary"])
        if current_boundary != anchor_boundary:  # always save first value in new half hour boundary
            self._save_anchor(current_boundary, solar, usage)

        if now >= anchor_boundary + timedelta(minutes=60):  # If we missed the entire window, skip it
            return

        if current_boundary > anchor_boundary:  # we observed at least one reading inside the window
            # value is calculated and writen when the first reading from the next period happens

            solar_delta = solar - anchor["solar"]
            usage_delta = usage - anchor["usage"]

            half_hour_key = anchor_boundary.strftime("%H:%M")
            date_key = anchor_boundary.date().isoformat()

            self._write_halfhour_summaries(
                date_key=date_key,
                half_hour_key=half_hour_key,
                solar_value=solar_delta,
                usage_value=usage_delta
            )

    def _save_anchor(self, boundary, solar, usage):
        anchor = {
            "boundary": boundary.isoformat(),
            "solar": solar,
            "usage": usage
        }
        print("write_anchor", anchor)
        self.__state.write(anchor)

    def _write_halfhour_summaries(self, date_key, half_hour_key, solar_value, usage_value):
        print("Half hour summary:", date_key, half_hour_key, solar_value, usage_value)
        self._write_solar_actuals(date_key, half_hour_key, solar_value)
        self._write_usage_actuals(date_key, half_hour_key, usage_value)

    def _write_solar_actuals(self, date_key, half_hour_key, solar_value):
        store = JsonStore(Filenames.SOLAR_ACTUALS.value)
        data = store.read()
        if date_key not in data:
            data[date_key] = {}
        data[date_key][half_hour_key] = solar_value
        store.write(dict(sorted(data.items())))

    def _write_usage_actuals(self, date_key, half_hour_key, usage_value):
        store = JsonStore(Filenames.USAGE_ACTUALS.value)
        data = store.read()
        if date_key not in data:
            data[date_key] = {}
        data[date_key][half_hour_key] = usage_value
        store.write(dict(sorted(data.items())))


if __name__ == "__main__":
    poller = MinutePoller()
    poller.run()

