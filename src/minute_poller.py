import json
import logging
import os
import time
from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from solarcontrolar.givenergyfactory import GivEnergyFactory
from solarcontrolar.givlocal import get_retry_delays, is_bad_battery_percent

logger = logging.getLogger(__name__)


class MinutePoller:
    def __init__(self):
        self.__state = JsonStore(Filenames.MINUTE_POLLER_STATE_FILE.value)

    def _store_minute_value(self, date_str, time_str, solar, usage):
        minute_store = JsonStore(Filenames.MINUTE_TOTALS_FILE.value)
        data = minute_store.read()

        if date_str not in data:
            data[date_str] = {}

        data[date_str][time_str] = {
            "solar": solar,
            "usage": usage
        }
        minute_store.write(data)
        entry_count = len(data)
        print(f"{Filenames.MINUTE_TOTALS_FILE.value}: {date_str} {time_str} solar={solar} usage={usage} "
              f"({entry_count} {'entry' if entry_count == 1 else 'entries'})")
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
        entry_count = len(data)
        print(f"{Filenames.MINUTE_POWER_FILE.value}: {date_str} {time_str} status={status} "
              f"solar={solar} grid={grid} inverter={inverter} home={home} battery={battery} "
              f"({entry_count} {'entry' if entry_count == 1 else 'entries'})")
        return data

    def run(self):
        print("============================================================================")
        print("Current time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        givenergy = GivEnergyFactory().instance()
        self._save_meter_data_latest(givenergy)
        self._save_power_data(givenergy)

    def _save_power_data(self, givenergy):
        raw = givenergy.system_data_latest()["data"]
        logger.info("system-data-latest: %s", json.dumps(raw, separators=(",", ":")))

        # Split timestamp
        dt = datetime.fromisoformat(raw["time"])
        date_str = dt.date().isoformat()
        time_str = dt.time().isoformat()

        # Extract fields
        battery = raw.get("battery", {}).get("percent")
        status = raw["status"]
        solar = raw["solar"]["power"]
        grid = raw["grid"]["power"]
        inverter = raw["inverter"]["power"]
        home = raw["consumption"]

        if is_bad_battery_percent(battery):
            logger.warning("Battery level %r outside 0-100, writing anyway (corrupt data)", battery)

        self._store_power_data(date_str, time_str, status, solar, grid, inverter, home, battery)

    def _load_anchor(self, now):
        anchor = self.__state.read()
        if not anchor:
            logger.debug("No anchor state, treating as first run")
            return None

        try:
            anchor_boundary = datetime.fromisoformat(anchor["boundary"])
            anchor_solar = anchor["solar"]
            anchor_usage = anchor["usage"]
        except (KeyError, TypeError, ValueError):
            logger.warning("Corrupt poller anchor state %r, re-anchoring", anchor)
            return None

        if not (now - timedelta(days=1)) <= anchor_boundary <= now + timedelta(minutes=5):
            logger.warning("Stale poller anchor boundary %s (now=%s), re-anchoring",
                           anchor_boundary.isoformat(), now.isoformat())
            return None

        return {"boundary": anchor_boundary, "solar": anchor_solar, "usage": anchor_usage}

    def _save_meter_data_latest(self, givenergy):
        date_str, time_str, solar, usage = givenergy.get_meter_data_latest()
        logger.info("meter-data-latest: %s", json.dumps(
            {"date": date_str, "time": time_str, "solar": solar, "usage": usage},
            separators=(",", ":")))

        try:
            now = datetime.fromisoformat(f"{date_str}T{time_str}")
        except ValueError:
            logger.warning("Unparseable meter timestamp %r/%r, skipping half-hour summary",
                           date_str, time_str)
            return

        current_boundary = now.replace(
            minute=(now.minute // 30) * 30,
            second=0,
            microsecond=0
        )

        anchor = self._load_anchor(now)
        if not anchor:
            self._store_minute_value(date_str, time_str, solar, usage)
            self._save_anchor(current_boundary, solar, usage)
            return

        if not self._usage_plausible(anchor, now, usage):
            retried = self._refetch_until_usage_plausible(
                givenergy, anchor, now, date_str, time_str, solar, usage)
            if retried is None:
                print("Usage still implausible, rejecting this minute's reading")
                return
            date_str, time_str, solar, usage = retried
            try:
                now = datetime.fromisoformat(f"{date_str}T{time_str}")
            except ValueError:
                logger.warning("Unparseable meter timestamp %r/%r, skipping half-hour summary",
                               date_str, time_str)
                return
            current_boundary = now.replace(
                minute=(now.minute // 30) * 30,
                second=0,
                microsecond=0
            )

        self._store_minute_value(date_str, time_str, solar, usage)

        anchor_boundary = anchor["boundary"]

        if now >= anchor_boundary + timedelta(minutes=60):
            logger.warning("Gap since last poll %s (>60 min), skipping missed window and "
                           "re-anchoring at %s",
                           anchor_boundary.isoformat(), current_boundary.isoformat())
            self._save_anchor(current_boundary, solar, usage)
            return

        if current_boundary > anchor_boundary:
            # value is calculated and written when the first reading from the next period happens
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

        if current_boundary != anchor_boundary:
            # always save first value in a new half hour boundary
            self._save_anchor(current_boundary, solar, usage)

    def _usage_plausible(self, anchor, now, usage):
        if usage < anchor["usage"]:
            logger.warning("Usage regression: %.3f < anchor %.3f", usage, anchor["usage"])
            return False
        elapsed_hours = max((now - anchor["boundary"]).total_seconds() / 3600.0, 1.0 / 60.0)
        max_rate = self._max_usage_kwh_per_hour()
        rate = (usage - anchor["usage"]) / elapsed_hours
        if rate > max_rate:
            logger.warning("Usage rate %.3f kWh/h exceeds max %.3f (usage=%.3f, anchor=%.3f, "
                           "elapsed=%.2fh)", rate, max_rate, usage, anchor["usage"], elapsed_hours)
            return False
        return True

    def _refetch_until_usage_plausible(self, givenergy, anchor, now,
                                       date_str, time_str, solar, usage):
        fetched = json.dumps({"date": date_str, "time": time_str,
                              "solar": solar, "usage": usage}, separators=(",", ":"))
        max_rate = self._max_usage_kwh_per_hour()
        print(f"Usage implausible vs anchor {anchor['boundary'].isoformat()} "
              f"(anchor_solar={anchor['solar']}, anchor_usage={anchor['usage']}, "
              f"max {max_rate} kWh/h): fetched={fetched}, retrying meter data")
        attempts = 0
        for delay in get_retry_delays():
            attempts += 1
            time.sleep(delay)
            date_str, time_str, solar, usage = givenergy.get_meter_data_latest()
            logger.info("meter-data-latest: %s", json.dumps(
                {"date": date_str, "time": time_str, "solar": solar, "usage": usage},
                separators=(",", ":")))
            try:
                retry_now = datetime.fromisoformat(f"{date_str}T{time_str}")
            except ValueError:
                retry_now = now
            if self._usage_plausible(anchor, retry_now, usage):
                logger.warning("Usage plausible after %d retry attempt(s): fetched=%s",
                               attempts, json.dumps(
                                   {"date": date_str, "time": time_str,
                                    "solar": solar, "usage": usage},
                                   separators=(",", ":")))
                return date_str, time_str, solar, usage
        return None

    def _max_usage_kwh_per_hour(self):
        raw = os.getenv("GIVENERGY_USAGE_MAX_KWH_PER_HOUR", "50")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 50.0
        return value if value > 0 else 50.0

    def _save_anchor(self, boundary, solar, usage):
        anchor = {
            "boundary": boundary.isoformat(),
            "solar": solar,
            "usage": usage
        }
        self.__state.write(anchor)
        print(f"{Filenames.MINUTE_POLLER_STATE_FILE.value}: anchor={anchor}")

    def _write_halfhour_summaries(self, date_key, half_hour_key, solar_value, usage_value):
        self._write_solar_actuals(date_key, half_hour_key, solar_value)
        self._write_usage_actuals(date_key, half_hour_key, usage_value)

    def _write_solar_actuals(self, date_key, half_hour_key, solar_value):
        store = JsonStore(Filenames.SOLAR_ACTUALS.value)
        data = store.read()
        if date_key not in data:
            data[date_key] = {}
        data[date_key][half_hour_key] = solar_value
        store.write(dict(sorted(data.items())))
        print(f"{Filenames.SOLAR_ACTUALS.value}: {date_key} {half_hour_key} solar={solar_value}")

    def _write_usage_actuals(self, date_key, half_hour_key, usage_value):
        store = JsonStore(Filenames.USAGE_ACTUALS.value)
        data = store.read()
        if date_key not in data:
            data[date_key] = {}
        data[date_key][half_hour_key] = usage_value
        store.write(dict(sorted(data.items())))
        print(f"{Filenames.USAGE_ACTUALS.value}: {date_key} {half_hour_key} usage={usage_value}")


if __name__ == "__main__":
    from common.logging_setup import setup_logging
    setup_logging()
    poller = MinutePoller()
    poller.run()