import json
from datetime import datetime, timedelta

log_file = r'd:\game\mycode\devPython\python\trend_bot_6\trend_bot_6\data\journal.sim.jsonl'
cutoff = datetime.now() - timedelta(minutes=15)

print(f"Reading order_update from {cutoff} to now...")
try:
    with open(log_file, 'r', encoding='utf-8') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 10 * 1024 * 1024))
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
        if event == 'order_update':
            payload = record.get('payload', {})
            state = payload.get('state')
            fillSz = payload.get('fillSz', '0')
            px = payload.get('px')
            sz = payload.get('sz')
            print(f"[{dt.strftime('%H:%M:%S')}] order_update: state={state}, fillSz={fillSz}, px={px}, sz={sz}")

except Exception as e:
    print(e)
