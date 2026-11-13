"""RIYA local Windows reminder worker; independent of Edge while user is signed in."""
from __future__ import annotations
import argparse, json, logging, os, subprocess, time
from datetime import datetime
from pathlib import Path
from riya_db import RiyaDatabase

ROOT=Path(__file__).resolve().parent
DEFAULT_DB=ROOT/'data'/'riya.db'
LOG_PATH=ROOT/'data'/'reminder_worker.log'


def show_windows_notification(title: str, body: str, tag: str='RIYA') -> None:
    if os.name != 'nt':
        raise RuntimeError('Windows notifications are available only on Windows.')
    env=os.environ.copy(); env['RIYA_TOAST_TITLE']=title[:63]; env['RIYA_TOAST_BODY']=body[:255]
    script=ROOT/'riya_notify.ps1'
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],env=env,capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Notification failed')[-1000:])


def process_once(db: RiyaDatabase, notifier=show_windows_notification, now: datetime|None=None, dry_run: bool=False) -> dict:
    now=now or datetime.now().astimezone().replace(tzinfo=None)
    reconciled=db.reconcile_session_reminders(now)
    claimed=db.claim_due_reminders(now)
    delivered=failed=0
    for item in claimed:
        data=item.get('data',{}); title=str(data.get('title') or 'RIYA reminder')
        try:
            if not dry_run: notifier('RIYA reminder',f'{title} is scheduled now.',item.get('idempotency_key','RIYA'))
            db.finish_reminder(item['id'],True); delivered+=1
            logging.info('Delivered reminder %s',item['id'])
        except Exception as exc:
            db.finish_reminder(item['id'],False,str(exc)); failed+=1
            logging.exception('Reminder delivery failed: %s',item['id'])
    return {'reconciled':reconciled,'claimed':len(claimed),'delivered':delivered,'failed':failed,'counts':db.reminder_counts()}


def main() -> int:
    parser=argparse.ArgumentParser(description='RIYA background reminder worker')
    parser.add_argument('--db',default=str(DEFAULT_DB)); parser.add_argument('--interval',type=int,default=15)
    parser.add_argument('--once',action='store_true'); parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if not 5<=args.interval<=3600: parser.error('--interval must be between 5 and 3600 seconds')
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(LOG_PATH),level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    db=RiyaDatabase(args.db); logging.info('Worker started; database=%s',args.db)
    try:
        while True:
            try:
                result=process_once(db,dry_run=args.dry_run)
                if result['claimed'] or result['reconciled']['created'] or result['reconciled']['cancelled']:
                    logging.info('Cycle: %s',json.dumps(result))
            except Exception: logging.exception('Reminder cycle failed')
            if args.once: break
            time.sleep(args.interval)
    except KeyboardInterrupt: logging.info('Worker stopped by user')
    return 0

if __name__=='__main__': raise SystemExit(main())
