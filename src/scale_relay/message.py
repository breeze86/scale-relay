"""Build user-facing event messages."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from scale_relay.config import ProfileConfig
from scale_relay.models import WeightMeasurement


def build_weight_message(
    measurement: WeightMeasurement,
    profile: ProfileConfig,
    prompt_text: str,
    history: dict[str, Any] | None = None,
) -> str:
    lines = [prompt_text.strip(), "", "本次称重摘要："]

    if profile.gender:
        lines.append(f"- 性别：{_gender_label(profile.gender)}")
    if profile.height_cm:
        lines.append(f"- 身高：{profile.height_cm:g} cm")

    lines.extend(
        [
            f"- 体重：{measurement.weight_kg:.1f} kg",
            f"- 高频阻抗：{measurement.impedance_high} Ω",
            f"- 低频阻抗：{measurement.impedance_low} Ω",
            f"- 心率：{measurement.heart_rate if measurement.heart_rate is not None else '未解析'}",
        ]
    )

    bmi = calculate_bmi(measurement.weight_kg, profile.height_cm)
    if bmi is not None:
        lines.append(f"- BMI：{bmi:.1f}")

    if history:
        statistics = history.get("statistics") or {}
        data_quality = history.get("data_quality") or {}
        weight_stats = statistics.get("weight") or {}
        lines.extend(
            [
                "",
                "历史数据摘要：",
                f"- 历史记录数：{data_quality.get('sample_count', 0)} 条",
                f"- 最近记录数：{data_quality.get('recent_sample_count', 0)} 条",
                f"- 统计窗口：最近 {data_quality.get('statistics_days', 0)} 天",
            ]
        )
        previous_weight = statistics.get("previous_weight_kg")
        delta_since_previous = statistics.get("delta_since_previous_kg")
        avg_30d = weight_stats.get("avg_30d_kg")
        delta_30d = weight_stats.get("delta_30d_kg")
        if previous_weight is not None:
            lines.append(f"- 上次体重：{previous_weight:.1f} kg")
        if delta_since_previous is not None:
            lines.append(f"- 较上次变化：{delta_since_previous:+.1f} kg")
        if avg_30d is not None:
            lines.append(f"- 最近 30 天均重：{avg_30d:.1f} kg")
        if delta_30d is not None:
            lines.append(f"- 最近 30 天变化：{delta_30d:+.1f} kg")
        if data_quality.get("insufficient_history"):
            lines.append("- 历史数据不足，请谨慎判断长期趋势。")

    lines.extend(
        [
            "",
            "历史数据阅读规则：",
            "- payload.history.records 按时间升序排列。",
            "- interval_from_previous_minutes 表示该记录距离上一条记录的分钟数。",
            "- same_day_sequence 表示该记录是当天第几次称重。",
            "- 如果相邻记录间隔较短，尤其是同一天多次称重，请将其视为短时波动参考，不要直接当作长期趋势。",
            "- 趋势判断应优先结合 payload.history.statistics 和 payload.history.weekly_series。",
            "",
            "请优先参考 payload.current 和 payload.history 中的结构化数据。",
            "不要输出原始 JSON，除非需要排查异常。",
        ]
    )
    return "\n".join(lines)


def build_profile_payload(profile: ProfileConfig) -> dict[str, object]:
    return {key: value for key, value in asdict(profile).items() if value is not None}


def calculate_bmi(weight_kg: float, height_cm: float | None) -> float | None:
    if height_cm is None or height_cm <= 0:
        return None
    height_m = height_cm / 100
    return weight_kg / (height_m * height_m)


def _gender_label(gender: str) -> str:
    normalized = gender.strip().lower()
    if normalized in {"male", "m"}:
        return "男"
    if normalized in {"female", "f"}:
        return "女"
    return gender
