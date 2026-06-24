# Scale Relay 开发文档

## 1. 技术选型

项目建议使用 Python 实现。

原因：

- 已验证的 BLE 采集代码基于 Python。
- `bleak`、`xiaomi-ble`、`bluetooth-sensor-state-data` 已经跑通。
- Xiaomi Cloud token 提取生态主要也是 Python。
- 本项目主要是本地守护进程和 CLI，Python 足够直接。

推荐基础依赖：

```text
bleak
xiaomi-ble
bluetooth-sensor-state-data
httpx
pyyaml
pydantic
typer
rich
```

说明：

- `httpx` 用于后续 Hermes Agent Webhook 请求。
- `pydantic` 用于配置和数据模型校验。
- `typer` 用于 CLI。
- `rich` 只用于 CLI 输出，不输出敏感明文。

不建议引入：

```text
export2garmin
garminconnect
bluepy
pillow
```

这些依赖不是本项目核心路径所需。

## 2. 推荐目录结构

```text
scale-relay/
  docs/
    requirements.md
    development.md
    xiaomi_s400_ble_local_collection_runbook.md

  src/
    scale_relay/
      __init__.py
      cli.py
      config.py
      models.py
      logging.py
      service.py

      xiaomi_cloud/
        __init__.py
        auth.py
        client.py
        devices.py
        extract_key.py
        models.py

      ble/
        __init__.py
        xiaomi_s400.py
        models.py

      sinks/
        __init__.py
        base.py
        stdout.py
        hermes_webhook.py
        http.py

  tests/
    test_config.py
    test_models.py
    test_sinks.py

  config.example.yaml
  pyproject.toml
  README.md
```

## 3. 模块职责

### 3.1 CLI

文件：

```text
src/scale_relay/cli.py
```

职责：

- 注册命令。
- 调用业务模块。
- 做用户交互。
- 不直接实现 BLE 解析、HTTP 发送、小米云协议细节。

建议命令：

```bash
scale-relay xiaomi login
scale-relay xiaomi devices
scale-relay xiaomi extract-key
scale-relay config init
scale-relay config validate
scale-relay once
scale-relay listen
```

### 3.2 配置模块

文件：

```text
src/scale_relay/config.py
```

职责：

- 读取 YAML 配置。
- 写入 YAML 配置。
- 校验 MAC、BLE KEY、Hermes Agent Webhook 配置。
- 对敏感字段脱敏展示。

核心模型：

```text
AppConfig
XiaomiConfig
DeviceConfig
SinkConfig
RetryConfig
```

### 3.3 Xiaomi Cloud 模块

目录：

```text
src/scale_relay/xiaomi_cloud/
```

职责：

- 小米账号登录。
- 区域选择。
- 获取设备列表。
- 识别 S400。
- 提取 BLE KEY。

建议先参考并精简 Xiaomi Cloud Tokens Extractor 的关键逻辑，只保留本项目需要的流程。

不要直接整包复制无关代码。

核心输出：

```text
XiaomiDevice
XiaomiScaleCredentials
```

示例：

```json
{
  "name": "Xiaomi Body Composition Scale S400",
  "model": "yunmai.scales.ms104",
  "did": "xxx",
  "mac": "E3:2B:13:0A:37:D9",
  "ble_key": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "region": "cn"
}
```

安全要求：

- 不通过 CLI 参数接收账号密码。
- 优先 QR 登录。
- 登录态如需落盘，必须明确路径和权限。
- 日志中不输出完整 token、cookie、BLE KEY。

### 3.4 BLE 模块

目录：

```text
src/scale_relay/ble/
```

职责：

- 扫描蓝牙广播。
- 过滤目标 MAC。
- 使用 BLE KEY 解密 FE95 广播。
- 解析称重字段。
- 输出统一称重事件。

核心实现参考：

```text
docs/xiaomi_s400_ble_local_collection_runbook.md
```

需要保留的核心逻辑：

- `BleakScanner`
- `BluetoothServiceInfo`
- `XiaomiBluetoothDeviceData(bindkey=...)`
- `xiaomi_parser.supported(service_info)`
- `xiaomi_parser.update(service_info)`
- `Mass`
- `Impedance Low`
- `Impedance High`
- `Stabilized`
- 解密失败检测
- watchdog 超时

需要调整的地方：

- 删除 export2garmin 命名。
- 删除 Garmin 输出格式。
- 不直接 `print to_import;...`。
- 改为返回 `WeightMeasurement`。
- 常驻模式需要去重和冷却时间。

### 3.5 数据模型

文件：

```text
src/scale_relay/models.py
```

核心模型：

```python
class WeightMeasurement:
    device_type: str
    device_name: str | None
    device_mac: str
    timestamp: int
    weight_kg: float
    impedance_high: int
    impedance_low: int
    heart_rate: int | None
    stabilized: bool
    source: str
```

约束：

- `weight_kg` 必须大于 0。
- `impedance_high`、`impedance_low` 必须大于 0。
- `heart_rate` 未解析时为 `None`。
- `timestamp` 使用 Unix 秒级时间戳。

### 3.6 Sink 模块

目录：

```text
src/scale_relay/sinks/
```

职责：

- 接收统一 `WeightMeasurement`。
- 转换成目标服务格式。
- 发送。
- 处理超时、重试、错误日志。

基础接口：

```python
class MeasurementSink:
    async def send(self, measurement: WeightMeasurement) -> None:
        ...
```

第一版 sink：

- `StdoutSink`

后续优先实现 sink：

- `HermesWebhookSink`

后续 sink：

- `HttpSink`
- `MqttSink`
- `FileSink`
- `SqliteSink`

### 3.7 服务编排

文件：

```text
src/scale_relay/service.py
```

职责：

- 加载配置。
- 创建 BLE listener。
- 创建 sink。
- 编排 `once` 和 `listen`。
- 处理异常和退出信号。

运行模式：

```text
once:
  启动 BLE 扫描
  获取一次完整称重
  发送 sink
  退出

listen:
  启动 BLE 扫描
  每次获取完整称重后发送 sink
  继续等待下一次称重
```

## 4. BLE 监听流程

单次监听流程：

```text
读取配置
校验 MAC / BLE KEY
创建 XiaomiBluetoothDeviceData
启动 BleakScanner
过滤目标 MAC
构造 BluetoothServiceInfo
判断 parser.supported
调用 parser.update
读取 entity_values / binary_entity_values
等待 Mass + Impedance Low + Impedance High + Stabilized
生成 WeightMeasurement
返回给 service
```

常驻监听需要增加：

- 上一次发送记录。
- 冷却时间。
- 幂等判断。
- 扫描异常恢复。

建议幂等键：

```text
device_mac + timestamp_window + weight_kg + impedance_high + impedance_low
```

第一版也可以简单用：

```text
同一设备在 cooldown_seconds 内相同 weight/impedance 不重复发送
```

## 5. 输出与 Hermes Agent Webhook

第一阶段默认使用 `stdout` sink，直接输出结构化称重事件 JSON，先验证 S400 采集链路。

后续 Hermes 接入使用 Hermes Agent 原生 Webhook adapter。

当前 macOS 开发环境已经验证 Hermes Agent Webhook HMAC 签名发送成功。Ubuntu / Debian / PVE 仍需作为目标部署环境做最终验证。

Scale Relay 不扩展 Hermes Agent，不直接调用 Hermes 内部 Python API，也不承担分析和微信发送逻辑。Scale Relay 只向已经启用 gateway 的 Hermes profile Webhook route 发送结构化事件。

推荐链路：

```text
接收 WeightMeasurement
写入 SQLite 历史库
查询 recent records / statistics / weekly series
映射为通用外部事件
生成 X-Request-ID
使用 route secret 计算 HMAC-SHA256
POST Hermes Agent Webhook URL
超时控制
失败重试
记录结果
```

### 5.1 Hermes 侧通用配置

Hermes profile 的 `platforms.webhook` 应保持通用。当前目标是 `jj` profile，且该 profile 已经启用 gateway。

推荐 Hermes 动态订阅：

```bash
hermes gateway setup
hermes webhook subscribe scale-relay-weight \
  --events "weight_measurement" \
  --prompt "你收到一个外部事件，请根据 message 和 payload 处理。\n\n{message}\n\n事件：\n{__raw__}" \
  --deliver weixin \
  --description "Scale Relay weight measurement events"
```

`scale-relay-weight` 是动态订阅名称，会成为 webhook URL 路径的一部分。`hermes webhook subscribe` 返回的 URL 和 HMAC secret 需要写入 Scale Relay 的 `sink.url` / `sink.secret`。

说明：

- `platforms.webhook` 是 Hermes profile 的通用外部事件入口。
- 动态订阅建议使用清晰名称，例如 `scale-relay-weight`，避免让订阅名看起来像命令关键字。
- 体重分析意图优先通过 Scale Relay 的 `prompt.text` 配置表达；长期偏好和背景可以放在 `jj` profile 的 `SOUL.md`、memory 或 skill 中。
- Hermes 的发送目标由动态订阅的 `--deliver` 和 delivery 参数控制，不由 Scale Relay payload 自动控制。
- Scale Relay 不传 `channel` / `chat_id`，避免采集端影响 Hermes 路由判断。

### 5.2 Scale Relay 请求体

Scale Relay 发送通用事件：

```json
{
  "event_type": "weight_measurement",
  "source": "scale-relay",
  "intent": "analyze_and_notify",
  "payload_schema": {
    "name": "scale_relay.weight_measurement",
    "version": "1.0"
  },
  "message": "用户分析意图...\\n\\n本次称重摘要...\\n\\n历史数据摘要...\\n\\n数据说明...\\n\\n输出要求...",
  "profile": {
    "user_id": "jj",
    "gender": "female",
    "height_cm": 160
  },
  "payload": {
    "current": {
      "device_type": "xiaomi_s400",
      "user_id": "jj",
      "device_name": "Xiaomi Body Composition Scale S400",
      "device_mac": "E3:2B:13:0A:37:D9",
      "timestamp": 1782205025,
      "weight_kg": 48.9,
      "bmi": 19.1,
      "impedance_high": 428,
      "impedance_low": 462,
      "heart_rate": null,
      "stabilized": true,
      "source": "ble"
    },
    "history": {
      "records": [],
      "statistics": {},
      "weekly_series": [],
      "data_quality": {}
    }
  },
  "sent_at": 1782205025
}
```

`message` 由 Scale Relay 在服务端拼接：用户业务意图来自 `prompt.text`，本次摘要、历史摘要、数据说明、历史阅读规则和输出要求由代码内置生成。`message` 不要求用户了解 payload 字段名。真正发送渠道仍由 Hermes 动态订阅的 `--deliver` 配置决定。

请求头：

```text
Content-Type: application/json
X-Webhook-Signature: <hmac_sha256_hex>
X-Request-ID: scale-relay:xiaomi_s400:<device_mac>:<timestamp>
```

签名规则：

```text
hmac_sha256(secret, raw_request_body)
```

Hermes Webhook adapter 的 Generic 签名头使用 `X-Webhook-Signature`，值为原始 HMAC-SHA256 hex digest。

### 5.3 幂等

Hermes Webhook adapter 会使用 `X-GitHub-Delivery` / `X-Request-ID` 等请求 ID 做短期幂等。Scale Relay 必须稳定生成 `X-Request-ID`，避免重试导致重复触发 agent run。

推荐：

```text
scale-relay:xiaomi_s400:<normalized_mac>:<timestamp>:<weight_kg>:<impedance_high>:<impedance_low>
```

### 5.4 失败处理

需要处理：

- `401`：签名错误或 secret 不匹配。
- `404`：route 不存在。
- `413`：body 过大。
- `429`：Hermes route 限流。
- `502`：Hermes delivery target 失败。
- 其它非 2xx。

第一版失败后只做有限重试和日志记录，不做本地持久化队列。

## 6. 配置文件

默认查找顺序建议：

```text
--config 指定路径
./config.yaml
~/.config/scale-relay/config.yaml
/etc/scale-relay/config.yaml
```

示例：

```yaml
xiaomi:
  region: cn

device:
  type: xiaomi_s400
  name: "Xiaomi Body Composition Scale S400"
  model: "yunmai.scales.ms104"
  mac: "E3:2B:13:0A:37:D9"
  ble_key: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  hci: 0

listen:
  scan_timeout_seconds: 180
  cooldown_seconds: 10

profile:
  user_id: "jj"
  gender: "female"
  height_cm: 160

history:
  enabled: true
  storage_path: "data/measurements.sqlite3"
  recent_measurements_limit: 21
  statistics_days: 30
  include_weekly_series: true

prompt:
  text: |
    目标用户是一名孕妇，孕期起始日期为：2026-04-22。

    请分析本次体重变化，输出适合微信阅读的简短中文消息。
    不要做医疗诊断。

sink:
  type: stdout
```

## 7. 日志规范

日志需要包含：

- 服务启动。
- 使用的蓝牙适配器。
- 发现目标设备。
- 解析到称重字段。
- 成功生成称重事件。
- sink 发送成功。
- sink 发送失败。
- BLE KEY 解密失败。
- 蓝牙适配器错误。

日志不能包含：

- 完整 BLE KEY。
- 完整 Xiaomi token。
- 完整 cookie。
- Hermes Webhook secret。

脱敏规则建议：

```text
1234567890abcdef1234567890abcdef -> 1234************************cdef
```

## 8. 错误处理

需要明确处理：

- 配置文件不存在。
- 配置字段缺失。
- BLE KEY 格式错误。
- 蓝牙适配器不存在。
- BlueZ 服务不可用。
- 没有扫描到目标 MAC。
- 解密失败。
- 只解析到体重，没有解析到阻抗。
- Hermes Agent Webhook 超时。
- Hermes Agent Webhook 返回非 2xx。

常驻模式下，除配置错误外，运行时错误应尽量记录后继续。

## 9. 开发步骤

建议按以下顺序实现：

1. 创建 Python 项目骨架。
2. 实现配置模型和校验。
3. 实现统一 `WeightMeasurement` 模型。
4. 实现 `stdout` sink。
5. 从手册代码抽取 S400 BLE listener。
6. 实现 `once` 命令。
7. 实现 `listen` 命令。
8. 预留并实现 Hermes Agent Webhook sink，但前期默认不启用。
9. 集成 Xiaomi Cloud 设备信息提取。
10. 实现 `xiaomi extract-key`。
11. 实现 `config init` 和 `config validate`。
12. 补充 README 和 systemd 示例。

## 10. 测试策略

优先测试：

- 配置校验。
- BLE KEY 脱敏。
- Hermes Agent Webhook 请求体映射。
- Hermes Agent Webhook HMAC 签名。
- Hermes Agent Webhook 重试逻辑。
- 称重事件去重逻辑。

BLE 实机测试：

- 正确 BLE KEY。
- 错误 BLE KEY。
- 未站上秤超时。
- 只显示体重但未完成阻抗。
- 完整测量后生成事件。
- 常驻模式连续两次称重。

由于 BLE 广播依赖实机和系统蓝牙，自动化测试不强行覆盖完整实机链路。核心解析和发送逻辑应可通过单元测试覆盖。

## 11. 与现有手册的关系

`docs/xiaomi_s400_ble_local_collection_runbook.md` 是已跑通的实操记录。

开发时应从中复用：

- 系统依赖说明。
- BLE KEY 获取事实。
- S400 设备识别信息。
- `xiaomi-ble` 解析方式。
- 成功输出字段。
- 常见问题排查。

开发时应剔除：

- export2garmin 项目结构。
- Garmin 相关依赖。
- `to_import;...` 输出格式。
- 与 S400 无关的配置项。

## 12. 待确认技术问题

- Xiaomi Cloud QR 登录是否直接内聚实现，还是 vendoring 精简后的 extractor 逻辑。
- 登录态是否需要落盘。
- 是否需要支持多个 Xiaomi region 自动扫描。
- `jj` profile 的 Webhook route URL。
- `jj` profile 的 Webhook route secret。
- `jj` profile 的最终发送渠道和目标配置。
- Hermes Agent Webhook 发送失败是否需要本地持久化队列。
