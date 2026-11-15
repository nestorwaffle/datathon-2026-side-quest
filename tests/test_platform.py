import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from devflight.identity import Store
from devflight.platform import Analytics, create_app
from devflight.explorer import Explorer


class QueryClient:
    def __init__(self): self.queries=[]
    def query(self,sql):
        self.queries.append(sql)
        return [{"events":1,"errors":0,"session_id":"test-session","event_id":"test-event"}]

class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.store.bootstrap()
        self.token=(self.store.home/"admin.token").read_text().strip()
        self.admin=self.store.authenticate(self.token,"login")
        self.client=QueryClient();self.analytics=Analytics(self.client)

    def user(self,role="member"):
        data=self.store.manage(self.admin,{"kind":"user","name":"Test user","role":role})
        return self.store.authenticate(data["credential"],"login"),data["credential"]

    def test_authenticated_ingest_overrides_forged_org_and_user(self):
        member,_=self.user()
        row=self.store.ingest(member,{"org_id":"victim","user_id":"victim","event_id":"same","session_id":"a"})
        self.assertEqual(row["org_id"],member["org_id"])
        self.assertEqual(row["user_id"],member["user_id"])
        self.store.ingest(member,{"event_id":"same"})
        self.assertEqual(self.store.status()["total"],1)

    def test_five_producers_remain_durable_across_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        def produce(number):
            return [self.store.ingest(self.admin,{'event_id':f'{number}-{i}','session_id':f'session-{number}'})['event_id'] for i in range(4)]
        with ThreadPoolExecutor(max_workers=5) as pool: identifiers=[event for batch in pool.map(produce,range(5)) for event in batch]
        self.assertEqual(len(set(identifiers)),20)
        reopened=Store(self.temp.name)
        self.assertEqual(reopened.status()['pending'],20)
        with reopened.db() as db: self.assertEqual(db.execute('SELECT count(DISTINCT json_extract(payload,\'$.session_id\')) FROM outbox').fetchone()[0],5)

    def test_revocation_is_individual_and_org_scoped(self):
        token=self.store.issue(self.admin,"ingest")
        from devflight.identity import digest
        self.store.manage(self.admin,{"kind":"revoke_key","credential_id":digest(token)})
        with self.assertRaises(PermissionError):self.store.authenticate(token,"ingest")
        self.assertEqual(self.store.authenticate(self.token,"login")["role"],"admin")

    def test_role_change_applies_to_existing_session_and_ingest_credentials(self):
        member,_=self.user()
        session=self.store.issue(member)
        ingest=self.store.issue(member,"ingest")
        self.store.manage(self.admin,{"kind":"membership","user_id":member['user_id'],"role":"viewer"})
        self.assertEqual(self.store.authenticate(session)['role'],'viewer')
        with self.assertRaises(PermissionError):self.store.ingest(self.store.authenticate(ingest,'ingest'),{'event_id':'denied'})
        with self.assertRaises(ValueError):self.store.manage(self.admin,{"kind":"membership","user_id":self.admin['user_id'],"role":"viewer"})

    def test_member_and_manager_scope_enforced_in_sql(self):
        member,_=self.user()
        self.analytics.query_tool(member,"overview",{})
        self.assertIn("user_id='"+member["user_id"]+"'",self.client.queries[-1])
        with self.assertRaises(ValueError):self.analytics.query_tool(member,"overview",{"org_id":"other"})
        with self.assertRaises(PermissionError):self.analytics.query_tool(member,"run_sql",{"sql":"SELECT *"})

    def test_unassigned_manager_cannot_read_other_unassigned_investigations(self):
        manager,_=self.user("team_manager")
        member,_=self.user()
        self.store.save_investigation(member,{"id":"private-member-investigation"})
        self.assertEqual(self.store.list_investigations(manager),[])
        self.assertEqual([u['id'] for u in self.store.settings(manager)['users']],[manager['user_id']])

    def test_org_switch_and_cache_cannot_cross_memberships(self):
        second=self.store.manage(self.admin,{"kind":"organization","name":"Second"})["id"]
        switched=self.store.authenticate(self.store.switch(self.admin,second))
        self.analytics.query_tool(self.admin,"overview",{})
        self.analytics.query_tool(switched,"overview",{})
        self.assertEqual(len(self.client.queries),2)
        self.assertNotEqual(self.client.queries[0],self.client.queries[1])
        self.store.ingest(self.admin,{"event_id":"private-count"})
        self.assertEqual(self.store.status(switched)["total"],0)
        member,_=self.user()
        with self.assertRaises(PermissionError):self.store.switch(member,second)

    def test_http_auth_origin_and_viewer_permissions(self):
        with TestClient(create_app(self.store,self.analytics,workers=False)) as client:
            self.assertEqual(client.get('/api/overview').status_code,401)
            self.assertEqual(client.post('/api/login',json={"token":self.token},headers={"Origin":"http://evil.example"}).status_code,403)
            response=client.post('/api/login',json={"token":self.token})
            self.assertEqual(response.status_code,200)
            self.assertIn("HttpOnly",response.headers['set-cookie'])
            self.assertEqual(client.get('/api/overview').status_code,200)
            _,token=self.user('viewer')
            self.assertEqual(client.post('/api/login',json={"token":token}).status_code,200)
            self.assertEqual(client.post('/api/settings',json={"kind":"team","name":"no"}).status_code,403)
            self.assertEqual(client.post('/api/investigations',json={"question":"no"}).status_code,403)

    def test_ambiguous_network_timeout_keeps_stable_batch_with_new_events(self):
        class Remote:
            def __init__(self):self.tokens=[];self.fail=True
            def insert(self,table,rows,token):
                self.tokens.append(token)
                if self.fail: raise TimeoutError('response lost')
        remote=Remote()
        self.store.ingest(self.admin,{"event_id":"one"})
        with self.assertRaises(TimeoutError):self.store.sync_once(remote)
        self.store.ingest(self.admin,{"event_id":"two"})
        remote.fail=False
        Store(self.temp.name).sync_once(remote)
        self.assertEqual(remote.tokens[0],remote.tokens[1])
        self.assertEqual(self.store.status()["pending"],1)
        self.store.sync_once(remote)
        self.assertEqual(self.store.status()["pending"],0)

    def test_cross_org_investigation_and_export_denied(self):
        second=self.store.manage(self.admin,{"kind":"organization","name":"Second"})["id"]
        identity=self.store.authenticate(self.store.switch(self.admin,second))
        self.store.save_investigation(self.admin,{"id":"one","evidence":[]})
        self.assertEqual(self.store.list_investigations(identity),[])
        explorer=Explorer(self.store,self.analytics)
        with patch.object(explorer,"schema",return_value=['event_id','session_id']):
            result=explorer.query(self.admin,{"fields":["event_id"]})
            with self.assertRaises(ValueError):explorer.query(identity,{"fields":["event_id"],"offline":True})
            with self.assertRaises(PermissionError):explorer.query(identity,{"table":"dev_events_raw","fields":["event_id"]})
            with self.assertRaises(PermissionError):explorer.query(self.admin,{"table":"dev_platform_events;DROP TABLE x","fields":[]})
            with self.assertRaises(PermissionError):explorer.query(self.admin,{"fields":["prompt"]})
            self.assertIn(self.admin['org_id'],result['sql'])

    def test_archival_never_compacts_pending_and_preserves_payload(self):
        import gzip,time
        self.store.ingest(self.admin,{"event_id":"old","tool":"retained"})
        self.store.ingest(self.admin,{"event_id":"pending"})
        with self.store.db() as db:db.execute("UPDATE outbox SET acked=? WHERE id=(SELECT id FROM outbox ORDER BY created LIMIT 1)",(time.time()-86400*10,))
        self.store.manage(self.admin,{"kind":"retention","archive_after_days":1})
        self.store.archive_confirmed()
        archives=list(self.store.home.glob('archive-*.jsonl.gz'))
        self.assertEqual(len(archives),1)
        self.assertIn('retained',gzip.decompress(archives[0].read_bytes()).decode())
        self.assertEqual(self.store.status()['pending'],1)

    def test_numeric_otlp_usage_and_metric_non_additivity(self):
        def body(field,scope,record):return {field:[{"scopeLogs" if scope=='logs' else "scopeMetrics":[{record[0]:[record[1]]}]}]}
        log={"eventName":"usage","attributes":[{"key":"input_token_count","value":{"intValue":"12"}}]}
        self.store.ingest_otlp(self.admin,'logs',body('resourceLogs','logs',('logRecords',log)))
        metric={"name":"tokens","sum":{"aggregationTemporality":2,"dataPoints":[{"asInt":"200","timeUnixNano":"1"}]}}
        self.store.ingest_otlp(self.admin,'metrics',body('resourceMetrics','metrics',('metrics',metric)))
        with self.store.db() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM outbox ORDER BY created')]
        self.assertEqual(rows[0]['input_tokens'],12)
        self.assertIsNone(rows[1]['input_tokens'])
