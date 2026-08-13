# 事件构建与日历导入
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

from .config import (
    ICS_OUTPUT_FILE, CALENDAR_NAME, CONFIRM_BEFORE_IMPORT, CALENDAR_URL,
    LOCATIONS_JSON, _PROJECT_DIR, BADMINTON_KEYWORDS, BADMINTON_VENUES,
)
from .locations import match_location
from .ics_utils import generate_ics

def _normalize_title(title: str) -> str:
    """统一标题用于去重比较（羽毛球活动 → 羽毛球）"""
    if any(kw in title for kw in BADMINTON_KEYWORDS):
        return "羽毛球"
    return title

def _norm_text(s: str) -> str:
    """去空格 + 小写，用于场馆名比较（忽略大小写/空格差异）"""
    return re.sub(r"\s+", "", s or "").lower()

def _is_badminton_venue(raw_venue: str) -> bool:
    """判断地点是否与羽毛球相关（关键字 + 常去球馆名单）"""
    t = _norm_text(raw_venue)
    if not t:
        return False
    if any(_norm_text(kw) in t for kw in BADMINTON_KEYWORDS):
        return True
    return any(t == _norm_text(v) or _norm_text(v) in t for v in BADMINTON_VENUES)

def _title_looks_like_venue(title: str, locations: list[dict], raw_venue: str) -> bool:
    """标题是否被地点/场馆名污染（AI 把场馆名当成了标题）"""
    t = _norm_text(title)
    if not t:
        return False
    if raw_venue and t == _norm_text(raw_venue):
        return True
    for loc in locations:
        name = _norm_text(loc.get("name") or "")
        if not name:
            continue
        if t == name or (len(t) >= 2 and (t in name or name in t)):
            return True
    return False

def _infer_title(raw_venue: str, description: str, fallback: str) -> str:
    """标题被场馆名污染时，根据地点/描述推断活动类型标题"""
    if _is_badminton_venue(f"{raw_venue} {description}"):
        return "羽毛球"
    return fallback

def build_event(raw: dict, locations: list[dict]) -> dict:
    """加工解析结果为最终事件数据（含地点匹配）

    Args:
        raw: AI 解析返回的原始日程 dict
        locations: 地点配置列表

    Returns:
        含 location_matched 等扩展字段的事件 dict
    """
    title = _normalize_title(raw["title"])

    # --- 标题兜底：AI 可能把场馆名当标题，改回活动类型 ---
    if title and _title_looks_like_venue(title, locations, raw.get("_raw_venue", "")):
        title = _infer_title(
            raw.get("_raw_venue", ""),
            raw.get("description", ""),
            fallback=title,
        )

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

def check_duplicate_via_ics(events: list[dict], target: dict) -> tuple[str, dict | None]:
    """对照已解析的 .ics 事件列表检查重复 / 时间变更

    Returns:
        ("identical", matched_event) — 日期+标题+时间完全一致，跳过
        ("update", matched_event)     — 日期+标题一致但时间不同，需要更新
        ("new", None)                 — 无匹配，全新事件
    """
    target_date = target["start_date"]
    target_norm = _normalize_title(target["title"])
    target_start = target.get("start_time", "")
    target_end = target.get("end_time", "")
    for ev in events:
        if ev["date"] == target_date and _normalize_title(ev["summary"]) == target_norm:
            ev_start = ev.get("start_time", "")
            ev_end = ev.get("end_time", "")
            if ev_start == target_start and ev_end == target_end:
                return ("identical", ev)
            else:
                return ("update", ev)
    return ("new", None)

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
