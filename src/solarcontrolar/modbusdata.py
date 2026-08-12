def _field(json_key):
    def getter(self):
        return self._data[json_key]
    return property(getter)


class PowerFlows:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise TypeError(f"PowerFlows data must be a dict, got {type(data).__name__}")
        self._data = data

    solar_to_house = _field("solarToHouse")
    solar_to_battery = _field("solarToBattery")
    solar_to_grid = _field("solarToGrid")
    battery_to_house = _field("batteryToHouse")
    battery_to_grid = _field("batteryToGrid")
    grid_to_house = _field("gridToHouse")
    grid_to_battery = _field("gridToBattery")


class Slot:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise TypeError(f"Slot data must be a dict, got {type(data).__name__}")
        self._data = data

    start = _field("start")
    end = _field("end")
    target_state_of_charge = _field("targetStateOfCharge")


class TimedDischargeSlot:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise TypeError(f"TimedDischargeSlot data must be a dict, got {type(data).__name__}")
        self._data = data

    start = _field("start")
    end = _field("end")


class ModbusData:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise TypeError(f"ModbusData data must be a dict, got {type(data).__name__}")
        self._data = data

    generation = _field("generation")
    serial_number = _field("serialNumber")
    model_code = _field("modelCode")
    solar_power = _field("solarPower")
    pv_string1_power = _field("pvString1Power")
    pv_string2_power = _field("pvString2Power")
    battery_power = _field("batteryPower")
    grid_power = _field("gridPower")
    load_power = _field("loadPower")
    inverter_output_power = _field("inverterOutputPower")
    grid_apparent_power = _field("gridApparentPower")
    eps_backup_power = _field("epsBackupPower")
    pv_string1_voltage = _field("pvString1Voltage")
    pv_string2_voltage = _field("pvString2Voltage")
    pv_string1_current = _field("pvString1Current")
    pv_string2_current = _field("pvString2Current")
    state_of_charge = _field("stateOfCharge")
    battery_voltage = _field("batteryVoltage")
    battery_current = _field("batteryCurrent")
    grid_voltage = _field("gridVoltage")
    grid_frequency = _field("gridFrequency")
    inverter_current = _field("inverterCurrent")
    eps_backup_voltage = _field("epsBackupVoltage")
    eps_backup_frequency = _field("epsBackupFrequency")
    inverter_heatsink_temp = _field("inverterHeatsinkTemp")
    charger_temperature = _field("chargerTemperature")
    battery_temperature = _field("batteryTemperature")
    pv_energy_total_kwh = _field("pvEnergyTotalKwh")
    battery_charge_energy_total_kwh = _field("batteryChargeEnergyTotalKwh")
    battery_discharge_energy_total_kwh = _field("batteryDischargeEnergyTotalKwh")
    grid_import_energy_total_kwh = _field("gridImportEnergyTotalKwh")
    grid_export_energy_total_kwh = _field("gridExportEnergyTotalKwh")
    consumption_energy_total_kwh = _field("consumptionEnergyTotalKwh")
    battery_throughput_total_kwh = _field("batteryThroughputTotalKwh")
    hours_of_operation = _field("hoursOfOperation")
    pv_energy_today_kwh = _field("pvEnergyTodayKwh")
    pv_string1_energy_today_kwh = _field("pvString1EnergyTodayKwh")
    pv_string2_energy_today_kwh = _field("pvString2EnergyTodayKwh")
    battery_charge_energy_today_kwh = _field("batteryChargeEnergyTodayKwh")
    battery_discharge_energy_today_kwh = _field("batteryDischargeEnergyTodayKwh")
    grid_import_energy_today_kwh = _field("gridImportEnergyTodayKwh")
    grid_export_energy_today_kwh = _field("gridExportEnergyTodayKwh")
    consumption_energy_today_kwh = _field("consumptionEnergyTodayKwh")
    eco_mode = _field("ecoMode")
    timed_export = _field("timedExport")
    timed_charge = _field("timedCharge")
    charge_target_state_of_charge = _field("chargeTargetStateOfCharge")
    battery_reserve_percent = _field("batteryReservePercent")
    charge_rate_percent = _field("chargeRatePercent")
    discharge_rate_percent = _field("dischargeRatePercent")
    battery_pause_mode = _field("batteryPauseMode")
    system_time = _field("systemTime")

    @property
    def charge_slots(self):
        return [Slot(slot) for slot in self._data["chargeSlots"]]

    @property
    def discharge_slots(self):
        return [Slot(slot) for slot in self._data["dischargeSlots"]]

    @property
    def timed_discharge_slot(self):
        return TimedDischargeSlot(self._data["timedDischargeSlot"])

    @property
    def power_flows(self):
        return PowerFlows(self._data["powerFlows"])

    @property
    def batteries(self):
        return self._data["batteries"]

    @property
    def meters(self):
        return self._data["meters"]