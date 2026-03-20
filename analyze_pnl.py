import json
from datetime import datetime, timedelta
import collections

log_file = r'd:\game\mycode\devPython\python\trend_bot_6\trend_bot_6\data\journal.sim.jsonl'
cutoff = datetime.now() - timedelta(hours=3) # Look further back to see more action

fills = 0
total_pnl = 0

print(f"Reading logs from {cutoff} to now...")
try:
    with open(log_file, 'r', encoding='utf-8') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 200 * 1024 * 1024))
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
        payload = record.get('payload', {})
        
        if event == 'order_update':
            if payload.get('state') == 'filled' or float(payload.get('fillSz', 0)) > 0:
                fills += 1
                
        # Look for custom profit logging if any
        if 'realized_pnl' in line or event == 'realized_pnl':
            # This depends on the bot's specific PNL logging
            pnl = payload.get('pnl', 0)
            if pnl:
                total_pnl += float(pnl)

    print(f"\nFills (partial or full) in last 3 hours: {fills}")
    print(f"Total Logged PNL events found: {total_pnl}")
        
except Exception as e:
    print(e)
