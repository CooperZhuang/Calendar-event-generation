# 羽毛球订阅同步
from __future__ import annotations
import os
from datetime import datetime, timezone
from .ics_utils import fetch_ics, unfold_ics, split_vevents, _get_prop, _prop_value
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
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        f"X-PUBLISHED-TTL:PT1H",
    ]
    for block in matched_blocks:
        lines.append(block)
    lines.append("END:VCALENDAR")

    ics_content = "\r\n".join(lines) + "\r\n"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ics_content)
    print(f"  → 已更新 {output_path}（{len(matched_blocks)} 个羽毛球事件）")
    return len(matched_blocks)
