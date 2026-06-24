# Scale Relay AGENTS.md

## Communication

- 默认使用简体中文。
- 先给结论，再给分析。
- 表达直接、务实，少废话。
- 不确定的内容必须明确说明，不要编造。
- 涉及需求变更、接口变更、依赖变更时，先说明影响范围。

## Project Goal

Scale Relay 是一个本地 Linux 体重数据采集与转发工具。

当前已验证 Xiaomi Cloud 登录、S400 BLE 采集、`stdout` 输出、本地历史存储、历史上下文生成和 Hermes Agent Webhook 发送。Ubuntu / Debian / PVE 仍是目标部署环境。

第一阶段只聚焦 Xiaomi Mijia Scale S400：

```text
小米账号初始化
↓
获取 S400 MAC / BLE KEY
↓
本地 BLE 监听 S400 加密广播
↓
解析体重 / 高频阻抗 / 低频阻抗
↓
写入本地历史
↓
构造 current/history/statistics/weekly_series 事件
↓
输出结构化日志或发送结构化事件到 Hermes Agent Webhook
```

项目需要覆盖从初始化到运行的完整流程，避免用户为了获取 BLE KEY 额外手工运行另一个项目。

## Authoritative Docs

开发前优先阅读并遵守：

- `docs/requirements.md`
- `docs/development.md`
- `docs/xiaomi_s400_ble_local_collection_runbook.md`

其中：

- `requirements.md` 是产品边界和验收标准。
- `development.md` 是模块设计和开发路线。
- `xiaomi_s400_ble_local_collection_runbook.md` 是已在 Ubuntu 跑通的实操依据。

如果实现和文档冲突，先更新方案并等待确认，不要直接偏离。

## Development Workflow

- 开发前先给修改方案，待确认后再实现。
- 如果用户明确说“直接改”“立即开发”“现在就开发”，可以直接实现。
- 优先最小必要改动，避免无关重构。
- 优先复用已有文档确认过的方案。
- 改动时说明：
  - 改了什么。
  - 为什么改。
  - 影响范围。
- 修改完成后优先执行格式检查、lint、typecheck、tests。
- 如果某项检查没有执行，必须说明原因。

## Technical Direction

- 项目默认使用 Python。
- 第一版是 CLI + 本地服务，不做 Web UI。
- 推荐依赖：
  - `bleak`
  - `xiaomi-ble`
  - `bluetooth-sensor-state-data`
  - `httpx`
  - `pyyaml`
  - `pydantic`
  - `typer`
  - `rich`
- 不要引入无关重量级框架。
- 允许使用本地 SQLite 保存称重历史；不要引入远程数据库，除非需求文档明确更新。
- 不要主动做 systemd 自动安装，第一版只保留示例即可。

## Hard Boundaries

禁止漂移到以下方向，除非用户明确改变需求：

- 不做 Garmin / export2garmin 集成。
- 不做 Home Assistant 集成。
- 不做 Web UI。
- 不做多用户管理。
- 不做多体重秤管理。
- 不做云端长期同步。
- 不做云端数据库持久化；本地 SQLite 历史库是当前需求的一部分。
- 不做微信直接发送逻辑。
- 不把分析逻辑写进 Scale Relay。
- 不扩展或修改 Hermes Agent 代码。
- 不把 Hermes 做成自定义业务 HTTP API。

## Xiaomi Cloud Scope

项目内需要包含 BLE KEY 获取能力。

必须支持：

- 小米账号 QR 登录。
- 区域选择，至少支持 `cn`。
- 获取设备列表。
- 识别 Xiaomi Mijia Scale S400。
- 提取并保存：
  - `name`
  - `model`
  - `did`
  - `mac`
  - `ble_key`
  - `region`

约束：

- 不通过命令行参数接收小米账号密码。
- 不在日志中输出完整 token、cookie、BLE KEY。
- BLE KEY 写入配置前需要用户确认。
- 小米账号登录只用于一次性初始化，不进入常驻 BLE 监听服务。
- 可以参考 Xiaomi Cloud Tokens Extractor，但不要粗暴复制整个项目；只保留本项目需要的登录、设备列表和 BLE KEY 提取能力。

## BLE Collection Scope

S400 BLE 监听必须基于已验证链路：

- `BleakScanner`
- `BluetoothServiceInfo`
- `XiaomiBluetoothDeviceData(bindkey=...)`
- `xiaomi_parser.supported(service_info)`
- `xiaomi_parser.update(service_info)`

必须解析：

- `Mass`
- `Impedance Low`
- `Impedance High`
- `Stabilized`

正式称重事件要求：

- 必须有体重。
- 必须有高频阻抗。
- 必须有低频阻抗。
- 如果存在 `Stabilized`，必须为 `true`。

注意：

- `heart_rate` 当前没有稳定解析来源，使用 `null`，不要用 `0` 表示真实值。
- 解密失败要提示 BLE KEY 可能错误。
- 常驻模式必须避免同一次称重重复发送。

## Data Model

内部 `WeightMeasurement` 采集模型保持稳定：

```json
{
  "device_type": "xiaomi_s400",
  "device_name": "Xiaomi Body Composition Scale S400",
  "device_mac": "E3:2B:13:0A:37:D9",
  "timestamp": 1782205025,
  "weight_kg": 48.9,
  "impedance_high": 428,
  "impedance_low": 462,
  "heart_rate": null,
  "stabilized": true,
  "source": "ble"
}
```

发送给 sink 的事件必须包含：

- `payload.current`：本次完整称重数据。
- `payload.history.records`：当前 `profile.user_id` 最近 N 条历史原始记录。
- `payload.history.statistics`：当前用户的统计摘要。
- `payload.history.weekly_series`：当前用户的按周聚合趋势。
- `payload.history.data_quality`：历史数量、缺失字段、是否数据不足等质量标记。

历史数据必须按 `profile.user_id` 隔离。配置为 `a` 用户时，只写入和统计 `a` 用户；配置为 `b` 用户时，只写入和统计 `b` 用户。旧历史库缺少 `user_id` 时可以迁移为 `default`。

`statistics` 只放确定性计算结果，不放分析结论。趋势判断、建议和表达交给 Hermes Agent。

`payload.history.records` 中每条记录必须补充采样上下文字段：

- `interval_from_previous_minutes`：距离上一条记录的分钟数，第一条为 `null`。
- `same_day_sequence`：该记录是当天第几次称重。

不要因为相邻时间较近而删除、合并或替换历史记录。短时波动如何解释由 Hermes 根据这些字段和提示词判断。

Hermes 字段映射必须在事件构造层 / sink 层完成，不要污染 BLE 解析层。

## History Scope

本地历史存储是当前核心功能。

必须支持：

- SQLite 本地历史库。
- 每次完整称重后写入历史。
- 按 `request_id` 去重。
- 按 `profile.user_id` 写入和查询。
- 最近记录数量由 `history.recent_measurements_limit` 控制。
- 统计窗口由 `history.statistics_days` 控制。
- `history.include_weekly_series=true` 时附带每周聚合。

历史记录应尽量保留当前能稳定拿到的数据：

- `weight_kg`
- `bmi`
- `impedance_high`
- `impedance_low`
- `heart_rate`
- `stabilized`
- `device_type`
- `device_name`
- `device_mac`
- `source`
- `timestamp`
- `user_id`
- `interval_from_previous_minutes`
- `same_day_sequence`

统计摘要可以包含均值、最大值、最小值、较上次变化、7 天/30 天变化、阻抗均值、BMI 均值等确定性指标。

## Hermes Agent Integration

第一阶段支持 `stdout` 输出和 Hermes Agent 原生 Webhook。

正确链路：

```text
Scale Relay
↓
Hermes Agent profile gateway webhook
↓
Hermes Agent run
↓
Hermes profile memory / skills / SOUL
↓
Hermes delivery channel，例如 weixin
```

Scale Relay 职责：

- 发送结构化事件。
- 发送前构造 `message + payload_schema + payload.current + payload.history`。
- 做 HMAC-SHA256 签名。
- 设置稳定 `X-Request-ID`。
- 处理超时、重试和非 2xx。

Scale Relay 不负责：

- 体重趋势分析。
- 微信消息生成。
- 微信发送。
- Hermes profile 选择。
- Hermes Agent 内部任务调度。

Hermes 侧统一使用动态 webhook 订阅。订阅名建议使用清晰名称，例如 `scale-relay-weight`，不要使用容易被误解为命令关键字的 `events`。

推荐 prompt：

```text
你收到一个外部事件，请根据 message 和 payload 处理。

{message}

事件：
{__raw__}
```

Scale Relay 发送事件：

```json
{
  "event_type": "weight_measurement",
  "source": "scale-relay",
  "intent": "analyze_and_notify",
  "payload_schema": {
    "name": "scale_relay.weight_measurement",
    "version": "1.0"
  },
  "message": "用户业务意图 + 本次摘要 + 历史摘要 + 数据说明 + 输出要求",
  "profile": {
    "user_id": "jj",
    "gender": "male",
    "height_cm": 170
  },
  "payload": {
    "current": {
      "device_type": "xiaomi_s400",
      "device_name": "Xiaomi Body Composition Scale S400",
      "device_mac": "E3:2B:13:0A:37:D9",
      "timestamp": 1782205025,
      "weight_kg": 48.9,
      "bmi": 16.9,
      "impedance_high": 428,
      "impedance_low": 462,
      "heart_rate": null,
      "interval_from_previous_minutes": 120,
      "stabilized": true,
      "source": "ble",
      "same_day_sequence": 2,
      "user_id": "jj"
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

请求头：

```text
Content-Type: application/json
X-Webhook-Signature: <hmac_sha256_hex>
X-Request-ID: scale-relay:xiaomi_s400:<normalized_mac>:<timestamp>:<weight_kg>:<impedance_high>:<impedance_low>
```

签名规则：

```text
hmac_sha256(secret, raw_request_body)
```

## Sink Design

第一阶段必须支持：

- `stdout`
- `hermes_webhook`

保留后续扩展设计：

- `http`
- `mqtt`
- `file`
- `sqlite`
- `postgresql`

新增 sink 时不得修改 BLE listener 的数据解析逻辑。

## Configuration

推荐配置形态：

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
  gender: "male"
  height_cm: 170

history:
  enabled: true
  storage_path: "data/measurements.sqlite3"
  recent_measurements_limit: 21
  statistics_days: 30
  include_weekly_series: true

prompt:
  text: |
    目标用户正在进行减脂体重管理。

    请分析本次体重变化。
    输出适合目标渠道阅读的简短中文消息。

sink:
  type: hermes_webhook
  url: "http://127.0.0.1:8644/webhooks/scale-relay-weight"
  secret: "<hermes webhook subscribe 返回的 HMAC secret>"
  event_type: "weight_measurement"
  intent: "analyze_and_notify"
  timeout_seconds: 10
  retry:
    attempts: 3
    backoff_seconds: 2
```

配置校验必须覆盖：

- MAC 格式。
- BLE KEY 为 32 位十六进制字符串。
- HCI adapter 为非负整数。
- `profile.user_id` 不能为空。
- `history.recent_measurements_limit` 大于 0。
- `history.statistics_days` 大于 0。
- `prompt.text` 不能为空。
- 当 `sink.type=hermes_webhook` 时，Hermes Webhook URL 存在。
- 当 `sink.type=hermes_webhook` 时，Hermes Webhook secret 存在。

## Security

敏感信息必须脱敏：

- BLE KEY。
- Xiaomi token。
- Xiaomi cookie。
- Hermes Webhook secret。

禁止：

- 把账号密码写入命令行参数。
- 在日志中打印完整 secret。
- 在异常堆栈中泄漏完整 secret。
- 伪造运行结果、测试结果或接口返回结果。

配置文件建议权限为 `0600`。

## Commands

第一版 CLI 目标：

```bash
scale-relay xiaomi login
scale-relay xiaomi devices
scale-relay xiaomi extract-key
scale-relay config init
scale-relay config validate
scale-relay doctor
scale-relay debug scan-ble
scale-relay once
scale-relay listen
```

## Testing

优先覆盖：

- 配置校验。
- 敏感字段脱敏。
- WeightMeasurement 模型校验。
- Hermes Webhook payload 映射。
- Hermes Webhook HMAC 签名。
- Hermes Webhook 重试逻辑。
- 历史写入和按 `profile.user_id` 隔离。
- 历史统计摘要和 weekly series。
- 称重事件去重逻辑。

BLE 实机测试需要明确标注环境和结果，不要伪造。

## Dependency Discipline

- 不升级大版本依赖，除非用户确认。
- 不引入 axios；本项目是 Python，HTTP 使用 `httpx`。
- 不引入 `bluepy`，除非 `bleak` 路线被实机验证证明不可用。
- 不引入 Garmin 相关依赖。
- 不把第三方 token extractor 整包复制进项目。

## Definition of Done

功能完成至少满足：

- 代码实现符合 `docs/requirements.md` 和 `docs/development.md`。
- 敏感信息不会完整出现在日志中。
- 能用 `stdout` sink 调试称重事件。
- 能用 `hermes_webhook` sink 发送结构化事件。
- 已执行可用的格式检查、lint、typecheck、tests。
- 未执行的检查已说明原因。
