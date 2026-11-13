RIYA v15.3.0 — CONVERSATIONAL BRAIN-DUMP FLOW
===============================================

This build continues from v15.2.0 and corrects the initial brain-dump interaction.

WHAT CHANGED IN v15.3.0
-----------------------
- Removed the backend rule that forcibly replaced a natural AI response with
  "Which one feels like the best place to start?" whenever multiple tasks were found.
- Priority selection is no longer forced immediately after a brain dump.
- Updated the assistant instructions to acknowledge the full list and ask one
  useful missing-detail question at a time.
- Updated the chat copy and composer placeholder to frame RIYA as a conversational
  planning companion rather than a task-entry form.
- Preserved the existing database, API, category foundation, scheduling flow,
  conversation history and reminder worker.

TESTING
-------
- Python unit/integration tests run after the change.
- Ollama model quality still depends on the installed local model and has not
  been live-evaluated in this package.
- Existing reminder worker still provides Windows notifications, not phone calls.

RIYA v15.0 — PERSISTENT CONVERSATION FOUNDATION
===============================================

This build continues from RIYA v14.7 (Simple Page UI) and implements the first
milestone of the selected Hybrid LLM Assistant architecture.

WHAT IS NEW
-----------
1. SQLite schema migration v4
   - Adds ordered conversation message sequencing.
   - Adds turn IDs for idempotent user/assistant message writes.
   - Adds a working_memory table linked to each conversation.
   - Existing schema v1-v3 databases migrate automatically; existing task,
     session, reminder, audit and conversation records are retained.

2. Persistent conversations
   - Create and list independent conversations.
   - Retrieve a complete conversation transcript.
   - Store each user message before model processing.
   - Store each assistant response and its resulting working memory atomically.
   - Prevent duplicate message writes for retried turns.
   - Restore the most recently active conversation after browser refresh/server restart.
   - Start a new chat and reopen saved chats from the History page.

3. Persistent working memory
   - Stores the active goal, extracted draft tasks, pending question, priority state,
     schedule state and current schedule proposal.
   - Loads working memory into the system context sent to Ollama.
   - Keeps the transcript as the source of truth and working memory as a compact
     current-state summary.

4. API endpoints
   GET  /api/conversations
   POST /api/conversations
   GET  /api/conversations/{conversation_id}
   POST /api/conversations/{conversation_id}/messages
   POST /api/conversations/{conversation_id}/memory

5. Chat API changes
   - Accepts conversation_id, turn_id, user_message and user_message_id.
   - Loads the recent transcript from SQLite instead of trusting only browser memory.
   - Persists the assistant response and updated working memory.
   - Keeps the existing Ollama toolchain, task planner, schedule UI and reminder worker.

INSTALL / UPGRADE
-----------------
1. Close RIYA and make a backup of your current RIYA folder.
2. Export a JSON backup from RIYA Settings if you can still open the old version.
3. Extract this ZIP into a NEW folder. Do not extract over your old RIYA folder.
4. To preserve the exact existing SQLite database, copy the old folder's
   data\riya.db into the new folder's data\riya.db. Create the data folder if
   it does not exist. Keep a separate copy of the old database as a backup.
   - The ZIP intentionally does not contain a database file, so it cannot
     overwrite your existing database during extraction.
   - On first startup, schema v4 migration runs automatically.
5. If you do not copy the database, RIYA may import the browser localStorage
   task/settings backup on first launch. That fallback is not a substitute for
   copying the original database when it contains newer records.
6. Open PowerShell in the new folder and run:
       python riya_server.py
7. Open:
       http://127.0.0.1:8000/RIYA.html
8. Check the database status at:
       http://127.0.0.1:8000/api/db/status
   Schema version should report 4 and integrity should be OK.

TESTS AND VERIFICATION
----------------------
Run:
    python -m unittest discover -s tests -v

Automated test verification for the current release is recorded in the v15.1.0 section below.
Additional checks:
- Python compilation passed.
- Inline JavaScript syntax check passed with Node.js.
- v14.7 packaged database migrated to schema v4 in a disposable copy.
- Migrated database integrity_check and foreign_key_check passed.
- Conversation API tests cover create/list/restore, message writes, working-memory
  version checks, multi-turn history delivery to a mocked Ollama endpoint,
  idempotent writes and conversation isolation.

IMPORTANT LIMITATIONS
---------------------
- This milestone establishes durable transcript and working-memory persistence.
  It does NOT yet complete natural-language follow-up intelligence or remove every
  legacy deterministic task/schedule response path. Those are v15.1/v15.2 work.
- Ollama was mocked in API tests. Live Qwen3 response quality was not tested here.
- Actual Windows 11 / Edge rendering, restart behaviour and reminder popups were
  not tested on the user's PC.
- Multi-window simultaneous turns in the same conversation still need explicit
  request serialization; the database writes themselves are transactional.
- Long-term memory extraction/retrieval and full tool calling are future milestones.

LOCAL-FIRST / SAFETY
--------------------
- Conversation data and working memory are stored in local SQLite.
- No cloud service or external account is required for conversation persistence.
- Existing local Ollama endpoint remains http://127.0.0.1:11434/api/chat.
- Existing task/schedule approval safeguards remain in place; this milestone does
  not grant the model direct shell, filesystem or privileged Windows execution.


V15.0.1 HOTFIX — TASK VISIBILITY & PLANNER SYNC
------------------------------------------------
- Tasks extracted from chat are synchronised into the planner task state and
  verified against SQLite before RIYA reports the turn as complete.
- On startup, RIYA repairs missing planner task records from the saved
  conversation working-memory task list. Existing tasks are matched by stable
  AI task ID or a unique normalised title to avoid duplicate records.
- Tasks without a date now appear in the Tasks page under “Tasks awaiting a
  date” instead of disappearing into an invalid/blank date group.
- The Schedule page lists pending tasks from the planner database, not only
  drafts from the currently open conversation.
- The Calendar page also shows tasks awaiting a date so they remain discoverable;
  they appear on a calendar day only after a date is assigned.
- Schedule approval remains separate: captured tasks are pending tasks, not
  automatically scheduled sessions. User approval is still required to save
  proposed time slots.

Upgrade: extract this build into a NEW folder and retain your existing data\riya.db.
Do not overwrite or delete the old RIYA folder until the new build is verified.


V15.1.0 — EDITABLE FOUR-CATEGORY FOUNDATION
-------------------------------------------
New in this build:
1. Four required task categories are defined from the team's principles:
   - High-priority: enjoyable activities that matter for personal growth.
   - Delegatable: important activities the user dislikes and may hand off.
   - Enjoyable, low-growth: enjoyable activities with limited growth contribution.
   - Detrimental: disliked activities that negatively affect growth or progress.
2. Category names and descriptions can be edited in Settings. The four stable
   category IDs remain present so task data and rules stay consistent.
3. A rule-based classification service uses user-confirmed enjoyment,
   importance and growth-impact attributes. A user-selected category always
   overrides a suggestion. Missing/ambiguous attributes produce a review request;
   RIYA does not infer whether the user enjoys a task from its title.
4. New endpoints:
   GET  /api/riya/categories
   POST /api/riya/categories
   POST /api/riya/classify
5. Category definitions are stored in the existing SQLite settings table. No
   database schema migration is required.

VERIFICATION
------------
The v15.1.0 test suite contains 71 tests and passed in the build environment.
Python compilation and the inline JavaScript syntax check passed.

IMPORTANT SCOPE NOTES
---------------------
- This milestone establishes editable category definitions and a tested
  classification API. Full automatic task-to-category assignment in the brain
  dump workflow is the next implementation step.
- The existing reminder worker still delivers Windows desktop notifications;
  outbound phone calls are NOT implemented in this build.
- Voice input/output remains browser speech recognition/synthesis where
  supported. Sarvam speech services are a planned integration, not included.
- The existing local Ollama/Qwen3 chat backend remains in use.
- This package excludes the SQLite database file. RIYA creates data/riya.db on
  first launch. Back up any existing data/riya.db before replacing an installation.


RIYA v15.2.0 — UI/UX refresh
---------------------------
- Refined the existing midnight-indigo / violet visual identity; no palette change.
- Improved desktop workspace navigation with clearer active state, spacing and hover feedback.
- Added compact mobile bottom navigation for easier one-handed use.
- Improved typography, card hierarchy, form focus states, buttons, task rows and calendar interactions.
- Added reduced-motion support and safe-area spacing for mobile devices.
- This is a presentation-layer refresh. Existing routes, page IDs, task logic, API calls and database behavior are retained.
- Outbound phone-call reminders and Healer production integration remain future work.


RIYA v15.4.0 update:
- Adds inline structured task cards to the conversation after task extraction.
- Cards show only details actually returned by the backend; missing details remain visibly unconfirmed.
- Adds stricter category safety instructions: personal categories are not guessed from task titles.
- Existing APIs, SQLite schema, task planner, and reminder worker are retained.
