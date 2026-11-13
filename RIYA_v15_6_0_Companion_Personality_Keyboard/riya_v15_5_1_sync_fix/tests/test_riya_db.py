import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from riya_db import RiyaDatabase

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = RiyaDatabase(Path(self.tmp.name) / 'riya.db')
    def tearDown(self):
        self.tmp.cleanup()
    def test_schema_migrates_once(self):
        self.assertEqual(self.db.schema_version(), 4)
        self.db._initialize()
        self.assertEqual(self.db.schema_version(), 4)

    def test_schema_v1_database_migrates_to_revision_tracking(self):
        with self.db.transaction() as con:
            con.execute("DROP TABLE app_state_meta")
            con.execute("DELETE FROM schema_migrations WHERE version IN (2,3,4)")
        migrated=RiyaDatabase(self.db.path)
        self.assertEqual(migrated.schema_version(), 4)
        self.assertEqual(migrated.state_revision(), 0)
        self.assertTrue(migrated.integrity_check()['ok'])


    def test_conversation_messages_and_working_memory_survive_reopen(self):
        cid=self.db.create_conversation('Verilog plan')
        self.db.append_conversation_message(cid,'user','I have a Verilog assignment',message_id='u1',turn_id='turn1')
        self.db.append_conversation_message(cid,'assistant','When is it due?',turn_id='turn1')
        self.db.save_working_memory(cid,{'active_goal':'Finish Verilog assignment','pending_question':'deadline','draft_tasks':[{'task_id':'t1','title':'Verilog assignment'}]})
        reopened=RiyaDatabase(self.db.path).get_conversation(cid)
        self.assertEqual([m['role'] for m in reopened['messages']],['user','assistant'])
        self.assertEqual(reopened['working_memory']['active_goal'],'Finish Verilog assignment')
        self.assertEqual(reopened['working_memory']['draft_tasks'][0]['task_id'],'t1')

    def test_conversation_message_append_is_idempotent(self):
        cid=self.db.create_conversation('Idempotency')
        first=self.db.append_conversation_message(cid,'user','Yes',message_id='same-id',turn_id='turn-x')
        second=self.db.append_conversation_message(cid,'user','Yes again',message_id='same-id',turn_id='turn-x')
        self.assertEqual(first,second)
        self.assertEqual(len(self.db.get_conversation(cid)['messages']),1)

    def test_working_memory_optimistic_version_rejects_stale_update(self):
        cid=self.db.create_conversation('Memory version')
        self.assertEqual(self.db.save_working_memory(cid,{'goal':'one'},expected_version=0),1)
        with self.assertRaises(RuntimeError):
            self.db.save_working_memory(cid,{'goal':'stale'},expected_version=0)
        self.assertEqual(self.db.get_conversation(cid)['working_memory']['goal'],'one')


    def test_complete_turn_persists_reply_and_memory_atomically_and_idempotently(self):
        cid=self.db.create_conversation('Atomic turn')
        self.db.append_conversation_message(cid,'user','Plan my week',message_id='atomic-user',turn_id='atomic-turn')
        version=self.db.complete_conversation_turn(cid,'I can help plan your week.',{'active_goal':'Plan my week'},turn_id='atomic-turn')
        version2=self.db.complete_conversation_turn(cid,'A duplicate answer should not be added.',{'active_goal':'Plan my week'},turn_id='atomic-turn')
        bundle=self.db.get_conversation(cid)
        self.assertEqual(version,1)
        self.assertEqual(version2,2)
        self.assertEqual(len(bundle['messages']),2)
        self.assertEqual(bundle['messages'][-1]['content'],'I can help plan your week.')
        self.assertEqual(bundle['working_memory']['active_goal'],'Plan my week')

    def test_conversations_are_isolated(self):
        first=self.db.create_conversation('First')
        second=self.db.create_conversation('Second')
        self.db.append_conversation_message(first,'user','Verilog')
        self.db.append_conversation_message(second,'user','Internship report')
        self.assertEqual(self.db.get_conversation(first)['messages'][0]['content'],'Verilog')
        self.assertEqual(self.db.get_conversation(second)['messages'][0]['content'],'Internship report')

    def test_task_and_session_roundtrip(self):
        tid = self.db.create_task('Verilog practice', estimated_minutes=180)
        sid = self.db.create_session(tid, '2026-11-12T11:00:00', '2026-11-12T12:00:00')
        task = self.db.get_task(tid)
        self.assertEqual(task['title'], 'Verilog practice')
        self.assertEqual(task['sessions'][0]['id'], sid)
    def test_foreign_key_rejects_orphan_session(self):
        with self.assertRaises(Exception):
            self.db.create_session('missing-task', '2026-11-12T11:00:00', '2026-11-12T12:00:00')
    def test_invalid_session_range_rejected(self):
        tid = self.db.create_task('Test')
        with self.assertRaises(ValueError):
            self.db.create_session(tid, '2026-11-12T12:00:00', '2026-11-12T11:00:00')
    def test_transaction_rolls_back(self):
        try:
            with self.db.transaction() as con:
                con.execute("INSERT INTO settings VALUES('x','1','now')")
                raise RuntimeError('simulated failure')
        except RuntimeError:
            pass
        self.assertEqual(self.db.get_settings(), {})
    def test_idempotency_receipt(self):
        first = self.db.record_receipt('key-1', 'create_task', {'task_id': 'abc'})
        second = self.db.record_receipt('key-1', 'create_task', {'task_id': 'different'})
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            self.db.record_receipt('key-1', 'delete_task', {})
    def test_legacy_backup_import_export(self):
        backup = {'app':'RIYA','tasks':[{'id':'t1','title':'FPGA','status':'scheduled','sessions':[{'id':'s1','date':'2026-11-12','start':'10:00','end':'11:00','status':'scheduled'}]}], 'history':[{'id':'h1','at':'2026-11-10T00:00:00Z','action':'Created','detail':'FPGA'}], 'settings':{'workStart':'09:00'}}
        result = self.db.import_backup(backup)
        self.assertEqual(result, {'tasks':1,'sessions':1,'history':1,'settings':1})
        exported = self.db.export_backup()
        self.assertEqual(exported['tasks'][0]['id'], 't1')
        self.assertEqual(exported['tasks'][0]['sessions'][0]['id'], 's1')
        self.assertEqual(exported['settings']['workStart'], '09:00')
    def test_invalid_backup_does_not_change_database(self):
        self.db.create_task('Existing')
        with self.assertRaises(ValueError):
            self.db.import_backup({'app':'other','tasks':[]})
        self.assertEqual(self.db.counts()['tasks'], 1)


    def test_replace_app_state_replaces_and_preserves_ids(self):
        backup = {'app':'RIYA','tasks':[{'id':'t1','title':'One','sessions':[{'id':'s1','date':'2026-11-12','start':'09:00','end':'10:00','status':'scheduled'}]}],
                  'history':[{'id':'h1','action':'Created','detail':'One'}], 'settings':{'theme':'dark'}}
        result = self.db.replace_app_state(backup)
        self.assertEqual(result['tasks'], 1)
        self.assertEqual(result['sessions'], 1)
        data = self.db.export_app_state()
        self.assertEqual(data['tasks'][0]['id'], 't1')
        self.assertEqual(data['tasks'][0]['sessions'][0]['id'], 's1')
        self.assertEqual(data['settings']['theme'], 'dark')
        backup2 = {'app':'RIYA','tasks':[{'id':'t2','title':'Two','sessions':[]}], 'history':[], 'settings':{}}
        self.db.replace_app_state(backup2)
        data2 = self.db.export_app_state()
        self.assertEqual([x['id'] for x in data2['tasks']], ['t2'])
        self.assertEqual([x['id'] for x in data2['history']], ['h1'])
        self.assertEqual(data2['settings'], {})

    def test_replace_app_state_invalid_payload_is_atomic(self):
        good = {'app':'RIYA','tasks':[{'id':'keep','title':'Keep me','sessions':[]}], 'history':[], 'settings':{}}
        self.db.replace_app_state(good)
        bad = {'app':'RIYA','tasks':[{'id':'bad','title':'Bad','sessions':[{'id':'s','date':'2026-11-12','start':'12:00','end':'11:00'}]}], 'history':[], 'settings':{}}
        with self.assertRaises(ValueError):
            self.db.replace_app_state(bad)
        self.assertEqual(self.db.export_app_state()['tasks'][0]['id'], 'keep')


    def test_snapshot_sync_preserves_audit_and_cancels_orphaned_reminders(self):
        import uuid
        now = '2026-11-11T00:00:00+00:00'
        with self.db.transaction() as con:
            con.execute("INSERT INTO tasks(id,title,status,created_at,updated_at,data_json) VALUES(?,?,?,?,?,?)",
                        ('old-task','Old','pending',now,now,'{}'))
            con.execute("INSERT INTO sessions(id,task_id,start_at,end_at,status,created_at,updated_at,data_json) VALUES(?,?,?,?,?,?,?,?)",
                        ('old-session','old-task','2026-11-12T09:00:00','2026-11-12T10:00:00','scheduled',now,now,'{}'))
            con.execute("INSERT INTO reminders(id,session_id,due_at,status,created_at,updated_at,data_json) VALUES(?,?,?,?,?,?,?)",
                        ('reminder-1','old-session','2026-11-12T08:50:00','pending',now,now,'{}'))
            con.execute("INSERT INTO proposals(id,kind,status,created_at,updated_at,data_json) VALUES(?,?,?,?,?,?)",
                        ('proposal-1','schedule','pending',now,now,'{}'))
            con.execute("INSERT INTO proposal_items(id,proposal_id,task_id,data_json) VALUES(?,?,?,?)",
                        ('proposal-item-1','proposal-1','old-task','{}'))
            con.execute("INSERT INTO action_history(id,action_type,risk_level,status,requested_by,created_at,updated_at,request_json,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        ('audit-1','desktop-action',1,'verified','user',now,now,'{}','{}'))
        self.db.replace_app_state({'app':'RIYA','tasks':[{'id':'new-task','title':'New','sessions':[]}], 'history':[], 'settings':{}})
        with self.db.connect() as con:
            reminder=con.execute("SELECT status,session_id FROM reminders WHERE id='reminder-1'").fetchone()
            proposal=con.execute("SELECT status FROM proposals WHERE id='proposal-1'").fetchone()
            audit=con.execute("SELECT action_type FROM action_history WHERE id='audit-1'").fetchone()
        self.assertEqual((reminder['status'],reminder['session_id']),('cancelled',None))
        self.assertEqual(proposal['status'],'stale')
        self.assertEqual(audit['action_type'],'desktop-action')

    def test_concurrent_task_writes_are_serialized_without_loss(self):
        import concurrent.futures
        def add(i):
            return self.db.create_task(f'Concurrent task {i}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=list(pool.map(add, range(24)))
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(self.db.counts()['tasks'], 24)


    def test_state_revision_increments_and_rejects_stale_snapshot(self):
        first={'app':'RIYA','tasks':[{'id':'rev-1','title':'First'}], 'history':[], 'settings':{}}
        result=self.db.replace_app_state(first, expected_revision=0)
        self.assertEqual(result['revision'], 1)
        second={'app':'RIYA','tasks':[{'id':'rev-2','title':'Second'}], 'history':[], 'settings':{}}
        with self.assertRaisesRegex(RuntimeError, 'REVISION_CONFLICT'):
            self.db.replace_app_state(second, expected_revision=0)
        snapshot=self.db.export_app_state()
        self.assertEqual(snapshot['revision'], 1)
        self.assertEqual(snapshot['tasks'][0]['id'], 'rev-1')

    def test_integrity_check_reports_database_and_foreign_keys(self):
        self.db.create_task('Integrity task')
        result=self.db.integrity_check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['integrity'], ['ok'])
        self.assertEqual(result['foreign_key_errors'], [])

    def test_snapshot_sync_normalizes_times_with_seconds(self):
        self.db.replace_app_state({'app':'RIYA','tasks':[{'id':'seconds-task','title':'Seconds','sessions':[
            {'id':'seconds-session','date':'2026-11-12','start':'09:00:30','end':'10:00:30'}]}], 'history':[], 'settings':{}})
        data=self.db.export_app_state()
        self.assertEqual(data['tasks'][0]['sessions'][0]['start'],'09:00')
        with self.db.connect() as con:
            row=con.execute("SELECT start_at,end_at FROM sessions WHERE id='seconds-session'").fetchone()
        self.assertEqual(row['start_at'],'2026-11-12T09:00:30')
        self.assertEqual(row['end_at'],'2026-11-12T10:00:30')

if __name__ == '__main__':
    unittest.main(verbosity=2)
