#!/usr/bin/env python3
"""
日程文本 → .ics 生成 + 自动插入 Mac 日历（含去重、自动发现新地点）

输入格式（字段间换行分隔，字段名与 JSON 一致，中英文标签均可）：

    标题：羽毛球活动                → title
    开始日期：2026-05-31            → start_date
    开始时间：19:00                 → start_time
    结束日期：2026-05-31            → end_date
    结束时间：21:00                 → end_time
    地点：上海奥埔篮羽运动中心       → location_name
    地址：曹路镇镇北路2-1           → address
    描述：费用￥34                  → description
    全天：false                     → is_all_day

    时间：2026-05-31 19:00-21:00   → 便捷写法(_parse_time)

中英文标签均可（title / start_date / location_name …）。

_parse_time 便捷格式：
    2026-05-31 19:00 - 21:00      同一天
    YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM  跨天
    YYYY-MM-DD                     全天活动

   用法：
    cat schedule.txt | python3 schedule_agent.py
    python3 schedule_agent.py "标题：..."
    python3 schedule_agent.py -i         交互式问答模式
"""

from __future__ import annotations

import json
import ai_parser
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta

# ── 加载项目根目录下的 .env ──
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_PROJECT_DIR, ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                if _key not in os.environ:
                    os.environ[_key] = _val.strip().strip("\"'")

# ====================================================================
# 配置 —— 改这里
# ====================================================================

CALENDAR_NAME = "个人日程"                                    # 目标日历名称
CONFIRM_BEFORE_IMPORT = True                                  # True=弹窗确认, False=静默导入
ICS_OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "schedule.ics"
)                                              # .ics 输出路径（项目目录，每次覆盖）
BADMINTON_ICS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "badminton.ics"
)                                              # 羽毛球公共订阅 .ics（累积更新）
CALENDAR_URL = os.environ.get("CALENDAR_URL", "")              # 从环境变量读取，不在源码中暴露
LOCATIONS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locations.json")
LOCATIONS_EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locations.example.json")

# ====================================================================
# 地点配置（JSON）加载与保存
# ====================================================================


def load_locations() -> dict:
    """加载 locations.json，返回 {locations: [...], badminton_keywords: [...], ...}"""
    default = {
        "badminton_keywords": ["羽毛球", "羽球", "打球", "badminton", "Badminton"],
        "last_updated": None,
        "locations": [],
    }
    if not os.path.exists(LOCATIONS_JSON):
        if os.path.exists(LOCATIONS_EXAMPLE):
            import shutil
            shutil.copyfile(LOCATIONS_EXAMPLE, LOCATIONS_JSON)
            print(f"📋 已从 {os.path.basename(LOCATIONS_EXAMPLE)} 初始化地点配置，请替换为你的真实数据")
        else:
            return default
    try:
        with open(LOCATIONS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_locations(data: dict):
    """保存 locations.json"""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(LOCATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def match_location(venue: str, address: str, locations: list[dict]) -> dict | None:
    """根据输入的地点/地址匹配地点列表

    Args:
        venue: 输入的地点字段
        address: 输入的地址字段
        locations: 地点列表（从 JSON 加载）

    Returns:
        匹配的 location dict，或 None
    """
    combined = (venue + " " + (address or "")).lower()

    for loc in locations:
        for kw in loc.get("keywords", []):
            if kw.lower() in combined:
                return loc

    return None


# ====================================================================
# .ics 网络获取 & 解析
# ====================================================================


def fetch_ics(url: str) -> str:
    """从 URL 获取 .ics 内容（支持 webcal:// 和 https://）"""
    http_url = url.replace("webcal://", "https://")
    req = urllib.request.Request(http_url, headers={
        "User-Agent": "Schedule-Agent/1.0",
        "Accept": "text/calendar",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        # 尝试用 utf-8 解码，失败则用 latin-1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


def unfold_ics(text: str) -> str:
    """将 .ics 的 continuation lines（行首空格/制表符）合拼回去"""
    lines = text.replace("\r\n", "\n").split("\n")
    result = []
    for line in lines:
        if line and (line[0] == " " or line[0] == "\t"):
            if result:
                result[-1] += line[1:]  # 去掉行首一个空格/制表符
        else:
            result.append(line)
    return "\n".join(result)


def split_vevents(ics_text: str) -> list[str]:
    """将 .ics 按 VEVENT 拆分为独立块"""
    unfolded = unfold_ics(ics_text)
    blocks = []
    current = []
    in_event = False
    for line in unfolded.split("\n"):
        line = line.rstrip("\r")
        if line == "BEGIN:VEVENT":
            in_event = True
            current = [line]
        elif line == "END:VEVENT":
            current.append(line)
            blocks.append("\n".join(current))
            current = []
            in_event = False
        elif in_event:
            current.append(line)
    return blocks


def _get_prop(block: str, prop_name: str) -> str | None:
    """从 VEVENT 块中提取属性的值（含参数部分一起返回原始行）"""
    # 匹配行首为属性名，可选后跟 ;param=val...: 然后是值
    for line in block.split("\n"):
        stripped = line.strip()
        if stripped.startswith(prop_name + ":") or re.match(rf"^{re.escape(prop_name)};", stripped):
            return stripped
    return None


def _prop_value(line: str) -> str:
    """从完整属性行中提取冒号后的值"""
    idx = line.index(":")
    return line[idx + 1:]


def parse_ics_events(vevent_blocks: list[str]) -> list[dict]:
    """解析 VEVENT 块列表，提取用于去重和地点发现的字段"""
    events = []
    for block in vevent_blocks:
        event = {"summary": "", "date": "", "location": "", "structured_loc": ""}

        summary_line = _get_prop(block, "SUMMARY")
        if summary_line:
            event["summary"] = _prop_value(summary_line)

        dtstart_line = _get_prop(block, "DTSTART")
        if dtstart_line:
            val = _prop_value(dtstart_line)
            # 提取日期部分：YYYYMMDD 或 YYYYMMDDTHHMMSS
            m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
            if m:
                event["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        loc_line = _get_prop(block, "LOCATION")
        if loc_line:
            event["location"] = _prop_value(loc_line)

        structured = _get_prop(block, "X-APPLE-STRUCTURED-LOCATION")
        if structured:
            event["structured_loc"] = structured

        events.append(event)
    return events


# ====================================================================
# 自动发现新地点
# ====================================================================


def _generate_keywords(name: str, address: str) -> list[str]:
    """从地点名称和地址自动生成匹配关键词"""
    keywords = []
    seen = set()

    def add(word: str):
        w = word.strip().strip('"').strip("'")
        if w and len(w) >= 2 and w not in seen:
            seen.add(w)
            keywords.append(w)

    # 全名
    add(name)

    # 按常见分隔符拆分
    for sep in [" ", "·", "（", "(", "）", ")", "\\n", "-", "—", "|"]:
        for part in name.split(sep):
            add(part)

    # 从地址中提取关键部分
    if address:
        # 取前几个字符和后几个字符做关键词
        add(address)
        # 地址中的数字编号
        nums = re.findall(r"\d+[\w-]*号?", address)
        for n in nums:
            add(n)

    return keywords


def extract_new_locations(events: list[dict], existing: list[dict]) -> list[dict]:
    """从解析的事件中提取新增地点（含结构化数据）"""
    # 构建已有地点的 MapKit Handle + 名称 + 坐标索引
    existing_handles: set[str] = set()
    existing_names: set[str] = set()
    existing_coords: set[tuple[float, float]] = set()
    for loc in existing:
        sl = loc.get("structured_loc") or ""
        m = re.search(r"X-APPLE-MAPKIT-HANDLE=([^;]+)", sl)
        if m:
            existing_handles.add(m.group(1))
        existing_names.add(loc.get("name", "").strip().lower())
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        if lat is not None and lng is not None:
            existing_coords.add((round(lat, 4), round(lng, 4)))

    # 从事件中提取新地点
    seen_handles: set[str] = set()
    seen_names_in_batch: set[str] = set()
    seen_coords_in_batch: set[tuple[float, float]] = set()
    new_locations = []

    for ev in events:
        sl = ev.get("structured_loc")
        if not sl:
            continue

        # 用 MapKit Handle 做唯一指纹
        m = re.search(r"X-APPLE-MAPKIT-HANDLE=([^;]+)", sl)
        handle = m.group(1) if m else ""

        if handle and handle in existing_handles:
            continue
        if handle and handle in seen_handles:
            continue
        seen_handles.add(handle)

        # 提取名称和地址
        loc_raw = ev.get("location", "")
        name, address = _parse_structured_location_details(sl, loc_raw)
        loc_name = name or (loc_raw.split("\\n")[0] if loc_raw else "")
        if not loc_name:
            continue
        name_key = loc_name.strip().lower()

        # 从 geo 提取经纬度
        lat, lng = None, None
        geo_m = re.search(r":geo:([\d.]+),([\d.]+)", sl)
        if geo_m:
            lat = float(geo_m.group(1))
            lng = float(geo_m.group(2))

        # 按名称去重（用于无 MapKit Handle 的地点）
        if name_key in existing_names or name_key in seen_names_in_batch:
            continue
        seen_names_in_batch.add(name_key)

        # 按坐标去重（近似匹配）
        if lat is not None and lng is not None:
            coord_key = (round(lat, 4), round(lng, 4))
            if coord_key in existing_coords or coord_key in seen_coords_in_batch:
                continue
            seen_coords_in_batch.add(coord_key)

        # 提取 radius
        radius = None
        rad_m = re.search(r"X-APPLE-RADIUS=([\d.]+)", sl)
        if rad_m:
            radius = float(rad_m.group(1))

        keywords = _generate_keywords(loc_name, address)

        new_locations.append({
            "id": f"auto_{len(existing) + len(new_locations) + 1}",
            "name": loc_name,
            "address": address or "",
            "keywords": keywords,
            "loc_line": loc_raw,
            "latitude": lat,
            "longitude": lng,
            "radius": radius,
            "structured_loc": sl,
            "source": "auto_discovered",
        })

    return new_locations


def _parse_structured_location_details(structured_line: str, loc_fallback: str):
    """从 X-APPLE-STRUCTURED-LOCATION 提取 name 和 address"""
    name = ""
    address = ""

    # 提取 X-TITLE
    m = re.search(r'X-TITLE=([^:]+?)(?::geo:|$)', structured_line)
    if m:
        raw = m.group(1)
        # 去掉可能的引号
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        # X-TITLE 中可能有 \n 分隔 name 和 address
        parts = raw.split("\\n")
        name = parts[0].strip()
        if len(parts) > 1:
            address = parts[1].strip()

    # 提取 X-ADDRESS
    m = re.search(r'X-ADDRESS="([^"]*)"', structured_line)
    if m and not address:
        address = m.group(1).strip()

    # fallback: 从 LOCATION 解析
    if not name and loc_fallback:
        parts = loc_fallback.split("\\n")
        name = parts[0].strip()
        if len(parts) > 1 and not address:
            address = parts[1].strip()

    return name, address


def update_locations_from_ics(ics_text: str, json_path: str) -> int:
    """从 .ics 中发现新地点并写入 JSON"""
    data = load_locations()
    events = parse_ics_events(split_vevents(ics_text))
    new_locs = extract_new_locations(events, data.get("locations", []))

    if new_locs:
        data["locations"].extend(new_locs)
        save_locations(data)
        return len(new_locs)
    return 0


# ====================================================================
# 文本解析器 —— 通用日程文本 → 标准化 JSON
# ====================================================================

# 文本标签 → JSON 字段名（1:1 对齐）
FIELD_NAMES = {
    # ── 中文 → JSON ──
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
    # ── 英文直通（与 JSON key 相同）──
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

    # ─── 格式1: YYYY-MM-DD HH:MM - HH:MM（同一天） ───
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

    # ─── 格式2: YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM（显式跨天） ───
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

    # ─── 格式3: YYYY-MM-DD（全天） ───
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s*$', s)
    if m:
        result["start_date"] = s.strip()
        result["is_all_day"] = True
        return result

    # ─── 格式4: MM-DD HH:MM - HH:MM（无年份，默认今年） ───
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

    # ─── 格式5: X月X日 HH:MM - HH:MM（中文日期格式） ───
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

    # ─── 格式6: 相对日期 + 时间 ───
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

    # ─── 格式7: 纯相对日期（全天） ───
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

    # ─── JSON 输入检测 ───
    if trimmed.startswith("{") or trimmed.startswith("["):
        try:
            data = json.loads(trimmed)
            if isinstance(data, list):
                data = data[0] if data else {}
            return _parse_json_input(data)
        except (json.JSONDecodeError, IndexError, KeyError):
            pass  # 非合法 JSON，走文本解析

    # ─── 文本标号字段解析 ───
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


def build_event(raw: dict, locations: list[dict]) -> dict:
    """加工解析结果为最终事件数据（含地点匹配）

    Args:
        raw: parse_input() 返回的原始解析结果
        locations: 地点配置列表

    Returns:
        含 location_matched 等扩展字段的事件 dict
    """
    title = _normalize_title(raw["title"])

    # --- 地点识别 ---
    matched = match_location(
        raw.get("_raw_venue", ""),
        raw.get("_raw_address", ""),
        locations,
    )
    if matched:
        loc_name = matched["name"]
        loc_address = matched["address"]
        needs_structured = matched.get("structured_loc") is not None
    else:
        loc_name = raw["location_name"]
        loc_address = raw.get("_raw_address", "")
        needs_structured = False

    return {
        "title": title,
        "_raw_title": raw["title"],
        "start_date": raw["start_date"],
        "start_time": raw["start_time"],
        "end_date": raw["end_date"],
        "end_time": raw["end_time"],
        "is_all_day": raw["is_all_day"],
        "location_name": loc_name,
        "location_address": loc_address,
        "location_matched": matched,
        "needs_structured_location": needs_structured,
        "description": raw["description"],
    }


# ====================================================================
# .ics 生成
# ====================================================================


def _get_loc_line(event: dict) -> str | None:
    """获取 LOCATION 行（用于 .ics）"""
    loc = event.get("location_matched")
    if loc and loc.get("loc_line"):
        return loc["loc_line"]
    parts = [event["location_name"]]
    if event["location_address"]:
        parts.append(event["location_address"])
    return "\\n".join(parts)


def _get_structured_loc(event: dict) -> str | None:
    """获取 X-APPLE-STRUCTURED-LOCATION 行"""
    loc = event.get("location_matched")
    if loc and loc.get("structured_loc"):
        return loc["structured_loc"]
    return None


def _generate_vevent(event: dict) -> list[str]:
    """生成单个 VEVENT 的行列表（不含外层 VCALENDAR 包裹）"""
    # 时间
    if event["is_all_day"]:
        sd = event["start_date"].replace("-", "")
        ed = _add_days(event["start_date"], 1).replace("-", "")
        lines_dt = [
            f"DTSTART;VALUE=DATE:{sd}",
            f"DTEND;VALUE=DATE:{ed}",
        ]
    else:
        st = f"{event['start_date'].replace('-', '')}T{event['start_time'].replace(':', '')}00"
        et = f"{event['end_date'].replace('-', '')}T{event['end_time'].replace(':', '')}00"
        lines_dt = [
            f"DTSTART;TZID=Asia/Shanghai:{st}",
            f"DTEND;TZID=Asia/Shanghai:{et}",
        ]

    uid = str(uuid.uuid4()).upper()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VEVENT",
        *lines_dt,
        f"SUMMARY:{event['title']}",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
    ]

    # 地点
    loc_line = _get_loc_line(event)
    if loc_line:
        lines.append(f"LOCATION:{loc_line}")

    structured = _get_structured_loc(event)
    if structured:
        lines.append(structured)
    elif not loc_line and event["location_name"]:
        loc = event["location_name"]
        if event["location_address"]:
            loc += "\\n" + event["location_address"]
        lines.append(f"LOCATION:{loc}")

    # 描述
    if event.get("description"):
        desc_escaped = event["description"].replace(chr(10), "\\n")
        lines.append(f"DESCRIPTION:{desc_escaped}")

    lines.append("END:VEVENT")
    return lines


def generate_ics(event: dict) -> str:
    """生成单个事件的 .ics 内容"""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Schedule Agent//Pure Python//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    lines.extend(_generate_vevent(event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def generate_combined_ics(events: list[dict]) -> str:
    """生成包含多个事件的合并 .ics（只弹一次对话框）"""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Schedule Agent//Pure Python//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        lines.extend(_generate_vevent(event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def sync_badminton_ics(calendar_url: str, badminton_kw: list[str],
                       output_path: str) -> int:
    """从 iCloud 日历拉取全部事件，筛选羽毛球相关，生成累积 .ics

    Returns:
        写入的羽毛球事件数量
    """
    raw_ics = fetch_ics(calendar_url)
    vevent_blocks = split_vevents(raw_ics)

    matched_blocks = []
    for block in vevent_blocks:
        summary_line = _get_prop(block, "SUMMARY")
        if not summary_line:
            continue
        summary = _prop_value(summary_line)
        if any(kw.lower() in summary.lower() for kw in badminton_kw):
            matched_blocks.append(block)

    if not matched_blocks:
        print("  → 未找到羽毛球相关事件")
        # 仍然生成空 VCALENDAR，确保 CI 中 git add 不会失败
        matched_blocks = []  # 后续循环会写入只有头的空日历

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Schedule Agent//Badminton Subscription//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:羽毛球活动",
        "X-WR-CALDESC:羽毛球活动订阅日历",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        f"X-PUBLISHED-TTL:PT12H",
    ]
    for block in matched_blocks:
        lines.append(block)
    lines.append("END:VCALENDAR")

    ics_content = "\r\n".join(lines) + "\r\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ics_content)
    print(f"  → 已更新 {output_path}（{len(matched_blocks)} 个羽毛球事件）")
    return len(matched_blocks)


def _add_days(date_str: str, n: int) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=n)).strftime("%Y-%m-%d")
def check_duplicate_via_ics(events: list[dict], target: dict) -> bool:
    """通过已解析的 .ics 事件列表检查重复（标题归一化后比较）"""
    target_date = target["start_date"]
    target_norm = _normalize_title(target["title"])
    for ev in events:
        if ev["date"] == target_date and _normalize_title(ev["summary"]) == target_norm:
            return True
    return False


def dedup_events_internal(events: list[dict]) -> list[dict]:
    """去除输入事件列表内部的重复项（同一天 + 同标题归一化）"""
    seen: set[tuple[str, str]] = set()
    result = []
    for event in events:
        key = (event["start_date"], _normalize_title(event["title"]))
        if key in seen:
            print(f"  ⏭️ 输入内有重复: 「{event['title']}」{event['start_date']}，跳过")
            continue
        seen.add(key)
        result.append(event)
    return result


def import_to_calendar(ics_path: str):
    """导入日历（使用项目目录下的 .ics 文件）"""
    if CONFIRM_BEFORE_IMPORT:
        subprocess.run(["open", "-a", "Calendar", ics_path])
        print(f"⏳ 已打开日历导入对话框，请手动确认导入到「{CALENDAR_NAME}」")
    else:
        script = f'''
        tell application "Calendar"
            activate
            import "{ics_path}"
        end tell
        '''
        subprocess.run(["osascript", "-e", script])
        print(f"✅ 已自动导入到「{CALENDAR_NAME}」")


def save_ics_file(ics_content: str, ics_path: str | None = None) -> str | None:
    """保存 .ics 到项目目录（每次覆盖同一文件）"""
    path = ics_path or ICS_OUTPUT_FILE
    with open(path, "w", encoding="utf-8") as f:
        f.write(ics_content)
    return path


def print_preview(event: dict):
    print()
    print("=" * 50)
    print(f"  事件: {event['title']}")
    if event["is_all_day"]:
        print(f"  时间: {event['start_date']}（全天）")
    else:
        print(f"  时间: {event['start_date']} {event['start_time']}"
              f"  ~  {event['end_date']} {event['end_time']}")
    if event["location_name"]:
        print(f"  地点: {event['location_name']}")
        if event["location_address"]:
            print(f"  地址: {event['location_address']}")
    if event.get("description"):
        desc_short = event["description"][:80]
        if len(event["description"]) > 80:
            desc_short += "..."
        print(f"  备注: {desc_short}")
    print("=" * 50)
    print()


# ====================================================================
# 主流程
# ====================================================================


def ai_mode():
    """AI-powered interactive mode: parse images or free-form text via AI.

    Accepts image file paths or pasted text. Events accumulate across
    rounds; type 'd' to finish and generate .ics.
    """
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        print("❌ 缺少 openai 依赖，请运行: pip install openai")
        sys.exit(1)

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    print()
    print("=" * 56)
    print("  🤖 AI 日程解析模式")
    print("=" * 56)
    print(f"  模型: {model}")
    print(f"  API : {base_url}")
    print()
    print("  图片: 拖入或输入文件路径（多张用英文逗号分隔）")
    print("  文本: 直接粘贴非结构化日程描述")
    print("  输入 'd' 完成并生成 .ics，输入 'q' 退出")
    print("-" * 56)
    print()

    locations_data = load_locations()
    locations = locations_data.get("locations", [])

    ics_events = None
    if CALENDAR_URL:
        try:
            print("📡 正在获取最新日历数据...")
            ics_text = fetch_ics(CALENDAR_URL)
            update_locations_from_ics(ics_text, LOCATIONS_JSON)
            locations_data = load_locations()
            locations = locations_data.get("locations", [])
            ics_events = parse_ics_events(split_vevents(ics_text))
        except Exception:
            pass

    all_events: list[dict] = []

    while True:
        try:
            raw = input("📋 图片/文本 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw.lower() == "q":
            print("👋 已退出")
            return

        if raw.lower() == "d":
            if not all_events:
                print("⚠️  还没有收集到任何日程")
                continue
            break

        if not raw:
            continue

        image_paths: list[str] = []
        text_input: str | None = None

        parts = [p.strip() for p in raw.split(",")]
        looks_like_files = all(
            "/" in p or "\\" in p or any(p.lower().endswith(ext)
            for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".bmp"))
            for p in parts
        )

        if looks_like_files:
            valid_paths = []
            for p in parts:
                p = os.path.expanduser(p)
                if os.path.isfile(p):
                    valid_paths.append(p)
                else:
                    print(f"  ⚠️  文件不存在，跳过: {p}")
            if valid_paths:
                image_paths = valid_paths
            else:
                print("  ❌ 没有有效的图片文件")
                continue
        else:
            text_input = raw

        img_label = f"{len(image_paths)} 张图片" if image_paths else ""
        txt_label = "文本" if text_input else ""
        label = " + ".join(filter(None, [img_label, txt_label]))
        print(f"⏳ 正在调用 AI 解析 ({label})...")

        try:
            parsed = ai_parser.parse_with_ai(
                image_paths=image_paths if image_paths else None,
                text=text_input,
            )
        except Exception as e:
            print(f"  ❌ AI 解析失败: {e}")
            continue

        if not parsed:
            print("  ⚠️  AI 未解析到任何日程")
            continue

        print(f"✅ 解析到 {len(parsed)} 个日程：\n")

        for ev in parsed:
            event = build_event(ev, locations)
            print_preview(event)
            all_events.append(event)
            print()

    if not all_events:
        print("👋 没有日程需要生成")
        return

    if len(all_events) > 1:
        before = len(all_events)
        all_events = dedup_events_internal(all_events)
        skipped = before - len(all_events)
        if skipped:
            print(f"  → 输入内去重：跳过了 {skipped} 个重复项")

    final_events = all_events
    if sys.platform == "darwin" and ics_events:
        print("🔍 检查日历中是否有重复事件...")
        deduped = []
        for event in all_events:
            if check_duplicate_via_ics(ics_events, event):
                print(f"  ⏭️  「{event['title']}」{event['start_date']} 已存在，跳过")
            else:
                deduped.append(event)
        final_events = deduped

    if not final_events:
        print("✅ 全部已存在，无需导入")
        return

    if len(final_events) == 1:
        ics = generate_ics(final_events[0])
    else:
        ics = generate_combined_ics(final_events)
    saved = save_ics_file(ics)
    if saved:
        print(f"  → .ics 已保存: {saved}")

    if sys.platform == "darwin":
        print("📅 导入日历...")
        import_to_calendar(saved)
    else:
        print(f"📄 非 macOS，仅生成 .ics: {saved}")

    locations_data = load_locations()
    badminton_kw = locations_data.get("badminton_keywords", ["羽毛球"])
    if CALENDAR_URL:
        try:
            print("🏸 更新羽毛球订阅日历...")
            sync_badminton_ics(CALENDAR_URL, badminton_kw, BADMINTON_ICS_FILE)
        except Exception as e:
            print(f"⚠️  同步羽毛球订阅失败: {e}")

    print("\n✅ 完成！")


def main():
    # --- 0. 特殊模式 ---
    if len(sys.argv) > 1 and sys.argv[1] in ("--ai", "--vision"):
        ai_mode()
        return

    if len(sys.argv) > 1 and sys.argv[1] in ("--interactive", "-i"):
        interactive_mode()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--sync-badminton":
        if not CALENDAR_URL:
            print("❌ 需要配置 CALENDAR_URL")
            sys.exit(1)
        locations_data = load_locations()
        badminton_kw = locations_data.get("badminton_keywords", ["羽毛球"])
        try:
            print("🏸 正在同步羽毛球订阅日历...")
            count = sync_badminton_ics(CALENDAR_URL, badminton_kw, BADMINTON_ICS_FILE)
            if count:
                print(f"✅ 已同步 {count} 个羽毛球事件到 {BADMINTON_ICS_FILE}")
            else:
                print("✅ 无羽毛球事件")
        except Exception as e:
            print(f"❌ 同步失败: {e}")
            sys.exit(1)
        return

    # --- 1. 加载地点配置 ---
    locations_data = load_locations()
    locations = locations_data.get("locations", [])

    # --- 2. 尝试获取最新 .ics（用于去重 + 自动发现新地点）---
    ics_events = None
    if CALENDAR_URL:
        try:
            print("📡 正在获取最新日历数据...")
            ics_text = fetch_ics(CALENDAR_URL)

            # 自动发现新地点
            new_count = update_locations_from_ics(ics_text, LOCATIONS_JSON)
            if new_count > 0:
                # 重新加载（配置已更新）
                locations_data = load_locations()
                locations = locations_data.get("locations", [])
                print(f"  → 发现 {new_count} 个新地点，已更新 locations.json")
            else:
                print(f"  → 日历已是最新，无新地点")

            # 解析事件用于去重
            ics_events = parse_ics_events(split_vevents(ics_text))
            print(f"  → 共 {len(ics_events)} 个日历事件")

        except Exception as e:
            print(f"⚠️  获取日历失败: {e}，使用本地缓存")
            ics_events = None

    # --- 3. 读取输入 ---
    if len(sys.argv) > 1:
        text = sys.argv[1]
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        print("用法:")
        print("  cat schedule.txt | python3 schedule_agent.py")
        print('  python3 schedule_agent.py "标题：..."')
        print("  python3 schedule_agent.py -i    交互式问答模式")
        print("  python3 schedule_agent.py --ai  AI 图片/文本解析模式")
        sys.exit(1)

    if not text.strip():
        print("❌ 输入为空")
        sys.exit(1)

    # --- 4. 解析（支持 JSON 数组批量） ---
    try:
        raw_list = parse_input_batch(text)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    total = len(raw_list)
    events = []
    for idx, raw in enumerate(raw_list, 1):
        if not raw["title"]:
            print(f"❌ [{idx}/{total}] 缺少「标题」字段")
            continue
        if not raw["start_date"]:
            print(f"❌ [{idx}/{total}] 「{raw['title']}」缺少「时间」字段")
            continue

        if total > 1:
            print(f"\n─── [{idx}/{total}] {raw['title']} ───")

        event = build_event(raw, locations)
        print_preview(event)
        events.append(event)

    if not events:
        print("❌ 无有效事件")
        sys.exit(1)

    # --- 5. 输入内部去重 ---
    if len(events) > 1:
        before = len(events)
        events = dedup_events_internal(events)
        skipped = before - len(events)
        if skipped:
            print(f"  → 输入内去重：跳过了 {skipped} 个重复项")

    # --- 6. 跟日历比对去重 ---
    final_events = events
    if sys.platform == "darwin":
        print("🔍 检查日历中是否有重复事件...")
        deduped = []
        for event in events:
            duplicate = False
            if ics_events is not None:
                duplicate = check_duplicate_via_ics(ics_events, event)

            if duplicate:
                print(f"  ⏭️  「{event['title']}」{event['start_date']} 已存在，跳过")
            else:
                deduped.append(event)
        final_events = deduped

    if not final_events:
        print("✅ 全部已存在，无需导入")
        return

    # --- 7. 生成合并 .ics（多事件合为一个文件，只弹一次对话框） ---
    if len(final_events) == 1:
        ics = generate_ics(final_events[0])
    else:
        ics = generate_combined_ics(final_events)
    saved = save_ics_file(ics)

    if saved:
        print(f"   → .ics 已保存: {saved}")

    # --- 8. 导入日历（仅 macOS）---
    if sys.platform == "darwin":
        print("📅 导入日历...")
        import_to_calendar(saved)
    else:
        print(f"📄 非 macOS，仅生成 .ics: {saved}")

    # --- 9. 同步羽毛球订阅 .ics ---
    locations_data = load_locations()
    badminton_kw = locations_data.get("badminton_keywords", ["羽毛球"])
    if CALENDAR_URL:
        try:
            print("🏸 更新羽毛球订阅日历...")
            sync_badminton_ics(CALENDAR_URL, badminton_kw, BADMINTON_ICS_FILE)
        except Exception as e:
            print(f"⚠️  同步羽毛球订阅失败: {e}")

    print("✅ 完成！")


def interactive_mode():
    """交互式问答模式：粘贴完整日程文本即可生成 .ics

    支持格式：
      - 结构化文本（标签：值 格式）
      - JSON 单对象 / JSON 数组
      - 多段文本（用 --- 或空行分隔，批量导入）
    """
    print("=" * 60)
    print("  📋 日程输入助手（交互式模式）")
    print("=" * 60)
    print()
    print("  支持的格式：")
    print("  ──────────────────────────────────────────")
    print()
    print("  结构化文本（中英文标签均可）：")
    print("    标题：羽毛球活动")
    print("    时间：2026-05-31 19:00-21:00")
    print("    地点：上海奥埔篮羽运动中心")
    print("    地址：曹路镇镇北路2-1")
    print("    描述：费用￥34")
    print()
    print("  JSON 单对象：")
    print('    {"title": "羽毛球", "start_date": "2026-05-31", ...}')
    print()
    print("  JSON 数组（批量）：")
    print('    [{"title": "羽毛球", ...}, {"title": "团建", ...}]')
    print()
    print("  多段文本（用 --- 或空行分隔，批量）：")
    print("    标题：羽毛球")
    print("    时间：2026-05-31 19:00-21:00")
    print()
    print("    标题：团建")
    print("    时间：2026-06-01 09:00-17:00")
    print("  ──────────────────────────────────────────")
    print()

    # --- 加载地点配置 ---
    locations_data = load_locations()
    locations = locations_data.get("locations", [])

    # --- 尝试获取最新 .ics ---
    ics_events = None
    if CALENDAR_URL:
        try:
            print("  📡 正在获取最新日历数据...")
            ics_text = fetch_ics(CALENDAR_URL)
            new_count = update_locations_from_ics(ics_text, LOCATIONS_JSON)
            if new_count:
                print(f"  → 发现 {new_count} 个新地点并已保存")
            ics_events = parse_ics_events(split_vevents(unfold_ics(ics_text)))
        except Exception as e:
            print(f"  ⚠️  获取日历数据失败: {e}")

    # 重新加载（可能有新地点）
    locations_data = load_locations()
    locations = locations_data.get("locations", [])

    # --- 收集文本 ---
    print("  请粘贴日程内容，输入空行结束：")
    print()
    input_lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if not input_lines:
                continue  # 忽略开头的空行
            break
        input_lines.append(line)

    if not input_lines:
        print("\n  ❌ 未输入任何内容")
        return

    text = "\n".join(input_lines)
    print(f"\n  ✅ 已接收 {len(input_lines)} 行文本，正在解析...\n")

    # --- 解析 ---
    events = parse_input_batch(text)

    if not events:
        print("  ❌ 未能解析出有效事件，请检查格式后重试")
        print()
        print("  示例：")
        print("    标题：羽毛球")
        print("    时间：2026-05-31 19:00-21:00")
        return

    # --- 构建并预览 ---
    print(f"  共解析出 {len(events)} 个事件：\n")
    for i, raw in enumerate(events):
        if len(events) > 1:
            print(f"  ─── [{i+1}/{len(events)}] {raw['title']} ───")
        event = build_event(raw, locations)
        print_preview(event)

    # --- 确认 ---
    try:
        confirm = input("  确认导入？[Y/n] ").strip().lower()
    except EOFError:
        confirm = "y"
    if confirm not in ("", "y", "yes"):
        print("  👋 已取消")
        return

    # ────────── 后续处理 ──────────

    events = [build_event(raw, locations) for raw in events]
    # --- 输入内部去重 ---
    if len(events) > 1:
        before = len(events)
        events = dedup_events_internal(events)
        skipped = before - len(events)
        if skipped:
            print(f"  → 输入内去重：跳过了 {skipped} 个重复项")

    # --- 跟日历比对去重 ---
    final_events = events
    if sys.platform == "darwin":
        print("  🔍 检查日历中是否有重复事件...")
        deduped = []
        for event in events:
            duplicate = False
            if ics_events is not None:
                duplicate = check_duplicate_via_ics(ics_events, event)
            if duplicate:
                print(f"  ⏭️  「{event['title']}」{event['start_date']} 已存在，跳过")
            else:
                deduped.append(event)
        final_events = deduped

    if not final_events:
        print("  ✅ 全部已存在，无需导入")
        return

    # --- 生成合并 .ics ---
    if len(final_events) == 1:
        ics = generate_ics(final_events[0])
    else:
        ics = generate_combined_ics(final_events)
    saved = save_ics_file(ics)
    if saved:
        print(f"  → .ics 已保存: {saved}")

    # --- 导入日历（仅 macOS） ---
    if sys.platform == "darwin":
        print("  📅 导入日历...")
        import_to_calendar(saved)
    else:
        print(f"  📄 非 macOS，仅生成 .ics: {saved}")

    # --- 同步羽毛球订阅 .ics ---
    locations_data = load_locations()
    badminton_kw = locations_data.get("badminton_keywords", ["羽毛球"])
    if CALENDAR_URL:
        try:
            print("  🏸 更新羽毛球订阅日历...")
            sync_badminton_ics(CALENDAR_URL, badminton_kw, BADMINTON_ICS_FILE)
        except Exception as e:
            print(f"  ⚠️  同步羽毛球订阅失败: {e}")

    print("\n  ✅ 完成！")




if __name__ == "__main__":
    main()
