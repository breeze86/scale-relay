# Scale Relay

Scale Relay 是一个把 Xiaomi Mijia Scale S400 接入 Hermes Agent 的轻量连接层。它让 AI 不只停留在对话里，而是接入真实生活数据：你的每一次称重都会被采集、解析，并交给 Hermes profile 结合历史记录进行趋势分析、总结变化，给出适合日常参考的健康建议。

在这个实践里，Hermes Agent 可以成为一个持续响应的体重管家。Scale Relay 负责可靠采集、组装事件、提交数据；Hermes Agent 负责根据 profile route 做分析、结合记忆判断趋势，并发送给消息平台（如：飞书、微信）。当前第一版只支持 Xiaomi Mijia Scale S400 与 Hermes Agent，后续可以在保持采集层稳定的前提下扩展更多设备或目标服务。

## 当前状态

已验证链路：

- Xiaomi Cloud QR 登录。
- S400 设备信息读取与 `BLE KEY` 提取。
- Ubuntu / macOS 上 S400 BLE 扫描、FE95 广播解密、体重/阻抗解析。
- `stdout` 本地 JSON 输出。
- Hermes Agent Webhook HMAC 签名发送。
- Hermes Agent 收到事件并响应。

目标部署环境包含 Ubuntu / Debian / PVE。代码已按 Linux BlueZ `hci` 适配器模型设计，但最终部署前仍建议在目标机器上做一次实机验证。

## 功能

- 通过 QR 登录 Xiaomi Cloud，不在命令行传账号密码。
- 列出 Xiaomi 账号下的设备，并识别 S400。
- 从已同步到 Xiaomi Cloud(米家APP) 的设备信息中提取 S400 所需的 `MAC`、`BLE KEY`、型号等信息，并写入配置。
- 监听 S400 BLE 广播，解析：
  - 体重 `weight_kg`
  - 高频阻抗 `impedance_high`
  - 低频阻抗 `impedance_low`
  - 稳定状态 `stabilized`
- 支持一次性监听和常驻监听。
- 支持 `stdout` 与 `hermes_webhook` 两种 sink。
- 本地保存称重历史，并向 Hermes 提供最近记录、统计摘要和每周趋势。
- 分析意图通过 `prompt.text` 配置，payload 保持通用结构，不写死孕妇、减脂等场景。
- Hermes 发送失败时记录错误，并降级输出本次称重事件 JSON，避免数据直接丢失。
- 兼容 macOS CoreBluetooth 不暴露真实 BLE MAC 的情况。
- 提供 `doctor` 环境检查命令，并在 BLE 监听前输出平台/蓝牙环境检查日志。

## 工作方式

```text
Xiaomi Mijia Scale S400
  -> BLE encrypted advertisement
  -> Scale Relay
  -> parse weight / impedance
  -> save local history
  -> build message + current/history payload
  -> Hermes Agent Webhook
  -> Hermes route deliver
```

Scale Relay 不决定最终消息发给谁。发送渠道、chat、profile 侧记忆和后续分析由 Hermes Agent route 配置控制。

## 环境要求

- Python 3.11+
- Xiaomi Mijia Scale S400 已绑定到 Xiaomi Home / 米家 App，并至少连接/同步过一次
- 可用蓝牙适配器
- 使用 Hermes 时，需要 Hermes Agent 已启用 Webhook gateway

Linux 运行 BLE 监听通常还需要 BlueZ 相关组件。具体系统依赖和原始实操记录见：

- [docs/xiaomi_s400_ble_local_collection_runbook.md](docs/xiaomi_s400_ble_local_collection_runbook.md)

这些属于系统前置准备，不由 Scale Relay 自动安装或修改。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

安装后会提供 `scale-relay` 命令。

## 快速开始

### 1. 在米家 App 中绑定并同步 S400

先在 Xiaomi Home / 米家 App 中完成 S400 绑定，并让体重秤与 App 至少连接/同步一次。

Scale Relay 后续提取 `MAC`、`BLE KEY`、型号等信息时，读取的是 Xiaomi Cloud 中已经同步过的设备信息。如果设备只完成了本地配对但没有同步到账号云端，`xiaomi devices` 或 `xiaomi extract-key` 可能找不到设备或拿不到完整信息。

### 2. 准备 Hermes Webhook

如果要使用 `hermes_webhook` sink，需要先在 Hermes 侧启用 webhook adapter，创建动态 webhook 订阅，拿到 URL 和 HMAC secret，再初始化或填写 Scale Relay 配置。

本项目假设你已经在使用 Hermes Agent，并且已有可运行的 gateway。先启用 Hermes webhook adapter：

```bash
hermes config set platforms.webhook.enabled true
hermes config set platforms.webhook.extra.port 8644
hermes config set platforms.webhook.extra.secret global-secret
hermes config check
```

启动或重启 Hermes gateway：

```bash
hermes gateway run
```

在另一个终端确认 webhook adapter 正在监听：

```bash
curl http://127.0.0.1:8644/health
```

预期返回：

```json
{"status": "ok", "platform": "webhook"}
```

这里的 `8644` 是 Hermes Webhook adapter 的默认端口。如果你的 Hermes 使用其它端口，后续 `sink.url` 也要同步使用实际端口。

确认 gateway 可用后，创建 Scale Relay 使用的动态 webhook 订阅：

```bash
hermes webhook subscribe scale-relay-weight \
  --events "weight_measurement" \
  --prompt "你收到一个外部事件，请根据 message 和 payload 处理。\n\n{message}\n\n事件：\n{__raw__}" \
  --deliver feishu \
  --description "Scale Relay weight measurement events"
```

`hermes webhook subscribe` 会返回类似：

```text
URL:    http://localhost:8644/webhooks/scale-relay-weight
Secret: <generated-secret>
```

这里的 `scale-relay-weight` 是动态订阅名称，会成为 webhook URL 路径的一部分：`/webhooks/scale-relay-weight`。

后续初始化 Scale Relay 配置时，把这个 URL 和 Secret 填到 `sink.url` / `sink.secret`。

如果只想先验证 BLE 采集链路，可以暂时选择 `stdout`，稍后再把 sink 改为 `hermes_webhook`。

### 3. 初始化 Scale Relay 配置

```bash
scale-relay config init
```

初始化阶段如果选择 `hermes_webhook`，需要填入上一步 Hermes 返回的 webhook URL 和 secret。

校验配置：

```bash
scale-relay --config config.yaml config validate
```

### 4. 登录 Xiaomi Cloud

```bash
scale-relay xiaomi login
```

命令会输出两类地址：

- `QR image URL`：本地二维码图片地址，可用 Xiaomi Home / 米家 App 扫码登录。
- `Login URL`：小米登录授权链接，也可以直接在浏览器打开完成授权。

`--host` 只影响 `QR image URL` 里展示的 host，不是小米服务器地址，也不是体重秤地址。本机运行、本机浏览器打开时不需要填写，默认就是 `127.0.0.1`。

扩展场景：如果命令运行在远程主机上，并希望 `QR image URL` 直接显示远程主机可访问 IP，可以使用 `--host`：

```bash
scale-relay xiaomi login --host 192.168.10.240
```

### 5. 查看设备

```bash
scale-relay xiaomi devices --region cn
```

如果不确定设备在哪个区域：

```bash
scale-relay xiaomi devices --all-regions
```

### 6. 提取 BLE KEY 并写入配置

```bash
scale-relay --config config.yaml xiaomi extract-key --region cn --write-config
```

如果账号下有多个 S400，可以指定 `MAC` 或 Xiaomi `did`：

```bash
scale-relay --config config.yaml xiaomi extract-key --region cn --mac E3:2B:13:0A:37:D9 --write-config
```

### 7. 监听一次称重

建议首次运行前先做环境检查：

```bash
scale-relay --config config.yaml doctor
```

```bash
scale-relay --log-level INFO --config config.yaml once
```

如果当前配置是 Hermes，但想临时只看本地输出：

```bash
scale-relay --log-level INFO --config config.yaml once --sink stdout
```

### 8. 常驻监听

```bash
scale-relay --log-level INFO --config config.yaml listen
```

同样可以临时覆盖 sink：

```bash
scale-relay --log-level INFO --config config.yaml listen --sink stdout
```

## 配置示例

完整示例见 [config.example.yaml](config.example.yaml)。

### 关键字段

- `device.mac`：体重秤真实 BLE MAC，用于 Xiaomi BLE 解密和设备识别。
- `device.ble_key`：S400 BLE 加密广播解密密钥，必须是 32 位 hex。
- `device.hci`：Linux 蓝牙适配器编号，`0` 表示 `hci0`。
- `device.ble_address`：macOS CoreBluetooth UUID 兜底字段，默认不需要。
- `profile.user_id`：用户标识。历史记录、统计摘要、每周趋势都会按该用户过滤。
- `profile.gender` / `profile.height_cm`：用户基础属性，`height_cm` 用于本地计算 BMI。
- `history.storage_path`：本地 SQLite 历史库路径。
- `history.recent_measurements_limit`：每次发送给 Hermes 的最近原始称重记录数量。
- `history.statistics_days`：统计摘要的时间窗口，单位是天。
- `history.include_weekly_series`：是否附带按周聚合后的历史趋势。
- `prompt.text`：发给 Hermes 的分析意图和输出要求。孕妇、减脂、普通体重管理等场景都建议通过这里表达。
- `sink.secret`：Hermes Webhook route secret，用于 HMAC 签名。

## Hermes Agent 对接说明

快速开始中的第 2 步已经包含完整 Hermes Webhook 准备流程。本节只说明几个容易混淆的点。

`hermes config set platforms.webhook.extra.secret global-secret` 设置的是 webhook adapter 的全局 fallback secret。Scale Relay 推荐使用 `hermes webhook subscribe` 返回的动态订阅 secret；如果动态订阅自己有 secret，会优先使用动态订阅 secret。

如果 Hermes 运行在另一台机器上，把 `localhost` 或 `127.0.0.1` 换成 Hermes gateway 的实际 IP，例如：

```yaml
sink:
  url: "http://192.168.10.240:8644/webhooks/scale-relay-weight"
```

需要指定目标会话时，可以在 `hermes webhook subscribe` 中按 Hermes 平台能力添加对应的 delivery 参数，例如 `--deliver-chat-id`。如果不指定，Hermes 会使用该平台的 home channel。

注意：`hermes webhook subscribe` 创建的是动态订阅，不会回写 Hermes profile 的 `config.yaml`。Hermes 会把动态订阅保存到 `~/.hermes/webhook_subscriptions.json`，gateway 收到请求时会加载该文件。也就是说，你原来的 Hermes `config.yaml` 看起来没有变化是正常的。

本项目文档统一采用动态订阅方式。Scale Relay 使用 `hermes webhook subscribe` 返回的 URL 和 Secret，不再要求手动维护 Hermes profile 的静态 route 配置。

Scale Relay 发送给 Hermes 的事件包含：

- `event_type`
- `source`
- `intent`
- `message`
- `profile`
- `payload`
- `sent_at`

其中 `message` 由 `prompt.text`、本次称重摘要和历史摘要组成；`payload.current` 是本次完整称重数据，`payload.history` 包含最近记录、统计摘要、每周趋势和数据质量标记。

注意：

- Scale Relay 不传 `channel` 或 `chat_id`。
- 真正发送渠道仍由 `hermes webhook subscribe` 的 `--deliver` 和 delivery 参数决定。
- Scale Relay 的 `sink.secret` 必须使用 `hermes webhook subscribe` 返回的 Secret。
- Hermes 返回非 2xx、连接失败或签名错误时，Scale Relay 会输出失败日志，并把本次称重 JSON 打到终端。

## 命令参考

```bash
# 配置
scale-relay config init
scale-relay --config config.yaml config validate

# Xiaomi Cloud
scale-relay xiaomi login --host 127.0.0.1
scale-relay xiaomi devices --region cn
scale-relay xiaomi devices --all-regions
scale-relay --config config.yaml xiaomi extract-key --region cn --write-config

# BLE 调试
scale-relay --config config.yaml doctor
scale-relay doctor --hci 1
scale-relay debug scan-ble --seconds 30
scale-relay debug scan-ble --seconds 30 --hci 1

# 采集
scale-relay --log-level INFO --config config.yaml once
scale-relay --log-level INFO --config config.yaml once --sink stdout
scale-relay --log-level INFO --config config.yaml listen
```

## BLE 说明

`once`、`listen` 和 `debug scan-ble` 启动前会做一次轻量 BLE 环境检查。检查只输出日志，不会安装 BlueZ、启动 systemd 服务、修改权限或改变系统配置。

### Linux

Linux 使用 BlueZ 的 `hciX` 适配器命名。`device.hci: 0` 对应 `hci0`。

Ubuntu / Debian 常见前置准备：

```bash
sudo apt update
sudo apt install -y bluetooth bluez
sudo systemctl enable --now bluetooth
```

这些命令需要在部署机器上手动执行。Scale Relay 不会自动执行系统安装或服务配置。

查看本机蓝牙适配器：

```bash
hcitool dev
```

如果有多个适配器，可以把配置改成对应编号，或调试时使用：

```bash
scale-relay debug scan-ble --seconds 30 --hci 1
```

也可以先运行：

```bash
scale-relay --config config.yaml doctor
```

`doctor` 会检查当前平台、Python 版本、Linux 下 `hciX` 是否存在，以及 `bluetoothctl` / `hciconfig` 是否可用。

### macOS

macOS 使用 CoreBluetooth，通常不会暴露真实 BLE MAC，而是显示一个 UUID，例如：

```text
B40914D1-8EB7-DB31-5F1A-9C10FDCD8015
```

Scale Relay 会优先用真实 `device.mac` 解析数据，同时通过设备名称、FE95 广播和 MAC 后缀辅助匹配 S400。大多数情况下不需要配置 `ble_address`。

如果自动匹配不足，可以先扫描：

```bash
scale-relay debug scan-ble --seconds 30
```

再把稳定出现的 CoreBluetooth UUID 写到 `device.ble_address`。

## 输出示例

`stdout` sink 输出的是完整称重事件，结构与 Hermes Webhook 请求体一致：

```json
{
  "event_type": "weight_measurement",
  "source": "scale-relay",
  "intent": "analyze_and_notify",
  "message": "目标用户正在进行减脂体重管理...",
  "profile": {
    "user_id": "jj",
    "gender": "male",
    "height_cm": 170
  },
  "payload": {
    "current": {
      "device_mac": "E3:2B:13:0A:37:D9",
      "device_name": "Mijia Body Composition Scale S400",
      "device_type": "xiaomi_s400",
      "user_id": "jj",
      "weight_kg": 49.1,
      "bmi": 19.2,
      "impedance_high": 407,
      "impedance_low": 442,
      "heart_rate": null,
      "interval_from_previous_minutes": null,
      "stabilized": true,
      "source": "ble",
      "same_day_sequence": 1,
      "timestamp": 1782229190
    },
    "history": {
      "records": [
        {
          "timestamp": 1782229190,
          "weight_kg": 49.1,
          "bmi": 19.2,
          "interval_from_previous_minutes": null,
          "same_day_sequence": 1
        }
      ],
      "statistics": {},
      "weekly_series": [],
      "data_quality": {}
    }
  },
  "sent_at": 1782229190
}
```

Hermes sink 会发送包含 `message` 和 `payload` 的事件。成功日志类似：

```text
Hermes Webhook sent request_id=scale-relay:xiaomi_s400:...
```

## 常见问题

### `Xiaomi session not found`

先执行：

```bash
scale-relay xiaomi login --host 127.0.0.1
```

### 没有扫描日志或没有发现体重秤

先确认系统蓝牙权限，然后执行：

```bash
scale-relay --log-level INFO --config config.yaml once
scale-relay debug scan-ble --seconds 30
```

S400 只有在唤醒、上称、测量过程中才会高频广播。

### macOS 看到的是 UUID，不是 MAC

这是 CoreBluetooth 行为。保持 `device.mac` 为真实 MAC；只有自动匹配不足时才配置 `device.ble_address`。

### 解密失败或没有完整体重数据

优先检查 `device.ble_key` 是否来自当前这台 S400。重新执行：

```bash
scale-relay --config config.yaml xiaomi extract-key --region cn --write-config
```

### Hermes 返回 `401 Invalid signature`

`sink.secret` 和 Hermes route 的 `secret` 不一致。若 route 配了独立 secret，应使用 route secret。

### Hermes 连接失败

检查：

- `sink.url` 的 IP、端口、路径是否正确。
- Hermes gateway 是否启用。
- Hermes route 是否存在。
- 防火墙或容器网络是否允许访问。

失败时 Scale Relay 仍会把本次称重 JSON 输出到终端。

## 安全

- 不要提交真实 `config.yaml`。
- 不要公开 `BLE KEY`、Xiaomi session、cookie、token、Hermes Webhook secret。
- Xiaomi 登录使用 QR 登录，不在命令行传密码。
- 本地 session 和配置文件会尽量使用 `0600` 权限。
- 日志中 secret 会做掩码处理，但仍应避免把完整调试日志公开到外部。

## 致谢与来源

本项目属于面向自身使用场景的工程化整合，并不是从零发现 S400 BLE 协议或 Xiaomi Cloud 提取流程。项目实现和实操验证参考、复用了以下公开项目和资料的思路：

- [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)：提供 Xiaomi Cloud 设备 token / BLE KEY 提取流程参考。
- [RobertWojtowicz/export2garmin](https://github.com/RobertWojtowicz/export2garmin)：提供体重秤数据采集与导出场景参考，本项目早期 S400 BLE 实操验证基于其目录结构和思路做过适配。
- [Bluetooth-Devices/xiaomi-ble](https://github.com/Bluetooth-Devices/xiaomi-ble)：用于解析 Xiaomi BLE FE95 广播数据。
- [hbldh/bleak](https://github.com/hbldh/bleak)：提供跨平台 BLE 扫描能力。
- [Bluetooth-Devices/bluetooth-sensor-state-data](https://github.com/Bluetooth-Devices/bluetooth-sensor-state-data)：提供 BLE 传感器数据结构支持。

Scale Relay 的主要工作是把上述能力收敛成一个更小、更明确的本地服务：只保留 S400 所需的登录、配置、BLE 监听和数据标准化能力，并把真实称重数据接入 Hermes Agent，让 Hermes profile 可以基于日常测量结果进行分析、提醒和长期陪伴。

## 开发

运行测试：

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

编译检查：

```bash
PYTHONPATH=src python3 -m compileall -q src tests
```

项目约束见：

- [AGENTS.md](AGENTS.md)
- [docs/requirements.md](docs/requirements.md)
- [docs/development.md](docs/development.md)
