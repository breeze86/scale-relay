# Scale Relay 需求文档

## 1. 项目定位

Scale Relay 是一个运行在本地 Linux 主机上的体重数据采集与转发工具。

第一阶段目标是完整支持 Xiaomi Mijia Scale S400：

```text
小米账号初始化
↓
获取体重秤 MAC / BLE KEY
↓
本地 BLE 监听 S400 加密广播
↓
解析称重数据
↓
保存本地历史并构造 current/history 事件
↓
输出结构化日志或发送给 Hermes Agent
```

项目需要覆盖从初始化到运行的完整流程，避免用户为了获取 BLE KEY 额外手工运行另一个项目。

## 2. 背景

Xiaomi Mijia Scale S400 不直接明文广播完整称重数据。

已验证流程如下：

```text
S400 通过 BLE FE95 广播加密数据
需要 Xiaomi Cloud 中的 BLE KEY 解密
使用 xiaomi-ble 可解析出 Mass / Impedance Low / Impedance High
```

当前 `docs/xiaomi_s400_ble_local_collection_runbook.md` 已经记录了在 Ubuntu 系统上跑通的实操流程和验证代码。

当前项目实现已在 macOS 开发环境验证：

- Xiaomi Cloud QR 登录。
- S400 `MAC` / `BLE KEY` 提取。
- S400 BLE 扫描与 FE95 解密。
- 体重、高频阻抗、低频阻抗解析。
- `stdout` 输出。
- SQLite 本地历史存储。
- 历史记录、统计摘要、每周趋势上下文生成。
- Hermes Agent Webhook HMAC 签名发送。

Ubuntu / Debian / PVE 仍是目标部署环境，需要保留最终实机验证。

本项目需要将该流程工程化：

- 保留已验证的 BLE 解析链路。
- 整合 Xiaomi Cloud 设备信息提取能力。
- 剔除 Garmin、export2garmin 等无关能力。
- 抽象目标服务发送层，支持 `stdout` 与 Hermes Agent 原生 Webhook。

## 3. 用户目标

用户需要完成两类操作：

1. 初始化设备信息。
   - 登录小米账号。
   - 获取 S400 的 MAC、BLE KEY、设备型号等信息。
   - 写入本项目配置。

2. 监听并转发称重数据。
   - 本地监听 BLE 广播。
   - 解密并解析 S400 称重结果。
   - 写入本地历史。
   - 构造本次数据、最近历史、统计摘要和每周趋势。
   - 输出结构化日志或发送到 Hermes Agent Webhook。

## 4. MVP 范围

第一版必须包含：

- 小米账号 QR 登录。
- 小米设备列表获取。
- S400 设备识别。
- S400 MAC / BLE KEY 提取。
- 配置文件生成与校验。
- S400 BLE 扫描。
- FE95 广播解密。
- 称重数据解析。
- `stdout` 调试输出。
- 本地历史存储。
- 历史上下文生成。
- 按 `profile.user_id` 隔离历史记录和统计摘要。
- 配置化 prompt，用于表达分析意图。
- 单次监听模式。
- 常驻监听模式。

第一版暂不包含：

- Web UI。
- 多用户管理。
- 多体重秤管理。
- 自动安装系统依赖。
- 自动注册 systemd 服务。
- Garmin 相关能力。
- Home Assistant 集成。
- 云端长期同步。

## 5. 功能需求

### 5.1 小米账号初始化

项目需要提供一次性命令，用于登录小米账号并提取设备信息。

建议命令：

```bash
scale-relay xiaomi login
scale-relay xiaomi devices
scale-relay xiaomi extract-key
```

要求：

- 优先支持 QR 登录。
- 不通过命令行参数传入小米账号密码。
- 支持选择 Xiaomi Home 区域，至少支持 `cn`。
- 能列出账号下设备。
- 能识别 S400 设备。
- 能提取并展示以下字段：
  - `name`
  - `model`
  - `did`
  - `mac`
  - `ble_key`
  - `region`
- 日志和终端输出必须对敏感字段脱敏。
- 用户确认后才能将 BLE KEY 写入配置文件。

### 5.2 配置管理

项目需要提供配置初始化与校验能力。

建议命令：

```bash
scale-relay config init
scale-relay config validate
```

配置文件至少包含：

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

    请结合本次称重数据、最近称重记录、最近 30 天统计和每周趋势，分析本次体重变化。
    输出适合微信阅读的简短中文消息。

sink:
  type: stdout
```

校验要求：

- `mac` 必须是合法 MAC 地址。
- `ble_key` 必须是 32 位十六进制字符串。
- `hci` 必须是非负整数。
- `profile.user_id` 不能为空。
- `history.recent_measurements_limit` 必须大于 0。
- `history.statistics_days` 必须大于 0。
- `prompt.text` 不能为空。
- `sink.type` 必须是已支持类型。
- 当 `sink.type=hermes_webhook` 时，Hermes Webhook URL 和 secret 必须存在。

### 5.3 BLE 监听

项目需要支持监听 Xiaomi Mijia Scale S400 的 BLE 广播。

建议命令：

```bash
scale-relay once
scale-relay listen
```

要求：

- 使用配置中的 `mac` 过滤目标设备。
- 使用配置中的 `ble_key` 解密广播。
- 默认监听 `hci0`，支持配置切换。
- 识别并解析以下字段：
  - `Mass`
  - `Impedance Low`
  - `Impedance High`
  - `Stabilized`
- 只有称重稳定且阻抗字段完整时才生成正式称重事件。
- 解密失败时提示 BLE KEY 可能错误。
- 支持监听超时。
- 常驻模式下，一次称重完成后继续等待下一次称重。
- 需要避免同一次称重被重复发送。

### 5.4 数据模型

内部统一称重事件建议为：

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
  "interval_from_previous_minutes": 120,
  "same_day_sequence": 2,
  "stabilized": true,
  "source": "ble"
}
```

说明：

- `heart_rate` 当前没有稳定解析来源，使用 `null`，不要用 `0` 表示真实值。
- `timestamp` 使用本地接收到完整称重数据的时间。
- Hermes Agent Webhook 字段映射由事件构造层和 sink 单独处理，不污染 BLE 解析层。

### 5.5 本地历史与统计上下文

项目需要在每次完整称重后写入本地历史，并在发送 Hermes 或 `stdout` 输出时携带历史上下文。

要求：

- 使用本地 SQLite 保存历史记录。
- 历史库路径由 `history.storage_path` 配置。
- 写入时必须带上 `profile.user_id`。
- 查询最近记录、统计摘要、每周趋势时必须按当前 `profile.user_id` 过滤。
- 同一个 SQLite 文件可以保存多个用户的数据，但不同用户之间不能互相污染统计结果。
- 旧历史库如果没有 `user_id` 字段，可以迁移为 `default` 用户。
- 历史写入需要按 request_id 去重，避免同一次称重重复进入历史。

历史原始记录应尽量保留可稳定拿到的数据：

```json
{
  "user_id": "jj",
  "device_type": "xiaomi_s400",
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
}
```

发送事件中的历史结构：

```json
{
  "history": {
    "records": [],
    "statistics": {},
    "weekly_series": [],
    "data_quality": {}
  }
}
```

`records`：

- 最近 N 条原始记录。
- N 由 `history.recent_measurements_limit` 控制。
- 按时间升序输出，便于 Hermes 判断变化。
- 每条记录需要包含 `interval_from_previous_minutes`，表示距离上一条记录的分钟数；第一条为 `null`。
- 每条记录需要包含 `same_day_sequence`，表示该记录是当天第几次称重。
- 不因相邻时间较近而丢弃、合并记录；是否视为短时波动由 Hermes 根据字段和提示词判断。

`statistics`：

- 只包含确定性统计结果，不包含“偏快”“偏慢”“异常”等分析结论。
- 可包含较上次变化、7 天均值、30 天均值、最小/最大值、BMI 均值、阻抗均值等。
- 统计窗口由 `history.statistics_days` 控制。

`weekly_series`：

- 当 `history.include_weekly_series=true` 时输出。
- 按自然周聚合，包含每周样本数、均重、最大/最小体重、平均 BMI 等。

`data_quality`：

- 需要标记总样本数、最近记录数、统计窗口样本数。
- 历史不足时设置 `insufficient_history=true`。
- 缺失字段需要写入 `missing_fields`，例如 `heart_rate`。

发送给 Hermes 的 `message` 必须包含历史阅读规则：

```text
历史数据阅读规则：
- payload.history.records 按时间升序排列。
- interval_from_previous_minutes 表示该记录距离上一条记录的分钟数。
- same_day_sequence 表示该记录是当天第几次称重。
- 如果相邻记录间隔较短，尤其是同一天多次称重，请将其视为短时波动参考，不要直接当作长期趋势。
- 趋势判断应优先结合 payload.history.statistics 和 payload.history.weekly_series。
```

### 5.6 输出与转发

项目第一阶段默认使用 `stdout` sink，直接输出结构化称重事件，方便先验证 S400 采集链路。

要求：

- `stdout` sink 独立实现。
- 输出必须是结构化 JSON。
- 输出内容使用完整外部事件，包含 `payload.current` 和 `payload.history`。
- 不输出完整 BLE KEY、Xiaomi token、cookie 等敏感信息。

### 5.7 Hermes Agent Webhook 转发

Hermes Agent Webhook 是当前第一版接入目标之一。采集链路可先用 `stdout` 验证，稳定后切换到 `hermes_webhook`。

Hermes Agent 已经原生支持 Webhook adapter。Scale Relay 不需要扩展 Hermes Agent，也不需要直接调用 Hermes 内部代码。Scale Relay 只负责向 Hermes Agent Gateway 暴露的 Webhook route 发送结构化事件。

推荐链路：

```text
scale-relay
↓
Hermes Agent profile gateway webhook
↓
Hermes Agent run
↓
Hermes profile memory / skills / SOUL
↓
Hermes delivery channel，比如 weixin
```

要求：

- Hermes Webhook sink 独立实现。
- 支持 HTTP POST。
- 支持 HMAC-SHA256 签名。
- 支持 `X-Request-ID` 幂等请求头。
- 支持请求超时。
- 支持有限重试。
- 失败时记录错误。
- 不在日志中输出 secret。
- 后续可以在不改 BLE 监听代码的情况下增加其它 sink。

Hermes 侧统一使用动态 webhook 订阅，不要求手动维护 Hermes profile 的静态 route 配置。

推荐命令：

```bash
hermes webhook subscribe scale-relay-weight \
  --events "weight_measurement" \
  --prompt "你收到一个外部事件，请根据 message 和 payload 处理。\n\n{message}\n\n事件：\n{__raw__}" \
  --deliver weixin \
  --description "Scale Relay weight measurement events"
```

`scale-relay-weight` 是动态订阅名称，会成为 webhook URL 路径的一部分。`hermes webhook subscribe` 会返回 webhook URL 和 HMAC secret。Scale Relay 的 `sink.url` / `sink.secret` 必须使用该命令返回的值。

Hermes 的发送目标由 `hermes webhook subscribe` 的 `--deliver` 和 delivery 参数控制，不由 Scale Relay payload 自动控制。Scale Relay 不传 `channel` / `chat_id`，避免采集端影响 Hermes 路由判断。

Scale Relay 发送的事件结构为：

```json
{
  "event_type": "weight_measurement",
  "source": "scale-relay",
  "intent": "analyze_and_notify",
  "message": "目标用户是一名孕妇...\\n\\n本次称重摘要...\\n\\n历史数据摘要...",
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
      "interval_from_previous_minutes": 120,
      "same_day_sequence": 2,
      "heart_rate": null,
      "stabilized": true,
      "source": "ble"
    },
    "history": {
      "records": [],
      "statistics": {
        "sample_count": 1,
        "weight": {
          "latest_kg": 48.9,
          "avg_7d_kg": 48.9,
          "avg_30d_kg": 48.9
        }
      },
      "weekly_series": [],
      "data_quality": {
        "sample_count": 1,
        "insufficient_history": true,
        "missing_fields": ["heart_rate"]
      }
    }
  },
  "sent_at": 1782205025
}
```

Hermes profile 选择不由 Scale Relay 控制。Scale Relay 只发送到用户配置的 Hermes profile gateway URL。当前目标是已经启用 gateway 的 `jj` profile。

Scale Relay 在服务端根据 `prompt.text`、本次称重和历史上下文拼好 `message`，并计算 BMI、均值、差值、每周聚合等确定性字段。真正发送渠道必须由 Hermes 动态订阅的 `--deliver` 指定，例如 `--deliver feishu`。

### 5.8 通用发送层

项目需要保留通用性。

第一阶段至少支持：

- `stdout`：调试输出。

后续优先支持：

- `hermes_webhook`：发送到 Hermes Agent 原生 Webhook。

后续可扩展：

- `http`：通用 HTTP POST。
- `mqtt`。
- `file`。
- `sqlite`。
- `postgresql`。

## 6. 非功能需求

### 6.1 运行环境

目标运行环境：

- Ubuntu。
- Debian。
- PVE。

系统依赖：

- BlueZ。
- 可用蓝牙适配器。
- Python 3。

### 6.2 安全

要求：

- 不在命令行参数中接收小米账号密码。
- 优先 QR 登录。
- BLE KEY、token、cookie 必须脱敏输出。
- 配置文件建议权限为 `0600`。
- 常驻服务不需要小米账号登录能力。
- Xiaomi Cloud 登录态只用于一次性初始化。

### 6.3 可维护性

要求：

- BLE 解析、Xiaomi Cloud、Hermes 发送分层实现。
- Hermes Agent 接入只依赖其原生 Webhook，不修改 Hermes Agent。
- 不把业务逻辑堆到 CLI 入口。
- 不引入与 S400 无关的大量代码。
- 保留已验证手册作为溯源文档。

### 6.4 鲁棒性

要求：

- BLE KEY 错误有明确提示。
- 蓝牙适配器不可用有明确提示。
- 未扫描到设备有明确提示。
- Hermes Agent Webhook 不可用时不能导致进程异常退出。
- 常驻监听模式需要处理重复广播和重复发送。

## 7. 验收标准

MVP 验收标准：

1. 用户可以只使用本项目命令完成 S400 初始化。
2. 项目可以提取并保存 S400 的 MAC 和 BLE KEY。
3. `scale-relay config validate` 可以校验配置。
4. `scale-relay once` 可以监听一次称重并输出结构化结果。
5. `scale-relay listen` 可以持续监听多次称重。
6. `stdout` sink 可以直接输出称重事件 JSON。
7. BLE KEY、token 等敏感信息不会完整出现在日志中。

## 8. 待确认事项

- `jj` profile 的 Webhook route URL。
- `jj` profile 的 Webhook route secret。
- `jj` profile 的最终发送渠道和目标配置。
- Hermes 失败时是否需要本地缓冲。
- 是否需要支持多个小米区域自动扫描。
