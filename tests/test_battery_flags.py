import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tenacity import stop_after_attempt, wait_none

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from solarcontrolar.givenergymodbus import GivenergyModbus

MODULE = 'solarcontrolar.givenergymodbus'


class BatteryFlagTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(),
                                     one_shot_command=AsyncMock())
        for name, value in [('Client', Mock(return_value=self.client)),
                            ('acquire_lock', Mock(return_value='test-lock')),
                            ('release_lock', Mock())]:
            patcher = patch(f'{MODULE}.{name}', value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.modbus = GivenergyModbus.__new__(GivenergyModbus)
        self.modbus.inverter_ip = 'test-inverter'
        self.modbus.inverter_port = 8899
        self.modbus._read_holding_register = AsyncMock()

    def assert_cleaned_up(self):
        self.client.close.assert_awaited_once()
        self.release_lock.assert_called_once_with('test-lock')

    async def test_unchanged_flag_returns_false_without_writing(self):
        self.modbus._read_holding_register.return_value = 1
        self.assertFalse(await self.modbus._set_battery_flag(96, True))
        self.client.one_shot_command.assert_not_awaited()
        self.modbus._read_holding_register.assert_awaited_once_with(self.client, 96)
        self.assert_cleaned_up()

    async def test_confirmed_charge_enable_returns_true(self):
        self.modbus._read_holding_register.side_effect = [0, 1]
        self.assertTrue(await self.modbus.set_enable_charge(True))
        request = self.client.one_shot_command.await_args.args[0][0]
        self.assertEqual((request.register, request.value), (96, 1))
        self.assertEqual(self.modbus._read_holding_register.await_count, 2)
        self.assert_cleaned_up()

    async def test_confirmed_discharge_disable_returns_true(self):
        self.modbus._read_holding_register.side_effect = [1, 0]
        self.assertTrue(await self.modbus.set_enable_discharge(False))
        request = self.client.one_shot_command.await_args.args[0][0]
        self.assertEqual((request.register, request.value), (59, 0))
        self.assert_cleaned_up()

    async def test_readback_mismatch_raises(self):
        self.modbus._read_holding_register.side_effect = [0, 0]
        with self.assertRaisesRegex(RuntimeError, r'HR\(96\).*wanted=1 actual=0'):
            await self.modbus._set_battery_flag(96, True)
        self.assert_cleaned_up()

    async def test_public_setter_retries_unconfirmed_write(self):
        self.modbus._read_holding_register.side_effect = [0, 0, 0, 1]
        setter = GivenergyModbus.set_enable_charge.retry_with(
            stop=stop_after_attempt(2), wait=wait_none())
        self.assertTrue(await setter(self.modbus, True))
        self.assertEqual(self.client.one_shot_command.await_count, 2)
        self.assertEqual(self.client.close.await_count, 2)
        self.assertEqual(self.release_lock.call_count, 2)

    async def test_connection_failure_closes_client_and_releases_lock(self):
        self.client.connect.side_effect = OSError('unavailable')
        with self.assertRaises(OSError):
            await self.modbus._set_battery_flag(96, True)
        self.client.one_shot_command.assert_not_awaited()
        self.assert_cleaned_up()

    async def test_write_failure_closes_client_and_releases_lock(self):
        self.modbus._read_holding_register.return_value = 0
        self.client.one_shot_command.side_effect = OSError('write failed')
        with self.assertRaises(OSError):
            await self.modbus._set_battery_flag(96, True)
        self.assert_cleaned_up()

    async def test_readback_failure_closes_client_and_releases_lock(self):
        self.modbus._read_holding_register.side_effect = [0, OSError('read failed')]
        with self.assertRaises(OSError):
            await self.modbus._set_battery_flag(96, True)
        self.assert_cleaned_up()


if __name__ == '__main__':
    unittest.main()
