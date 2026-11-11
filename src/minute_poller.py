import asyncio
import logging
import math
from datetime import datetime, timedelta

from common.json_store import JsonStore
from filenames import Filenames
from solarcontrolar.givenergymodbus import GivenergyModbus, InverterSnapshot

logger = logging.getLogger(__name__)


class MinutePoller:
    def __init__(self):
        self.__state = JsonStore(Filenames.MINUTE_POLLER_STATE_FILE.value)

    def _store_minute_value(self, date_str, time_str, solar, usage, *,
                            grid_import_total=None, grid_export_total=None, ac_charge_total=None):
        minute_store = JsonStore(Filenames.MINUTE_TOTALS_FILE.value)
        data = minute_store.read()

        if date_str not in data:
            data[date_str] = {}

        data[date_str][time_str] = {
            "solar": solar,
            "usage": usage,
            "grid_import_total": grid_import_total,
            "grid_export_total": grid_export_total,
            "ac_charge_total": ac_charge_total,
            "usage_method": "givtcp_dc_hybrid_v2",
            "solar_method": "pv_ir11_12_v1"
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
        if data.date_str and data.time_str:
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

    def get_meter_data_latest(self, data: InverterSnapshot):
        date_str = data.date_str
        time_str = data.time_str

        solar_total = data.generation_total
        usage_total = data.consumption_total
        return date_str, time_str, solar_total, usage_total

    def _save_meter_data_latest(self, data: InverterSnapshot):
        """Store cumulative kWh and summarise complete, observed half-hours.

        Interpolate counters at boundaries between adjacent polls (max 180s).
        Versioned state prevents deltas across energy formula/register changes.
        """
        date_str, time_str, solar, usage = self.get_meter_data_latest(data)
        try:
            now = datetime.fromisoformat(f"{date_str}T{time_str}")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
                       for v in (solar, usage)):
                raise ValueError("invalid energy counters")
        except (ValueError, TypeError):
            logger.warning("Invalid meter sample; dropping anchor")
            self.__state.write({})
            return

        state = self.__state.read()
        sample = {"timestamp": now.isoformat(), "solar": solar, "usage": usage}
        next_state = {"version": 3, "last_sample": sample}
        if state.get("version") == 3:
            try:
                previous = state["last_sample"]
                then = datetime.fromisoformat(previous["timestamp"])
                seconds = (now - then).total_seconds()
                # Duplicate/out-of-order polls must not replace a newer baseline.
                if seconds <= 0:
                    logger.warning("Ignoring duplicate or backwards meter timestamp")
                    return
                valid = (seconds <= 180 and all(
                    isinstance(previous[k], (int, float)) and math.isfinite(previous[k])
                    and sample[k] >= previous[k] - 0.3 for k in ("solar", "usage")))
            except (KeyError, TypeError, ValueError):
                valid = False
            if valid:
                boundary = now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)
                if then < boundary <= now:
                    fraction = (boundary - then).total_seconds() / seconds
                    counters = {k: previous[k] + fraction * (sample[k] - previous[k])
                                for k in ("solar", "usage")}
                    anchor = state.get("anchor", {})
                    if anchor.get("boundary") == (boundary - timedelta(minutes=30)).isoformat():
                        try:
                            deltas = {k: round(counters[k] - anchor[k], 3) for k in counters}
                            if all(math.isfinite(v) and v >= 0 for v in deltas.values()):
                                start = boundary - timedelta(minutes=30)
                                self._write_halfhour_summaries(
                                    start.date().isoformat(), start.strftime("%H:%M"),
                                    deltas["solar"], deltas["usage"])
                            else:
                                logger.warning("Negative half-hour delta; skipping suspect period")
                        except (KeyError, TypeError, ValueError):
                            logger.warning("Invalid half-hour anchor; re-anchoring")
                    next_state["anchor"] = {"boundary": boundary.isoformat(), **counters}
                elif "anchor" in state:
                    next_state["anchor"] = state["anchor"]
            else:
                logger.warning("Poll gap, counter reset or corrupt state; dropping partial period")
        # An exact boundary can start a complete period immediately.
        if now.minute % 30 == 0 and now.second == 0 and now.microsecond == 0:
            next_state["anchor"] = {"boundary": now.isoformat(), "solar": solar, "usage": usage}
        self._store_minute_value(
            date_str, time_str, solar, usage,
            grid_import_total=data.grid_import_total,
            grid_export_total=data.grid_export_total,
            ac_charge_total=data.ac_charge_total,
        )
        self.__state.write(next_state)

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
    asyncio.run(MinutePoller().run())
