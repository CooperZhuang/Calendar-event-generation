# 命令行交互模式（AI 模式 / 交互模式）
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from .ai_parser import parse_with_ai
from .config import CALENDAR_NAME, CONFIRM_BEFORE_IMPORT, ICS_OUTPUT_FILE, BADMINTON_ICS_FILE, CALENDAR_URL, LOCATIONS_JSON, _PROJECT_DIR
from .locations import load_locations, update_locations_from_ics
from .ics_utils import fetch_ics, unfold_ics, split_vevents, parse_ics_events, generate_ics, generate_combined_ics
from .parser import parse_input, parse_input_batch
from .events import build_event, save_ics_file, print_preview, check_duplicate_via_ics, dedup_events_internal, import_to_calendar
from .sync import sync_badminton_ics

def _cleanup_tmp(path: str):
    """删除临时文件（忽略错误）"""
    try:
        os.remove(path)
    except OSError:
        pass

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
    print("  图片: :img 读剪贴板 / 拖入文件路径（英文逗号分隔多张，可多次添加后 d）")
    print("  文本: 直接粘贴日程描述（多行粘贴后补空行，解析后即确认导入）")
    print("  命令: :img 读剪贴板 | d 生成ics | q 退出")
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

        if raw.lower() == ":img":
            # 从剪贴板读取图片
            print("  📋 正在从剪贴板读取图片...")
            try:
                result = subprocess.run(
                    ["osascript", "-e", "get the clipboard as «class PNGf»"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    print("  ❌ 剪贴板中没有图片")
                    continue
                hex_str = result.stdout.strip()
                if not hex_str.startswith("«data PNGf"):
                    print("  ❌ 剪贴板数据格式异常")
                    continue
                hex_data = hex_str[len("«data PNGf"):].rstrip("»")
                img_bytes = bytes.fromhex(hex_data.replace(" ", ""))
                tmp_path = os.path.join(tempfile.gettempdir(), f"codex_clipboard_{os.getpid()}.png")
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                image_paths = [tmp_path]
                print(f"  ✅ 已读取剪贴板图片 ({len(img_bytes)} 字节)")
            except subprocess.TimeoutExpired:
                print("  ❌ 读取剪贴板超时")
                continue
            except Exception as e:
                print(f"  ❌ 读取剪贴板失败: {e}")
                continue

            print("⏳ 正在调用 AI 解析 (剪贴板图片)...")
            try:
                parsed = parse_with_ai(image_paths=image_paths)
            except Exception as e:
                print(f"  ❌ AI 解析失败: {e}")
                _cleanup_tmp(tmp_path)
                continue
            _cleanup_tmp(tmp_path)

            if not parsed:
                print("  ⚠️  AI 未解析到任何日程")
                continue

            print(f"✅ 解析到 {len(parsed)} 个日程：\n")
            for ev in parsed:
                event = build_event(ev, locations)
                print_preview(event)
                all_events.append(event)
                print()

            try:
                confirm = input("  确认导入？[Y=生成ics / n=继续添加] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "y"
            if confirm in ("", "y", "yes"):
                break
            print()
            continue

        if not raw:
            continue

        # 判断是文件路径还是文本
        parts = [p.strip() for p in raw.split(",")]
        looks_like_files = all(
            "/" in p or "\\" in p or any(p.lower().endswith(ext)
            for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".bmp"))
            for p in parts
        )

        image_paths: list[str] = []
        text_input: str | None = None

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
            # 多行文本：继续读取直到空行
            lines = [raw]
            while True:
                try:
                    line = input()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line.strip():
                    break
                lines.append(line)
            text_input = "\n".join(lines)

        img_label = f"{len(image_paths)} 张图片" if image_paths else ""
        txt_label = "文本" if text_input else ""
        label = " + ".join(filter(None, [img_label, txt_label]))
        print(f"⏳ 正在调用 AI 解析 ({label})...")

        try:
            parsed = parse_with_ai(
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

        # 文本输入则直接确认，图片可继续添加
        if text_input:
            try:
                confirm = input("  确认导入？[Y=生成ics / n=继续添加] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                confirm = "y"
            if confirm in ("", "y", "yes"):
                break
            print()
            continue

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
