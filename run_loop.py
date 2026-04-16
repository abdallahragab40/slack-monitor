#!/usr/bin/env python3
"""
Cloud runner for slack_monitor.py
Runs the monitor every 2 minutes, only during UK work hours (Mon-Fri, 9AM-5PM BST/GMT).
Deploy this file on Railway, Render, or any cloud Python host.
"""

import time
import importlib.util
import os
import sys
from datetime import datetime
import pytz

# Path to the monitor script (same directory)
MONITOR_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_monitor.py")

# Work hours config (UK timezone)
UK_TZ         = pytz.timezone("Europe/London")
WORK_START_HR = 9   # 9 AM UK
WORK_END_HR   = 17  # 5 PM UK
WORK_DAYS     = {0, 1, 2, 3, 4}  # Monday=0 ... Friday=4

CHECK_INTERVAL_SECONDS = 120  # Run every 2 minutes


def is_work_hours() -> bool:
    now_uk = datetime.now(UK_TZ)
    if now_uk.weekday() not in WORK_DAYS:
        return False
    return WORK_START_HR <= now_uk.hour < WORK_END_HR


def run_monitor():
    """Dynamically load and run slack_monitor.main()"""
    spec = importlib.util.spec_from_file_location("slack_monitor", MONITOR_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def main():
    print("=== Slack Monitor Cloud Runner ===")
    print(f"Check interval : every {CHECK_INTERVAL_SECONDS // 60} minutes")
    print(f"Active hours   : Mon-Fri {WORK_START_HR}:00-{WORK_END_HR}:00 UK time")
    print("==================================\n")

    while True:
        if is_work_hours():
            try:
                run_monitor()
            except Exception as e:
                print(f"[ERROR] Monitor crashed: {e}", file=sys.stderr)
        else:
            now_uk = datetime.now(UK_TZ)
            print(f"[{now_uk.strftime('%Y-%m-%d %H:%M %Z')}] Outside work hours — sleeping...")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
