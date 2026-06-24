import base64
import unittest

from scale_relay.config import app_config_from_dict, with_device_credentials
from scale_relay.xiaomi_cloud.client import _decrypt_rc4, _encrypt_rc4, normalize_regions
from scale_relay.xiaomi_cloud.rc4 import rc4_crypt

from test_config import valid_config


class XiaomiCloudTests(unittest.TestCase):
    def test_rc4_known_vector_without_drop(self):
        encrypted = rc4_crypt(b"Key", b"Plaintext", drop=0)
        self.assertEqual(encrypted.hex().upper(), "BBF316E8D940AF0AD3")

    def test_xiaomi_rc4_roundtrip(self):
        password = base64.b64encode(b"0123456789abcdef").decode()
        payload = "hello-xiaomi"
        encrypted = _encrypt_rc4(password, payload)
        decrypted = _decrypt_rc4(password, encrypted)
        self.assertEqual(decrypted.decode(), payload)

    def test_normalize_regions(self):
        self.assertEqual(normalize_regions("cn"), ["cn"])
        self.assertIn("sg", normalize_regions(None, all_regions=True))

    def test_with_device_credentials(self):
        config = app_config_from_dict(valid_config())
        updated = with_device_credentials(
            config,
            name="Scale",
            model="yunmai.scales.ms104",
            mac="AA:BB:CC:DD:EE:FF",
            ble_key="abcdefabcdefabcdefabcdefabcdefab",
        )
        self.assertEqual(updated.device.mac, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(updated.device.ble_key, "abcdefabcdefabcdefabcdefabcdefab")


if __name__ == "__main__":
    unittest.main()
