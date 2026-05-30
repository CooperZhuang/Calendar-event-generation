#!/usr/bin/env python3
"""
日程文本 → .ics 生成 + 自动插入 Mac 日历（含去重、自动发现新地点）

用法：
   cat schedule.txt | python3 schedule_agent.py
   python3 schedule_agent.py "标题：..."
   python3 schedule_agent.py -i         交互式问答模式
   python3 schedule_agent.py --ai       AI 模式
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from schedule_agent.config import (
    CALENDAR_NAME, CONFIRM_BEFORE_IMPORT, ICS_OUTPUT_FILE,
    BADMINTON_ICS_FILE, CALENDAR_URL, LOCATIONS_JSON, _PROJECT_DIR,
)
from schedule_agent.locations import load_locations, update_locations_from_ics
from schedule_agent.ics_utils import (
    fetch_ics, unfold_ics, split_vevents, parse_ics_events, generate_ics, generate_combined_ics,
)
from schedule_agent.parser import parse_input, parse_input_batch
from schedule_agent.events import (
    build_event, save_ics_file, print_preview,
    check_duplicate_via_ics, dedup_events_internal, import_to_calendar,
)
from schedule_agent.sync import sync_badminton_ics
from schedule_agent.cli import ai_mode, interactive_mode

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
            ics_events = parse_ics_events(split_vevents(unfold_ics(ics_text)))
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

if __name__ == "__main__":
    main()
