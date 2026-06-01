# 命令行交互模式（AI 模式 / 交互模式）
from __future__ import annotations
import json
import os
import select
import subprocess
import sys
import tempfile
import termios
import time
import tty
from datetime import datetime, timedelta

from .ai_parser import parse_with_ai
from .config import (
    BADMINTON_KEYWORDS, CALENDAR_NAME, CONFIRM_BEFORE_IMPORT, ICS_OUTPUT_FILE,
    BADMINTON_ICS_FILE, CALENDAR_URL, LOCATIONS_JSON, _PROJECT_DIR,
)
from .locations import load_locations, update_locations_from_ics
from .ics_utils import fetch_ics, unfold_ics, split_vevents, parse_ics_events, generate_ics, generate_combined_ics
from .parser import parse_input, parse_input_batch
from .events import build_event, save_ics_file, print_preview, check_duplicate_via_ics, dedup_events_internal, import_to_calendar
from .sync import sync_badminton_ics

def _clipboard_has_image() -> bool:
    """检测剪贴板是否包含图片"""
    try:
        result = subprocess.run(
            ["osascript", "-e", "get the clipboard as «class PNGf»"],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0 and result.stdout.strip().startswith("«data PNGf")
    except Exception:
        return False

def _read_clipboard_image() -> str | None:
    """从剪贴板读取图片，保存为临时 PNG，返回路径"""
    try:
        result = subprocess.run(
            ["osascript", "-e", "get the clipboard as «class PNGf»"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        hex_str = result.stdout.strip()
        if not hex_str.startswith("«data PNGf"):
            return None
        hex_data = hex_str[len("«data PNGf"):].rstrip("»")
        img_bytes = bytes.fromhex(hex_data.replace(" ", ""))
        tmp_path = os.path.join(tempfile.gettempdir(), f"codex_clipboard_{os.getpid()}.png")
        with open(tmp_path, "wb") as f:
            f.write(img_bytes)
        return tmp_path
    except Exception:
        return None

def _cleanup_tmp(path: str):
    """删除临时文件（忽略错误）"""
    try:
        os.remove(path)
    except OSError:
        pass

def _clear_clipboard():
    """清空剪贴板"""
    try:
        subprocess.run(
            ["osascript", "-e", 'set the clipboard to ""'],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass

def _input_paste_aware(prompt):
    """读取用户输入，同时监控剪贴板。

    如果检测到剪贴板图片且用户尚未输入任何文字，立即返回 ("", True)。
    否则等用户按回车后返回 (输入内容, False)。
    """
    print(prompt, end="", flush=True)

    old = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin)
        buffer = []
        last_check = 0.0
        while True:
            now = time.time()
            if now - last_check > 0.2:
                last_check = now
                if not buffer and _clipboard_has_image():
                    sys.stdout.write("\r\n  \U0001f4cb 检测到剪贴板图片！\r\n")
                    sys.stdout.flush()
                    return ("", True)

            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not r:
                continue

            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch == "\x04":
                raise EOFError
            elif ch in ("\x7f", "\x08"):
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            elif ch == "\x1b":
                try:
                    r2, _, _ = select.select([sys.stdin], [], [], 0.01)
                    if r2:
                        sys.stdin.read(1)
                        r3, _, _ = select.select([sys.stdin], [], [], 0.01)
                        if r3:
                            sys.stdin.read(1)
                except Exception:
                    pass
            elif ch.isprintable() or ch == "\t":
                buffer.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)

    return ("".join(buffer), False)


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
    print("  图片: Cmd+V 粘贴截图 → 可添加多张 → 确认后 AI 解析生成 .ics")
    print("  文本: 直接粘贴日程描述（多行粘贴后补空行，解析后即确认导入）")
    print("  命令: d 生成ics | q 退出")
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
    pending_images: list[str] = []  # 待解析的剪贴板图片临时路径

    while True:
        try:
            raw, paste_img = _input_paste_aware("📋 图片/文本 > ")
            if paste_img:
                raw = ":img"
            else:
                raw = raw.strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw.lower() == "q":
            # 清理待解析图片
            for p in pending_images:
                _cleanup_tmp(p)
            pending_images.clear()
            print("👋 已退出")
            return

        if raw.lower() == "d":
            # 有待解析图片 → 自动解析
            if pending_images:
                print(f"⏳ 正在调用 AI 解析 ({len(pending_images)} 张待解析图片)...")
                try:
                    parsed = parse_with_ai(image_paths=list(pending_images))
                except Exception as e:
                    print(f"  ❌ AI 解析失败: {e}")
                    for p in pending_images:
                        _cleanup_tmp(p)
                    pending_images.clear()
                    continue
                for p in pending_images:
                    _cleanup_tmp(p)
                pending_images.clear()
                if parsed:
                    print(f"  ✅ 解析到 {len(parsed)} 个日程：\n")
                    for ev in parsed:
                        event = build_event(ev, locations)
                        print_preview(event)
                        all_events.append(event)
                        print()
            if not all_events:
                print("⚠️  还没有收集到任何日程")
                continue
            break

        # ── 剪贴板图片粘贴检测 ──
        if _clipboard_has_image():
            raw_parts = [p.strip() for p in raw.split(",")]
            is_paths = all(
                "/" in p or "\\" in p or any(p.lower().endswith(ext)
                for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".bmp"))
                for p in raw_parts
            ) if raw else False
        else:
            is_paths = False
        if raw.lower() == ":img" or (not is_paths and raw.lower() not in ("q", "d") and _clipboard_has_image()):
            print("  📋 检测到剪贴板图片，读取中...")
            tmp_path = _read_clipboard_image()
            if not tmp_path:
                print("  ❌ 剪贴板中没有图片")
                continue
            pending_images.append(tmp_path)
            _clear_clipboard()
            print(f"  ✅ 已读取剪贴板图片 ({os.path.getsize(tmp_path)} 字节) [累计 {len(pending_images)} 张]")
            try:
                more = input("  还要添加更多图片吗？[回车=添加 / n=解析生成ics] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                more = "n"
            if more in ("", "y", "yes"):
                print("  → 请继续 Cmd+V 粘贴下一张图片\n")
                continue
            # 不再添加 → 解析所有累积图片
            print(f"⏳ 正在调用 AI 解析 ({len(pending_images)} 张图片)...")
            try:
                parsed = parse_with_ai(image_paths=list(pending_images))
            except Exception as e:
                print(f"  ❌ AI 解析失败: {e}")
                for p in pending_images:
                    _cleanup_tmp(p)
                pending_images.clear()
                continue
            for p in pending_images:
                _cleanup_tmp(p)
            pending_images.clear()

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

        # ── 无图片但有待解析图片 → 自动解析 ──
        if pending_images:
            print(f"⏳ 正在调用 AI 解析 ({len(pending_images)} 张待解析图片)...")
            try:
                parsed = parse_with_ai(image_paths=list(pending_images))
            except Exception as e:
                print(f"  ❌ AI 解析失败: {e}")
                for p in pending_images:
                    _cleanup_tmp(p)
                pending_images.clear()
                continue
            for p in pending_images:
                _cleanup_tmp(p)
            pending_images.clear()

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
            status, matched = check_duplicate_via_ics(ics_events, event)
            if status == "identical":
                print(f"  ⏭️  「{event['title']}」{event['start_date']} 已存在，跳过")
            elif status == "update":
                old_start = matched.get("start_time", "?")
                old_end = matched.get("end_time", "?")
                print(f"  🔄 「{event['title']}」{event['start_date']} 时间变更: {old_start}~{old_end} → {event['start_time']}~{event['end_time']}")
                deduped.append(event)
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
    badminton_kw = BADMINTON_KEYWORDS
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
    print('    {"标题": "羽毛球活动", "时间": "2026-05-31 19:00-21:00", ...}')
    print()
    print("  JSON 数组（批量导入）：")
    print('    [{"标题": "...", ...}, {"标题": "...", ...}]')
    print()
    print("  多段文本（用 --- 或空行分隔多条日程）：")
    print("    标题：活动一")
    print("    时间：2026-05-31 19:00-21:00")
    print("    地点：场地A")
    print()
    print("    ---")
    print()
    print("    标题：活动二")
    print("    时间：2026-06-01 14:00-16:00")
    print("    地点：场地B")
    print()
    print("  输入完成后补一个空行提交。")
    print("=" * 60)
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

    print("💬 请粘贴日程内容（输入完成后补一个空行确认）：\n")

    lines = []
    blank_count = 0
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if not line.strip():
            blank_count += 1
            if blank_count >= 2:
                break
        else:
            blank_count = 0
        lines.append(line)

    raw_text = "\n".join(lines).strip()
    if not raw_text:
        print("👋 没有输入任何内容")
        return

    print()
    print("⏳ 正在解析...")
    try:
        events_data = parse_input_batch(raw_text)
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        return

    if not events_data:
        print("❌ 未能解析出有效日程，请检查格式")
        return

    all_events = []
    for data in events_data:
        event = build_event(data, locations)
        print_preview(event)
        all_events.append(event)
        print()

    try:
        confirm = input("  确认导入？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "y"
    if confirm not in ("", "y", "yes"):
        print("👋 已取消")
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
            status, matched = check_duplicate_via_ics(ics_events, event)
            if status == "identical":
                print(f"  ⏭️  「{event['title']}」{event['start_date']} 已存在，跳过")
            elif status == "update":
                old_start = matched.get("start_time", "?")
                old_end = matched.get("end_time", "?")
                print(f"  🔄 「{event['title']}」{event['start_date']} 时间变更: {old_start}~{old_end} → {event['start_time']}~{event['end_time']}")
                deduped.append(event)
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
    badminton_kw = BADMINTON_KEYWORDS
    if CALENDAR_URL:
        try:
            print("  🏸 更新羽毛球订阅日历...")
            sync_badminton_ics(CALENDAR_URL, badminton_kw, BADMINTON_ICS_FILE)
        except Exception as e:
            print(f"  ⚠️  同步羽毛球订阅失败: {e}")

    print("\n  ✅ 完成！")
