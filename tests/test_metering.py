import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from common.json_store import JsonStore
from minute_poller import MinutePoller
from solarcontrolar.givenergymodbus import _decode_snapshot, PlantWrapper, _uint32


def registers():
    ir, hr = [0]*60, [0]*60
    hr[0] = 0x2001
    hr[35:41] = [26, 8, 15, 12, 0, 0]
    hr[55] = 100
    ir[45:47] = [0, 10000]   # 1000 kWh inverter energy (load balance)
    ir[11:13] = [0, 16000]   # 1600 kWh actual PV total
    ir[32:34] = [0, 5000]    # 500 kWh import
    ir[21:23] = [0, 2000]    # 200 kWh export
    ir[27:29] = [0, 1000]    # 100 kWh AC charging
    ir[42] = 350
    return ir, hr

class DecodeTests(unittest.TestCase):
    def test_load_excludes_ac_charge(self):
        ir, hr = registers()
        self.assertEqual(_decode_snapshot(ir, hr, 0).consumption_total, 1200)
        # Import and AC charging rise together: house load must not rise.
        ir[33] += 10; ir[28] += 10
        self.assertEqual(_decode_snapshot(ir, hr, 0).consumption_total, 1200)

    def test_pv_counter_independent_of_battery_inverter_output(self):
        ir, hr = registers()
        ir[18] = ir[20] = 0  # night: no PV power
        ir[52] = 500         # battery discharge
        before = _decode_snapshot(ir, hr, 0)
        ir[46] += 10        # inverter supplied 1 kWh from battery
        after = _decode_snapshot(ir, hr, 0)
        self.assertEqual(before.generation_total, 1600)
        self.assertEqual(after.generation_total, before.generation_total)
        self.assertEqual(after.consumption_total - before.consumption_total, 1)

    def test_pv_scale_and_high_word(self):
        ir, hr = registers()
        ir[11:13] = [1, 2345]
        self.assertEqual(_decode_snapshot(ir, hr, 0).generation_total, 6788.1)

    def test_missing_pv_does_not_change_usage(self):
        ir, hr = registers(); ir[11] = None
        snapshot = _decode_snapshot(ir, hr, 0)
        self.assertIsNone(snapshot.generation_total)
        self.assertEqual(snapshot.consumption_total, 1200)

    def test_additional_energy_counters_scale_high_words_and_preserve_zero(self):
        ir, hr = registers()
        ir[32:34] = [1, 2345]
        ir[21:23] = [2, 3456]
        ir[27:29] = [0, 0]
        snapshot = _decode_snapshot(ir, hr, 0)
        self.assertEqual(snapshot.grid_import_total, 6788.1)
        self.assertEqual(snapshot.grid_export_total, 13452.8)
        self.assertEqual(snapshot.ac_charge_total, 0.0)

    def test_missing_additional_energy_counter_is_unavailable(self):
        for high in (32, 21, 27):
            ir, hr = registers(); ir[high] = None
            snapshot = _decode_snapshot(ir, hr, 0)
            attribute = {32: 'grid_import_total', 21: 'grid_export_total', 27: 'ac_charge_total'}[high]
            self.assertIsNone(getattr(snapshot, attribute))

    def test_soc_is_not_energy_meter(self):
        ir, hr = registers()
        a = _decode_snapshot(ir, hr, 0)
        ir[59] = 100
        self.assertEqual(a.consumption_total, _decode_snapshot(ir, hr, 0).consumption_total)

    def test_signs_and_units(self):
        ir, hr = registers(); ir[30] = 65536-500; ir[52] = 65536-300
        s = _decode_snapshot(ir, hr, 0)
        self.assertEqual((s.grid_power, s.battery_power, s.house_power), (500, -300, 350))
        self.assertEqual(_uint32(1, 2), 65538)
        self.assertEqual(s.battery_capacity_kwh, 5.12)

    def test_missing_counters_and_clock(self):
        ir, hr = registers(); ir[27] = None; hr[36] = 13
        ir[30] = ir[52] = None
        s = _decode_snapshot(ir, hr, 0)
        self.assertIsNone(s.consumption_total)
        self.assertIsNone(s.date_str)
        self.assertIsNone(s.grid_power)
        self.assertIsNone(s.battery_power)

    def test_unsupported_layout(self):
        ir, hr = registers()
        for dtc in (0x3001, 0x4001, 0x8001, None):
            hr[0] = dtc
            with self.assertRaises(ValueError): _decode_snapshot(ir, hr, 0)

    def test_wrapper_parity(self):
        inv = SimpleNamespace(status=SimpleNamespace(name='NORMAL'), battery_soc=50,
            system_time=datetime(2026,8,15), p_pv=lambda:1000, grid_import_power=500,
            grid_export_power=0, battery_discharge_power=0,battery_charge_power=300,
            p_load_demand=350,e_pv_generation_total=1000,e_pv_total=1600,e_grid_in_total=500,
            e_grid_out_total=200,e_inverter_in_total=100,enable_charge=False,enable_discharge=True)
        w=PlantWrapper(SimpleNamespace(inverter=inv))
        self.assertEqual(w.consumption_total,1200)
        self.assertEqual(w.house_power,350)
        self.assertEqual(w.generation_total,1600)
        self.assertEqual((w.grid_import_total, w.grid_export_total, w.ac_charge_total),
                         (500, 200, 100))

class PollerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.patch=patch('minute_poller.JsonStore', side_effect=lambda name:JsonStore(str(root/name)))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.poller=MinutePoller()
        self.root=root
        self.output=contextlib.redirect_stdout(io.StringIO()); self.output.__enter__()
        self.addCleanup(self.output.__exit__,None,None,None)

    def feed(self, timestamp, solar=100, usage=200):
        t=datetime.fromisoformat(timestamp)
        self.poller._save_meter_data_latest(SimpleNamespace(date_str=t.date().isoformat(),
            time_str=t.time().isoformat(),generation_total=solar,consumption_total=usage,
            grid_import_total=500.1,grid_export_total=200.2,ac_charge_total=100.3))

    def actuals(self): return JsonStore(str(self.root/'usage_actuals.json')).read()

    def test_minute_entry_records_lifetime_counters_and_preserves_history(self):
        store = JsonStore(str(self.root/'minute_totals.json'))
        old = {'solar': 1, 'usage': 2}
        store.write({'2026-08-14': {'12:00:00': old}})
        self.feed('2026-08-15T12:00:00')
        saved = store.read()
        entry = saved['2026-08-15']['12:00:00']
        self.assertEqual((entry['grid_import_total'], entry['grid_export_total'],
                          entry['ac_charge_total']), (500.1, 200.2, 100.3))
        self.assertEqual(saved['2026-08-14']['12:00:00'], old)
        self.assertEqual((entry['solar'], entry['usage']), (100, 200))

    def test_complete_period_and_restart(self):
        start=datetime(2026,8,15,12)
        for minute in range(31):
            self.poller=MinutePoller() # cron creates a fresh instance each minute
            self.feed((start+timedelta(minutes=minute)).isoformat(),100+minute/60,200+minute/30)
        self.assertEqual(self.actuals(),{'2026-08-15':{'12:00':1.0}})

    def test_partial_start_not_published(self):
        for minute in range(15,31): self.feed(f'2026-08-15T12:{minute:02}:00')
        self.assertEqual(self.actuals(),{})

    def test_boundary_interpolation(self):
        start=datetime(2026,8,15,11,59,30)
        for minute in range(32):
            self.feed((start+timedelta(minutes=minute)).isoformat(),100+minute/30,200+minute/30)
        self.assertEqual(self.actuals(),{'2026-08-15':{'12:00':1.0}})

    def test_gap_does_not_create_complete_period(self):
        self.feed('2026-08-15T12:00:00')
        self.feed('2026-08-15T12:29:00')
        self.feed('2026-08-15T12:30:00')
        self.assertEqual(self.actuals(),{})

    def test_legacy_formula_anchor_dropped(self):
        JsonStore(str(self.root/'minute_poller_state.json')).write(
            {'boundary':'2026-08-15T12:00:00','solar':0,'usage':0})
        self.feed('2026-08-15T12:30:00')
        self.assertEqual(self.actuals(),{})

    def test_previous_solar_register_state_is_not_differenced(self):
        JsonStore(str(self.root/'minute_poller_state.json')).write({
            'version': 2,
            'last_sample': {'timestamp': '2026-08-15T12:29:00', 'solar': 50, 'usage': 200},
            'anchor': {'boundary': '2026-08-15T12:00:00', 'solar': 50, 'usage': 200}})
        self.feed('2026-08-15T12:30:00', solar=1600, usage=201)
        self.assertEqual(self.actuals(), {})
        self.assertEqual(JsonStore(str(self.root/'solar_actuals.json')).read(), {})
        state = JsonStore(str(self.root/'minute_poller_state.json')).read()
        self.assertEqual(state['version'], 3)
        entry = JsonStore(str(self.root/'minute_totals.json')).read()['2026-08-15']['12:30:00']
        self.assertEqual(entry['solar_method'], 'pv_ir11_12_v1')

    def test_reset_and_invalid_sample(self):
        self.feed('2026-08-15T12:00:00')
        self.feed('2026-08-15T12:01:00',usage=2)
        self.feed('2026-08-15T12:02:00',usage=float('nan'))
        self.assertEqual(JsonStore(str(self.root/'minute_poller_state.json')).read(),{})
        self.assertEqual(self.actuals(),{})

    def test_duplicate_and_backwards_ignored(self):
        self.feed('2026-08-15T12:00:00')
        self.feed('2026-08-15T12:00:00',usage=999)
        self.feed('2026-08-15T11:59:00',usage=999)
        state=JsonStore(str(self.root/'minute_poller_state.json')).read()
        self.assertEqual(state['last_sample']['usage'],200)

    def test_midnight(self):
        start=datetime(2026,8,15,23,30)
        for minute in range(31):
            self.feed((start+timedelta(minutes=minute)).isoformat(),100+minute/30,200+minute/30)
        self.assertEqual(self.actuals(),{'2026-08-15':{'23:30':1.0}})

if __name__=='__main__': unittest.main()

