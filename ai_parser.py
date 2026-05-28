#!/usr/bin/env python3
"""
AI-powered schedule parser.

Uses OpenAI-compatible vision API to extract structured JSON from
images (screenshots of events, posters, etc.) or free-form text.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime


# ── Prompt template ──────────────────────────────────────────────────────────
# {current_time} is replaced at runtime with the current date/time.

_PROMPT_TEMPLATE = """# 角色与任务

你是一个极其严格、具备高泛化能力的通用日程事件解析器。请接收图片 OCR 结果或任意结构化的日程文本输入，将其解析为标准化的 JSON 输出，供下游程序自动生成标准日历 .ics 文件。



# 核心约束

1. 必须且只能输出一个合法的 JSON 字符串。

2. 严禁包含任何解释性文字、前后缀，严禁将 JSON 包裹在 ```json ... ``` 等 Markdown 代码块中。



# 上下文基准（用于推算相对时间和缺失的年份）

- 当前系统时间：{current_time}



# 输出 JSON 格式

[{

  "title": "字符串，事件主体/标题名称。如果原始文本没有明确标题，请根据内容提炼一个简短、概括性的标题，绝不留空",

  "start_date": "YYYY-MM-DD 格式。若输入无显式年份，则默认使用 `# 上下文基准` 中的年份",

  "start_time": "HH:MM 格式，24小时制。若是全天活动，设为空字符串 \"\"",

  "end_date": "YYYY-MM-DD 格式。跨天事件需根据时间差自动计算并调整日期",

  "end_time": "HH:MM 格式，24小时制。若是全天活动，设为空字符串 \"\"",

  "is_all_day": 布尔值,

  "location_name": "字符串，事件发生具体的地点、场馆、房间或会议室名称。如果没有明确地点，设为空字符串 \"\"",

  "description": "字符串，将文本中所有不属于时间、地点的非核心关键信息（如备注、费用、参与人、座位号、组织者等），按 '原文字段名：具体值' 的格式用 \\\\n 拼接输出。若无任何附加信息，设为 \"\""

}]



# 解析与推算规则



## 1. 时间解析规则（核心）

- **格式化规范**：日期必须严格为 "YYYY-MM-DD"，时间必须严格为 "HH:MM"。

- **相对时间推算**：依据 `# 上下文基准` 提供的当前时间，准确推算诸如"今天"、"明天"、"本周五"、"下周三"的具体公历日期。

- **全天活动判定**：若输入只有日期，完全没有提及任何具体整点时间（例如："6月1日儿童节"、"本周五团建"），则判定 `is_all_day = true`，且 `start_time` 和 `end_time` 填充为 `""`。

- **自动跨天处理**：若结束时间在数值上小于开始时间（例如：22:00 - 02:00），默认视为跨越到次日，`end_date` 必须在 `start_date` 的基础上自动加 1 天。



## 2. 地点提取规则

- 准确提取文本中代表空间位置的文本（如"1号会议室"、"百丽宫影城5号厅"、"奥埔篮羽运动中心"）。

- **不要**在提示词中硬编码任何特定场馆。保持对原始地点的无损提取。



## 3. 描述生成规则

- 提炼所有零散的附加信息。例如输入中含有"票价：50元，座位：3排2座"，需转换为 `"description": "票价：50元\\n座位：3排2座"`。



## 4. 上下文规则

- 不考虑上下文，我会一次性把所有图片发给你，历史对话对你来说没有意义



## 5. 去重

- 给到的图片可能包含重复的日程，自动去除



## 6. 特殊状态

- 如果提到已退款，则应该忽略跳过，不要输出这部分"""


def _get_client():
    """Create OpenAI client from environment variables."""
    try:
        from openai import OpenAI
    except ImportError:
        print("❌ 缺少 openai 依赖，请运行: pip install openai")
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ 请设置环境变量 OPENAI_API_KEY")
        print("   export OPENAI_API_KEY=sk-...")
        sys.exit(1)

    base_url = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs)


def _encode_image(image_path: str) -> str:
    """Encode image file as base64 data URL string."""
    with open(image_path, "rb") as f:
        raw = f.read()

    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime = mime_map.get(ext, "image/png")

    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _build_prompt() -> str:
    """Build the prompt with current date/time substituted."""
    now = datetime.now()
    weekdays_cn = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday = weekdays_cn[now.weekday()]
    current_time = now.strftime(f"%Y-%m-%d {weekday}")
    return _PROMPT_TEMPLATE.replace("{current_time}", current_time)


def _extract_json(text: str) -> str:
    """Try to extract JSON array from AI response, stripping markdown fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def parse_with_ai(
    image_paths: list[str] | None = None,
    text: str | None = None,
) -> list[dict]:
    """Send images and/or text to AI and parse schedule events."""
    if not image_paths and not text:
        raise ValueError("至少需要提供图片路径或文本内容")

    client = _get_client()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    prompt = _build_prompt()

    content: list[dict] = []

    if image_paths:
        for p in image_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"图片文件不存在: {p}")
            data_url = _encode_image(p)
            content.append({
                "type": "image_url",
                "image_url": {"url": data_url, "detail": "high"},
            })

    if text:
        prompt = f"{prompt}\n\n以下是用户提供的日程文本：\n\n{text}"

    content.insert(0, {"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content or ""
    json_str = _extract_json(raw)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"⚠️  AI 返回的不是合法 JSON，原始响应：\n{raw[:500]}")
        raise ValueError(f"AI 返回非法 JSON: {e}") from e

    if isinstance(result, dict):
        result = [result]

    if not isinstance(result, list):
        raise ValueError(f"AI 返回格式异常（期望 JSON 数组）: {type(result)}")

    for ev in result:
        ev.setdefault("is_all_day", False)
        ev.setdefault("description", "")
        ev.setdefault("location_name", "")
        if "location_name" in ev and ev["location_name"]:
            ev["_raw_venue"] = ev["location_name"]

    return result
