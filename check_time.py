import json
from datetime import datetime
import os

log_file = r'd:\game\mycode\devPython\python\trend_bot_6\trend_bot_6\data\journal.sim.jsonl'
try:
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        if lines:
            last_line = lines[-1]
            record = json.loads(last_line)
            ts = record.get('ts_ms')
            if ts:
                dt = datetime.fromtimestamp(ts/1000)
                print(f"Last log timestamp: {dt}")
        print(f"File size: {os.path.getsize(log_file)} bytes")
except Exception as e:
    print(e)
