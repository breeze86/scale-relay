import unittest
from io import StringIO
from unittest.mock import patch

from scale_relay.cli import main
from scale_relay.doctor import check_ble_environment


class DoctorTests(unittest.TestCase):
    @patch("scale_relay.doctor.platform.system", return_value="Darwin")
    @patch("scale_relay.doctor.platform.python_version", return_value="3.13.3")
    def test_macos_does_not_require_bluez(self, *_):
        checks = check_ble_environment(0)
        messages = [check.message for check in checks]
        self.assertTrue(any("CoreBluetooth" in message for message in messages))
        warnings = [check.message for check in checks if check.level == "warning"]
        self.assertFalse(any("BlueZ" in warning for warning in warnings))

    @patch("scale_relay.doctor.shutil.which", return_value=None)
    @patch("scale_relay.doctor.Path.exists", return_value=False)
    @patch("scale_relay.doctor.platform.system", return_value="Linux")
    @patch("scale_relay.doctor.platform.python_version", return_value="3.13.3")
    def test_linux_warns_when_bluez_tools_or_adapter_are_missing(self, *_):
        checks = check_ble_environment(1)
        warnings = [check.message for check in checks if check.level == "warning"]
        self.assertTrue(any("hci1" in warning for warning in warnings))
        self.assertTrue(any("bluetoothctl" in warning for warning in warnings))
        self.assertTrue(any("hciconfig" in warning for warning in warnings))

    @patch("scale_relay.doctor.platform.system", return_value="Darwin")
    @patch("scale_relay.doctor.platform.python_version", return_value="3.13.3")
    def test_doctor_command_runs_without_config_on_macos(self, *_):
        output = StringIO()
        with patch("sys.stdout", output):
            code = main(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("environment check ok", output.getvalue())


if __name__ == "__main__":
    unittest.main()
