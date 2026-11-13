"""RIYA SQLite persistence foundation (standard library only).

This module is deliberately independent of the UI until its repository contract
has been tested. The application can migrate from localStorage without losing
existing data by importing an exported RIYA JSON backup through import_backup().
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class RiyaDatabase:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        if self.path != ":memory:":
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
        return con

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _initialize(self) -> None:
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)""")
            current = con.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(f"Database schema {current} is newer than this RIYA build ({SCHEMA_VERSION}).")
            if current < 1:
                self._migration_1(con)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (1, _now()))
                current = 1
            if current < 2:
                self._migration_2(con)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (2, _now()))
                current = 2
            if current < 3:
                self._migration_3(con)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (3, _now()))
                current = 3
            if current < 4:
                self._migration_4(con)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (4, _now()))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _migration_1(con: sqlite3.Connection) -> None:
        script = """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','in_progress','completed','cancelled','archived')),
            priority TEXT, kind TEXT, deadline TEXT, estimated_minutes INTEGER,
            notes TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
            start_at TEXT NOT NULL, end_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled'
              CHECK(status IN ('scheduled','completed','cancelled','missed','rescheduled')),
            version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}', CHECK(end_at > start_at)
        );
        CREATE INDEX sessions_by_start ON sessions(start_at);
        CREATE INDEX sessions_by_task ON sessions(task_id);
        CREATE TABLE proposals (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','approved','rejected','stale','failed')),
            version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL
        );
        CREATE TABLE proposal_items (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT, data_json TEXT NOT NULL
        );
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
            content TEXT NOT NULL, created_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX messages_by_conversation ON messages(conversation_id, created_at);
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, category TEXT NOT NULL, content TEXT NOT NULL,
            source TEXT, confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0,1)),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE notes (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE reminders (
            id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id) ON DELETE RESTRICT,
            due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','delivered','cancelled','failed')),
            idempotency_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE app_permissions (
            id TEXT PRIMARY KEY, app_key TEXT NOT NULL UNIQUE, executable_path TEXT NOT NULL,
            allowed_actions_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE action_history (
            id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, action_type TEXT NOT NULL,
            risk_level INTEGER NOT NULL CHECK(risk_level BETWEEN 0 AND 3),
            status TEXT NOT NULL CHECK(status IN ('proposed','awaiting_approval','approved','running','verified','failed','cancelled')),
            requested_by TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT
        );
        CREATE TABLE file_operations (
            id TEXT PRIMARY KEY, action_id TEXT REFERENCES action_history(id) ON DELETE RESTRICT,
            operation TEXT NOT NULL, source_path TEXT, destination_path TEXT,
            status TEXT NOT NULL, created_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE automations (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            trigger_json TEXT NOT NULL, action_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE operation_receipts (
            idempotency_key TEXT PRIMARY KEY, operation TEXT NOT NULL,
            result_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """
        # sqlite3.executescript() implicitly commits an open transaction. Execute
        # complete SQL statements individually so DDL and migration version commit
        # together in the surrounding BEGIN IMMEDIATE transaction.
        statement = ""
        for line in script.splitlines():
            statement += line + "\n"
            if sqlite3.complete_statement(statement):
                if statement.strip():
                    con.execute(statement)
                statement = ""
        if statement.strip():
            raise RuntimeError("Incomplete SQL statement in RIYA migration.")

    @staticmethod
    def _migration_2(con: sqlite3.Connection) -> None:
        con.execute("CREATE TABLE app_state_meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)")
        con.execute("INSERT INTO app_state_meta(id,revision) VALUES(1,0)")

    @staticmethod
    def _migration_3(con: sqlite3.Connection) -> None:
        # Add an explicit processing lease so a crashed worker can safely retry.
        con.execute("ALTER TABLE reminders RENAME TO reminders_v2")
        con.execute("""CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES sessions(id) ON DELETE RESTRICT,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','processing','delivered','cancelled','failed')),
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT
        )""")
        con.execute("""INSERT INTO reminders(id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json)
            SELECT id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json FROM reminders_v2""")
        con.execute("DROP TABLE reminders_v2")
        con.execute("CREATE INDEX reminders_due_status ON reminders(status,due_at)")

    @staticmethod
    def _migration_3(con: sqlite3.Connection) -> None:
        con.execute("ALTER TABLE reminders RENAME TO reminders_v2")
        con.execute("""CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES sessions(id) ON DELETE RESTRICT,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
              CHECK(status IN ('pending','processing','delivered','cancelled','failed')),
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL DEFAULT '{}',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT
        )""")
        con.execute("""INSERT INTO reminders(id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json)
            SELECT id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json FROM reminders_v2""")
        con.execute("DROP TABLE reminders_v2")
        con.execute("CREATE INDEX reminders_due_status ON reminders(status,due_at)")

    @staticmethod
    def _migration_4(con: sqlite3.Connection) -> None:
        # Ordered, idempotent transcript records and one durable working-memory
        # document per conversation. Existing v1-v3 conversations are preserved.
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        if "sequence_no" not in cols:
            con.execute("ALTER TABLE messages ADD COLUMN sequence_no INTEGER")
        if "turn_id" not in cols:
            con.execute("ALTER TABLE messages ADD COLUMN turn_id TEXT")
        rows = con.execute("SELECT id,conversation_id FROM messages ORDER BY conversation_id,created_at,id").fetchall()
        counters = {}
        for row in rows:
            cid = row["conversation_id"]
            counters[cid] = counters.get(cid, 0) + 1
            con.execute("UPDATE messages SET sequence_no=? WHERE id=?", (counters[cid], row["id"]))
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS messages_turn_role ON messages(conversation_id,turn_id,role) WHERE turn_id IS NOT NULL")
        con.execute("CREATE INDEX IF NOT EXISTS messages_sequence ON messages(conversation_id,sequence_no)")
        con.execute("""CREATE TABLE IF NOT EXISTS working_memory (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            version INTEGER NOT NULL DEFAULT 1,
            memory_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )""")

    def create_conversation(self, title: str = "New conversation", *, conversation_id: str | None = None,
                            initial_messages: list[dict] | None = None,
                            working_memory: dict | None = None) -> str:
        cid = conversation_id or str(uuid.uuid4())
        now = _now()
        with self.transaction() as con:
            con.execute("INSERT INTO conversations(id,title,created_at,updated_at,data_json) VALUES(?,?,?,?,?)",
                        (cid, str(title or "New conversation")[:160], now, now, "{}"))
            if isinstance(initial_messages, list):
                seq = 0
                for item in initial_messages[-500:]:
                    if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
                        continue
                    content = item.get("content")
                    if not isinstance(content, str) or not content.strip():
                        continue
                    seq += 1
                    mid = str(item.get("id") or uuid.uuid4())
                    con.execute("INSERT INTO messages(id,conversation_id,role,content,created_at,data_json,sequence_no,turn_id) VALUES(?,?,?,?,?,?,?,?)",
                                (mid, cid, item["role"], content[:5000], now, "{}", seq, item.get("turn_id")))
            if isinstance(working_memory, dict):
                con.execute("INSERT INTO working_memory(conversation_id,version,memory_json,updated_at) VALUES(?,?,?,?)",
                            (cid, 1, _json(working_memory), now))
        return cid

    def list_conversations(self, limit: int = 100) -> list[dict]:
        with closing(self.connect()) as con:
            rows = con.execute("""SELECT c.id,c.title,c.created_at,c.updated_at,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                (SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY sequence_no DESC LIMIT 1) AS last_message
                FROM conversations c ORDER BY c.updated_at DESC LIMIT ?""", (max(1,min(int(limit),200)),)).fetchall()
            return [dict(r) for r in rows]

    def append_conversation_message(self, conversation_id: str, role: str, content: str,
                                    *, message_id: str | None = None, turn_id: str | None = None) -> str:
        if role not in ("user", "assistant"):
            raise ValueError("Conversation message role must be user or assistant.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Conversation message cannot be empty.")
        mid = message_id or str(uuid.uuid4())
        now = _now()
        with self.transaction() as con:
            if not con.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise KeyError("Conversation not found.")
            existing = con.execute("SELECT id FROM messages WHERE id=?", (mid,)).fetchone()
            if not existing and turn_id:
                existing = con.execute("SELECT id FROM messages WHERE conversation_id=? AND turn_id=? AND role=?", (conversation_id, turn_id, role)).fetchone()
            if existing:
                return str(existing["id"])
            seq = int(con.execute("SELECT COALESCE(MAX(sequence_no),0)+1 FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0])
            con.execute("INSERT INTO messages(id,conversation_id,role,content,created_at,data_json,sequence_no,turn_id) VALUES(?,?,?,?,?,?,?,?)",
                        (mid, conversation_id, role, content[:5000], now, "{}", seq, turn_id))
            if role == 'user' and seq == 1:
                con.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (content.strip()[:60], now, conversation_id))
            else:
                con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        return mid

    def get_conversation(self, conversation_id: str, *, message_limit: int = 500) -> dict | None:
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not row:
                return None
            messages = [dict(r) for r in con.execute("SELECT id,role,content,created_at,sequence_no,turn_id FROM messages WHERE conversation_id=? ORDER BY sequence_no LIMIT ?", (conversation_id, max(1,min(message_limit,2000))))]
            mem = con.execute("SELECT version,memory_json,updated_at FROM working_memory WHERE conversation_id=?", (conversation_id,)).fetchone()
            memory = json.loads(mem["memory_json"]) if mem else {}
            return {"conversation":dict(row),"messages":messages,"working_memory":memory,"memory_version":int(mem["version"]) if mem else 0}

    def save_working_memory(self, conversation_id: str, memory: dict, *, expected_version: int | None = None) -> int:
        if not isinstance(memory, dict):
            raise ValueError("Working memory must be an object.")
        encoded = _json(memory)
        if len(encoded) > 100_000:
            raise ValueError("Working memory is too large.")
        now = _now()
        with self.transaction() as con:
            if not con.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise KeyError("Conversation not found.")
            row = con.execute("SELECT version FROM working_memory WHERE conversation_id=?", (conversation_id,)).fetchone()
            current = int(row["version"]) if row else 0
            if expected_version is not None and current != expected_version:
                raise RuntimeError(f"MEMORY_CONFLICT: expected {expected_version}, current {current}")
            new_version = current + 1
            con.execute("""INSERT INTO working_memory(conversation_id,version,memory_json,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET version=excluded.version,memory_json=excluded.memory_json,updated_at=excluded.updated_at""",
                (conversation_id, new_version, encoded, now))
            con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            return new_version

    def complete_conversation_turn(self, conversation_id: str, reply: str, memory: dict,
                                   *, turn_id: str | None = None) -> int:
        """Atomically persist the assistant reply and its resulting working memory."""
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Assistant reply cannot be empty.")
        encoded = _json(memory if isinstance(memory, dict) else {})
        if len(encoded) > 100_000:
            raise ValueError("Working memory is too large.")
        now = _now()
        with self.transaction() as con:
            if not con.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise KeyError("Conversation not found.")
            existing = None
            if turn_id:
                existing = con.execute("SELECT id FROM messages WHERE conversation_id=? AND turn_id=? AND role='assistant'", (conversation_id, turn_id)).fetchone()
            if not existing:
                seq = int(con.execute("SELECT COALESCE(MAX(sequence_no),0)+1 FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0])
                con.execute("INSERT INTO messages(id,conversation_id,role,content,created_at,data_json,sequence_no,turn_id) VALUES(?,?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), conversation_id, 'assistant', reply[:5000], now, "{}", seq, turn_id))
            row = con.execute("SELECT version FROM working_memory WHERE conversation_id=?", (conversation_id,)).fetchone()
            version = int(row["version"]) if row else 0
            version += 1
            con.execute("""INSERT INTO working_memory(conversation_id,version,memory_json,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(conversation_id) DO UPDATE SET version=excluded.version,memory_json=excluded.memory_json,updated_at=excluded.updated_at""",
                (conversation_id, version, encoded, now))
            con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            return version

    def state_revision(self) -> int:
        with closing(self.connect()) as con:
            row = con.execute("SELECT revision FROM app_state_meta WHERE id=1").fetchone()
            return int(row[0]) if row else 0

    def integrity_check(self) -> dict[str, Any]:
        with closing(self.connect()) as con:
            result = [str(row[0]) for row in con.execute("PRAGMA integrity_check")]
            fk_errors = [dict(row) for row in con.execute("PRAGMA foreign_key_check")]
        return {"ok": result == ["ok"] and not fk_errors, "integrity": result, "foreign_key_errors": fk_errors}

    def schema_version(self) -> int:
        with closing(self.connect()) as con:
            return int(con.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0])

    def counts(self) -> dict[str, int]:
        tables = ("tasks", "sessions", "proposals", "proposal_items", "conversations", "messages",
                  "working_memory", "memories", "notes", "reminders", "app_permissions", "action_history",
                  "file_operations", "automations", "settings", "operation_receipts")
        with closing(self.connect()) as con:
            return {table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}

    def save_settings(self, values: dict[str, Any]) -> None:
        now = _now()
        with self.transaction() as con:
            for key, value in values.items():
                con.execute("""INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
                    (str(key), _json(value), now))
            con.execute("UPDATE app_state_meta SET revision=revision+1 WHERE id=1")

    def get_settings(self) -> dict[str, Any]:
        with closing(self.connect()) as con:
            return {r["key"]: json.loads(r["value_json"]) for r in con.execute("SELECT * FROM settings")}

    def create_task(self, title: str, *, task_id: str | None = None, status: str = "pending",
                    priority: str | None = None, kind: str | None = None, deadline: str | None = None,
                    estimated_minutes: int | None = None, notes: str = "", data: dict | None = None) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Task title is required.")
        now, task_id = _now(), task_id or str(uuid.uuid4())
        with self.transaction() as con:
            con.execute("""INSERT INTO tasks(id,title,status,priority,kind,deadline,estimated_minutes,notes,created_at,updated_at,data_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, title.strip(), status, priority, kind, deadline, estimated_minutes, notes, now, now, _json(data or {})))
            con.execute("UPDATE app_state_meta SET revision=revision+1 WHERE id=1")
        return task_id

    def create_session(self, task_id: str, start_at: str, end_at: str, *, session_id: str | None = None,
                       status: str = "scheduled", data: dict | None = None) -> str:
        if not start_at or not end_at or end_at <= start_at:
            raise ValueError("Session end must be later than session start.")
        now, session_id = _now(), session_id or str(uuid.uuid4())
        with self.transaction() as con:
            con.execute("""INSERT INTO sessions(id,task_id,start_at,end_at,status,created_at,updated_at,data_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (session_id, task_id, start_at, end_at, status, now, now, _json(data or {})))
            con.execute("UPDATE app_state_meta SET revision=revision+1 WHERE id=1")
        return session_id

    def get_task(self, task_id: str) -> dict | None:
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            task = dict(row); task["data"] = json.loads(task.pop("data_json"))
            task["sessions"] = [dict(x) for x in con.execute("SELECT * FROM sessions WHERE task_id=? ORDER BY start_at", (task_id,))]
            for session in task["sessions"]:
                session["data"] = json.loads(session.pop("data_json"))
            return task


    def export_app_state(self) -> dict:
        """Return a frontend-compatible, read-only snapshot from SQLite."""
        with closing(self.connect()) as con:
            tasks=[]
            for row in con.execute("SELECT * FROM tasks ORDER BY created_at, id"):
                item=json.loads(row["data_json"] or "{}")
                item["id"]=row["id"]
                item["title"]=row["title"]
                item["status"]=row["status"]
                item["priority"]=row["priority"]
                item["kind"]=row["kind"]
                item["deadline"]=row["deadline"]
                item["duration"]=row["estimated_minutes"]
                item["notes"]=row["notes"]
                sessions=[]
                for sr in con.execute("SELECT * FROM sessions WHERE task_id=? ORDER BY start_at", (row["id"],)):
                    session=json.loads(sr["data_json"] or "{}")
                    start=sr["start_at"]
                    end=sr["end_at"]
                    session.update({"id":sr["id"],"date":start[:10],"start":start[11:16],"end":end[11:16],"status":sr["status"]})
                    sessions.append(session)
                item["sessions"]=sessions
                # Compatibility summary fields: reflect the first active session only.
                active=next((x for x in sessions if x.get("status")=="scheduled"), None)
                if active:
                    item.update({"status":"scheduled","date":active["date"],"start":active["start"],"end":active["end"]})
                elif row["status"]=="scheduled":
                    item["status"]="pending"
                tasks.append(item)
            history=[]
            for row in con.execute("SELECT * FROM action_history ORDER BY created_at DESC LIMIT 500"):
                req=json.loads(row["request_json"] or "{}")
                result=json.loads(row["result_json"] or "{}")
                history.append({"id":row["id"],"at":row["created_at"],"action":row["action_type"],"detail":result.get("detail",req.get("detail",""))})
            settings={r["key"]:json.loads(r["value_json"]) for r in con.execute("SELECT * FROM settings")}
            revision_row = con.execute("SELECT revision FROM app_state_meta WHERE id=1").fetchone()
            revision = int(revision_row[0]) if revision_row else 0
            return {"ok":True,"source":"sqlite","schema_version":self.schema_version(),"revision":revision,"tasks":tasks,"history":history,"settings":settings}

    def reconcile_session_reminders(self, now_local: datetime | None = None) -> dict[str, int]:
        """Create/update one idempotent reminder per scheduled session and lead time."""
        from datetime import timedelta
        now_local = now_local or datetime.now().astimezone().replace(tzinfo=None)
        now = _now()
        created = cancelled = 0
        with self.transaction() as con:
            settings = {r["key"]: json.loads(r["value_json"]) for r in con.execute("SELECT * FROM settings")}
            enabled = settings.get("notifications") is True
            try:
                lead = int(settings.get("reminderMinutes", 10))
            except (TypeError, ValueError):
                lead = 10
            lead = max(0, min(120, lead))
            active = {}
            if enabled:
                rows = con.execute("""SELECT s.id AS session_id,s.start_at,s.status AS session_status,t.title
                    FROM sessions s JOIN tasks t ON t.id=s.task_id WHERE s.status='scheduled'""").fetchall()
                for row in rows:
                    try:
                        start = datetime.fromisoformat(row["start_at"])
                    except ValueError:
                        continue
                    if start.tzinfo:
                        start = start.astimezone().replace(tzinfo=None)
                    due = start - timedelta(minutes=lead)
                    if start <= now_local or due < now_local - timedelta(minutes=2):
                        continue
                    key = f"session:{row['session_id']}:lead:{lead}"
                    active[key] = (row["session_id"], due.isoformat(timespec="seconds"), row["title"])
            existing = con.execute("SELECT id,idempotency_key,status FROM reminders WHERE status IN ('pending','processing')").fetchall()
            active_keys = set(active)
            for row in existing:
                if row["idempotency_key"] not in active_keys:
                    con.execute("UPDATE reminders SET status='cancelled',updated_at=? WHERE id=?", (now, row["id"]))
                    cancelled += 1
            for key, (session_id, due_at, title) in active.items():
                cur = con.execute("""INSERT OR IGNORE INTO reminders
                    (id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json)
                    VALUES(?,?,?,'pending',?,?,?,?)""",
                    (str(uuid.uuid5(uuid.NAMESPACE_URL, key)), session_id, due_at, key, now, now, _json({"title": title, "source": "scheduled_session"})))
                created += cur.rowcount
                con.execute("""UPDATE reminders SET due_at=?,data_json=?,updated_at=?
                    WHERE idempotency_key=? AND status='pending'""", (due_at, _json({"title": title, "source": "scheduled_session"}), now, key))
        return {"created": created, "cancelled": cancelled}

    def claim_due_reminders(self, now_local: datetime | None = None, lease_seconds: int = 120, limit: int = 20) -> list[dict]:
        now_local = now_local or datetime.now().astimezone().replace(tzinfo=None)
        now_text = now_local.isoformat(timespec="seconds")
        stale_before = (now_local - __import__('datetime').timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        claimed = []
        with self.transaction() as con:
            rows = con.execute("""SELECT * FROM reminders WHERE due_at<=? AND
                (status='pending' OR (status='processing' AND COALESCE(last_attempt_at,'')<=?))
                ORDER BY due_at LIMIT ?""", (now_text, stale_before, limit)).fetchall()
            for row in rows:
                cur = con.execute("""UPDATE reminders SET status='processing',attempt_count=attempt_count+1,
                    last_attempt_at=?,updated_at=? WHERE id=? AND
                    (status='pending' OR (status='processing' AND COALESCE(last_attempt_at,'')<=?))""",
                    (now_text, _now(), row["id"], stale_before))
                if cur.rowcount:
                    item = dict(row); item["attempt_count"] = int(row["attempt_count"]) + 1
                    item["data"] = json.loads(item.pop("data_json") or "{}")
                    claimed.append(item)
        return claimed

    def finish_reminder(self, reminder_id: str, success: bool, error: str | None = None, max_attempts: int = 5) -> None:
        now = _now()
        with self.transaction() as con:
            row = con.execute("SELECT attempt_count FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if not row:
                return
            status = "delivered" if success else ("failed" if int(row["attempt_count"]) >= max_attempts else "pending")
            data_row = con.execute("SELECT data_json FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            data = json.loads(data_row["data_json"] or "{}")
            if error:
                data["last_error"] = str(error)[:500]
            con.execute("UPDATE reminders SET status=?,data_json=?,updated_at=? WHERE id=?",
                        (status, _json(data), now, reminder_id))

    def reminder_counts(self) -> dict[str, int]:
        with closing(self.connect()) as con:
            return {r["status"]: int(r["n"]) for r in con.execute("SELECT status,COUNT(*) n FROM reminders GROUP BY status")}

    def reconcile_session_reminders(self, now_local: datetime | None = None) -> dict[str, int]:
        from datetime import timedelta
        now_local = now_local or datetime.now().astimezone().replace(tzinfo=None)
        now = _now()
        created = cancelled = 0
        with self.transaction() as con:
            settings = {r["key"]: json.loads(r["value_json"]) for r in con.execute("SELECT * FROM settings")}
            enabled = settings.get("notifications") is True
            try: lead = int(settings.get("reminderMinutes", 10))
            except (TypeError, ValueError): lead = 10
            lead = max(0, min(120, lead))
            active = {}
            if enabled:
                rows = con.execute("""SELECT s.id AS session_id,s.start_at,s.status AS session_status,t.title
                    FROM sessions s JOIN tasks t ON t.id=s.task_id WHERE s.status='scheduled'""").fetchall()
                for row in rows:
                    try: start = datetime.fromisoformat(row["start_at"])
                    except ValueError: continue
                    if start.tzinfo: start = start.astimezone().replace(tzinfo=None)
                    if start <= now_local: continue
                    due = start - timedelta(minutes=lead)
                    key = f"session:{row['session_id']}:lead:{lead}"
                    active[key] = (row["session_id"], due.isoformat(timespec="seconds"), row["title"])
            existing = con.execute("SELECT id,idempotency_key,status FROM reminders WHERE status IN ('pending','processing')").fetchall()
            active_keys = set(active)
            for row in existing:
                if row["idempotency_key"] not in active_keys:
                    con.execute("UPDATE reminders SET status='cancelled',updated_at=? WHERE id=?", (now, row["id"]))
                    cancelled += 1
            for key, (session_id, due_at, title) in active.items():
                cur = con.execute("""INSERT OR IGNORE INTO reminders
                    (id,session_id,due_at,status,idempotency_key,created_at,updated_at,data_json)
                    VALUES(?,?,?,'pending',?,?,?,?)""",
                    (str(uuid.uuid5(uuid.NAMESPACE_URL, key)), session_id, due_at, key, now, now, _json({"title": title, "source": "scheduled_session"})))
                created += cur.rowcount
                con.execute("UPDATE reminders SET due_at=?,data_json=?,updated_at=? WHERE idempotency_key=? AND status='pending'",
                            (due_at, _json({"title": title, "source": "scheduled_session"}), now, key))
        return {"created": created, "cancelled": cancelled}

    def claim_due_reminders(self, now_local: datetime | None = None, lease_seconds: int = 120, limit: int = 20) -> list[dict]:
        from datetime import timedelta
        now_local = now_local or datetime.now().astimezone().replace(tzinfo=None)
        now_text = now_local.isoformat(timespec="seconds")
        stale_before = (now_local - timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        claimed = []
        with self.transaction() as con:
            rows = con.execute("""SELECT * FROM reminders WHERE due_at<=? AND
                (status='pending' OR (status='processing' AND COALESCE(last_attempt_at,'')<=?))
                ORDER BY due_at LIMIT ?""", (now_text, stale_before, limit)).fetchall()
            for row in rows:
                cur = con.execute("""UPDATE reminders SET status='processing',attempt_count=attempt_count+1,
                    last_attempt_at=?,updated_at=? WHERE id=? AND
                    (status='pending' OR (status='processing' AND COALESCE(last_attempt_at,'')<=?))""",
                    (now_text, _now(), row["id"], stale_before))
                if cur.rowcount:
                    item = dict(row); item["attempt_count"] = int(row["attempt_count"]) + 1
                    item["data"] = json.loads(item.pop("data_json") or "{}")
                    claimed.append(item)
        return claimed

    def finish_reminder(self, reminder_id: str, success: bool, error: str | None = None, max_attempts: int = 5) -> None:
        now = _now()
        with self.transaction() as con:
            row = con.execute("SELECT attempt_count,data_json FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if not row: return
            status = "delivered" if success else ("failed" if int(row["attempt_count"]) >= max_attempts else "pending")
            data = json.loads(row["data_json"] or "{}")
            if error: data["last_error"] = str(error)[:500]
            con.execute("UPDATE reminders SET status=?,data_json=?,updated_at=? WHERE id=?",
                        (status, _json(data), now, reminder_id))

    def reminder_counts(self) -> dict[str, int]:
        with closing(self.connect()) as con:
            return {r["status"]: int(r["n"]) for r in con.execute("SELECT status,COUNT(*) n FROM reminders GROUP BY status")}

    def record_receipt(self, key: str, operation: str, result: dict) -> dict:
        if not key:
            raise ValueError("An idempotency key is required.")
        with self.transaction() as con:
            old = con.execute("SELECT operation,result_json FROM operation_receipts WHERE idempotency_key=?", (key,)).fetchone()
            if old:
                if old["operation"] != operation:
                    raise ValueError("Idempotency key was already used for a different operation.")
                return json.loads(old["result_json"])
            con.execute("INSERT INTO operation_receipts VALUES(?,?,?,?)", (key, operation, _json(result), _now()))
            return result

    def import_backup(self, backup: dict) -> dict[str, int]:
        """Import legacy RIYA JSON backup atomically; preserve task/session IDs where possible."""
        if not isinstance(backup, dict) or backup.get("app") != "RIYA" or not isinstance(backup.get("tasks"), list):
            raise ValueError("Invalid RIYA backup format.")
        now = _now()
        imported = {"tasks": 0, "sessions": 0, "history": 0, "settings": 0}
        with self.transaction() as con:
            for task in backup["tasks"]:
                if not isinstance(task, dict) or not str(task.get("title", "")).strip():
                    continue
                tid = str(task.get("id") or uuid.uuid4())
                status = task.get("status", "pending")
                if status not in {"pending", "in_progress", "completed", "cancelled", "archived", "scheduled"}:
                    status = "pending"
                if status == "scheduled":
                    status = "pending"  # session status remains authoritative for schedule state
                extras = dict(task)
                sessions = extras.pop("sessions", []) if isinstance(extras.get("sessions", []), list) else []
                con.execute("""INSERT INTO tasks(id,title,status,priority,kind,deadline,estimated_minutes,notes,created_at,updated_at,data_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,status=excluded.status,
                    priority=excluded.priority,kind=excluded.kind,deadline=excluded.deadline,estimated_minutes=excluded.estimated_minutes,
                    notes=excluded.notes,updated_at=excluded.updated_at,data_json=excluded.data_json""",
                    (tid, str(task["title"]).strip(), status, task.get("priority"), task.get("kind"), task.get("deadline"),
                     task.get("duration"), str(task.get("notes", "")), task.get("createdAt", now), now, _json(extras)))
                imported["tasks"] += 1
                for session in sessions:
                    if not isinstance(session, dict) or not session.get("date") or not session.get("start") or not session.get("end"):
                        continue
                    sid = str(session.get("id") or uuid.uuid4())
                    start_at = f"{session['date']}T{session['start']}:00"
                    end_at = f"{session['date']}T{session['end']}:00"
                    if end_at <= start_at:
                        continue
                    sstatus = session.get("status", "scheduled")
                    if sstatus not in {"scheduled", "completed", "cancelled", "missed", "rescheduled"}:
                        sstatus = "scheduled"
                    con.execute("""INSERT INTO sessions(id,task_id,start_at,end_at,status,created_at,updated_at,data_json)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET task_id=excluded.task_id,start_at=excluded.start_at,
                        end_at=excluded.end_at,status=excluded.status,updated_at=excluded.updated_at,data_json=excluded.data_json""",
                        (sid, tid, start_at, end_at, sstatus, now, now, _json(session)))
                    imported["sessions"] += 1
            for item in backup.get("history", []) if isinstance(backup.get("history", []), list) else []:
                if not isinstance(item, dict):
                    continue
                aid = str(item.get("id") or uuid.uuid4())
                con.execute("""INSERT OR IGNORE INTO action_history(id,action_type,risk_level,status,requested_by,created_at,updated_at,request_json,result_json)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (aid, str(item.get("action", "legacy_history")), 0, "verified", "legacy_import",
                     item.get("at", now), now, _json(item), _json({"detail": item.get("detail", "")})))
                imported["history"] += 1
            for key, value in (backup.get("settings", {}) or {}).items():
                con.execute("INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                            (str(key), _json(value), now))
                imported["settings"] += 1
            con.execute("UPDATE app_state_meta SET revision=revision+1 WHERE id=1")
        return imported

    def export_backup(self) -> dict:
        with closing(self.connect()) as con:
            tasks = []
            for row in con.execute("SELECT * FROM tasks ORDER BY created_at"):
                task = dict(row); extras = json.loads(task.pop("data_json")); task.update(extras)
                task["id"] = row["id"]
                task["sessions"] = []
                for sr in con.execute("SELECT * FROM sessions WHERE task_id=? ORDER BY start_at", (row["id"],)):
                    s = dict(sr); data = json.loads(s.pop("data_json"))
                    start = s.pop("start_at"); end = s.pop("end_at")
                    s.update(data); s["date"] = start[:10]; s["start"] = start[11:16]; s["end"] = end[11:16]
                    s["id"] = sr["id"]; task["sessions"].append(s)
                tasks.append(task)
            history = []
            for row in con.execute("SELECT * FROM action_history ORDER BY created_at"):
                history.append(json.loads(row["request_json"]))
            settings = self.get_settings()
            return {"app": "RIYA", "version": 2, "exportedAt": _now(), "tasks": tasks, "history": history, "settings": settings}

    def replace_app_state(self, backup: dict, expected_revision: int | None = None) -> dict[str, int]:
        """Atomically replace the frontend-owned task/history/settings snapshot.

        This is used by the local UI sync bridge. All rows are validated before
        the transaction; the replacement and receipt are committed together.
        """
        if not isinstance(backup, dict) or backup.get("app") != "RIYA":
            raise ValueError("Invalid RIYA state payload.")
        tasks = backup.get("tasks")
        history = backup.get("history", [])
        settings = backup.get("settings", {})
        if not isinstance(tasks, list) or not isinstance(history, list) or not isinstance(settings, dict):
            raise ValueError("RIYA state requires tasks/history arrays and a settings object.")
        now = _now()
        imported = {"tasks": 0, "sessions": 0, "history": 0, "settings": 0}
        # Validate and normalise before opening the write transaction.
        clean_tasks = []
        seen_task_ids = set()
        seen_session_ids = set()
        for task in tasks:
            if not isinstance(task, dict) or not str(task.get("title", "")).strip():
                raise ValueError("Every task must have a non-empty title.")
            tid = str(task.get("id") or "")
            if not tid or len(tid) > 160 or tid in seen_task_ids:
                raise ValueError("Every task must have a unique, valid ID.")
            seen_task_ids.add(tid)
            status = task.get("status", "pending")
            if status == "scheduled":
                status = "pending"
            if status not in {"pending", "in_progress", "completed", "cancelled", "archived"}:
                status = "pending"
            sessions = task.get("sessions", [])
            if not isinstance(sessions, list):
                raise ValueError(f"Sessions for task {tid} must be an array.")
            clean_sessions = []
            for session in sessions:
                if not isinstance(session, dict):
                    raise ValueError(f"Invalid session in task {tid}.")
                sid = str(session.get("id") or "")
                day, start, end = session.get("date"), session.get("start"), session.get("end")
                if not sid or len(sid) > 160 or sid in seen_session_ids:
                    raise ValueError("Every session must have a unique, valid ID.")
                if not all(isinstance(x, str) for x in (day, start, end)):
                    raise ValueError(f"Session {sid} requires date, start and end.")
                try:
                    from datetime import date as _date, time as _time
                    _date.fromisoformat(day)
                    st, et = _time.fromisoformat(start), _time.fromisoformat(end)
                except Exception as exc:
                    raise ValueError(f"Session {sid} has an invalid date or time.") from exc
                if et <= st:
                    raise ValueError(f"Session {sid} end must be later than its start.")
                # Store a canonical ISO time; do not append seconds to an
                # already-seconds-bearing input.
                session = dict(session)
                session["start"] = st.isoformat(timespec="seconds")
                session["end"] = et.isoformat(timespec="seconds")
                ss = session.get("status", "scheduled")
                if ss not in {"scheduled", "completed", "cancelled", "missed", "rescheduled"}:
                    raise ValueError(f"Session {sid} has an invalid status.")
                seen_session_ids.add(sid)
                clean_sessions.append(dict(session))
            clean_tasks.append((dict(task), tid, status, clean_sessions))
        with self.transaction() as con:
            current_row = con.execute("SELECT revision FROM app_state_meta WHERE id=1").fetchone()
            current_revision = int(current_row[0]) if current_row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise RuntimeError(f"REVISION_CONFLICT: expected {expected_revision}, current {current_revision}")
            # Child rows first; no other module-owned tables are touched.
            # Preserve reminders and audit history. A reminder tied to a session
            # removed from the UI snapshot is cancelled and detached, not deleted.
            incoming_session_ids = {str(session["id"]) for _, _, _, sessions in clean_tasks for session in sessions}
            linked = con.execute("SELECT id,session_id FROM reminders WHERE session_id IS NOT NULL").fetchall()
            for reminder in linked:
                if reminder["session_id"] not in incoming_session_ids:
                    con.execute("UPDATE reminders SET status='cancelled',session_id=NULL,updated_at=? WHERE id=?",
                                (now, reminder["id"]))
            # Keep proposal records for audit; invalidate their task references
            # before replacing the UI-owned task snapshot.
            con.execute("UPDATE proposals SET status='stale',updated_at=? WHERE status='pending'", (now,))
            con.execute("DELETE FROM proposal_items")
            con.execute("DELETE FROM sessions")
            con.execute("DELETE FROM tasks")
            con.execute("DELETE FROM settings")
            for task, tid, status, sessions in clean_tasks:
                extras = dict(task)
                extras.pop("sessions", None)
                con.execute("""INSERT INTO tasks(id,title,status,priority,kind,deadline,estimated_minutes,notes,created_at,updated_at,data_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (tid, str(task["title"]).strip(), status, task.get("priority"), task.get("kind"),
                     task.get("deadline"), task.get("duration"), str(task.get("notes", "")),
                     task.get("createdAt", now), now, _json(extras)))
                imported["tasks"] += 1
                for session in sessions:
                    sid = str(session["id"])
                    start_at = f'{session["date"]}T{session["start"]}'
                    end_at = f'{session["date"]}T{session["end"]}'
                    con.execute("""INSERT INTO sessions(id,task_id,start_at,end_at,status,created_at,updated_at,data_json)
                        VALUES(?,?,?,?,?,?,?,?)""",
                        (sid, tid, start_at, end_at, session.get("status", "scheduled"),
                         now, now, _json(session)))
                    imported["sessions"] += 1
            for item in history[-500:]:
                if not isinstance(item, dict):
                    continue
                aid = str(item.get("id") or uuid.uuid4())
                con.execute("""INSERT INTO action_history(id,action_type,risk_level,status,requested_by,created_at,updated_at,request_json,result_json)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET action_type=excluded.action_type,updated_at=excluded.updated_at,
                    request_json=excluded.request_json,result_json=excluded.result_json""",
                    (aid, str(item.get("action", "history"))[:120], 0, "verified", "user",
                     item.get("at", now), now, _json(item), _json({"detail": item.get("detail", "")})))
                imported["history"] += 1
            for key, value in settings.items():
                con.execute("INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?)",
                            (str(key), _json(value), now))
                imported["settings"] += 1
            con.execute("UPDATE app_state_meta SET revision=revision+1 WHERE id=1")
            imported["revision"] = current_revision + 1
        return imported

