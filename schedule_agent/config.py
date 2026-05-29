# 日程 Agent 配置常量
from __future__ import annotations
import os

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_PROJECT_DIR, ".env")
if os.path.isfile(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                if _key not in os.environ:
                    os.environ[_key] = _val.strip().strip("\"'")

CALENDAR_NAME = "个人日程"
CONFIRM_BEFORE_IMPORT = True
ICS_OUTPUT_FILE = os.path.join(_PROJECT_DIR, "output", "schedule.ics")
BADMINTON_ICS_FILE = os.path.join(_PROJECT_DIR, "output", "badminton.ics")
CALENDAR_URL = os.environ.get("CALENDAR_URL", "")
LOCATIONS_JSON = os.path.join(_PROJECT_DIR, "data", "locations.json")
LOCATIONS_EXAMPLE = os.path.join(_PROJECT_DIR, "data", "locations.example.json")
