#!/usr/bin/env python3
"""Schedule Agent — AI 模式全量测试"""

import sys
import os

# 确保能找到项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from schedule_agent import *

passed = 0
failed = 0


def check(cond: bool, msg: str):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        print(f"  ❌ {msg}")


def mk(title, loc="", desc="", start="2026-06-01", s_time="18:00",
       end="2026-06-01", e_time="20:00", all_day=False):
    """构造 AI 解析返回的原始日程 dict"""
    return {
        "title": title,
        "start_date": start,
        "start_time": "" if all_day else s_time,
        "end_date": end,
        "end_time": "" if all_day else e_time,
        "is_all_day": all_day,
        "location_name": loc,
        "description": desc,
        "_raw_venue": loc,
        "_raw_address": "",
    }


# ─── 1. 模块加载 ──
print("\n── 模块加载 ──")
check(load_locations is not None, "load_locations")
check(build_event is not None, "build_event")
check(generate_ics is not None, "generate_ics")
check(ai_mode is not None, "ai_mode")

# ─── 2. 标题重写 ──
print("\n── 标题重写 ──")
locs = load_locations().get("locations", [])
e = build_event(mk("羽毛球活动"), locs)
check(e["title"] == "羽毛球", f"羽毛球活动 → {e['title']}")

e = build_event(mk("打羽毛球"), locs)
check(e["title"] == "羽毛球", f"打羽毛球 → {e['title']}")

e = build_event(mk("团建"), locs)
check(e["title"] == "团建", f"团建 → {e['title']}")

# ─── 3. 标题兜底（AI 把场馆名当标题） ──
print("\n── 标题兜底 ──")
e = build_event(mk("奥埔篮羽运动中心", "奥埔篮羽运动中心"), locs)
check(e["title"] == "羽毛球", "场馆名标题 → 羽毛球")

e = build_event(mk("上海奥埔篮羽运动中心", "上海奥埔篮羽运动中心"), locs)
check(e["title"] == "羽毛球", "场馆全称标题 → 羽毛球")

e = build_event(mk("Victor热爱体育中心", "VICTOR 热爱体育中心"), locs)
check(e["title"] == "羽毛球", "Victor热爱体育中心（大小写/空格差异）→ 羽毛球")

e = build_event(mk("嘿猩猩羽毛球馆", "嘿猩猩羽毛球馆"), locs)
check(e["title"] == "羽毛球", "含羽毛球关键字场馆 → 羽毛球")

e = build_event(mk("羽毛球", "奥埔篮羽运动中心"), locs)
check(e["title"] == "羽毛球", "正常标题不被误伤（羽毛球）")

e = build_event(mk("同学聚会", "海底捞"), locs)
check(e["title"] == "同学聚会", "正常标题不被误伤（同学聚会）")

e = build_event(mk("奥埔篮羽运动中心", "某神秘场馆X"), locs)
check(e["title"] == "奥埔篮羽运动中心", "无法推断时保守保留原标题")

e = build_event(mk("某运动中心", "某运动中心", desc="羽毛球订场 2小时"), locs)
check(e["title"] == "羽毛球", "描述含羽毛球可推断")

# ─── 4. 地点匹配 ──
print("\n── 地点匹配 ──")
e = build_event(mk("羽毛球", "上海奥埔篮羽运动中心"), locs)
check(e["location_matched"] is not None, "奥埔 → 已匹配")
if e["location_matched"]:
    check(e["location_matched"]["id"] == "aopu", f"id → {e['location_matched']['id']}")
check(e["needs_structured_location"] is True, "需结构化定位")

e = build_event(mk("羽毛球", "VICTOR 热爱体育中心"), locs)
check(e["location_matched"] is not None, "热爱 → 已匹配")
if e["location_matched"]:
    check(e["location_matched"]["id"] == "reai", f"id → {e['location_matched']['id']}")

e = build_event(mk("参展", "国家会展中心(上海)"), locs)
check(e["location_matched"] is not None, "会展中心 → 已匹配")
check(e["needs_structured_location"] is False, "无结构化定位")

# 未知地点
e = build_event(mk("聚餐", "随便餐厅"), locs)
check(e["location_matched"] is None, "未知 → 不匹配")
check(e["location_name"] == "随便餐厅", "原样保留 → 随便餐厅")

# ─── 5. .ics 生成 ──
print("\n── .ics 生成 ──")
e = build_event(mk("羽毛球", "上海奥埔篮羽运动中心"), locs)
ics = generate_ics(e)
check("BEGIN:VCALENDAR" in ics, "BEGIN:VCALENDAR")
check("END:VCALENDAR" in ics, "END:VCALENDAR")
check("BEGIN:VEVENT" in ics, "BEGIN:VEVENT")
check("END:VEVENT" in ics, "END:VEVENT")
check("SUMMARY:羽毛球" in ics, "SUMMARY:羽毛球")
check("X-APPLE-STRUCTURED-LOCATION" in ics, "结构化定位")
check(ics.count("LOCATION:") == 1, "LOCATION 唯一")

# 未知地点 .ics
e = build_event(mk("聚餐", "新天地餐厅"), locs)
ics = generate_ics(e)
check("LOCATION:新天地餐厅" in ics.replace("\n", ""), "LOCATION 正确")
check(ics.count("LOCATION:") == 1, "未知地点 LOCATION 唯一")

# 全天活动 .ics
e = build_event(mk("出差", all_day=True), locs)
ics = generate_ics(e)
check("DTSTART;VALUE=DATE:20260601" in ics, "全天 DTSTART")
check("DTEND;VALUE=DATE:20260602" in ics, "全天 DTEND")
check("DTSTART;TZID" not in ics, "无 TZID")

# 描述含换行的 .ics
e = build_event(mk("羽毛球", desc="费用：¥34\n人数：男2 女2"), locs)
ics = generate_ics(e)
check("DESCRIPTION:费用：¥34" in ics, "DESCRIPTION 含描述")
check("人数：男2 女2" in ics, "DESCRIPTION 含描述多行")

# 合并 .ics
e1 = build_event(mk("羽毛球", "上海奥埔篮羽运动中心"), locs)
e2 = build_event(mk("聚餐", "新天地餐厅"), locs)
ics = generate_combined_ics([e1, e2])
check(ics.count("BEGIN:VEVENT") == 2, "合并 ics 含 2 个事件")

# ─── 6. 去重检测（含归一化） ──
print("\n── 去重检测 ──")
events = [
    {"date": "2026-06-01", "summary": "羽毛球"},
    {"date": "2026-06-02", "summary": "团建"},
]
e = {"start_date": "2026-06-01", "title": "羽毛球"}
status, _ = check_duplicate_via_ics(events, e)
check(status == "identical", "精确匹配 → identical")

e = {"start_date": "2026-06-03", "title": "羽毛球"}
status, _ = check_duplicate_via_ics(events, e)
check(status == "new", "日期不同 → new")

e = {"start_date": "2026-06-01", "title": "聚餐"}
status, _ = check_duplicate_via_ics(events, e)
check(status == "new", "标题不同 → new")

# 归一化匹配
events2 = [
    {"date": "2026-06-01", "summary": "羽毛球活动"},
    {"date": "2026-06-02", "summary": "打羽毛球"},
]
e = {"start_date": "2026-06-01", "title": "羽毛球"}
status, _ = check_duplicate_via_ics(events2, e)
check(status == "identical", "羽毛球 vs 羽毛球活动 → identical")

e = {"start_date": "2026-06-02", "title": "羽毛球"}
status, _ = check_duplicate_via_ics(events2, e)
check(status == "identical", "羽毛球 vs 打羽毛球 → identical")

# 时间变更检测
events3 = [
    {"date": "2026-06-01", "summary": "羽毛球", "start_time": "18:00", "end_time": "19:00"},
]
e = {"start_date": "2026-06-01", "title": "羽毛球", "start_time": "18:00", "end_time": "22:00"}
status, matched = check_duplicate_via_ics(events3, e)
check(status == "update", "时间不同 → update")
check(matched is not None and matched["start_time"] == "18:00", "返回匹配的旧事件含原时间")

# 时间完全一致
e2 = {"start_date": "2026-06-01", "title": "羽毛球", "start_time": "18:00", "end_time": "19:00"}
status2, _ = check_duplicate_via_ics(events3, e2)
check(status2 == "identical", "时间一致 → identical")

# ─── 7. 输入内部去重 ──
print("\n── 输入内部去重 ──")
events_in = [
    {"start_date": "2026-06-01", "title": "羽毛球"},
    {"start_date": "2026-06-01", "title": "羽毛球"},
    {"start_date": "2026-06-01", "title": "羽毛球活动"},
    {"start_date": "2026-06-02", "title": "团建"},
    {"start_date": "2026-06-02", "title": "团建"},
    {"start_date": "2026-06-03", "title": "聚餐"},
]
deduped = dedup_events_internal(events_in)
check(len(deduped) == 3, f"6条→3条: {len(deduped)}")
check(deduped[0]["title"] == "羽毛球", "第1条：羽毛球")
check(deduped[1]["title"] == "团建", "第2条：团建")
check(deduped[2]["title"] == "聚餐", "第3条：聚餐")

# 无重复
deduped2 = dedup_events_internal([
    {"start_date": "2026-06-01", "title": "羽毛球"},
    {"start_date": "2026-06-02", "title": "团建"},
])
check(len(deduped2) == 2, "无重复时不变")

# ─── 8. AI Parser 模块 ──
print("\n── AI Parser ──")
from schedule_agent import ai_parser

check(hasattr(ai_parser, "_build_prompt"), "_build_prompt 存在")
check(hasattr(ai_parser, "_encode_image"), "_encode_image 存在")
check(hasattr(ai_parser, "_extract_json"), "_extract_json 存在")
check(hasattr(ai_parser, "parse_with_ai"), "parse_with_ai 存在")

# Prompt substitution
prompt = ai_parser._build_prompt()
today = datetime.now().strftime("%Y-%m-%d")
check(today in prompt, f"prompt 包含当前日期 {today}")
check("{current_time}" not in prompt, "prompt 中无未替换的占位符")
check("严禁使用地点、场馆" in prompt, "prompt 含标题防场馆名规则")

# JSON extraction (strip markdown fences)
raw = '```json\n[{"title":"测试"}]\n```'
clean = ai_parser._extract_json(raw)
check(clean == '[{"title":"测试"}]', f"去除 markdown 代码块: {clean!r}")

raw2 = '[{"title":"无包裹"}]'
clean2 = ai_parser._extract_json(raw2)
check(clean2 == '[{"title":"无包裹"}]', f"无需去除: {clean2!r}")

# Image encoding (use a small test file)
import struct, zlib


def _create_minimal_png(path: str):
    """Create a 1x1 red pixel PNG for testing."""
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_pixel = b"\x00\xff\x00\x00"
    idat = zlib.compress(raw_pixel)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


test_png = os.path.join(os.path.dirname(__file__), "_test_1x1.png")
_create_minimal_png(test_png)
try:
    data_url = ai_parser._encode_image(test_png)
    check(data_url.startswith("data:image/png;base64,"), f"PNG base64 编码: {data_url[:30]}...")
finally:
    os.remove(test_png)

# parse_with_ai 无参数应抛错
try:
    ai_parser.parse_with_ai()
    check(False, "无参数应抛 ValueError")
except ValueError:
    check(True, "无参数正确抛 ValueError")

# ─── 汇总 ──
print(f"\n{'='*40}")
print(f"  通过: {passed}  |  失败: {failed}  |  总计: {passed + failed}")
print(f"{'='*40}")
sys.exit(0 if failed == 0 else 1)
