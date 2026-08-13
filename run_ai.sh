#!/bin/bash
# ============================================================================
#  🤖 AI 日程助手 · 一键启动脚本（双击运行）
# ----------------------------------------------------------------------------
#  双击运行：自动在「终端」中打开，并默认进入 AI 日程解析模式（main.py --ai）
#  终端手动运行：
#     ./run_ai.sh              # AI 日程解析模式（Cmd+V 粘贴截图 / 输入文本 → AI 解析 → .ics → 导入日历）
#     ./run_ai.sh --check-env  # 只检查环境，不启动程序
# ============================================================================
set -u

# ── 0. Finder 双击 / open 启动时，自动在「终端」中运行 ─────────────────────
if [ -z "${TERM_PROGRAM:-}" ] && [ "$(uname -s)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
  SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  SELF_ESC="$(printf '%s' "$SELF" | sed "s/'/'\\\\''/g")"
  osascript -e 'tell application "Terminal"' -e 'activate' \
    -e "do script \"bash '$SELF_ESC'\"" -e 'end tell' >/dev/null 2>&1
  exit 0
fi

# ── 1. 进入脚本所在目录（保证双击时工作目录正确）──────────────────────────
cd "$(dirname "$0")" || { echo "❌ 无法进入项目目录"; exit 1; }
PROJECT_DIR="$(pwd)"

echo "================================================================"
echo "   🤖 AI 日程助手 · 日程文本/图片 → .ics → 日历"
echo "================================================================"
echo "  项目目录: $PROJECT_DIR"

# ── 2. 准备 Python 环境（优先使用已有 .venv）────────────────────────────
PY=""
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
  echo "  ✅ 使用已有虚拟环境 .venv"
else
  echo "  ⏳ 未找到 .venv，正在创建虚拟环境..."
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv >/dev/null && uv pip install --python .venv/bin/python openai >/dev/null 2>&1 \
      || { echo "  ❌ 创建虚拟环境失败（uv），请手动运行: uv sync && uv pip install openai"; exit 1; }
  else
    python3 -m venv .venv && .venv/bin/pip install -q openai \
      || { echo "  ❌ 创建虚拟环境失败，请确认已安装 Python 3.11+"; exit 1; }
  fi
  PY=".venv/bin/python"
  echo "  ✅ 虚拟环境创建完成"
fi

# openai 依赖检查（--ai 模式必需）
if ! "$PY" -c "import openai" >/dev/null 2>&1; then
  echo "  ⏳ 正在安装 openai 依赖..."
  "$PY" -m pip install -q openai \
    || { echo "  ❌ 安装 openai 失败，请手动运行: $PY -m pip install openai"; exit 1; }
  echo "  ✅ openai 安装完成"
fi

# ── 3. 检查 .env 配置（OPENAI_API_KEY）──────────────────────────────────
if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "  ⚠️  已从 .env.example 生成 .env"
fi
API_KEY="$(grep -E '^[[:space:]]*OPENAI_API_KEY=' ".env" | head -1 | cut -d= -f2- | sed "s/^[\"']//; s/[\"']$//" | xargs)"
if [ -z "$API_KEY" ] || [ "$API_KEY" = "sk-..." ]; then
  echo ""
  echo "  ❌ 未配置 OPENAI_API_KEY，无法调用 AI。"
  echo "     请编辑 .env 文件，填入你的 API Key："
  echo "       OPENAI_API_KEY=sk-xxxx"
  echo "     兼容任意 OpenAI 接口（DeepSeek / Qwen / 硅基流动 等），"
  echo "     如需自定义接口，可同时配置 OPENAI_BASE_URL / OPENAI_MODEL。"
  echo ""
  if [ "$(uname -s)" = "Darwin" ]; then
    open -e ".env" 2>/dev/null && echo "  📝 已用文本编辑器打开 .env"
  fi
  echo ""
  read -r -p "  按回车键退出..." _
  exit 1
fi

# ── 4. 启动程序（默认 AI 模式）──────────────────────────────────────────
CHECK_ONLY=0
case "${1:-}" in
  --check-env) CHECK_ONLY=1 ;;
  "") ;;
  *) echo "  ⚠️  未知参数: $1（仅支持 --check-env）" ;;
esac

echo ""
if [ "$CHECK_ONLY" = "1" ]; then
  echo "  ✅ 环境检查通过"
  echo "  📦 Python: $("$PY" --version 2>&1)"
  echo "  📦 openai : $("$PY" -c "import openai; print(openai.__version__)" 2>/dev/null || echo "未知")"
  echo "  📄 .env   : 已配置 OPENAI_API_KEY"
  exit 0
fi

echo "  🚀 启动 AI 日程解析模式（Cmd+V 粘贴截图 / 输入文本，d 生成 / q 退出）..."
echo ""
"$PY" main.py

echo ""
echo "  ✅ 程序已结束"
read -r -p "  按回车键关闭窗口..." _
