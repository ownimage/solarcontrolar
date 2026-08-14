import asyncio
import os

from givenergy_modbus.client.client import Client
from tenacity import retry, stop_after_attempt, wait_fixed

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

DEFAULT_PORT = 8899

RETRY_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 10


def lock_path():
    if os.name == "nt":
        return os.path.join(os.environ.get("TEMP", "."), "givenergy.lock")
    return "/tmp/givenergy.lock"


def acquire_lock():
    lockfile = open(lock_path(), "a+")
    if fcntl is not None:
        fcntl.flock(lockfile, fcntl.LOCK_EX)
    elif msvcrt is not None:
        lockfile.seek(0, os.SEEK_END)
        if lockfile.tell() == 0:
            lockfile.write("\0")
            lockfile.flush()
        msvcrt.locking(lockfile.fileno(), msvcrt.LK_LOCK, 1)
    return lockfile


def release_lock(lockfile):
    if fcntl is not None:
        fcntl.flock(lockfile, fcntl.LOCK_UN)
    elif msvcrt is not None:
        try:
            msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    lockfile.close()


class PlantWrapper:
    def __init__(self, plant):
        inv = plant.inverter
        self._status = inv.status.name
        self._battery_soc = inv.battery_soc
        self._system_time = inv.system_time
        self._date_str = inv.system_time.date().isoformat()
        self._time_str = inv.system_time.time().isoformat()
        self._solar_power = inv.p_pv()
        self._grid_power = inv.grid_import_power - inv.grid_export_power
        self._battery_power = inv.battery_discharge_power - inv.battery_charge_power
        self._house_power = - inv.p_load_demand
        self._generation_total = inv.e_pv_generation_total
        self._consumption_total = round(
            inv.e_pv_generation_total
            + inv.e_grid_in_total - inv.e_grid_out_total
            - inv.battery_capacity_kwh * inv.battery_soc / 100,
            1
        )
        self._enable_discharge = inv.enable_discharge
        self._enable_charge = inv.enable_charge

    @property
    def status(self):
        return self._status

    @property
    def battery_percentage(self):
        return self._battery_soc

    @property
    def system_time(self):
        return self._system_time

    @property
    def date_str(self):
        return self._date_str

    @property
    def time_str(self):
        return self._time_str

    @property
    def solar_power(self):
        return self._solar_power

    @property
    def grid_power(self):
        return self._grid_power

    @property
    def battery_power(self):
        return self._battery_power

    @property
    def house_power(self):
        return self._house_power

    @property
    def generation_total(self):
        return self._generation_total

    @property
    def consumption_total(self):
        return self._consumption_total

    @property
    def enable_discharge(self):
        return self._enable_discharge

    @property
    def enable_charge(self):
        return self._enable_charge


class GivenergyModbus():

    def __init__(self):
        self.inverter_ip = os.getenv('GIVENERGY_INVERTER_IP')
        # print(self.inverter_ip)
        if self.inverter_ip is None:
            raise ValueError("GIVENERGY_INVERTER_IP environment variable must be set")
        self.inverter_port = int(os.getenv('GIVENERGY_INVERTER_PORT', DEFAULT_PORT))

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def read_data(self):
        lock = acquire_lock()
        try:
            plant = await self._get_plant()
            inv = plant.inverter
            # print(f'battery charge percentage {inv.battery_soc}')
            # print(f'system time {inv.system_time}')
            # print(f'solar power {inv.p_pv()}')  # solar power
            # print(f'grid import power {inv.grid_import_power}')
            # print(f'grid export power {inv.grid_export_power}')
            # print(f'battery charge power {inv.battery_charge_power}')
            # print(f'battery discharge power {inv.battery_discharge_power}')
            # print(f'house power {inv.p_load_demand}')
            # print(f'generation total {inv.e_pv_generation_total}')
            # print(f'battery capacity {inv.battery_capacity_kwh}')
            # print(f'consumption total {inv.e_pv_generation_total + inv.e_grid_in_total - inv.e_grid_out_total - inv.battery_capacity_kwh * inv.battery_soc / 100}')
            # print(f'enable discharge {inv.enable_discharge}')
            # print(f'enable charge {inv.enable_charge}')
            # print(f'status {inv.status.name}')
            #
            # wrapper = PlantWrapper(plant)
            # print(f'wrapper battery percentage {wrapper.battery_percentage}')
            # print(f'wrapper system time {wrapper.system_time}')
            # print(f'wrapper solar power {wrapper.solar_power}')
            # print(f'wrapper grid power {wrapper.grid_power}')
            # print(f'wrapper battery power {wrapper.battery_power}')
            # print(f'wrapper house power {wrapper.house_power}')
            # print(f'wrapper generation total {wrapper.generation_total}')
            # print(f'wrapper consumption total {wrapper.consumption_total}')
            # print(f'wrapper enable discharge {wrapper.enable_discharge}')
            # print(f'wrapper enable charge {wrapper.enable_charge}')

            return plant
        finally:
            release_lock(lock)

    async def _get_plant(self):
        client = Client(host=self.inverter_ip, port=self.inverter_port)
        await client.connect()
        try:
            await client.detect()
            await client.load_config()
            await client.refresh()
        finally:
            await client.close()
        return client.plant

    async def _set_battery_flag(self, setter, reader, value):
        lock = acquire_lock()
        try:
            client = Client(host=self.inverter_ip, port=self.inverter_port)
            await client.connect()
            try:
                await client.detect()
                await client.load_config()
                before = getattr(client.plant.inverter, reader)
                inverter = client.plant.inverter
                await client.one_shot_command(getattr(inverter, setter)(value))
                await client.load_config()
                actual = getattr(client.plant.inverter, reader)
                if actual != value:
                    raise RuntimeError(
                        f"battery {reader} write not confirmed: wanted={value} actual={actual}"
                    )
                changed =  before != actual
                return changed
            finally:
                await client.close()
        finally:
            release_lock(lock)

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def set_enable_charge(self, enabled):
        return await self._set_battery_flag("set_enable_charge", "enable_charge", bool(enabled))

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def set_enable_discharge(self, enabled):
        return await self._set_battery_flag("set_enable_discharge", "enable_discharge", bool(enabled))



if __name__ == "__main__":
    givenergy_modbus = GivenergyModbus()
    asyncio.run(givenergy_modbus.set_enable_charge(False))
    asyncio.run(givenergy_modbus.set_enable_discharge(False))
    asyncio.run(givenergy_modbus.read_data())
