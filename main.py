#!/usr/bin/env python3
"""日程 Agent — AI 日程解析模式入口

用法：
   python3 main.py      # 进入 AI 模式（Cmd+V 粘贴截图 / 输入文本 → AI 解析 → .ics → 导入日历）
"""
from schedule_agent.cli import ai_mode

def main():
    ai_mode()

if __name__ == "__main__":
    main()
