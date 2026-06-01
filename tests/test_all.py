#!/usr/bin/env python3
"""Schedule Agent — 全量测试"""

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


# ─── 1. 模块加载 ───
print("\n── 模块加载 ──")
check(load_locations is not None, "load_locations")
check(parse_input is not None, "parse_input")
check(build_event is not None, "build_event")
check(generate_ics is not None, "generate_ics")

# ─── 2. 相对日期解析 ───
print("\n── 相对日期 ──")
r = parse_input("标题：测试\n时间：明天 14:00 - 16:00\n地点：奥埔")
check(r["start_date"] != "", "明天 → 有日期")
check(r["start_time"] == "14:00", f"开始时间 → {r['start_time']}")
check(r["end_time"] == "16:00", f"结束时间 → {r['end_time']}")

r = parse_input("标题：测试\n时间：今天 09:00 - 10:00")
check(r["start_date"] == datetime.now().strftime("%Y-%m-%d"), "今天 → 当天")

r = parse_input("标题：测试\n时间：本周五 18:00 - 20:00")
check(r["start_date"] != "", "本周五 → 有日期")

# ─── 3. 自动跨天 ───
print("\n── 自动跨天 ──")
r = parse_input("标题：夜班\n时间：2026-06-01 22:00 - 02:00")
check(r["end_date"] == "2026-06-02", f"22:00-02:00 → {r['end_date']}")

r = parse_input("标题：夜班\n时间：2026-06-01 23:30 - 00:30")
check(r["end_date"] == "2026-06-02", f"23:30-00:30 → {r['end_date']}")

# 边界：同时间的不跨天
r = parse_input("标题：全天\n时间：2026-06-01 09:00 - 09:00")
check(r["end_date"] == "2026-06-02", f"09:00-09:00 跨天 → {r['end_date']}")

# ─── 4. 显式跨天 ───
print("\n── 显式跨天 ──")
r = parse_input("标题：出差\n时间：2026-06-10 09:00 - 2026-06-11 18:00")
check(r["start_date"] == "2026-06-10", f"开始 → {r['start_date']}")
check(r["end_date"] == "2026-06-11", f"结束 → {r['end_date']}")

# ─── 5. 中文日期格式 ───
print("\n── 中文日期 ──")
r = parse_input("标题：电影\n时间：6月7日 19:00 - 21:30")
check(r["start_date"] == f"{datetime.now().year}-06-07", f"6月7日 → {r['start_date']}")

r = parse_input("标题：活动\n时间：12月25日 10:00 - 12:00")
check(r["start_date"] == f"{datetime.now().year}-12-25", f"12月25日 → {r['start_date']}")

# ─── 6. 全天活动 ───
print("\n── 全天活动 ──")
r = parse_input("标题：出差\n时间：2026-06-20")
check(r["is_all_day"] is True, "is_all_day=True")
check(r["start_time"] == "", "start_time 为空")
check(r["end_time"] == "", "end_time 为空")

r = parse_input("标题：放假\n时间：明天")
check(r["is_all_day"] is True, "相对日期全天 is_all_day=True")

# ─── 7. 描述生成 ───
print("\n── 描述生成 ──")
r = parse_input("标题：羽毛球\n时间：2026-06-01 18:00-20:00\n描述：费用：¥34\n人数：男2 女2\n备注：带水")
check("费用：¥34" in r["description"], "描述")
check("人数：男2 女2" in r["description"], "描述含人数")
check("备注：带水" in r["description"], "描述含备注")

r = parse_input("标题：打球\n时间：2026-06-01 18:00-20:00\n描述：场地：6、8\n组织者：Cooper")
check("场地：6、8" in r["description"], "描述含场地")
check("组织者：Cooper" in r["description"], "描述含组织者")

# ─── 8. 标题重写 ───
print("\n── 标题重写 ──")
locs = load_locations().get("locations", [])
e = build_event(parse_input("标题：羽毛球活动\n时间：2026-06-01 18:00-20:00"), locs)
check(e["title"] == "羽毛球", f"羽毛球活动 → {e['title']}")

e = build_event(parse_input("标题：打羽毛球\n时间：2026-06-01 18:00-20:00"), locs)
check(e["title"] == "羽毛球", f"打羽毛球 → {e['title']}")

e = build_event(parse_input("标题：团建\n时间：2026-06-01 18:00-20:00"), locs)
check(e["title"] == "团建", f"团建 → {e['title']}")

# ─── 9. 地点匹配 ───
print("\n── 地点匹配 ──")
e = build_event(parse_input("标题：羽毛球\n时间：2026-06-01 18:00-20:00\n地点：上海奥埔篮羽运动中心"), locs)
check(e["location_matched"] is not None, "奥埔 → 已匹配")
if e["location_matched"]:
    check(e["location_matched"]["id"] == "aopu", f"id → {e['location_matched']['id']}")
check(e["needs_structured_location"] is True, "需结构化定位")

e = build_event(parse_input("标题：羽毛球\n时间：2026-06-01 18:00-20:00\n地点：VICTOR 热爱体育中心"), locs)
check(e["location_matched"] is not None, "热爱 → 已匹配")
if e["location_matched"]:
    check(e["location_matched"]["id"] == "reai", f"id → {e['location_matched']['id']}")

e = build_event(parse_input("标题：参展\n时间：2026-06-01 09:00-17:00\n地点：国家会展中心(上海)"), locs)
check(e["location_matched"] is not None, "会展中心 → 已匹配")
check(e["needs_structured_location"] is False, "无结构化定位")

# 未知地点
e = build_event(parse_input("标题：聚餐\n时间：2026-06-01 12:00-13:00\n地点：随便餐厅"), locs)
check(e["location_matched"] is None, "未知 → 不匹配")
check(e["location_name"] == "随便餐厅", "原样保留 → 随便餐厅")

# ─── 10. .ics 生成 ───
print("\n── .ics 生成 ──")
e = build_event(parse_input("标题：羽毛球\n时间：2026-06-01 18:00-20:00\n地点：上海奥埔篮羽运动中心"), locs)
ics = generate_ics(e)
check("BEGIN:VCALENDAR" in ics, "BEGIN:VCALENDAR")
check("END:VCALENDAR" in ics, "END:VCALENDAR")
check("BEGIN:VEVENT" in ics, "BEGIN:VEVENT")
check("END:VEVENT" in ics, "END:VEVENT")
check("SUMMARY:羽毛球" in ics, "SUMMARY:羽毛球")
check("X-APPLE-STRUCTURED-LOCATION" in ics, "结构化定位")
check(ics.count("LOCATION:") == 1, "LOCATION 唯一")

# 未知地点 .ics
e = build_event(parse_input("标题：聚餐\n时间：2026-06-01 12:00-13:00\n地点：新天地餐厅"), locs)
ics = generate_ics(e)
check("LOCATION:新天地餐厅" in ics.replace("\\n", ""), "LOCATION 正确")
check(ics.count("LOCATION:") == 1, "未知地点 LOCATION 唯一")

# 全天活动 .ics
e = build_event(parse_input("标题：出差\n时间：2026-06-20"), locs)
ics = generate_ics(e)
check("DTSTART;VALUE=DATE:20260620" in ics, "全天 DTSTART")
check("DTEND;VALUE=DATE:20260621" in ics, "全天 DTEND")
check("DTSTART;TZID" not in ics, "无 TZID")

# 描述含换行的 .ics
e = build_event(parse_input("标题：羽毛球\n时间：2026-06-01 18:00-20:00\n描述：费用：¥34\n人数：男2 女2"), locs)
ics = generate_ics(e)
check("DESCRIPTION:费用：¥34" in ics, "DESCRIPTION 含描述")
check("人数：男2 女2" in ics, "DESCRIPTION 含描述多行")

# ─── 11. JSON 输入 ───
print("\n── JSON 输入 ──")
r = parse_input('{"title": "羽毛球", "start_date": "2026-06-07", "start_time": "14:00", "end_date": "2026-06-07", "end_time": "16:00", "is_all_day": false, "location_name": "上海奥埔篮羽运动中心", "description": "费用：¥34"}')
check(r["title"] == "羽毛球", "JSON 单对象 title")
check(r["start_date"] == "2026-06-07", "JSON 单对象 start_date")
check(r["location_name"] == "上海奥埔篮羽运动中心", "JSON 单对象 location")

r = parse_input('[{"title": "测试", "start_date": "2026-06-01"}, {"title": "测试2"}]')
check(r["title"] == "测试", "JSON 数组取第一项")

r = parse_input("标题：文本\n时间：明天 14:00 - 16:00")
check(r["title"] == "文本", "JSON 不干扰文本格式")

# 文本格式用 JSON 字段名
r = parse_input("title: 测试\ntime: 2026-06-07 14:00-16:00\nlocation_name: 奥埔")
check(r["title"] == "测试", "title: 标签")
check(r["location_name"] == "奥埔", "location_name: 标签")
check(r["start_date"] == "2026-06-07", "time: 标签解析")

r = parse_input("标题：羽毛球\ntitle: 覆盖\n时间：明天 14:00-16:00")
check(r["title"] == "覆盖", "中文标签可被英文覆盖")

# ─── 12. 标题归一化 ───
print("\n── 标题归一化 ──")
check(build_event(parse_input("标题：羽毛球活动\n时间：2026-06-01 18:00-20:00"), locs)["title"] == "羽毛球", "羽毛球活动 → 羽毛球")
check(build_event(parse_input("标题：打羽毛球\n时间：2026-06-01 18:00-20:00"), locs)["title"] == "羽毛球", "打羽毛球 → 羽毛球")
check(build_event(parse_input("标题：团建\n时间：2026-06-01 18:00-20:00"), locs)["title"] == "团建", "团建 → 不变")

# ─── 13. 去重检测（含归一化） ───
print("\n── 去重检测 ──")
# 精确匹配（无时间字段 → 默认空字符串，视为一致）
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

# ─── 14. 输入内部去重 ───
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

# ─── 汇总 ───
from schedule_agent import ai_parser


# ─── 15. AI Parser 模块 ───
print("\n── AI Parser ──")
check(hasattr(ai_parser, "_build_prompt"), "_build_prompt 存在")
check(hasattr(ai_parser, "_encode_image"), "_encode_image 存在")
check(hasattr(ai_parser, "_extract_json"), "_extract_json 存在")
check(hasattr(ai_parser, "parse_with_ai"), "parse_with_ai 存在")

# Prompt substitution
prompt = ai_parser._build_prompt()
today = datetime.now().strftime("%Y-%m-%d")
check(today in prompt, f"prompt 包含当前日期 {today}")
check("{current_time}" not in prompt, "prompt 中无未替换的占位符")

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

# ─── 汇总 ───
print(f"\n{'='*40}")
print(f"  通过: {passed}  |  失败: {failed}  |  总计: {passed + failed}")
print(f"{'='*40}")
sys.exit(0 if failed == 0 else 1)
