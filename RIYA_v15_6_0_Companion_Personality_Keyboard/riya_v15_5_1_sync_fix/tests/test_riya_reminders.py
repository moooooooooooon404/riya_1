import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from riya_db import RiyaDatabase
from riya_reminder_worker import process_once

class ReminderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=RiyaDatabase(Path(self.tmp.name)/"riya.db")
        self.now=datetime(2026,11,11,9,0,0)
    def tearDown(self): self.tmp.cleanup()
    def add_scheduled(self, start):
        tid=self.db.create_task("Verilog assignment")
        self.db.create_session(tid,start.isoformat(timespec="seconds"),(start+timedelta(hours=1)).isoformat(timespec="seconds"),session_id="session-1")
        self.db.save_settings({"notifications":True,"reminderMinutes":10})
    def test_reconciles_and_sends_due_reminder_once(self):
        self.add_scheduled(self.now+timedelta(minutes=10)); calls=[]
        first=process_once(self.db,notifier=lambda *args:calls.append(args),now=self.now)
        self.assertEqual(first["reconciled"]["created"],1); self.assertEqual(first["delivered"],1); self.assertEqual(len(calls),1)
        second=process_once(self.db,notifier=lambda *args:calls.append(args),now=self.now)
        self.assertEqual(second["claimed"],0); self.assertEqual(len(calls),1)
    def test_disabled_notifications_do_not_queue(self):
        tid=self.db.create_task("No notification")
        self.db.create_session(tid,(self.now+timedelta(minutes=5)).isoformat(),(self.now+timedelta(minutes=35)).isoformat())
        self.db.save_settings({"notifications":False,"reminderMinutes":10})
        process_once(self.db,now=self.now,dry_run=True)
        self.assertEqual(self.db.reminder_counts(),{})
    def test_late_worker_catches_up_before_session_start(self):
        self.add_scheduled(self.now+timedelta(minutes=5))
        result=process_once(self.db,now=self.now,dry_run=True)
        self.assertEqual(result["delivered"],1)
    def test_cancelled_session_cancels_pending_reminder(self):
        self.add_scheduled(self.now+timedelta(minutes=20)); process_once(self.db,now=self.now,dry_run=True)
        with self.db.transaction() as con: con.execute("UPDATE sessions SET status='cancelled' WHERE id='session-1'")
        result=process_once(self.db,now=self.now,dry_run=True)
        self.assertEqual(result["reconciled"]["cancelled"],1); self.assertEqual(self.db.reminder_counts().get("cancelled"),1)
    def test_two_workers_cannot_claim_same_reminder_at_once(self):
        import concurrent.futures
        self.add_scheduled(self.now+timedelta(minutes=10))
        self.db.reconcile_session_reminders(self.now)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.db.claim_due_reminders(self.now), range(2)))
        self.assertEqual(sum(len(x) for x in results),1)
    def test_failed_delivery_retries_then_marks_failed(self):
        self.add_scheduled(self.now+timedelta(minutes=10))
        for _ in range(5):
            process_once(self.db,notifier=lambda *args:(_ for _ in ()).throw(RuntimeError("blocked")),now=self.now)
            with self.db.transaction() as con: con.execute("UPDATE reminders SET last_attempt_at='2000-01-01T00:00:00' WHERE status='processing'")
        self.assertEqual(self.db.reminder_counts().get("failed"),1)

if __name__=="__main__": unittest.main()

