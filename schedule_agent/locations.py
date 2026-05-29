# 地点配置管理
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
import re
import shutil
import urllib.request

from .config import LOCATIONS_JSON, LOCATIONS_EXAMPLE, _PROJECT_DIR
from .ics_utils import split_vevents, parse_ics_events
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
    os.makedirs(os.path.dirname(LOCATIONS_JSON), exist_ok=True)
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

# .ics 网络获取 & 解析

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
