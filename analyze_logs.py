import json
import collections
from datetime import datetime

log_file = r'd:\game\mycode\devPython\python\trend_bot_6\trend_bot_6\data\journal.sim.jsonl'

events = collections.Counter()
errors = collections.Counter()
amend_count = 0
cancel_count = 0
place_count = 0
first_ts = None
last_ts = None
win_trades = 0
loss_trades = 0
total_profit = 0

print(f"Reading {log_file}...")
try:
    # Read the last 50000 lines or so
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    recent_lines = lines[-20000:] if len(lines) > 20000 else lines
    
    for line in recent_lines:
        try:
            record = json.loads(line)
        except:
            continue
            
        event = record.get('event')
        ts = record.get('ts_ms', 0)
        
        if not first_ts:
            first_ts = ts
        last_ts = ts
        
        events[event] += 1
        
        if event == 'amend_order_submitted':
            amend_count += 1
        elif event == 'place_order':
            place_count += 1
        elif event == 'cancel_order':
            cancel_count += 1
            
        if 'error' in event:
            errors[event] += 1
            payload = record.get('payload', {})
            reason = payload.get('reason', 'unknown')
            errors[f"Error: {event} - {reason}"] += 1

    duration_sec = (last_ts - first_ts) / 1000 if last_ts and first_ts else 0
    
    print(f"--- Log Analysis (Last {len(recent_lines)} lines) ---")
    print(f"Duration covered: {duration_sec:.1f} seconds ({(duration_sec/60):.1f} min)")
    print(f"Amends submitted: {amend_count} ({amend_count/max(1, duration_sec):.2f} / sec)")
    print(f"Places: {place_count}")
    print(f"Cancels: {cancel_count}")
    print("\nEvent Frequencies:")
    for k, v in events.most_common(10):
        print(f"  {k}: {v}")
    
    print("\nErrors (if any):")
    for k, v in errors.most_common(10):
        print(f"  {k}: {v}")
        
except FileNotFoundError:
    print("Log file not found.")
except Exception as e:
    print(f"Error: {e}")
