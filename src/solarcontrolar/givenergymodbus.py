import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime

from givenergy_modbus.client.client import Client
from givenergy_modbus.pdu import ReadHoldingRegistersRequest, ReadInputRegistersRequest, WriteHoldingRegisterRequest
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

# Inverter status register IR(0) → name, matching givenergy_modbus Status(Int)Enum.
_STATUS_NAMES = {
    0: "WAITING",
    1: "NORMAL",
    2: "WARNING",
    3: "FAULT",
    4: "FLASHING_FIRMWARE_UPDATE",
}


def _int16(value: int) -> int:
    """Interpret a 16-bit register value as a signed integer (two's complement)."""
    return value if value < 0x8000 else value - 0x10000


def _uint32(high: int, low: int) -> int:
    """Combine two registers into an unsigned 32-bit int."""
    return (high << 16) + low


@dataclass
class InverterSnapshot:
    """Values read directly from raw registers for a single-phase inverter."""

    battery_soc: int | None
    system_time: datetime | None
    date_str: str | None
    time_str: str | None
    solar_power: int | None
    grid_power: float | None
    battery_power: float | None
    grid_import_power: int | None
    grid_export_power: int | None
    battery_charge_power: int | None
    battery_discharge_power: int | None
    house_power: int | None
    generation_total: float | None
    battery_capacity_kwh: float | None
    consumption_total: float | None
    enable_discharge: bool | None
    enable_charge: bool | None
    status: str | None


def _system_battery_voltage(dtc_raw: int) -> float:
    """Nominal battery voltage for the device type code, as in Model.system_battery_voltage."""
    first_digit = f"{dtc_raw:04x}"[0]
    if first_digit == "8":
        return 307.0  # All-in-One
    if first_digit in ("4", "6"):
        return 76.8  # three-phase
    return 51.2


def _decode_snapshot(ir: list, hr: list, hr_enable_charge: int) -> InverterSnapshot:
    """Decode IR(0,60), HR(0,60) and HR(96) register values into an InverterSnapshot.

    Mirrors the single-phase register layout and its derived properties
    (e.g. battery_capacity_kwh, grid/battery powers, consumption total).
    """
    system_time = None
    if None not in (hr[35], hr[36], hr[37], hr[38], hr[39], hr[40]):
        try:
            system_time = datetime(hr[35] + 2000, hr[36], hr[37], hr[38], hr[39], hr[40])
        except ValueError:
            system_time = None

    p_pv1 = ir[18]
    p_pv2 = ir[20]
    solar_power = p_pv1 + p_pv2 if p_pv1 is not None and p_pv2 is not None else None

    p_grid_out = _int16(ir[30]) if ir[30] is not None else None
    grid_import_power = max(0, -p_grid_out) if p_grid_out is not None else None
    grid_export_power = max(0, p_grid_out) if p_grid_out is not None else None

    p_battery = _int16(ir[52]) if ir[52] is not None else None
    battery_charge_power = max(0, -p_battery) if p_battery is not None else None
    battery_discharge_power = max(0, p_battery) if p_battery is not None else None

    generation_total = _uint32(ir[45], ir[46]) / 10 if None not in (ir[45], ir[46]) else None

    battery_capacity_ah = hr[55]
    battery_capacity_kwh = (
        battery_capacity_ah * _system_battery_voltage(hr[0]) / 1000
        if battery_capacity_ah is not None and hr[0] is not None
        else None
    )

    e_grid_in_total = _uint32(ir[32], ir[33]) / 10 if None not in (ir[32], ir[33]) else None
    e_grid_out_total = _uint32(ir[21], ir[22]) / 10 if None not in (ir[21], ir[22]) else None
    battery_soc = ir[59]
    if None not in (generation_total, e_grid_in_total, e_grid_out_total, battery_capacity_kwh, battery_soc):
        consumption_total = round(
            generation_total + e_grid_in_total - e_grid_out_total - battery_capacity_kwh * battery_soc / 100,
            1,
        )
    else:
        consumption_total = None

    return InverterSnapshot(
        battery_soc=battery_soc,
        system_time=system_time,
        date_str=system_time.date().isoformat(),
        time_str=system_time.time().isoformat(),
        solar_power=solar_power,
        grid_power=grid_import_power - grid_export_power,
        battery_power=battery_discharge_power - battery_charge_power,
        grid_import_power=grid_import_power,
        grid_export_power=grid_export_power,
        battery_charge_power=battery_charge_power,
        battery_discharge_power=battery_discharge_power,
        house_power=ir[42],
        generation_total=generation_total,
        battery_capacity_kwh=battery_capacity_kwh,
        consumption_total=consumption_total,
        enable_discharge=bool(hr[59]) if hr[59] is not None else None,
        enable_charge=bool(hr_enable_charge),
        status=_STATUS_NAMES.get(ir[0], "UNKNOWN"),
    )


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
            print(f'battery charge percentage {inv.battery_soc}')
            print(f'system time {inv.system_time}')
            print(f'solar power {inv.p_pv()}')  # solar power
            print(f'grid import power {inv.grid_import_power}')
            print(f'grid export power {inv.grid_export_power}')
            print(f'battery charge power {inv.battery_charge_power}')
            print(f'battery discharge power {inv.battery_discharge_power}')
            print(f'house power {inv.p_load_demand}')
            print(f'generation total {inv.e_pv_generation_total}')
            print(f'battery capacity {inv.battery_capacity_kwh}')
            print(f'consumption total {inv.e_pv_generation_total + inv.e_grid_in_total - inv.e_grid_out_total - inv.battery_capacity_kwh * inv.battery_soc / 100}')
            print(f'enable discharge {inv.enable_discharge}')
            print(f'enable charge {inv.enable_charge}')
            print(f'status {inv.status.name}')

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

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def read_data_direct(self):
        """Fast alternative to read_data(): read just the registers backing the printed fields.

        Uses three register reads at the inverter (0x11) instead of detect()/load_config()/
        refresh(), which poll many more banks. Single-phase layout only.
        """
        lock = acquire_lock()
        try:
            client = Client(host=self.inverter_ip, port=self.inverter_port)
            await client.connect()
            try:
                responses = await client.execute(
                    [
                        ReadInputRegistersRequest(base_register=0, register_count=60, device_address=0x11),
                        ReadHoldingRegistersRequest(base_register=0, register_count=60, device_address=0x11),
                        ReadHoldingRegistersRequest(base_register=96, register_count=1, device_address=0x11),
                    ],
                    timeout=2.0,
                    retries=1,
                    retry_delay=0.5,
                )
            finally:
                await client.close()
            snapshot = _decode_snapshot(
                responses[0].register_values, responses[1].register_values, responses[2].register_values[0]
            )
            # print(f'battery charge percentage {snapshot.battery_soc}')
            # print(f'system time {snapshot.system_time}')
            # print(f'solar power {snapshot.solar_power}')  # solar power
            # print(f'grid import power {snapshot.grid_import_power}')
            # print(f'grid export power {snapshot.grid_export_power}')
            # print(f'battery charge power {snapshot.battery_charge_power}')
            # print(f'battery discharge power {snapshot.battery_discharge_power}')
            # print(f'house power {snapshot.house_power}')
            # print(f'generation total {snapshot.generation_total}')
            # print(f'battery capacity {snapshot.battery_capacity_kwh}')
            # print(f'consumption total {snapshot.consumption_total}')
            # print(f'enable discharge {snapshot.enable_discharge}')
            # print(f'enable charge {snapshot.enable_charge}')
            # print(f'status {snapshot.status}')
            return snapshot
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

    async def _read_holding_register(self, client, register):
        response = await client.send_request_and_await_response(
            ReadHoldingRegistersRequest(
                base_register=register,  # register 96 = enable charge
                register_count=1,
                device_address=0x11,  # inverter's setup address (same default the write uses)
            ),
            timeout=1.5,
            retries=0,
        )
        return response.register_values[0]


    async def _set_battery_flag(self, register: int, enabled : bool):
        value = 1 if enabled else 0
        lock = acquire_lock()
        try:
            client = Client(host=self.inverter_ip, port=self.inverter_port)
            await client.connect()
            try:
                before = await self._read_holding_register(client, register)
                if before == value:
                    # print('no change')
                    return False
                write_request = WriteHoldingRegisterRequest(register, value)
                await client.one_shot_command([write_request])
                before = await self._read_holding_register(client, register)
                # print('changed')
                return before != value
            finally:
                await client.close()
        finally:
            release_lock(lock)

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def set_enable_charge(self, enabled):
        return await self._set_battery_flag(96, enabled)

    @retry(stop=stop_after_attempt(RETRY_ATTEMPTS), wait=wait_fixed(RETRY_WAIT_SECONDS))
    async def set_enable_discharge(self, enabled):
        return await self._set_battery_flag(59, enabled)


if __name__ == "__main__":
    SEPARATOR = "\n" + ("=" * 60) + "\n"
    givenergy_modbus = GivenergyModbus()

    # # --- set_enable_charge ---
    # start = time.perf_counter()
    # asyncio.run(givenergy_modbus.set_enable_charge(False))
    # end = time.perf_counter()
    # print(f"{SEPARATOR}set_enable_charge() took {end - start:.3f} seconds{SEPARATOR}")
    #
    # # --- set_enable_discharge ---
    # start = time.perf_counter()
    # asyncio.run(givenergy_modbus.set_enable_discharge(False))
    # end = time.perf_counter()
    # print(f"{SEPARATOR}set_enable_discharge() took {end - start:.3f} seconds{SEPARATOR}")

    # --- read_data ---
    start = time.perf_counter()
    asyncio.run(givenergy_modbus.read_data())
    end = time.perf_counter()
    print(f"{SEPARATOR}read_data() took {end - start:.3f} seconds{SEPARATOR}")

    # --- read_data_direct (fast, register-only) ---
    start = time.perf_counter()
    asyncio.run(givenergy_modbus.read_data_direct())
    end = time.perf_counter()
    print(f"{SEPARATOR}read_data_direct() took {end - start:.3f} seconds{SEPARATOR}")
