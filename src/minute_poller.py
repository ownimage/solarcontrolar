import asyncio
import json
import logging
from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from solarcontrolar.givenergymodbus import GivenergyModbus, PlantWrapper, InverterSnapshot

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

    def _store_power_data(self, date_str, time_str, status, solar, grid, home, battery, battery_level):
        power_store = JsonStore(Filenames.MINUTE_POWER_FILE.value)
        data = power_store.read()

        if date_str not in data:
            data[date_str] = {}

        data[date_str][time_str] = {
            "status": status,
            "solar": solar,
            "grid": grid,
            "home": home,
            "battery": battery,
            "battery_level": battery_level
        }
        power_store.write(data)
        entry_count = len(data)
        print(f"{Filenames.MINUTE_POWER_FILE.value}: {date_str} {time_str} status={status} "
              f"solar={solar} grid={grid} home={home} battery={battery} battery_level={battery_level}"
              f"({entry_count} {'entry' if entry_count == 1 else 'entries'})")
        return data

    async def run(self):
        print("============================================================================")
        print("Current time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        data = await GivenergyModbus().read_data_direct()
        self._save_meter_data_latest(data)
        self._save_power_data(data)

    def _save_power_data(self, data: InverterSnapshot):
        logger.info("system-data-latest: %s", data.system_time)

        date_str = data.date_str
        time_str = data.time_str

        status = data.status
        solar = data.solar_power
        grid = data.grid_power
        home = data.house_power
        battery = data.battery_power
        battery_level = data.battery_soc

        self._store_power_data(date_str, time_str, status, solar, grid, home, battery, battery_level)

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

    def get_meter_data_latest(self, plantWrapper: PlantWrapper):
        date_str = plantWrapper.date_str
        time_str = plantWrapper.time_str

        solar_total = plantWrapper.generation_total
        usage_total = plantWrapper.consumption_total
        return date_str, time_str, solar_total, usage_total

    def _save_meter_data_latest(self, data: InverterSnapshot):
        date_str, time_str, solar, usage = self.get_meter_data_latest(data)
        logger.info("meter-data-latest: %s", json.dumps(
            {"date": date_str, "time": time_str, "solar": solar, "usage": usage},
            separators=(",", ":")))

        self._store_minute_value(date_str, time_str, solar, usage)

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
            self._save_anchor(current_boundary, solar, usage)
            return

        anchor_boundary = anchor["boundary"]

        if now >= anchor_boundary + timedelta(minutes=60):
            logger.warning("Gap since last poll %s (>60 min), skipping missed window and "
                           "re-anchoring at %s",
                           anchor_boundary.isoformat(), current_boundary.isoformat())
            self._save_anchor(current_boundary, solar, usage)
            return

        if current_boundary > anchor_boundary:
            # value is calculated and written when the first reading from the next period happens
            solar_delta = round(solar - anchor["solar"], 1)
            usage_delta = round(usage - anchor["usage"], 1)

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
    asyncio.run(MinutePoller().run())
