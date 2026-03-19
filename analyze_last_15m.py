import json
from datetime import datetime, timedelta
import collections

log_file = r'd:\game\mycode\devPython\python\trend_bot_6\trend_bot_6\data\journal.sim.jsonl'
events = collections.Counter()
cutoff = datetime.now() - timedelta(minutes=15)
amend_count = 0
decision_count = 0 
cancel_count = 0
place_count = 0

print(f"Reading logs from {cutoff} to now...")
try:
    with open(log_file, 'r', encoding='utf-8') as f:
        # Seek near the end roughly
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 100 * 1024 * 1024)) # read last 100MB
        lines = f.readlines()
        
    for line in lines:
        if not line.strip(): continue
        try:
            record = json.loads(line)
        except:
            continue
            
        ts = record.get('ts_ms')
        if not ts: continue
        dt = datetime.fromtimestamp(ts/1000)
        
        if dt < cutoff: continue
        
        event = record.get('event')
        events[event] += 1
        
        if event == 'amend_order_submitted': amend_count += 1
        elif event == 'decision': decision_count += 1
        elif event == 'place_order': place_count += 1
        elif event == 'cancel_order': cancel_count += 1
        
        if 'error' in event:
            payload = record.get('payload', {})
            error = payload.get('error', '')
            reason = payload.get('reason', '')
            events[f"ERROR: {event} ({reason}) - {error}"] += 1

    print("\n--- Last 15 Minutes ---")
    print(f"Decisions: {decision_count}") 
    print(f"Amends: {amend_count}")
    print(f"Cancels: {cancel_count}")
    print(f"Places: {place_count}")
    
    print("\nTop Events/Errors:")
    for k, v in events.most_common(20):
        print(f"  {k}: {v}")
        
except Exception as e:
    print(e)
