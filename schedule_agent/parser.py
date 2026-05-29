# 用户输入解析
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from .ics_utils import _add_days
FIELD_NAMES = {
    "标题": "title",
    "开始日期": "start_date",
    "开始时间": "start_time",
    "结束日期": "end_date",
    "结束时间": "end_time",
    "时间": "time",
    "地点": "location_name",
    "地址": "address",
    "描述": "description",
    "全天": "is_all_day",
    "title": "title",
    "start_date": "start_date",
    "start_time": "start_time",
    "end_date": "end_date",
    "end_time": "end_time",
    "time": "time",
    "location_name": "location_name",
    "address": "address",
    "description": "description",
    "is_all_day": "is_all_day",
}

_CORE = {"title", "start_date", "start_time", "end_date", "end_time", "time",
         "location_name", "address", "description", "is_all_day"}

def _resolve_date(text: str) -> str | None:
    """解析中文相对日期或绝对日期表达式，返回 YYYY-MM-DD 格式"""
    now = datetime.now()
    today = now.date()
    weekday = today.weekday()  # 0=Mon

    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3,
                   "五": 4, "六": 5, "日": 6, "天": 6}

    s = text.strip()
    if not s:
        return None

    # 纯相对日期
    if s == "今天":
        return today.isoformat()
    if s == "明天":
        return (today + timedelta(days=1)).isoformat()
    if s == "后天":
        return (today + timedelta(days=2)).isoformat()
    if s == "昨天":
        return (today - timedelta(days=1)).isoformat()

    # 本周X
    m = re.match(r'^本周([一二三四五六日天])$', s)
    if m:
        target = weekday_map[m.group(1)]
        return (today + timedelta(days=target - weekday)).isoformat()

    # 下周X
    m = re.match(r'^下周([一二三四五六日天])$', s)
    if m:
        target = weekday_map[m.group(1)]
        return (today + timedelta(days=target - weekday + 7)).isoformat()

    # 上周X
    m = re.match(r'^上周([一二三四五六日天])$', s)
    if m:
        target = weekday_map[m.group(1)]
        return (today + timedelta(days=target - weekday - 7)).isoformat()

    # YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s

    # MM-DD（无年份，使用当前年份）
    m = re.match(r'^(\d{1,2})-(\d{1,2})$', s)
    if m:
        return f"{now.year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"

    # X月X日
    m = re.match(r'^(\d{1,2})月(\d{1,2})日$', s)
    if m:
        return f"{now.year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"

    return None

def _parse_time(time_str: str) -> dict:
    """解析时间字符串，返回 {start_date, start_time, end_date, end_time, is_all_day}

    支持格式：
      - YYYY-MM-DD HH:MM - HH:MM              同一天
      - YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM    跨天
      - YYYY-MM-DD                             全天
      - MM-DD HH:MM - HH:MM                    无年份
      - 5月29日 HH:MM - HH:MM                  中文日期
      - 今天 / 明天 / 本周五 HH:MM - HH:MM      相对日期
      - 22:00 - 02:00                          自动跨天（结束<开始）
    """
    now = datetime.now()
    result = {"start_date": "", "start_time": "",
              "end_date": "", "end_time": "",
              "is_all_day": False}

    s = time_str.strip()

    m = re.match(
        r'(\d{4})-(\d{2})-(\d{2})\s+'
        r'(\d{2}):(\d{2})\s*[-~]\s*'
        r'(\d{2}):(\d{2})\s*$', s
    )
    if m:
        y, mo, d, h1, m1, h2, m2 = m.groups()
        result["start_date"] = f"{y}-{mo}-{d}"
        result["start_time"] = f"{h1}:{m1}"
        result["end_date"] = f"{y}-{mo}-{d}"
        result["end_time"] = f"{h2}:{m2}"
        # 结束时间 ≤ 开始时间 → 自动跨天（如 22:00-02:00）
        if int(h2) < int(h1) or (int(h2) == int(h1) and int(m2) <= int(m1)):
            dt = datetime.strptime(result["end_date"], "%Y-%m-%d") + timedelta(days=1)
            result["end_date"] = dt.strftime("%Y-%m-%d")
        return result

    m = re.match(
        r'(\d{4})-(\d{2})-(\d{2})\s+'
        r'(\d{2}):(\d{2})\s*[-~]\s*'
        r'(\d{4})-(\d{2})-(\d{2})\s+'
        r'(\d{2}):(\d{2})\s*$', s
    )
    if m:
        y1, mo1, d1, h1, m1, y2, mo2, d2, h2, m2 = m.groups()
        result["start_date"] = f"{y1}-{mo1}-{d1}"
        result["start_time"] = f"{h1}:{m1}"
        result["end_date"] = f"{y2}-{mo2}-{d2}"
        result["end_time"] = f"{h2}:{m2}"
        return result

    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s*$', s)
    if m:
        result["start_date"] = s.strip()
        result["is_all_day"] = True
        return result

    m = re.match(
        r'(\d{1,2})-(\d{1,2})\s+'
        r'(\d{2}):(\d{2})\s*[-~]\s*'
        r'(\d{2}):(\d{2})\s*$', s
    )
    if m:
        mo, d, h1, m1, h2, m2 = m.groups()
        result["start_date"] = f"{now.year}-{mo.zfill(2)}-{d.zfill(2)}"
        result["start_time"] = f"{h1}:{m1}"
        result["end_date"] = f"{now.year}-{mo.zfill(2)}-{d.zfill(2)}"
        result["end_time"] = f"{h2}:{m2}"
        if int(h2) < int(h1) or (int(h2) == int(h1) and int(m2) <= int(m1)):
            dt = datetime.strptime(result["end_date"], "%Y-%m-%d") + timedelta(days=1)
            result["end_date"] = dt.strftime("%Y-%m-%d")
        return result

    m = re.match(
        r'(\d{1,2})月(\d{1,2})日\s+'
        r'(\d{2}):(\d{2})\s*[-~]\s*'
        r'(\d{2}):(\d{2})\s*$', s
    )
    if m:
        mo, d, h1, m1, h2, m2 = m.groups()
        result["start_date"] = f"{now.year}-{mo.zfill(2)}-{d.zfill(2)}"
        result["start_time"] = f"{h1}:{m1}"
        result["end_date"] = f"{now.year}-{mo.zfill(2)}-{d.zfill(2)}"
        result["end_time"] = f"{h2}:{m2}"
        if int(h2) < int(h1) or (int(h2) == int(h1) and int(m2) <= int(m1)):
            dt = datetime.strptime(result["end_date"], "%Y-%m-%d") + timedelta(days=1)
            result["end_date"] = dt.strftime("%Y-%m-%d")
        return result

    # 今天 HH:MM - HH:MM, 明天 HH:MM - HH:MM, 本周五 HH:MM - HH:MM 等
    m = re.match(
        r'(.+?)\s+(\d{2}):(\d{2})\s*[-~]\s*(\d{2}):(\d{2})\s*$', s
    )
    if m:
        date_part, h1, m1, h2, m2 = m.groups()
        resolved = _resolve_date(date_part.strip())
        if resolved:
            result["start_date"] = resolved
            result["start_time"] = f"{h1}:{m1}"
            result["end_date"] = resolved
            result["end_time"] = f"{h2}:{m2}"
            if int(h2) < int(h1) or (int(h2) == int(h1) and int(m2) <= int(m1)):
                dt = datetime.strptime(result["end_date"], "%Y-%m-%d") + timedelta(days=1)
                result["end_date"] = dt.strftime("%Y-%m-%d")
            return result

    resolved = _resolve_date(s)
    if resolved:
        result["start_date"] = resolved
        result["is_all_day"] = True
        return result

    raise ValueError(f"无法解析时间格式: {time_str}")

def _parse_json_input(data: dict) -> dict:
    """将 JSON 格式的日程数据转为内部格式"""
    return {
        "title": data.get("title", ""),
        "start_date": data.get("start_date", ""),
        "start_time": data.get("start_time", ""),
        "end_date": data.get("end_date", ""),
        "end_time": data.get("end_time", ""),
        "is_all_day": data.get("is_all_day", False),
        "location_name": data.get("location_name", ""),
        "description": data.get("description", ""),
        "_raw_venue": data.get("location_name", ""),
        "_raw_address": data.get("_raw_address", ""),
    }

def parse_input(text: str) -> dict:
    """将结构化日程文本或 JSON 解析为标准化的输出格式

    输入格式（字段间换行分隔，字段名与 JSON 一致，中英文标签均可）：

        标题：<事件标题>               → title
        开始日期：<YYYY-MM-DD>          → start_date
        开始时间：<HH:MM>              → start_time
        结束日期：<YYYY-MM-DD>          → end_date
        结束时间：<HH:MM>              → end_time
        时间：<便捷表达式>              → _parse_time()
        地点：<地点名称>               → location_name
        地址：<详细地址>               → address
        描述：<自由文本>               → description
        全天：<true/false>             → is_all_day

    也支持 JSON 格式（与输出格式一致）：
        {"title": "...", "start_date": "...", ...}

    若 JSON 为数组，取第一个元素。

    Returns:
        {
            "title": str,
            "start_date": "YYYY-MM-DD",
            "start_time": "HH:MM",
            "end_date": "YYYY-MM-DD",
            "end_time": "HH:MM",
            "is_all_day": bool,
            "location_name": str,
            "description": str,
            "_raw_venue": str,
            "_raw_address": str,
        }
    """
    trimmed = text.strip()

    if trimmed.startswith("{") or trimmed.startswith("["):
        try:
            data = json.loads(trimmed)
            if isinstance(data, list):
                data = data[0] if data else {}
            return _parse_json_input(data)
        except (json.JSONDecodeError, IndexError, KeyError):
            pass  # 非合法 JSON，走文本解析

    fields = {}
    lines = trimmed.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        m = re.match(r'^([^：:]+)[：:]\s*(.*)$', line)
        if m:
            raw_key = m.group(1).strip()
            raw_val = m.group(2).strip()
            std_key = FIELD_NAMES.get(raw_key)
            if std_key is None:
                continue
            if std_key == "description":
                # 描述支持多行：持续读取直到碰到下一个已识别标签
                desc_lines = [raw_val] if raw_val else []
                while i < len(lines):
                    next_line = lines[i].strip()
                    nm = re.match(r'^([^：:]+)[：:]\s*(.*)$', next_line) if next_line else None
                    if nm and FIELD_NAMES.get(nm.group(1).strip()):
                        break
                    desc_lines.append(next_line)
                    i += 1
                fields["description"] = "\n".join(desc_lines)
                continue
            fields[std_key] = raw_val

    # 2. 标题
    title = fields.get("title", "")

    # 3. 时间
    raw_time = fields.get("time", "")
    if raw_time:
        time_result = _parse_time(raw_time)
    else:
        time_result = {
            "start_date": fields.get("start_date", ""),
            "start_time": fields.get("start_time", ""),
            "end_date": fields.get("end_date", ""),
            "end_time": fields.get("end_time", ""),
            "is_all_day": fields.get("is_all_day", False),
        }

    # 4. 地点
    location_name = fields.get("location_name", "")

    # 5. 描述
    description = fields.get("description", "")

    return {
        "title": title,
        "start_date": time_result["start_date"],
        "start_time": time_result["start_time"],
        "end_date": time_result["end_date"],
        "end_time": time_result["end_time"],
        "is_all_day": time_result["is_all_day"],
        "location_name": location_name,
        "description": description,
        # 内部字段（供下游 build_event 使用）
        "_raw_venue": location_name,
        "_raw_address": fields.get("address", ""),
    }

def parse_input_batch(text: str) -> list[dict]:
    """解析输入，返回事件列表（支持单条、JSON 数组、多段文本）

    多段文本用 --- 或连续空行分隔。
    """
    trimmed = text.strip()

    # JSON 数组
    if trimmed.startswith("["):
        try:
            data = json.loads(trimmed)
            if isinstance(data, list):
                return [_parse_json_input(item) for item in data]
        except json.JSONDecodeError:
            pass

    # JSON 单对象
    if trimmed.startswith("{"):
        try:
            data = json.loads(trimmed)
            return [_parse_json_input(data)]
        except json.JSONDecodeError:
            pass

    # 文本：按 --- 或连续空行分隔为多个事件
    blocks = re.split(r"\n\s*-{3,}\s*\n|\n\s*\n", trimmed)
    results = []
    for block in blocks:
        block = block.strip()
        if block:
            results.append(parse_input(block))
    return results

def _normalize_title(title: str) -> str:
    """统一标题用于去重比较（羽毛球活动 → 羽毛球）"""
    badminton_kw = ["羽毛球", "羽球", "打球", "badminton", "Badminton"]
    if any(kw in title for kw in badminton_kw):
        return "羽毛球"
    return title
