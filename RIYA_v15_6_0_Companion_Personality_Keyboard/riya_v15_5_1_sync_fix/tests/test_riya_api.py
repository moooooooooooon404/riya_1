import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from io import BytesIO
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import riya_server
from riya_db import RiyaDatabase

class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        riya_server.DB = RiyaDatabase(Path(cls.tmp.name) / 'api.db')
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), riya_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.tmp.cleanup()

    def setUp(self):
        riya_server.DB = RiyaDatabase(Path(self.tmp.name) / (self._testMethodName + '.db'))

    def get_json(self, path):
        with urlopen(self.base + path, timeout=3) as r:
            return json.loads(r.read())

    def post_json(self, path, payload, headers=None):
        h={'Content-Type':'application/json'}; h.update(headers or {})
        req=Request(self.base+path, data=json.dumps(payload).encode(), headers=h, method='POST')
        with urlopen(req, timeout=3) as r: return json.loads(r.read())

    def test_category_defaults_can_be_read_and_customized(self):
        defaults=self.get_json('/api/riya/categories')['categories']
        self.assertEqual(len(defaults),4)
        defaults[0]['label']='My growth priorities'
        saved=self.post_json('/api/riya/categories',{'categories':defaults})
        self.assertEqual(saved['categories'][0]['label'],'My growth priorities')
        reread=self.get_json('/api/riya/categories')
        self.assertEqual(reread['categories'][0]['label'],'My growth priorities')

    def test_classification_endpoint_does_not_guess_unknown_preferences(self):
        result=self.post_json('/api/riya/classify',{'attributes':{'enjoyment':'unknown','importance':'unknown','growth_impact':'unknown'}})['result']
        self.assertTrue(result['needs_review'])
        self.assertIsNone(result['category_id'])

    def test_classification_endpoint_respects_user_override(self):
        result=self.post_json('/api/riya/classify',{'attributes':{},'user_category':'delegatable'})['result']
        self.assertEqual(result['category_id'],'delegatable')
        self.assertEqual(result['source'],'user_override')

    def test_status_and_empty_snapshot(self):
        status=self.get_json('/api/db/status')
        self.assertTrue(status['ok']); self.assertEqual(status['schema_version'], 4)
        data=self.get_json('/api/db/data')
        self.assertEqual(data['source'], 'sqlite'); self.assertEqual(data['tasks'], [])


    def test_conversation_create_restore_and_memory_endpoints(self):
        created=self.post_json('/api/conversations',{'title':'Test conversation','messages':[{'id':'u1','role':'user','content':'I have a Verilog assignment'}],'working_memory':{'active_goal':'Finish Verilog'}})
        self.assertTrue(created['ok'])
        cid=created['conversation_id']
        bundle=self.get_json('/api/conversations/'+cid)
        self.assertEqual(bundle['messages'][0]['content'],'I have a Verilog assignment')
        self.assertEqual(bundle['working_memory']['active_goal'],'Finish Verilog')
        saved=self.post_json('/api/conversations/'+cid+'/memory',{'working_memory':{'active_goal':'Finish FPGA'},'expected_version':1})
        self.assertEqual(saved['memory_version'],2)
        restored=self.get_json('/api/conversations/'+cid)
        self.assertEqual(restored['working_memory']['active_goal'],'Finish FPGA')

    def test_conversation_list_returns_latest_persistent_thread(self):
        created=self.post_json('/api/conversations',{'title':'Persistent thread'})
        listing=self.get_json('/api/conversations')
        self.assertTrue(any(x['id']==created['conversation_id'] for x in listing['conversations']))


    def test_chat_turn_is_persisted_with_context_and_memory(self):
        created=self.post_json('/api/conversations',{'title':'Chat persistence test'})
        cid=created['conversation_id']
        fake_payload={'message':{'content':json.dumps({'reply':'That sounds interesting!','questions':[],'tasks':[]})}}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(fake_payload).encode()
        with patch('riya_server.urlopen',return_value=FakeResponse()):
            result=self.post_json('/api/chat',{'conversation_id':cid,'turn_id':'turn-1','user_message_id':'user-1','user_message':'Tell me a fun fact about space.','messages':[{'role':'user','content':'Tell me a fun fact about space.'}],'tasks':[],'draft_tasks':[],'settings':{},'current_date':'2026-11-12'})
        self.assertEqual(result['reply'],'That sounds interesting!')
        bundle=self.get_json('/api/conversations/'+cid)
        self.assertEqual([m['role'] for m in bundle['messages']],['user','assistant'])
        self.assertEqual(bundle['messages'][0]['content'],'Tell me a fun fact about space.')
        self.assertEqual(bundle['messages'][1]['content'],'That sounds interesting!')
        self.assertIn('draft_tasks',bundle['working_memory'])


    def test_initial_brain_dump_keeps_conversational_reply_instead_of_forced_priority_prompt(self):
        created=self.post_json('/api/conversations',{'title':'Brain dump conversation'})
        cid=created['conversation_id']
        model_reply='I have captured your plans. What time would you prefer to go to the gym?'
        model_tasks=[
            {'title':'Prepare for CCNA','missing_fields':['duration_minutes']},
            {'title':'Finish office project','missing_fields':['deadline']},
            {'title':'Go to the gym','missing_fields':['start_time']},
            {'title':'Spend time with family','missing_fields':[]},
            {'title':'Meet friend this Sunday','missing_fields':['start_time']},
            {'title':'Meeting next Wednesday at 11 AM','missing_fields':[]},
        ]
        fake_payload={'message':{'content':json.dumps({'reply':model_reply,'questions':[],'tasks':model_tasks})}}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(fake_payload).encode()
        with patch('riya_server.urlopen',return_value=FakeResponse()):
            result=self.post_json('/api/chat',{'conversation_id':cid,'turn_id':'brain-1','user_message_id':'brain-u1','user_message':'I have several things to do.','messages':[{'role':'user','content':'I have several things to do.'}],'tasks':[],'draft_tasks':[],'settings':{},'current_date':'2026-11-12'})
        self.assertEqual(result['reply'],model_reply)
        self.assertNotIn('Which one feels like the best place to start?',result['reply'])
        self.assertEqual(len(result['tasks']),6)
        self.assertFalse(result['priority_pending'])

    def test_followup_turn_receives_saved_conversation_history(self):
        created=self.post_json('/api/conversations',{'title':'Context continuity'})
        cid=created['conversation_id']
        captured=[]
        class FakeResponse:
            def __init__(self,reply): self.reply=reply
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps({'message':{'content':json.dumps({'reply':self.reply,'questions':[],'tasks':[]})}}).encode()
        def fake_urlopen(req,timeout=180):
            captured.append(json.loads(req.data.decode()))
            return FakeResponse('The assignment is about Verilog loops.' if len(captured)==1 else 'You said the assignment is about Verilog loops. Shall we build a testbench?')
        with patch('riya_server.urlopen',side_effect=fake_urlopen):
            self.post_json('/api/chat',{'conversation_id':cid,'turn_id':'c1','user_message_id':'u1','user_message':'I have a Verilog assignment.','tasks':[],'draft_tasks':[],'settings':{},'current_date':'2026-11-12'})
            self.post_json('/api/chat',{'conversation_id':cid,'turn_id':'c2','user_message_id':'u2','user_message':'It is about loops.','tasks':[],'draft_tasks':[],'settings':{},'current_date':'2026-11-12'})
        sent=[m['content'] for m in captured[1]['messages'] if m['role'] in ('user','assistant')]
        self.assertIn('I have a Verilog assignment.',sent)
        self.assertIn('The assignment is about Verilog loops.',sent)
        self.assertEqual(sent[-1],'It is about loops.')
        bundle=self.get_json('/api/conversations/'+cid)
        self.assertEqual(len(bundle['messages']),4)


    def test_manual_conversation_message_endpoint(self):
        created=self.post_json('/api/conversations',{'title':'Manual append'})
        cid=created['conversation_id']
        result=self.post_json('/api/conversations/'+cid+'/messages',{'id':'manual-assistant','role':'assistant','content':'Your task list is ready.'})
        self.assertTrue(result['ok'])
        bundle=self.get_json('/api/conversations/'+cid)
        self.assertEqual(bundle['messages'][0]['content'],'Your task list is ready.')

    def test_import_preserves_ids_sessions_settings(self):
        backup={'app':'RIYA','version':1,'tasks':[{'id':'task-A','title':'Project report','status':'scheduled','duration':60,'priority':'High','date':'2026-11-12','start':'10:00','end':'11:00','sessions':[{'id':'session-A','date':'2026-11-12','start':'10:00','end':'11:00','duration':60,'status':'scheduled'}]}], 'history':[{'id':'hist-A','at':'2026-11-11T09:00:00','action':'Created','detail':'Project report'}], 'settings':{'notifications':True}}
        result=self.post_json('/api/db/import', {'idempotency_key':'migration-test-1','backup':backup})
        self.assertTrue(result['ok'])
        data=self.get_json('/api/db/data')
        task=next(x for x in data['tasks'] if x['id']=='task-A')
        self.assertEqual(task['sessions'][0]['id'],'session-A')
        self.assertEqual(task['status'],'scheduled')
        self.assertTrue(data['settings']['notifications'])

    def test_import_repeat_does_not_duplicate_records(self):
        backup={'app':'RIYA','tasks':[{'id':'task-repeat','title':'Repeat-safe task'}], 'history':[], 'settings':{}}
        payload={'idempotency_key':'repeat-key','backup':backup}
        self.post_json('/api/db/import',payload)
        self.post_json('/api/db/import',payload)
        status=self.get_json('/api/db/status')
        self.assertEqual(sum(1 for x in self.get_json('/api/db/data')['tasks'] if x['id']=='task-repeat'),1)

    def test_cross_origin_write_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post_json('/api/db/settings', {'settings':{'x':1}}, {'Origin':'https://evil.example'})
        self.assertEqual(ctx.exception.code,403)

    def test_invalid_import_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.post_json('/api/db/import', {'idempotency_key':'bad-import','backup':{'app':'wrong','tasks':[]}})
        self.assertEqual(ctx.exception.code,400)


    def test_state_sync_endpoint_replaces_and_verifies_snapshot(self):
        state={'app':'RIYA','version':1,'tasks':[{'id':'api-task','title':'API task','sessions':[{'id':'api-session','date':'2026-11-12','start':'10:00','end':'11:00','status':'scheduled'}]}],
               'history':[], 'settings':{'workStart':'08:00'}}
        result=self.post_json('/api/db/state', {'state':state,'expected_revision':0})
        self.assertTrue(result['ok'])
        self.assertTrue(result['verified'])
        self.assertEqual(result['database']['tasks'][0]['id'],'api-task')
        self.assertEqual(result['database']['tasks'][0]['sessions'][0]['id'],'api-session')

    def test_state_sync_invalid_payload_rejected_without_data_loss(self):
        good={'app':'RIYA','tasks':[{'id':'preserve','title':'Preserve','sessions':[]}], 'history':[], 'settings':{}}
        self.post_json('/api/db/state', {'state':good,'expected_revision':0})
        bad={'app':'RIYA','tasks':[{'id':'bad','title':'Bad','sessions':[{'id':'bad-s','date':'2026-11-12','start':'13:00','end':'12:00'}]}], 'history':[], 'settings':{}}
        with self.assertRaises(HTTPError) as ctx:
            self.post_json('/api/db/state', {'state':bad,'expected_revision':1})
        self.assertEqual(ctx.exception.code,400)
        self.assertEqual(self.get_json('/api/db/data')['tasks'][0]['id'],'preserve')


    def test_state_sync_rejects_stale_revision_with_409(self):
        state1={'app':'RIYA','tasks':[{'id':'window-a','title':'Window A'}], 'history':[], 'settings':{}}
        state2={'app':'RIYA','tasks':[{'id':'window-b','title':'Window B'}], 'history':[], 'settings':{}}
        first=self.post_json('/api/db/state', {'state':state1,'expected_revision':0})
        self.assertEqual(first['revision'], 1)
        with self.assertRaises(HTTPError) as ctx:
            self.post_json('/api/db/state', {'state':state2,'expected_revision':0})
        self.assertEqual(ctx.exception.code, 409)
        current=self.get_json('/api/db/data')
        self.assertEqual(current['revision'], 1)
        self.assertEqual(current['tasks'][0]['id'], 'window-a')

    def test_state_sync_requires_revision(self):
        state={'app':'RIYA','tasks':[], 'history':[], 'settings':{}}
        with self.assertRaises(HTTPError) as ctx:
            self.post_json('/api/db/state', {'state':state})
        self.assertEqual(ctx.exception.code, 400)

    def test_integrity_endpoint(self):
        result=self.get_json('/api/db/integrity')
        self.assertTrue(result['ok'])

if __name__ == '__main__': unittest.main()
