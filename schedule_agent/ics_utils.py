# ICS 解析与生成
from __future__ import annotations
import re
import urllib.request
import hashlib
from datetime import datetime, timezone, timedelta
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
    """解析 VEVENT 块列表，提取用于去重、时间比较和地点发现的字段"""
    events = []
    for block in vevent_blocks:
        event = {"summary": "", "date": "", "start_time": "", "end_time": "",
                 "uid": "", "location": "", "structured_loc": ""}

        summary_line = _get_prop(block, "SUMMARY")
        if summary_line:
            event["summary"] = _prop_value(summary_line)

        dtstart_line = _get_prop(block, "DTSTART")
        if dtstart_line:
            val = _prop_value(dtstart_line)
            # 提取日期 + 可选时间：YYYYMMDD 或 YYYYMMDDTHHMMSS[Z]
            m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})Z?)?", val)
            if m:
                event["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                if m.group(4) and m.group(5):
                    event["start_time"] = f"{m.group(4)}:{m.group(5)}"

        dtend_line = _get_prop(block, "DTEND")
        if dtend_line:
            val = _prop_value(dtend_line)
            m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})Z?)?", val)
            if m and m.group(4) and m.group(5):
                event["end_time"] = f"{m.group(4)}:{m.group(5)}"

        uid_line = _get_prop(block, "UID")
        if uid_line:
            event["uid"] = _prop_value(uid_line)

        loc_line = _get_prop(block, "LOCATION")
        if loc_line:
            event["location"] = _prop_value(loc_line)

        structured = _get_prop(block, "X-APPLE-STRUCTURED-LOCATION")
        if structured:
            event["structured_loc"] = structured

        events.append(event)
    return events

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

    uid_hash = f"{event['title']}|{event['start_date']}"
    uid = hashlib.sha1(uid_hash.encode()).hexdigest()[:16] + "@schedule-agent"
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


def _add_days(date_str: str, n: int) -> str:
    """日期加 n 天（YYYY-MM-DD 格式）"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=n)).strftime("%Y-%m-%d")
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
