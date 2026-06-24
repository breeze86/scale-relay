# 小米米家体脂秤 S400 本地 BLE 数据采集操作文档

## 目标

在 Ubuntu / Debian / PVE 主机上，通过本地蓝牙扫描 Xiaomi Mijia Scale S400 的加密 BLE 广播，解密并解析出：

```text
体重 kg
高频阻抗 Ω
低频阻抗 Ω
心率，当前未解析到时用 0 占位
```

最终输出格式：

```text
to_import;timestamp;weight_kg;impedance_high;impedance_low;heart_rate
```

示例：

```text
to_import;1782205025;48.9;428;462;0
```

---

## 1. 原理概览

S400 不是旧款小米体脂秤那种明文广播体重的设备。

实际情况是：

```text
S400 通过 BLE FE95 广播加密数据
↓
需要从 Xiaomi Cloud 提取 BLE KEY
↓
用 xiaomi-ble 解密 FE95 广播
↓
得到 Mass / Impedance Low / Impedance High
```

已验证的关键事实：

```text
设备名: Mijia Scale S400 12D2
真实 MAC: E3:2B:13:0A:37:D9
Service UUID: 0000fe95-0000-1000-8000-00805f9b34fb
有效数据包长度: raw_fe95_len=24
解析字段:
  Mass
  Impedance Low
  Impedance High
```

---

## 2. 安全注意事项

提取 BLE KEY 需要登录 Xiaomi Home / 米家账号。这个过程会访问你账号下的米家设备信息，所以按高敏感操作处理。

建议：

```text
不要用 root 直接跑 token_extractor
不要用 Windows exe
不要用 bash <(curl ...)
不要把账号密码放在命令行参数里
优先使用 QR 登录
不要把完整 BLE KEY / token 发给别人
拿到 BLE KEY 后删除提取工具目录
```

推荐使用临时低权限用户：

```bash
adduser --disabled-password --gecos "" xiaomi_extract
su - xiaomi_extract
```

---

## 3. 系统依赖准备

先用 root 安装系统依赖。

```bash
apt update
apt install -y \
  wget \
  unzip \
  tar \
  git \
  bluetooth \
  bluez \
  python3 \
  python3-pip \
  python3-venv \
  python3-dev \
  build-essential \
  pkg-config \
  libglib2.0-dev \
  libbluetooth-dev \
  libssl-dev \
  libjpeg-dev \
  rfkill
```

如果没有 `unzip`，也可以用 Python 解压 zip：

```bash
python3 -m zipfile -e token_extractor.zip token_extractor
```

---

## 4. 提取 S400 的 BLE KEY

切到低权限用户：

```bash
su - xiaomi_extract
mkdir -p ~/work
cd ~/work
```

下载 Xiaomi Cloud Tokens Extractor：

```bash
wget https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor/releases/latest/download/token_extractor.zip -O token_extractor.zip
unzip token_extractor.zip -d token_extractor
cd token_extractor
```

创建 venv：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

运行：

```bash
python3 token_extractor.py
```

登录方式建议选择：

```text
q
```

即 QR code 登录。

如果 QR 页面需要在本地浏览器打开，可以在本地电脑开 SSH 端口转发：

```bash
ssh -L 31415:127.0.0.1:31415 root@你的服务器IP
```

然后浏览器打开：

```text
http://127.0.0.1:31415
```

服务器区域选择：

```text
米家 App 地区是中国大陆: cn
米家 App 地区是新加坡: sg
不确定: 直接回车，让脚本检查所有区域
```

成功后找到 S400 对应设备：

```text
NAME:     Xiaomi Body Composition Scale S400
MAC:      E3:2B:13:0A:37:D9
BLE KEY:  xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MODEL:    yunmai.scales.ms104
```

需要保存：

```text
MAC
BLE KEY
```

BLE KEY 应该是：

```text
32 位十六进制字符串
无空格
无冒号
无引号
无换行
```

---

## 5. 下载 export2garmin

可以继续用低权限用户，也可以在你自己的工作目录中执行。

```bash
cd ~/work

wget https://github.com/RobertWojtowicz/export2garmin/archive/refs/heads/master.tar.gz -O export2garmin.tar.gz
tar -xzf export2garmin.tar.gz
cd export2garmin-master
```

创建 venv：

```bash
python3 -m venv venv
source venv/bin/activate
```

安装 Python 依赖：

```bash
pip install --upgrade pip setuptools wheel
pip install --upgrade \
  bluepy \
  garminconnect \
  bleak \
  xiaomi-ble \
  requests \
  pycryptodome \
  charset-normalizer \
  pillow \
  colorama \
  bluetooth-sensor-state-data
```

验证版本：

```bash
python3 - <<'PY'
import importlib.metadata as m
for pkg in ["xiaomi-ble", "bluetooth-sensor-state-data", "bleak"]:
    try:
        print(pkg, m.version(pkg))
    except Exception as e:
        print(pkg, "NOT INSTALLED", e)
PY
```

本次跑通环境示例：

```text
xiaomi-ble 1.14.4
bluetooth-sensor-state-data 1.9.0
bleak 3.0.2
```

---

## 6. 配置 export2garmin

编辑配置文件：

```bash
nano user/export2garmin.cfg
```

找到或添加以下配置：

```ini
switch_s400=on
ble_miscale_mac=E3:2B:13:0A:37:D9
ble_miscale_key=你的32位BLE_KEY
ble_arg_hci=0
```

检查配置，不打印完整 key：

```bash
grep -nE "switch_s400|ble_miscale_mac|ble_miscale_key|ble_arg_hci" user/export2garmin.cfg \
  | sed -E 's/(ble_miscale_key=).{4}.+(.{4})/\1****\2/'
```

检查 key 格式：

```bash
python3 - <<'PY'
from pathlib import Path

cfg = Path("user/export2garmin.cfg").read_text()
key = None

for line in cfg.splitlines():
    line = line.strip()
    if line.startswith("ble_miscale_key="):
        key = line.split("=", 1)[1].strip()

print("key length:", len(key) if key else None)
print("hex only:", all(c in "0123456789abcdefABCDEF" for c in key) if key else None)
PY
```

正常输出：

```text
key length: 32
hex only: True
```

---

## 7. 替换 S400 采集脚本

先备份原文件：

```bash
cd ~/work/export2garmin-master
cp miscale/s400_ble.py miscale/s400_ble.py.bak.$(date +%Y%m%d_%H%M%S)
```

整文件替换：

```bash
cat > miscale/s400_ble.py <<'PY'
#!/usr/bin/python3
import argparse
import asyncio
import logging
import os
import signal
import subprocess
import time
from datetime import datetime

from bleak import BleakScanner
from bluetooth_sensor_state_data import BluetoothServiceInfo
from xiaomi_ble.parser import XiaomiBluetoothDeviceData


# Handling print function in BrokenPipeError exception
signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except BrokenPipeError:
        signal.raise_signal(signal.SIGPIPE)


safe_print("""
==========================================
Export 2 Garmin Connect v3.6 (s400_ble.py)
S400 patched version for xiaomi-ble >= 1.14.x
==========================================
""")


def now_str():
    return datetime.now().strftime("%d.%m.%Y-%H:%M:%S")


# Import bluetooth variables from config
path = os.path.dirname(os.path.dirname(__file__))
cfg_path = os.path.join(path, "user", "export2garmin.cfg")

with open(cfg_path, "r") as file:
    for raw_line in file:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("ble_miscale_") or line.startswith("ble_arg_hci"):
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            globals()[name.strip()] = value.strip()


ble_miscale_mac = globals().get("ble_miscale_mac", "").strip()
ble_miscale_key = globals().get("ble_miscale_key", "").strip()
ble_arg_hci = globals().get("ble_arg_hci", "0").strip()

if not ble_miscale_mac:
    raise SystemExit("Missing ble_miscale_mac in user/export2garmin.cfg")

if not ble_miscale_key:
    raise SystemExit("Missing ble_miscale_key in user/export2garmin.cfg")

if len(ble_miscale_key) != 32:
    raise SystemExit(
        f"Invalid ble_miscale_key length: {len(ble_miscale_key)}. "
        "Expected 32 hex chars."
    )

try:
    ble_key = bytes.fromhex(ble_miscale_key)
except ValueError as e:
    raise SystemExit(f"Invalid ble_miscale_key. It must be hex only: {e}")


# Arguments
parser = argparse.ArgumentParser()
parser.add_argument("-a", default=ble_arg_hci, help="BLE adapter number, e.g. 0 for hci0")
args = parser.parse_args()
ble_arg_hci = str(args.a)


def get_adapter_mac(hci_index):
    try:
        hci_out = subprocess.check_output(
            ["hcitool", "dev"],
            stderr=subprocess.DEVNULL,
        ).decode()

        for line in hci_out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == f"hci{hci_index}":
                return parts[1]
    except Exception:
        pass

    return "unknown"


ble_arg_mac = get_adapter_mac(ble_arg_hci)


# Xiaomi parser
xiaomi_parser = XiaomiBluetoothDeviceData(bindkey=ble_key)


# Runtime state
stop_event = None
mac_seen_event = None
scan_started_at = 0.0
last_found_print_at = 0.0
last_parsed_print = ""
last_decryption_log_at = 0.0


def get_entity_values(update):
    values = {}

    if not update or not update.entity_values:
        return values

    for value in update.entity_values.values():
        values[value.name] = value.native_value

    return values


def get_binary_values(update):
    binary_values = {}

    if not update or not update.binary_entity_values:
        return binary_values

    for value in update.binary_entity_values.values():
        binary_values[value.name] = value.native_value

    return binary_values


def normalize_measurement(values):
    mass = values.get("Mass")
    impedance_low = values.get("Impedance Low")
    impedance_high = values.get("Impedance High")
    if impedance_high is None:
        impedance_high = values.get("Impedance")
    heart_rate = values.get("Heart Rate", 0)
    return mass, impedance_high, impedance_low, heart_rate


def should_output(values, binary_values):
    mass, impedance_high, impedance_low, _ = normalize_measurement(values)

    if mass is None or impedance_high is None or impedance_low is None:
        return False

    if "Stabilized" in binary_values and binary_values["Stabilized"] is not True:
        return False

    return True


# Detect incorrect BLE KEY from xiaomi_ble logger
logger = logging.getLogger("xiaomi_ble.parser")
logger.setLevel(logging.DEBUG)


class DecryptionFailedHandler(logging.Handler):
    def emit(self, record):
        global last_decryption_log_at

        msg = record.getMessage()
        if "Decryption failed" not in msg:
            return

        now = time.time()
        if now - last_decryption_log_at > 1:
            safe_print(f"{now_str()} S400 * Decryption failed, check BLE KEY")
            last_decryption_log_at = now

            if stop_event is not None:
                stop_event.set()


logger.addHandler(DecryptionFailedHandler())


def detection_callback(device, advertisement_data):
    global last_found_print_at, last_parsed_print

    try:
        if device.address.upper() != ble_miscale_mac.upper():
            return

        if mac_seen_event is not None:
            mac_seen_event.set()

        now = time.time()

        # Avoid flooding terminal with identical "found" lines.
        if now - last_found_print_at > 5:
            safe_print(
                f"  BLE device found with address: {device.address.upper()} "
                f"name={device.name} rssi={advertisement_data.rssi}"
            )
            last_found_print_at = now

        service_info = BluetoothServiceInfo(
            name=device.name or "Mijia Scale S400",
            address=device.address,
            rssi=advertisement_data.rssi,
            manufacturer_data=advertisement_data.manufacturer_data,
            service_data=advertisement_data.service_data,
            service_uuids=advertisement_data.service_uuids,
            source=device.address,
        )

        if not xiaomi_parser.supported(service_info):
            return

        update = xiaomi_parser.update(service_info)

        values = get_entity_values(update)
        binary_values = get_binary_values(update)

        interesting = {
            key: values[key]
            for key in (
                "Mass",
                "Impedance",
                "Impedance Low",
                "Impedance High",
                "Heart Rate",
            )
            if key in values
        }

        if interesting:
            stabilized = binary_values.get("Stabilized", None)
            parsed_line = f"   parsed={interesting}, stabilized={stabilized}"

            # Print only when parsed values change.
            if parsed_line != last_parsed_print:
                safe_print(parsed_line)
                last_parsed_print = parsed_line

        if should_output(values, binary_values):
            mass, impedance_high, impedance_low, heart_rate = normalize_measurement(values)

            safe_print(f"{now_str()} S400 * Reading BLE data complete, finished BLE scan")
            safe_print(
                f"to_import;"
                f"{int(time.time())};"
                f"{float(mass):.1f};"
                f"{float(impedance_high):.0f};"
                f"{float(impedance_low):.0f};"
                f"{heart_rate}"
            )

            if stop_event is not None:
                stop_event.set()

    except Exception as e:
        safe_print(f"[CALLBACK-ERR] {type(e).__name__}: {e}")


async def watchdog(timeout=180):
    while not stop_event.is_set():
        await asyncio.sleep(1)

        elapsed = time.time() - scan_started_at
        if elapsed > timeout:
            safe_print(f"{now_str()} S400 * Reading BLE data failed, finished BLE scan")
            stop_event.set()


async def main():
    global stop_event, mac_seen_event, scan_started_at

    stop_event = asyncio.Event()
    mac_seen_event = asyncio.Event()
    scan_started_at = time.time()

    safe_print(f"{now_str()} * Starting scan with BLE adapter hci{ble_arg_hci}({ble_arg_mac}):")

    asyncio.create_task(watchdog(180))

    scanner = BleakScanner(detection_callback=detection_callback)
    scan_started = False

    try:
        await scanner.start()
        scan_started = True

        try:
            await asyncio.wait_for(mac_seen_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            safe_print(f"  BLE device not found with address: {ble_miscale_mac.upper()}")
            safe_print("  Keep the script running, then step on the scale.")

        await stop_event.wait()

    finally:
        if scan_started:
            try:
                await scanner.stop()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
PY

chmod +x miscale/s400_ble.py
```

---

## 8. 运行采集

运行前建议：

```text
关闭手机米家 App
最好临时关闭手机蓝牙
不要同时运行 bluetoothctl connect
确保 S400 已在米家 App 里绑定过
确保之前已完整测量过一次
```

运行：

```bash
cd ~/work/export2garmin-master
source venv/bin/activate
python3 miscale/s400_ble.py
```

看到脚本启动后，站上秤，完整等到：

```text
体重稳定
体脂/阻抗测量完成
秤灯熄灭
再多等 5–10 秒
```

成功输出示例：

```text
==========================================
Export 2 Garmin Connect v3.6 (s400_ble.py)
S400 patched version for xiaomi-ble >= 1.14.x
==========================================

23.06.2026-16:56:45 * Starting scan with BLE adapter hci0(40:9C:A7:22:4D:31):
  BLE device found with address: E3:2B:13:0A:37:D9 name=Mijia Scale S400 12D2 rssi=-69
   parsed={'Mass': 48.9, 'Impedance Low': 462.0}, stabilized=False
   parsed={'Mass': 48.9, 'Impedance Low': 462.0, 'Impedance High': 428.0}, stabilized=True
23.06.2026-16:57:05 S400 * Reading BLE data complete, finished BLE scan
to_import;1782205025;48.9;428;462;0
```

字段含义：

```text
to_import;timestamp;weight_kg;impedance_high;impedance_low;heart_rate
```

例如：

```text
to_import;1782205025;48.9;428;462;0
```

表示：

```text
时间戳: 1782205025
体重: 48.9 kg
高频阻抗: 428 Ω
低频阻抗: 462 Ω
心率: 0，占位值
```

验证时间戳：

```bash
date -d @1782205025
```

---

## 9. 常见问题排查

### 9.1 只看到 `BLE device found`，没有 `parsed`

说明脚本只扫到了普通广播，没有扫到完整测量结果包。

处理：

```text
保持脚本运行
重新站上秤
不要体重一显示就下来
等体脂/阻抗测完
等秤灯熄灭后再等 5–10 秒
```

---

### 9.2 出现 `Decryption failed`

说明 BLE KEY 不匹配。

处理：

```text
重新用 token_extractor 提取 BLE KEY
确认用的是同一个 Xiaomi Home 账号
确认地区 server 选对
确认没有重新绑定 / 重置过秤
确认配置里的 key 是 32 位 hex
```

---

### 9.3 `bluepy` 安装失败，提示 `glib.h: No such file or directory`

安装系统编译依赖：

```bash
apt update
apt install -y build-essential pkg-config libglib2.0-dev python3-dev libbluetooth-dev
```

然后重新安装：

```bash
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install bluepy
```

---

### 9.4 `pkg-config: No such file or directory`

安装：

```bash
apt install -y pkg-config
```

如果系统没有 `pkg-config` 包，试：

```bash
apt install -y pkgconf
```

---

### 9.5 `unzip: command not found`

安装：

```bash
apt install -y unzip
```

或者用 Python 解压：

```bash
python3 -m zipfile -e token_extractor.zip token_extractor
```

---

### 9.6 `hcitool` 找不到

安装 bluez：

```bash
apt install -y bluez bluetooth
```

检查蓝牙适配器：

```bash
hciconfig
hcitool dev
```

---

### 9.7 蓝牙适配器被占用

不要同时连接 GATT：

```bash
bluetoothctl disconnect E3:2B:13:0A:37:D9
```

重启蓝牙服务：

```bash
systemctl restart bluetooth
```

然后重新运行脚本：

```bash
python3 miscale/s400_ble.py
```

---

## 10. 后续扩展方向

当前脚本输出：

```text
to_import;timestamp;weight_kg;impedance_high;impedance_low;heart_rate
```

后续可以很容易改成：

```text
CSV 写入
JSON 输出
HTTP POST
MQTT 发布
写入 PostgreSQL / SQLite
接入 Home Assistant
```

当前最小可用状态已经完成：

```text
S400 本地 BLE 广播采集成功
BLE KEY 解密成功
体重 + 高频阻抗 + 低频阻抗解析成功
```
