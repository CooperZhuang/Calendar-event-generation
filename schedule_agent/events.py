# 事件构建与日历导入
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

from .config import ICS_OUTPUT_FILE, CALENDAR_NAME, CONFIRM_BEFORE_IMPORT, CALENDAR_URL, LOCATIONS_JSON, _PROJECT_DIR
from .locations import match_location
from .parser import _normalize_title
from .ics_utils import generate_ics
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

def save_ics_file(ics_content: str, ics_path: str | None = None) -> str | None:
    """保存 .ics 到项目目录（每次覆盖同一文件）"""
    path = ics_path or ICS_OUTPUT_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
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
