# 🏸 calendar-event-generation

[![Dependencies](https://img.shields.io/badge/dependencies-zero-success)](https://github.com/CooperZhuang/calendar-event-generation/blob/main/pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

结构化日程文本 / JSON → `.ics` 日历事件，一键导入 Apple / Google / Outlook 日历。纯 Python，零依赖。

## 为什么有这个项目

日常收到大量碎片化的日程信息——微信群截图、活动海报、邮件通知、订场确认。手动录入日历又慢又容易出错，尤其是场馆地址要在 Apple Maps 里手动搜索定位，每次都得反复放大缩小确认。

这个项目把流程拆成两步：

1. **📸 图片/OCR → 结构化 JSON** — 把截图发给任意支持视觉的 AI，用下方的 [Prompt](#图片ocr--json-prompt) 一键提取为标准 JSON
2. **📅 JSON → .ics 日历文件** — 把 JSON 喂给 `main.py`，自动生成带精确地图坐标的 `.ics`，双击即可导入系统日历

或者更简单——直接用内置的 `--ai` 模式，一步到位。

## 快速开始

```bash
git clone https://github.com/CooperZhuang/calendar-event-generation.git
cd calendar-event-generation

# 文本输入
python3 main.py "标题：羽毛球
开始日期：2026-06-07
开始时间：14:00
结束日期：2026-06-07
结束时间：16:00
地点：上海奥埔篮羽运动中心
描述：费用：¥34"

# JSON 输入
python3 main.py << 'EOF'
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
python3 main.py -i
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

## 🤖 AI 图片/文本解析
### 方式一：`--ai` 内置模式（推荐）

Cmd+V 粘贴截图，程序自动检测剪贴板并累积多张图片，确认后一次性 AI 解析生成 `.ics`：

```bash
# 1. 配置 API Key
cp .env.example .env      # 编辑 .env，填入 OPENAI_API_KEY（兼容任意 OpenAI 接口）

# 2. 安装依赖
pip install openai

# 3. 启动
python3 main.py --ai
```

```
🤖 AI 日程解析模式
模型: gpt-4o | API: https://api.openai.com/v1

📋 图片/文本 > [Cmd+V 粘贴截图 → 自动检测并读取剪贴板]
  📋 检测到剪贴板图片，读取中...
  ✅ 已读取剪贴板图片 (324158 字节) [累计 1 张]
  还要添加更多图片吗？[回车=添加 / n=解析生成ics]  [回车继续 Cmd+V]

📋 图片/文本 > [Cmd+V 粘贴第二张]
  ✅ 已读取剪贴板图片 (298401 字节) [累计 2 张]
  还要添加更多图片吗？[回车=添加 / n=解析生成ics] n

⏳ 正在调用 AI 解析 (2 张图片)...
✅ 解析到 3 个日程

📋 图片/文本 > d
→ .ics 已保存: schedule.ics
```

也支持直接粘贴文本（非结构化日程描述）、输入文件路径。兼容 DeepSeek、Qwen 等任意 OpenAI 兼容接口。

### 方式二：手动复制 Prompt

把活动海报、微信群截图发给 ChatGPT / Claude 时使用以下 Prompt：

<details>
<summary>📋 点击展开完整 Prompt</summary>

```
# 角色与任务

你是一个极其严格、具备高泛化能力的通用日程事件解析器。请接收图片 OCR 结果或任意结构化的日程文本输入，将其解析为标准化的 JSON 输出，供下游程序自动生成标准日历 .ics 文件。

# 核心约束

1. 必须且只能输出一个合法的 JSON 字符串。
2. 严禁包含任何解释性文字、前后缀，严禁将 JSON 包裹在 ```json ... ``` 等 Markdown 代码块中。

# 上下文基准（用于推算相对时间和缺失的年份）

- 当前系统时间：{{CURRENT_TIME}} （请程序调用时动态替换，例如：2026-05-26 Tuesday）

# 输出 JSON 格式

[{
  "title": "字符串，事件主体/标题名称。如果原始文本没有明确标题，请根据内容提炼一个简短、概括性的标题，绝不留空",
  "start_date": "YYYY-MM-DD 格式。若输入无显式年份，则默认使用 `# 上下文基准` 中的年份",
  "start_time": "HH:MM 格式，24小时制。若是全天活动，设为空字符串 \"\"",
  "end_date": "YYYY-MM-DD 格式。跨天事件需根据时间差自动计算并调整日期",
  "end_time": "HH:MM 格式，24小时制。若是全天活动，设为空字符串 \"\"",
  "is_all_day": 布尔值,
  "location_name": "字符串，事件发生具体的地点、场馆、房间或会议室名称。如果没有明确地点，设为空字符串 \"\"",
  "description": "字符串，将文本中所有不属于时间、地点的非核心关键信息（如备注、费用、参与人、座位号、组织者等），按 '原文字段名：具体值' 的格式用 \\n 拼接输出。若无任何附加信息，设为 \"\""
}]

# 解析与推算规则

## 1. 时间解析规则（核心）

- **格式化规范**：日期必须严格为 "YYYY-MM-DD"，时间必须严格为 "HH:MM"。
- **相对时间推算**：依据 `# 上下文基准` 提供的当前时间，准确推算诸如"今天"、"明天"、"本周五"、"下周三"的具体公历日期。
- **全天活动判定**：若输入只有日期，完全没有提及任何具体整点时间（例如："6月1日儿童节"、"本周五团建"），则判定 `is_all_day = true`，且 `start_time` 和 `end_time` 填充为 `""`。
- **自动跨天处理**：若结束时间在数值上小于开始时间（例如：22:00 - 02:00），默认视为跨越到次日，`end_date` 必须在 `start_date` 的基础上自动加 1 天。

## 2. 地点提取规则

- 准确提取文本中代表空间位置的文本（如"1号会议室"、"百丽宫影城5号厅"、"奥埔篮羽运动中心"）。
- **不要**在提示词中硬编码任何特定场馆。保持对原始地点的无损提取。

## 3. 描述生成规则

- 提炼所有零散的附加信息。例如输入中含有"票价：50元，座位：3排2座"，需转换为 `"description": "票价：50元\n座位：3排2座"`。

## 4. 上下文规则

- 不考虑上下文，我会一次性把所有图片发给你，历史对话对你来说没有意义

## 5. 去重

- 给到的图片可能包含重复的日程，自动去除

## 6. 特殊状态

- 如果提到已退款，则应该忽略跳过，不要输出这部分
```

</details>

将 Prompt 中的 `{{CURRENT_TIME}}` 替换为当日日期（如 `2026-05-28 Wednesday`），与截图一起发给 AI，将返回的 JSON 保存后运行：

```bash
cat event.json | python3 main.py
```

## 羽毛球订阅

CI 每 6 小时从 iCloud 拉取日历，按关键字匹配羽毛球活动，生成 `badminton.ics` 推送至 Secret Gist。Gist 不被索引、不可搜索——仅持有完整链接者可订阅。

```bash
python3 main.py --sync-badminton   # 手动触发
```

订阅者将 Gist raw URL 添加至日历应用即可，每 12 小时自动刷新。

## 配置

复制模板并填入真实值：

```bash
cp .env.example .env
```

| 变量 | 说明 | 必填 |
|------|------|------|
| `CALENDAR_URL` | iCloud 日历发布链接（去重 + 发现新地点） | 否 |
| `OPENAI_API_KEY` | AI 解析 API Key | `--ai` 模式下必填 |
| `OPENAI_BASE_URL` | 兼容接口地址，默认 `https://api.openai.com/v1` | 否 |
| `OPENAI_MODEL` | 模型名，默认 `gpt-4o` | 否 |

CI Secrets（GitHub Actions）：

| Secret | 说明 |
|--------|------|
| `CALENDAR_URL` | iCloud 日历发布链接 |
| `GIST_TOKEN` | GitHub PAT（`gist` 权限） |
| `GIST_ID` | Secret Gist ID |

## 项目结构
```
main.py                        # CLI 入口
schedule_agent/                # 核心包
├── __init__.py
├── ai_parser.py               # AI 图片/文本解析
├── cli.py                     # 命令行处理
├── config.py                  # 环境变量读取
├── events.py                  # 事件模型
├── ics_utils.py               # ICS 文件生成
├── locations.py               # 场馆坐标匹配
├── parser.py                  # 文本解析
└── sync.py                    # iCloud 日历同步
data/
└── locations.json             # 场馆数据库
tests/
├── test_all.py                # 83 项测试
└── fixtures/schedule.json
.env.example                   # 配置文件模板
.github/workflows/
└── sync-badminton.yml         # 每 6h 同步
```

## License

MIT © Cooper Zhuang
