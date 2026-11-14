"""Real API verification: exact recovery, stable retries and native OTLP tables."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Queue,Trace
from devflight.core import atomic_json,file_lock
from devflight.rawtree import RawTree

writer=RawTree();reader=RawTree(read_only=True)
queue=Queue('.devflight/dedup-probe')
event=Trace(queue,agent='transport-test').emit('transport.probe',{'synthetic':True,'value':None,'array':[1,True,'text']})
identity='live-retry-'+event['event_id']
writer.insert('dev_events_raw',[event],identity)
writer.insert('dev_events_raw',[event],identity)
rows=reader.query("SELECT event_json AS event FROM dev_events_raw WHERE event_id = '"+event['event_id']+"'")
assert len(rows)==1,'Remote retry duplicated a physical row'
assert json.loads(rows[0]['event'])==event,'Lossless event recovery failed'
with file_lock(queue.home/'sync.lock'):
    state=queue.state();state['acked']=sorted(set(state['acked'])|{event['event_id']})
    atomic_json(queue.home/'sync.json',state)
implementation=Queue('.devflight/implementation')
rows=reader.query("SELECT event_json AS event FROM dev_events_raw WHERE session_id = 'telemetry-implementation-20261114' AND event_json IS NOT NULL ORDER BY sequence")
remote={json.loads(row['event'])['event_id']:json.loads(row['event']) for row in rows}
assert all(remote.get(e['event_id'])==e for e in implementation.events()),'Implementation trace recovery failed'
tables={}
for table in ('dev_events_raw','dev_artifacts_raw','dev_traces','dev_logs','dev_metrics'):
    tables[table]=reader.query('SELECT count() AS rows FROM '+table)[0]['rows']
    assert int(tables[table])>0,table+' is empty'
report={'database':reader.database,'transport':'HTTP API','tables':tables,'implementation_events_verified':len(remote),
        'retry_physical_rows':len(reader.query("SELECT event_id FROM dev_events_raw WHERE event_id = '"+event['event_id']+"'")),
        'lossless_recovery':True,'implementation_queue':implementation.status(),
        'collector_queue':Queue('.devflight/collector').status(),
        'notes':'Transport probes are synthetic. Implementation events record actual commands and artifacts; no external new model session was invoked.'}
Path('documentation/telemetry-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
