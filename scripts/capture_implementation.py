"""Attach known artifacts to the actual test run for this implementation.

This is self-instrumented development evidence, not an imported provider export.
No inferred token usage, costs or hidden reasoning are added.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from devflight import Queue, Trace

queue=Queue('.devflight/implementation')
rows=queue.events()
root=next(e for e in reversed(rows) if e['event_type']=='run.started')
trace=Trace(queue,agent='codex',task='rawtree-ingestion',kind='instrumentation')
trace.run_id=root['run_id'];trace.trace_id=root['trace_id'];trace.parent_span_id=root['span_id']
trace.developer_id=root['developer_id'];trace.session_id=root['session_id']
trace.emit('agent.spawned',{'capture_method':'self-instrumented','purpose':'Attach code changed during this assistant task'})
for path in ('devflight/core.py','devflight/cli.py','devflight/adapters.py','devflight/collector.py','tests/test_telemetry.py'):
    trace.artifact(path)
trace.emit('agent.finished',{'capture_method':'self-instrumented'})
print(trace.trace_id)
