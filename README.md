# 🏸 calendar-event-generation

[![Dependencies](https://img.shields.io/badge/dependencies-zero-success)](https://github.com/CooperZhuang/calendar-event-generation/blob/main/pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

结构化日程文本 / JSON → `.ics` 日历事件，一键导入 Apple / Google / Outlook 日历。纯 Python，零依赖。

## 快速开始

```bash
git clone https://github.com/CooperZhuang/calendar-event-generation.git
cd calendar-event-generation

# 文本输入
python3 schedule_agent.py "标题：羽毛球
开始日期：2026-06-07
开始时间：14:00
结束日期：2026-06-07
结束时间：16:00
地点：上海奥埔篮羽运动中心
描述：费用：¥34"

# JSON 输入
python3 schedule_agent.py << 'EOF'
[
  {
    "title": "项目周会",
    "start_date": "2026-06-15",
    "start_time": "09:00",
    "end_date": "2026-06-15",
    "end_time": "10:00",
    "location_name": "3号会议室",
    "description": "本周进度同步"
  }
]
EOF

# 交互式问答
python3 schedule_agent.py -i
```

> Python ≥ 3.11。macOS 可直接导入日历应用；其他平台输出 `.ics` 文件。

## 特性

- **智能地点匹配** — 预设场馆数据库，模糊匹配 + Apple Maps 精确定位
- **灵活时间解析** — 中文日期、相对日期（明天/本周五）、全天事件、自动跨天
- **双重去重** — 输入内部去重 + iCloud 日历交叉比对
- **标题归一化** — "羽毛球活动""打羽毛球" → "羽毛球"
- **自动发现新地点** — iCloud 事件中未知场馆自动提取入库

## 输入格式

文本标签与 JSON 字段一一对应，中英文标签均可：

| 标签 | JSON | 示例 |
|------|------|------|
| `标题：` | `title` | `羽毛球` |
| `开始日期：` | `start_date` | `2026-06-07` |
| `开始时间：` | `start_time` | `14:00` |
| `结束日期：` | `end_date` | `2026-06-07` |
| `结束时间：` | `end_time` | `16:00` |
| `地点：` | `location_name` | `上海奥埔篮羽运动中心` |
| `地址：` | `address` | 辅助地点匹配 |
| `描述：` | `description` | 自由文本，支持多行 |
| `全天：` | `is_all_day` | `true` / `false` |

**便捷写法：** `时间：明天 14:00 - 16:00` 替代四个日期时间字段，自动解析中文日期（6月7日）、相对日期、跨天（22:00 - 02:00）。

`描述：` 之后的行持续捕获直到下一个字段或输入结束：

```
描述：费用：¥34
人数：男1 女1
场地：6号
```

## 羽毛球订阅

CI 每 6 小时从 iCloud 拉取日历，按关键字匹配羽毛球活动，生成 `badminton.ics` 推送至 Secret Gist。Gist 不被索引、不可搜索——仅持有完整链接者可订阅。

```bash
python3 schedule_agent.py --sync-badminton   # 手动触发
```

订阅者将 Gist raw URL 添加至日历应用即可，每 12 小时自动刷新。

## 配置

```bash
export CALENDAR_URL="https://pXX-caldav.icloud.com/published/2/..."
```

CI Secrets：

| Secret | 说明 |
|--------|------|
| `CALENDAR_URL` | iCloud 日历发布链接 |
| `GIST_TOKEN` | GitHub PAT（`gist` 权限） |
| `GIST_ID` | Secret Gist ID |

## 项目结构

```
schedule_agent.py
locations.json                 # 场馆数据库
tests/test_all.py              # 73 项测试
example/schedule.json
.github/workflows/
├── test.yml                   # CI
└── sync-badminton.yml         # 每 6h 同步
```

## License

MIT © Cooper Zhuang
