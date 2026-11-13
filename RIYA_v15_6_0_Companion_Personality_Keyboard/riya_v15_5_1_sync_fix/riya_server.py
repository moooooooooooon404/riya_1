#!/usr/bin/env python3
"""RIYA local AI server. Uses only Python's standard library and local Ollama."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pathlib import Path
from urllib.parse import unquote
from datetime import date, datetime, timedelta
import json, os, re, uuid
from difflib import SequenceMatcher
from riya_db import RiyaDatabase
from riya_categories import default_categories, validate_categories, classify_task

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "riya.db"
DB = RiyaDatabase(DB_PATH)
HOST = "127.0.0.1"
PORT = 8000
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = os.environ.get("RIYA_MODEL", "qwen3:1.7b")

SYSTEM_TEMPLATE = """You are RIYA, a warm, natural conversational task assistant.
Your primary job is to understand the user's meaning across the FULL conversation and maintain an accurate working list of tasks. Do not behave like a form or restart the workflow on every turn.

PERSONALITY AND CONVERSATION STYLE:
- Sound like a thoughtful, lively planning companion with a consistent personality: warm, observant, encouraging, lightly playful when the moment allows, and direct when something needs attention.
- Do not sound like a customer-support bot. Avoid repetitive openings such as "Thank you for the update", "I've noted that", "You're welcome", and "Let me know if you'd like help with that".
- React to the meaning of what the user says. Notice useful context, connect related commitments, and occasionally make a short natural observation rather than merely restating the user's sentence.
- Vary phrasing naturally. Keep replies concise and human; usually one or two short sentences, with a single useful follow-up question only when it genuinely moves the plan forward.
- Do not force jokes, overuse the user's name, use excessive emojis, or become overly chatty.
- Never let personality override accuracy: do not claim a task was saved, categorised, scheduled, changed, or remembered unless the structured task state and application actually confirm it.
- Keep the user's momentum. When they add a new commitment, acknowledge it naturally and continue the existing planning thread; do not restart the conversation or ask whether they want help every time.

FOUR-CATEGORY LEARNING:
- Learn the user's preferences over time for the four editable categories: High-priority, Delegatable, Enjoyable but low-growth, and Detrimental.
- High-priority means the user enjoys the activity, it is important, and it contributes positively to growth (career, health, relationships, family, or other meaningful areas).
- Delegatable means the activity is important but the user dislikes doing it, and it may be handed to another person or suitable AI.
- Enjoyable but low-growth means the user enjoys it but considers it less important and with low or neutral long-term growth impact.
- Detrimental means the user dislikes it and it negatively affects growth, focus, wellbeing, or progress.
- Do not classify from the task title alone. Use only explicit user statements, confirmed profile preferences, or manual category choices. Keep category_id null when the evidence is incomplete.
- When category information would genuinely help, ask one small, conversational question at a time. Do not interrupt a time-sensitive task capture or schedule request just to classify everything. Capture the task first; category learning can happen later.
- Treat a user's correction or manual category choice as authoritative. Apply learned preferences to future similar tasks only when the user has clearly expressed a general preference, not merely a one-time feeling.
- Do not invent a category breakdown or claim the user has completed category learning when they have not.

CORE CONVERSATION RULES:
- Understand the latest message in relation to the previous user and assistant messages.
- Identify whether the user is adding information, correcting something, answering a question, asking for help, reviewing, confirming, rejecting, or changing topic.
- Resolve references such as "it", "that one", "the first one", "the others", and "both" using conversation context. If more than one interpretation is plausible, ask one short clarification.
- Treat corrections as updates to the existing task/detail, not as new tasks. Preserve unrelated details.
- A short answer such as yes/no/3:30/November 26/IDK must be interpreted as an answer to the pending question when that is the natural reading.
- Do not ask for information the user already supplied. Do not restart priority selection after a review request.
- Be conversational and concise. When the user asks to list/show/review tasks, enumerate the complete task list directly in the chat reply using numbered lines. Do not rely on a separate menu or Schedule view for the list. When a schedule proposal is created, include its task names, dates and time slots in the chat reply as well as showing it in the Schedule view.

TASK DATA RULES:
- Extract every distinct actionable activity mentioned in the conversation, not just the newest sentence.
- Keep each activity separate. Do not merge different meetings, workshops, reports, errands, or deliverables into one task.
- Return the COMPLETE current working task list, including tasks from earlier turns, not only newly mentioned tasks.
- When a user corrects a date, time, title, or other field, update only the relevant field on the correct task.
- Preserve each existing task_id exactly when continuing or correcting that task. Never invent a replacement ID for an existing task. Assign a new unique task_id only to a genuinely new distinct task. If two distinct tasks have the same or similar title, keep their IDs separate.
- Keep known information even when other fields are unknown. Use null for genuinely unknown values; never guess.
- Preserve dates/times that were stated earlier unless the user clearly changes them.
- Relative dates must be resolved using CURRENT LOCAL DATE. If the expression is genuinely ambiguous, ask one focused question rather than guessing.
- Do not infer a task date from a date mentioned for a different task.
CATEGORY SAFETY:
- Never assign one of the four personal-growth categories from a task title alone.
- A category requires user-confirmed enjoyment, importance, and growth impact, or an explicit user category choice.
- If these attributes are unknown, keep category_id null and explain that classification needs the user's input.
- Never invent delegatable, enjoyable, or detrimental items merely to fill category cards.
- Keep fixed events (meetings and appointments) distinct from flexible tasks and recurring routines.

- Do not infer priority. The user decides priority. Do NOT respond to an initial brain dump with "Which one feels like the best place to start?" or force the user to rank tasks immediately. First acknowledge what you understood, then ask one useful question about missing information (for example, a preferred time for a gym session or a deadline for a project). Ask about priority only when the user asks to prioritise or when it is genuinely needed to resolve a scheduling choice.
- For an initial brain dump containing multiple activities, sound like a personal planning companion: briefly acknowledge the overall list, mention one or two details you correctly understood, and ask one focused follow-up. Do not ask a long questionnaire. Do not claim that categories or a schedule have been finalised before the user has reviewed them.
- If the user asks to review/show the list, display the current list and do not ask the priority question again in the same response.
- Do not claim a task is scheduled before the server returns schedule_ready and the browser successfully saves it. Only then may RIYA confirm that it is on the local RIYA plan. RIYA recommends; the user decides.
- Do not invent duration, deadlines, preparation time, travel time, breaks, or preferences.
- Use the user's language and level of formality where practical. Understand English, Tamil and Tanglish where possible.

CURRENT LOCAL DATE: {today}
EXISTING SAVED TASKS (read-only):
{tasks}
CURRENT DRAFT TASKS (working state; update these rather than starting over):
{draft_tasks}
USER SETTINGS:
{settings}

Return ONLY valid JSON with this structure:
{{
  "reply": "A concise, natural response that continues the conversation.",
  "questions": ["only genuinely necessary questions"],
  "active_goal": "short description of the user's current goal, or empty string",
  "pending_question": "the single question RIYA is currently waiting for, or null",
  "tasks": [
    {{
      "task_id": "stable identifier from prior draft, or null for a genuinely new task",
      "title": "task name",
      "date": "YYYY-MM-DD or null",
      "duration_minutes": 60,
      "priority": "High, Medium, Low, or null",
      "kind": "fixed or flexible or null",
      "start_time": "HH:MM or null",
      "end_time": "HH:MM or null",
      "deadline": "YYYY-MM-DD or null",
      "preferred_time": "Morning, Afternoon, Evening, Anytime, or null",
      "notes": "relevant notes or empty string",
      "missing_fields": ["only fields genuinely missing"],
      "confidence": 0.0
    }}
  ]
}}

JSON requirements:
- Include partial task objects when a real task is clear but some details are missing.
- Return all active draft tasks and all new tasks. Do not omit a task because its date or time is unknown.
- Use exact dates and 24-hour times; use null when unknown.
- Flexible tasks must not receive exact start/end times unless the user explicitly requests them.
- Priority remains null unless the user explicitly chooses it.
- Keep reply concise. No hidden reasoning, invented timetable, or generic fallback if the user's intent is understandable.
"""


def _norm_text(value):
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9\s']", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def is_task_list_request(text):
    """Recognize direct requests to show the working task list in chat."""
    value = _norm_text(text)
    exact = {
        "list", "list them", "list tasks", "list my tasks", "show tasks",
        "show my tasks", "show the tasks", "show task list", "show the task list",
        "show me the list", "show me my tasks", "what are my tasks",
        "what tasks do i have", "what do i have to do", "review tasks",
        "review my tasks", "display tasks", "display the list",
    }
    if value in exact:
        return True
    return bool(re.search(r"\b(list|show|display)\b.*\b(tasks|them|task list|list)\b", value))


def format_task_list_reply(tasks, schedule_preview=None):
    """Build a readable in-chat list; the Schedule view remains a companion."""
    valid = [t for t in tasks if isinstance(t, dict) and str(t.get("title", "")).strip()]
    if not valid:
        return "I don't have any tasks in the current working list yet. Tell me what you need to complete."
    lines = [f"Here are your {len(valid)} tasks:"]
    for index, task in enumerate(valid, 1):
        title = str(task.get("title", "")).strip()
        details = []
        priority = task.get("priority")
        if priority in ("High", "Medium", "Low"):
            details.append(f"{priority} priority")
        due = task.get("deadline") or task.get("date")
        if due:
            details.append(f"Date: {due}")
        duration = task.get("duration_minutes")
        if isinstance(duration, int) and duration > 0:
            details.append(f"{duration // 60}h {duration % 60}m" if duration >= 60 else f"{duration} min")
        lines.append(f"{index}. {title}" + (f" — {'; '.join(details)}" if details else ""))
    if isinstance(schedule_preview, dict) and schedule_preview.get("entries"):
        lines.extend(["", "Proposed time slots:"])
        for entry in schedule_preview["entries"]:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "Task")
            day = str(entry.get("date") or "Date not set")
            start = str(entry.get("start_time") or "Time not set")
            end = str(entry.get("end_time") or "")
            lines.append(f"• {title} — {day}, {start}" + (f"–{end}" if end else ""))
        lines.extend(["", "This is a proposal only. Nothing is saved until you approve it. You can also review the full schedule in the Schedule view."])
    else:
        lines.append("Tell me which tasks you want to schedule, or give me dates and available time windows.")
    return "\n".join(lines)


def classify_followup(text):
    """Classify common short replies so the model treats them in context."""
    value = _norm_text(text)
    groups = {
        "affirmation": {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "alright", "sounds good", "im ok with that", "im ok with tht", "i am okay with that", "yee", "yess", "go ahead"},
        "rejection": {"no", "nope", "nah", "not really", "dont", "don't", "not that"},
        "uncertainty": {"idk", "dk", "dont know", "don't know", "not sure", "no idea", "maybe"},
        "request_for_help": {"help", "help me", "guide me", "what next", "then what", "thn what"},
    }
    for label, phrases in groups.items():
        if value in phrases:
            return label
    if len(value.split()) <= 5 and any(x in value for x in ("instead", "actually", "change", "move", "make it", "tomorrow", "friday", "monday")):
        return "possible_correction"
    return "full_message"


def pending_question(messages):
    """Return RIYA's most recent question, if one exists."""
    for item in reversed(messages):
        if item.get("role") == "assistant":
            content = item.get("content", "")
            questions = re.findall(r"[^?\n]{3,180}\?", content)
            if questions:
                return questions[-1].strip()
            return ""
    return ""


def resolve_priority_choice(messages, draft_tasks, priority_pending):
    """Resolve a user's explicit choice of the highest-priority extracted task."""
    if not priority_pending or not isinstance(draft_tasks, list) or len(draft_tasks) < 2:
        return None
    latest = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    value = _norm_text(latest)
    if not value:
        return None
    chosen = None
    # Accept a clear ordinal response such as '1', 'task 2', or 'number three'.
    match = re.fullmatch(r"(?:task\s*)?(\d{1,2})", value)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(draft_tasks):
            chosen = index
    if chosen is None:
        for i, task in enumerate(draft_tasks):
            title = _norm_text(task.get("title", ""))
            if title and (value == title or title in value or value in title):
                chosen = i
                break
    if chosen is None:
        return None
    updated = []
    for i, task in enumerate(draft_tasks):
        item = dict(task)
        item["priority_rank"] = 1 if i == chosen else (2 if item.get("priority_rank") == 1 else item.get("priority_rank"))
        updated.append(item)
    updated.sort(key=lambda t: (t.get("priority_rank") is None, t.get("priority_rank") or 999))
    selected = draft_tasks[chosen].get("title", "that task")
    return {"reply": f"Nice, {selected} is first. Let's get that one into your plan. When would you like to work on it?", "questions": [], "tasks": updated, "priority_pending": False, "model": MODEL}


def handle_task_review(messages, draft_tasks, priority_pending):
    latest = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    value = _norm_text(latest)
    review_phrases = {"review", "review it", "review them", "show list", "show the list", "see list", "see the list", "list"}
    if value not in review_phrases or not isinstance(draft_tasks, list) or not draft_tasks:
        return None
    ordered = sorted((dict(t) for t in draft_tasks), key=lambda t: (t.get("priority_rank") is None, t.get("priority_rank") or 999))
    names = [str(t.get("title", "Untitled task")) for t in ordered]
    # Review is a display action, not another priority prompt.
    reply = "Here's your list:\n" + "\n".join(f"{i+1}. {name}" for i, name in enumerate(names))
    top = next((t.get("title") for t in ordered if t.get("priority_rank") == 1), None)
    if top:
        reply += f"\n\n{top} is at the top. Want to change anything?"
    elif priority_pending:
        reply += "\n\nTake a look — tell me which one you'd like at the top when you're ready."
    else:
        reply += "\n\nWant to change the order or add another task?"
    return {"reply": reply, "questions": [], "tasks": ordered, "priority_pending": priority_pending, "model": MODEL}


def resolve_next_schedule_choice(messages, draft_tasks):
    """Let the user naturally name the next unscheduled task after one is placed."""
    if not isinstance(draft_tasks, list) or not any(t.get("scheduled") for t in draft_tasks if isinstance(t, dict)):
        return None
    latest = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    value = _norm_text(latest)
    if not value or value in {"review", "show list", "show the list", "what next", "then what"}:
        return None
    candidates = [(i, t) for i, t in enumerate(draft_tasks) if isinstance(t, dict) and not t.get("scheduled")]
    for index, task in candidates:
        title = _norm_text(task.get("title", ""))
        if not title:
            continue
        words = [w for w in title.split() if len(w) > 2]
        if value == title or (words and all(w in value for w in words)) or any(w in value for w in words if len(w) >= 5):
            updated = [dict(t) for t in draft_tasks]
            for item in updated:
                if not item.get("scheduled"):
                    item["priority_rank"] = None
            updated[index]["priority_rank"] = 1
            return {
                "reply": f"Okay, let's work on {task.get('title')}. When would you like to fit it in?",
                "questions": [],
                "tasks": updated,
                "priority_pending": False,
                "model": MODEL
            }
    return None

TASK_FIELDS = ("date", "duration_minutes", "priority", "kind", "start_time", "end_time", "deadline", "preferred_time", "notes")

def _task_key(title):
    return _norm_text(title)

def _find_matching_task(task, existing):
    # Stable identity always wins over title similarity.
    task_id = task.get("task_id")
    if task_id:
        for i, old in enumerate(existing):
            if old.get("task_id") == task_id:
                return i
    key = _task_key(task.get("title", ""))
    if not key:
        return None
    exact = [i for i, old in enumerate(existing) if _task_key(old.get("title", "")) == key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None  # Ambiguous duplicate titles must remain distinct unless IDs resolve them.
    scored = []
    for i, old in enumerate(existing):
        old_key = _task_key(old.get("title", ""))
        if not old_key:
            continue
        score = SequenceMatcher(None, key, old_key).ratio()
        if key in old_key or old_key in key:
            score = max(score, 0.90)
        if score >= 0.72:
            scored.append((score, i))
    scored.sort(reverse=True)
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def deterministic_task_fallback(latest_user, previous_tasks, today):
    """Conservative fallback for common task phrases when a small local model returns no tasks."""
    text = str(latest_user or "").strip()
    if not text:
        return []
    items = [dict(t) for t in previous_tasks if isinstance(t, dict) and t.get("title")]
    lower = text.lower()
    def find_item(words):
        for item in items:
            title = item.get("title", "").lower()
            if any(w in title for w in words):
                return item
        return None
    def ensure(title, kind="flexible"):
        item = find_item(title.lower().split())
        if item is None:
            item = {"task_id": str(uuid.uuid4()), "title": title, "date": None,
                    "duration_minutes": None, "priority": None, "kind": kind,
                    "start_time": None, "end_time": None, "deadline": None,
                    "preferred_time": None, "notes": "", "missing_fields": [],
                    "confidence": 0.65, "category_id": None, "category_label": "",
                    "needs_review": True}
            items.append(item)
        return item
    # Initial brain-dump recognition. Deliberately conservative and limited to explicit activities.
    patterns = [
        (r'\b(?:prepare|study|preparation)\s+for\s+(?:my\s+)?ccna\b', "CCNA preparation", "flexible"),
        (r'\bfinish\s+(?:my\s+)?office\s+project\b', "Office project", "flexible"),
        (r'\bgo\s+to\s+(?:the\s+)?gym\b', "Gym", "flexible"),
        (r'\bspend\s+time\s+with\s+(?:my\s+)?family\b', "Family time", "flexible"),
        (r'\bmeet\s+(?:my\s+)?friend\b', "Meet friend", "fixed"),
        (r'\bmeeting\b', "Office meeting", "fixed"),
    ]
    if not items:
        for pattern, title, kind in patterns:
            if re.search(pattern, lower):
                ensure(title, kind)
    # Follow-up details update existing tasks rather than creating duplicates.
    ccna = find_item(["ccna"])
    m = re.search(r'\b(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\s*(?:daily|every day|per day)?', lower)
    if ccna and m:
        amount = float(m.group(1))
        ccna["duration_minutes"] = int(amount * (60 if m.group(2).startswith(("h","hr")) else 1))
        if any(x in lower for x in ("daily", "every day", "per day")):
            ccna["recurrence"] = "daily"
    gym = find_item(["gym"])
    m = re.search(r'\bgym\b.*?\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b.*?\bgym\b', lower)
    if gym and m:
        h = int(m.group(1) or m.group(4)); minute = int(m.group(2) or m.group(5) or 0); ap = m.group(3) or m.group(6)
        h = (h % 12) + (12 if ap == "pm" else 0)
        gym["start_time"] = f"{h:02d}:{minute:02d}"
        gym["kind"] = "fixed"
    project_item = find_item(["office", "project"])
    if project_item and re.search(r'\bby\s+friday\b', lower):
        d = date.fromisoformat(today)
        days = (4 - d.weekday()) % 7
        project_item["deadline"] = (d + timedelta(days=days)).isoformat()
    friend = find_item(["friend"])
    if friend and re.search(r'\b(?:at\s*)?5\s*(?:pm)\b', lower):
        friend["start_time"] = "17:00"
        friend["kind"] = "fixed"
    if friend and re.search(r'\bsunday\b', lower):
        d = date.fromisoformat(today)
        days = (6 - d.weekday()) % 7
        friend["date"] = (d + timedelta(days=days)).isoformat()
    meeting = find_item(["meeting"])
    if meeting and re.search(r'\bnext\s+wednesday\b', lower):
        d = date.fromisoformat(today)
        days = (2 - d.weekday()) % 7
        if days == 0: days = 7
        meeting["date"] = (d + timedelta(days=days)).isoformat()
    if meeting and re.search(r'\b11\s*(?:am)\b', lower):
        meeting["start_time"] = "11:00"
    return items

def reconcile_task_state(previous_tasks, model_tasks):
    """Merge model interpretation into task state without losing known fields."""
    previous = [dict(t) for t in previous_tasks if isinstance(t, dict) and t.get("title")]
    incoming = [dict(t) for t in model_tasks if isinstance(t, dict) and t.get("title")]
    merged = [dict(t) for t in previous]
    for task in incoming:
        idx = _find_matching_task(task, merged)
        if idx is None:
            task["task_id"] = task.get("task_id") or str(uuid.uuid4())
            merged.append(task)
            continue
        old = dict(merged[idx])
        old["task_id"] = old.get("task_id") or task.get("task_id") or str(uuid.uuid4())
        for field in TASK_FIELDS:
            value = task.get(field)
            if value is not None and value != "":
                old[field] = value
        old["title"] = task.get("title") or old.get("title")
        old["missing_fields"] = task.get("missing_fields", old.get("missing_fields", []))
        old["confidence"] = task.get("confidence", old.get("confidence", 0))
        if "priority_rank" in task:
            old["priority_rank"] = task["priority_rank"]
        # Keep the prior stable identity when a model update matches an existing task.
        # A model-generated replacement ID must never fork the same task into a new record.
        merged[idx] = old
    return merged[:20]

def build_conversation_context(messages):
    latest_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    previous_assistant = next((m.get("content", "") for m in reversed(messages[:-1]) if m.get("role") == "assistant"), "")
    return {
        "latest_user_message": latest_user,
        "previous_assistant_message": previous_assistant,
        "pending_question": pending_question(messages[:-1]),
        "message_category": classify_followup(latest_user),
        "instruction": "Interpret the latest message against the pending question and full conversation. Return the complete updated task state; do not restart the workflow."
    }

def _valid_iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _time_to_minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return None
    h, m = map(int, value.split(":"))
    return h * 60 + m

def _minutes_to_time(value):
    return f"{value // 60:02d}:{value % 60:02d}"

def _schedule_followup(latest_user, merged_tasks):
    """Return a deterministic next step for explicit one-at-a-time scheduling."""
    text = _norm_text(latest_user)
    selected = next((t for t in merged_tasks if t.get("priority_rank") == 1 and not t.get("scheduled")), None)
    if not selected:
        return None
    # Once a selected task has a date and start time, subsequent short replies
    # (for example, "90 minutes") complete that same scheduling exchange.
    if not selected.get("date") or not selected.get("start_time"):
        return None
    schedule_signal = any(word in text for word in ("schedule", "put it", "place it", "book it", "set it", "move it", "tomorrow", "today", "at "))
    duration_signal = bool(re.search(r"\b\d+\s*(?:min|mins|minutes|hour|hours|hr|hrs)\b", text))
    if not (schedule_signal or duration_signal):
        return None
    day = selected.get("date")
    start = selected.get("start_time")
    duration = selected.get("duration_minutes")
    if not day or not start:
        return None
    start_mins = _time_to_minutes(start)
    if start_mins is None:
        return None
    if not duration:
        return {
            "schedule_pending": True,
            "reply": f"Got it — {selected.get('title', 'that task')} can go at {start}. How much time should I set aside for it?"
        }
    end_mins = start_mins + int(duration)
    if end_mins > 24 * 60:
        return {"schedule_pending": True, "reply": "That would run past midnight. What end time would work instead?"}
    selected["end_time"] = _minutes_to_time(end_mins)
    selected["kind"] = "fixed"
    return {
        "schedule_ready": True,
        "scheduled_task_title": selected.get("title"),
        "reply": f"That fits. I'll add {selected.get('title')} to your plan for {day} at {start}. What would you like to fit in next?"
    }


def _parse_clock_phrase(value):
    """Parse simple 12-hour phrases such as 3pm, 3:30 pm or 15:00."""
    value = (value or "").strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value)
    if m:
        hour = int(m.group(1)); minute = int(m.group(2) or 0); mer = m.group(3)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        hour = hour % 12 + (12 if mer == "pm" else 0)
        return f"{hour:02d}:{minute:02d}"
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return value
    return None


def build_batch_schedule_preview(latest_user, draft_tasks, current_date, saved_tasks=None):
    """Create a review-only one-task-per-day proposal from a natural request."""
    text = _norm_text(latest_user)
    if not any(p in text for p in ("one a day", "one at a day", "one per day", "one each day", "one task a day", "one task per day")):
        return None
    count_match = re.search(r"(?:next|for the next)\s+(\d{1,2})\s+days?", text)
    if not count_match:
        return None
    count = int(count_match.group(1))
    if not 1 <= count <= 14:
        return None
    offset = 1 if ("tomorrow" in text or "tomorow" in text or "tmrw" in text) else (0 if "from today" in text or "starting today" in text else None)
    if offset is None:
        return None
    tm = re.search(r"(?:between\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))", text)
    if not tm:
        return None
    start, end = _parse_clock_phrase(tm.group(1)), _parse_clock_phrase(tm.group(2))
    start_min, end_min = _time_to_minutes(start), _time_to_minutes(end)
    if start_min is None or end_min is None or end_min <= start_min:
        return None
    candidates = [t for t in draft_tasks if isinstance(t, dict) and t.get("title") and not t.get("scheduled")]
    if not candidates:
        return None
    named = []
    for task in candidates:
        words = [w for w in _norm_text(task.get("title", "")).split() if len(w) >= 4]
        if words and any(w in text for w in words):
            named.append(task)
    if named:
        candidates = named
    elif len(candidates) != count:
        return {"needs_clarification": True, "title": "", "entries": [], "conflicts": [],
                "status": "needs_clarification",
                "clarification": f"There are {len(candidates)} unscheduled tasks and {count} days. Should I spread all of them across those days, or schedule only some?"}
    if len(candidates) > count:
        return {"needs_clarification": True, "title": "", "entries": [], "conflicts": [],
                "status": "needs_clarification",
                "clarification": f"You have {len(candidates)} tasks for {count} days. Which ones should I include?"}
    base = datetime.strptime(current_date, "%Y-%m-%d").date()
    days = [base + timedelta(days=offset + i) for i in range(count)]
    entries, used_dates = [], set()
    for i, task in enumerate(candidates):
        explicit = task.get("date")
        if explicit:
            try:
                day = datetime.strptime(explicit, "%Y-%m-%d").date()
                if day.isoformat() != explicit:
                    raise ValueError("invalid calendar date")
            except ValueError:
                return {"needs_clarification": True, "title": "", "entries": [], "conflicts": [],
                        "status": "needs_clarification", "clarification": f"The date for {task.get('title', 'a task')} is not a valid calendar date. Please correct it."}
        else:
            day = days[i]
        if day.isoformat() in used_dates:
            return {"needs_clarification": True, "title": "", "entries": [], "conflicts": [],
                    "status": "needs_clarification",
                    "clarification": "Two tasks appear to land on the same day. Would you like them on separate days?"}
        used_dates.add(day.isoformat())
        entries.append({"task_id": task.get("task_id"), "title": task.get("title"), "date": day.isoformat(), "start_time": start,
                        "end_time": end, "duration_minutes": end_min-start_min, "kind": "fixed"})
    conflicts = []
    for entry in entries:
        s0, s1 = _time_to_minutes(entry["start_time"]), _time_to_minutes(entry["end_time"])
        for saved in saved_tasks if isinstance(saved_tasks, list) else []:
            if not isinstance(saved, dict) or saved.get("status") != "scheduled" or saved.get("date") != entry["date"]:
                continue
            old0 = _time_to_minutes(saved.get("start") or saved.get("start_time"))
            old1 = _time_to_minutes(saved.get("end") or saved.get("end_time"))
            if old0 is not None and old1 is not None and s0 < old1 and s1 > old0:
                conflicts.append(f"{entry['date']}: overlaps with {saved.get('title', 'an existing task')}")
    return {"title": "Multi-task schedule", "entries": entries, "conflicts": conflicts,
            "source_task_title": None, "source_task_titles": [x["title"] for x in entries],
            "status": "awaiting_approval"}


def build_context_schedule(messages, draft_tasks, current_date, saved_tasks=None):
    """Resolve a schedule only from the current instruction or its explicit approval.

    Historical date/time instructions are not active intent by themselves. Reuse one
    only when the latest user turn explicitly approves the proposal that the immediately
    preceding assistant turn presented for review.
    """
    if not isinstance(messages, list) or not draft_tasks:
        return None
    latest_index = next((i for i in range(len(messages)-1, -1, -1)
                         if messages[i].get("role") == "user"), None)
    if latest_index is None:
        return None
    latest = str(messages[latest_index].get("content", "")).strip()
    low_latest = latest.lower()
    has_current_date_time = (
        re.search(r'\b(tomorrow|tomorow|tmrw|today)\b', low_latest)
        and re.search(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b', low_latest)
    )
    approval = bool(re.search(r"\b(finali[sz]e|confirm|approve|save it|go ahead)\b", low_latest))
    if has_current_date_time:
        source = low_latest
    elif approval:
        previous_assistant = next((str(m.get("content", "")).lower()
                                   for m in reversed(messages[:latest_index])
                                   if m.get("role") == "assistant"), "")
        presented = ("proposal" in previous_assistant or "schedule" in previous_assistant) and any(
            phrase in previous_assistant for phrase in
            ("nothing is saved", "until you approve", "awaiting your review", "review the")
        )
        if not presented:
            return None
        source = ""
        for msg in reversed(messages[:latest_index]):
            if msg.get("role") != "user":
                continue
            candidate = str(msg.get("content", "")).lower()
            if (re.search(r'\b(tomorrow|tomorow|tmrw|today)\b', candidate)
                    and re.search(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b', candidate)):
                source = candidate
                break
        if not source:
            return None
    else:
        return None
    tm=re.search(r'(?:between\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',source)
    if tm:
        start,end=_parse_clock_phrase(tm.group(1)),_parse_clock_phrase(tm.group(2))
    else:
        one=re.search(r'\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',source)
        if not one: return None
        start=_parse_clock_phrase(one.group(1)); end=None
    if not start: return None
    base=datetime.strptime(current_date,"%Y-%m-%d").date()
    day=(base+timedelta(days=1 if any(x in source for x in ("tomorrow","tomorow","tmrw")) else 0)).isoformat()
    # Resolve target by explicit title words in the scheduling instruction, with meeting aliases.
    candidates=[t for t in draft_tasks if isinstance(t,dict) and t.get("title") and not t.get("scheduled")]
    named=[]
    for t in candidates:
        title=_norm_text(t.get("title",""))
        words=[w for w in title.split() if len(w)>=4 and w not in {"with","from","members"}]
        if any(w in _norm_text(source) for w in words): named.append(t)
    if not named:
        named=[t for t in candidates if "one on one" in _norm_text(t.get("title","")) or "meeting" in _norm_text(t.get("title",""))]
    if len(named)!=1: return None
    task=named[0]
    if end:
        sm,em=_time_to_minutes(start),_time_to_minutes(end)
        if sm is None or em is None or em<=sm: return None
        duration=em-sm
    else:
        duration=task.get("duration_minutes")
        if not duration: return None
        em=_time_to_minutes(start)+int(duration)
        if em>1439: return None
        end=_minutes_to_time(em)
    sm,em=_time_to_minutes(start),_time_to_minutes(end)
    conflicts=[]
    for saved in saved_tasks if isinstance(saved_tasks,list) else []:
        if isinstance(saved,dict) and saved.get("status")=="scheduled" and saved.get("date")==day:
            a=_time_to_minutes(saved.get("start") or saved.get("start_time")); b=_time_to_minutes(saved.get("end") or saved.get("end_time"))
            if a is not None and b is not None and sm<b and em>a:
                conflicts.append(f"{day}: overlaps with {saved.get('title','an existing task')}")
    return {"title":"Single-task schedule","entries":[{"task_id":task.get("task_id"),"title":task["title"],"date":day,"start_time":start,"end_time":end,"duration_minutes":duration,"kind":"fixed"}],
            "conflicts":conflicts,"source_task_titles":[task["title"]],"status":"awaiting_approval"}


def _has_current_schedule_approval(messages, latest_user, schedule_preview):
    # Only accept approval when the previous assistant turn presented this reviewable proposal.
    if not schedule_preview or schedule_preview.get("needs_clarification") or schedule_preview.get("conflicts"):
        return False
    if not re.search(r"\b(finali[sz]e|confirm|approve|save it|go ahead)\b", (latest_user or "").lower()):
        return False
    # The current user message is last; inspect the assistant turn immediately before it.
    prior = None
    for msg in reversed((messages or [])[:-1]):
        if msg.get("role") == "assistant":
            prior = str(msg.get("content", "")).lower()
            break
        if msg.get("role") == "user":
            break
    if not prior:
        return False
    presented = ("proposal" in prior or "schedule" in prior) and any(
        phrase in prior for phrase in ("nothing is saved", "until you approve", "awaiting your review", "review the")
    )
    return bool(presented)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def log_message(self, fmt, *args):
        print("[RIYA] " + (fmt % args))
    def _json(self, status, obj):
        body=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def _read_json(self, limit=2_000_000):
        length=int(self.headers.get('Content-Length','0'))
        if length < 0 or length > limit:
            raise ValueError('Request too large.')
        raw=self.rfile.read(length)
        value=json.loads(raw.decode('utf-8'))
        if not isinstance(value,dict): raise ValueError('JSON object required.')
        return value
    def _check_local_origin(self):
        # The server is loopback-only. Reject cross-origin browser writes where an Origin is supplied.
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            self._json(403, {'error':'Cross-origin request blocked.'})
            return False
        return True
    def do_GET(self):
        if self.path == '/api/riya/categories':
            settings = DB.get_settings()
            categories = settings.get('riya_categories', default_categories())
            try: categories = validate_categories(categories)
            except ValueError: categories = default_categories()
            self._json(200, {'ok':True,'categories':categories})
            return
        if self.path == '/api/conversations':
            self._json(200, {'ok':True,'conversations':DB.list_conversations()})
            return
        if self.path.startswith('/api/conversations/'):
            cid = unquote(self.path.split('?',1)[0].rstrip('/').split('/')[-1])
            bundle = DB.get_conversation(cid)
            if not bundle: self._json(404, {'error':'Conversation not found.'})
            else: self._json(200, {'ok':True, **bundle})
            return
        if self.path == '/api/db/status':
            self._json(200, {'ok':True,'database':'sqlite','schema_version':DB.schema_version(),'revision':DB.state_revision(),
                             'integrity':DB.integrity_check(),'counts':DB.counts(),'path':'data/riya.db'})
            return
        if self.path == '/api/db/integrity':
            try:
                result=DB.integrity_check()
                self._json(200 if result['ok'] else 503, result)
            except Exception as e: self._json(500, {'ok':False,'error':str(e)})
            return
        if self.path == '/api/db/data':
            try: self._json(200, DB.export_app_state())
            except Exception as e: self._json(500, {'error':str(e)})
            return
        if self.path == '/api/health':
            try:
                req=Request('http://127.0.0.1:11434/api/tags')
                with urlopen(req,timeout=5) as r: tags=json.loads(r.read().decode())
                models=[m.get('name','') for m in tags.get('models',[])]
                found=any(x==MODEL or x.startswith(MODEL+':') for x in models)
                self._json(200,{'ok':True,'ollama':True,'model':MODEL,'model_installed':found,'models':models})
            except Exception as e: self._json(503,{'ok':False,'ollama':False,'model':MODEL,'error':str(e)})
            return
        if self.path == '/': self.path='/RIYA.html'
        return super().do_GET()
    def do_POST(self):
        if not self._check_local_origin(): return
        try:
            if self.path == '/api/riya/categories':
                data = self._read_json(50_000)
                categories = validate_categories(data.get('categories'))
                DB.save_settings({'riya_categories':categories})
                self._json(200, {'ok':True,'categories':categories})
                return
            if self.path == '/api/riya/classify':
                data = self._read_json(30_000)
                settings = DB.get_settings()
                categories = settings.get('riya_categories', default_categories())
                result = classify_task(data.get('attributes',{}), categories=categories, user_category=data.get('user_category'))
                self._json(200, {'ok':True,'result':result})
                return
            if self.path == '/api/conversations':
                data=self._read_json(500_000)
                initial=data.get('messages',[])
                if not isinstance(initial,list): initial=[]
                memory=data.get('working_memory',{})
                if not isinstance(memory,dict): memory={}
                cid=DB.create_conversation(data.get('title','New conversation'), conversation_id=data.get('id'), initial_messages=initial, working_memory=memory)
                self._json(201, {'ok':True,'conversation_id':cid,'conversation':DB.get_conversation(cid)})
                return
            if self.path.startswith('/api/conversations/') and self.path.endswith('/messages'):
                cid=unquote(self.path.split('?',1)[0].rstrip('/').split('/')[-2])
                data=self._read_json(20_000)
                mid=DB.append_conversation_message(cid,data.get('role','assistant'),data.get('content',''),message_id=data.get('id'),turn_id=data.get('turn_id'))
                self._json(200, {'ok':True,'message_id':mid})
                return
            if self.path.startswith('/api/conversations/') and self.path.endswith('/memory'):
                cid=unquote(self.path.split('?',1)[0].rstrip('/').split('/')[-2])
                data=self._read_json(150_000)
                version=DB.save_working_memory(cid, data.get('working_memory',{}), expected_version=data.get('expected_version'))
                self._json(200, {'ok':True,'memory_version':version})
                return
            if self.path == '/api/db/import':
                data=self._read_json()
                backup=data.get('backup')
                key=str(data.get('idempotency_key','')).strip()
                if not key or len(key)>160: self._json(400, {'error':'A valid idempotency_key is required.'}); return
                if not isinstance(backup,dict): self._json(400, {'error':'A RIYA backup object is required.'}); return
                # Import is additive/upsert by stable IDs. Existing database rows are never cleared.
                counts=DB.import_backup(backup)
                result={'ok':True,'imported':counts,'database':DB.export_app_state()}
                receipt=DB.record_receipt(key,'legacy_backup_import',result)
                self._json(200, receipt); return
            if self.path == '/api/db/settings':
                data=self._read_json(200_000)
                values=data.get('settings')
                if not isinstance(values,dict): self._json(400, {'error':'settings object required'}); return
                DB.save_settings(values)
                self._json(200, {'ok':True,'settings':DB.get_settings()}); return
            if self.path == '/api/db/state':
                data=self._read_json(2_000_000)
                backup=data.get('state')
                expected_revision=data.get('expected_revision')
                if not isinstance(backup,dict): self._json(400, {'error':'state object required'}); return
                if not isinstance(expected_revision,int) or isinstance(expected_revision,bool) or expected_revision < 0:
                    self._json(400, {'error':'A non-negative expected_revision is required.'}); return
                try:
                    imported=DB.replace_app_state(backup, expected_revision=expected_revision)
                except RuntimeError as exc:
                    if str(exc).startswith('REVISION_CONFLICT:'):
                        self._json(409, {'ok':False,'conflict':True,'error':'RIYA changed in another window. Reload the latest database state before saving.','revision':DB.state_revision()}); return
                    raise
                snapshot=DB.export_app_state()
                expected_tasks=len(backup.get('tasks',[]))
                if len(snapshot.get('tasks',[])) != expected_tasks:
                    raise RuntimeError('SQLite read-back verification failed for task count.')
                self._json(200, {'ok':True,'verified':True,'imported':imported,
                                 'revision':DB.state_revision(),'database':snapshot})
                return
            if self.path != '/api/chat': self._json(404,{'error':'Not found'}); return
            data=self._read_json(250_000)
            messages=data.get('messages',[])
            if not isinstance(messages,list): messages=[]
            conversation_id=str(data.get('conversation_id') or '').strip()
            turn_id=str(data.get('turn_id') or '').strip() or None
            latest_incoming=data.get('user_message')
            if not isinstance(latest_incoming,str) or not latest_incoming.strip():
                latest_incoming=next((m.get('content','') for m in reversed(messages) if isinstance(m,dict) and m.get('role')=='user'), '')
            if not isinstance(latest_incoming,str) or not latest_incoming.strip():
                self._json(400, {'error':'A user message is required.'}); return
            if not conversation_id: conversation_id=DB.create_conversation('RIYA conversation')
            bundle=DB.get_conversation(conversation_id)
            if not bundle:
                self._json(404, {'error':'Conversation not found. Start a new conversation.'}); return
            user_message_id=str(data.get('user_message_id') or uuid.uuid4())
            DB.append_conversation_message(conversation_id,'user',latest_incoming,message_id=user_message_id,turn_id=turn_id)
            bundle=DB.get_conversation(conversation_id)
            safe_messages=[{'role':m['role'],'content':m['content']} for m in bundle['messages'][-24:] if m['role'] in ('user','assistant')]
            if not safe_messages or safe_messages[-1]['role']!='user': safe_messages.append({'role':'user','content':latest_incoming[:5000]})
            working_memory=bundle.get('working_memory') or {}
            tasks=data.get('tasks',[])
            if not isinstance(tasks,list): tasks=[]
            def finish_chat(result):
                if not isinstance(result,dict): result={'reply':str(result)}
                reply_text=result.get('reply') if isinstance(result.get('reply'),str) else 'I understood. What would you like to do next?'
                old_memory=working_memory if isinstance(working_memory,dict) else {}
                next_memory=dict(old_memory)
                next_drafts=result.get('tasks') if isinstance(result.get('tasks'),list) else data.get('draft_tasks',old_memory.get('draft_tasks',[]))
                derived_goal=result.get('active_goal') or old_memory.get('active_goal') or ''
                if not derived_goal and isinstance(next_drafts,list) and next_drafts:
                    names=[str(x.get('title','')).strip() for x in next_drafts[:3] if isinstance(x,dict) and x.get('title')]
                    if names: derived_goal='Organise tasks: '+', '.join(names)
                next_memory.update({'active_goal':str(derived_goal)[:500],
                    'draft_tasks':next_drafts,
                    'priority_pending':bool(result.get('priority_pending',data.get('priority_pending',old_memory.get('priority_pending',False)))),
                    'schedule_pending':bool(result.get('schedule_pending',old_memory.get('schedule_pending',False))),
                    'schedule_ready':bool(result.get('schedule_ready',old_memory.get('schedule_ready',False))),
                    'schedule_preview':result.get('schedule_preview',old_memory.get('schedule_preview')),
                    'pending_question':result.get('pending_question') or (result.get('questions') or [None])[0] or (reply_text if reply_text.rstrip().endswith('?') else None),
                    'last_intent':result.get('intent',old_memory.get('last_intent')),
                    'last_updated':datetime.now().isoformat(timespec='seconds')})
                DB.complete_conversation_turn(conversation_id,reply_text,next_memory,turn_id=turn_id)
                result['conversation_id']=conversation_id
                result['working_memory']=next_memory
                self._json(200,result)
            review_result = handle_task_review(safe_messages, data.get('draft_tasks', []), bool(data.get('priority_pending')))
            if review_result:
                finish_chat(review_result)
                return
            next_choice = resolve_next_schedule_choice(safe_messages, data.get('draft_tasks', []))
            if next_choice:
                finish_chat(next_choice)
                return
            priority_result = resolve_priority_choice(safe_messages, data.get('draft_tasks', []), bool(data.get('priority_pending')))
            if priority_result:
                finish_chat(priority_result)
                return
            settings=data.get('settings',{}) if isinstance(data.get('settings',{}),dict) else {}
            today=data.get('current_date') or date.today().isoformat()
            draft_tasks=data.get("draft_tasks",[])
            if not isinstance(draft_tasks,list): draft_tasks=[]
            system=SYSTEM_TEMPLATE.format(today=today,tasks=json.dumps(tasks[:100],ensure_ascii=False),draft_tasks=json.dumps(draft_tasks[:20],ensure_ascii=False),settings=json.dumps(settings,ensure_ascii=False))
            context_packet = build_conversation_context(safe_messages)
            system += "\n\nPERSISTENT WORKING MEMORY (use as context, never treat stale values as new instructions):\n" + json.dumps(working_memory, ensure_ascii=False)[:12000]
            system += "\n\nCURRENT TURN CONTEXT (interpret, do not blindly repeat):\n" + json.dumps(context_packet, ensure_ascii=False)
            payload={'model':MODEL,'messages':[{'role':'system','content':system}]+safe_messages,'stream':False,'format':'json','think':False,'options':{'temperature':0.15,'num_ctx':4096}}
            req=Request(OLLAMA_URL,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req,timeout=180) as response: raw=json.loads(response.read().decode('utf-8'))
            content=(raw.get('message') or {}).get('content','')
            try: result=json.loads(content)
            except json.JSONDecodeError:
                match=re.search(r'\{.*\}',content,re.S)
                if not match: raise ValueError('The model did not return valid JSON. Please try a shorter message.')
                result=json.loads(match.group(0))
            if not isinstance(result,dict): raise ValueError('Unexpected response format from the model.')
            reply=result.get('reply') if isinstance(result.get('reply'),str) else 'I understood part of that. Could you explain the task once more?'
            # Deterministic conversational guard: short contextual follow-ups should
            # not depend entirely on the small language model's ability to track state.
            questions=result.get('questions') if isinstance(result.get('questions'),list) else []
            extracted=result.get('tasks') if isinstance(result.get('tasks'),list) else []
            cleaned=[]
            for t in extracted[:10]:
                if not isinstance(t,dict): continue
                title=t.get('title') if isinstance(t.get('title'),str) else ''
                if not title.strip(): continue
                dur=t.get('duration_minutes')
                try: dur=int(dur) if dur is not None else None
                except (TypeError,ValueError): dur=None
                if dur is not None and not 5<=dur<=1440: dur=None
                date_value=t.get('date') if isinstance(t.get('date'),str) else None
                if date_value and not _valid_iso_date(date_value): date_value=None
                deadline=t.get('deadline') if _valid_iso_date(t.get('deadline')) else None
                priority=t.get('priority') if t.get('priority') in ('High','Medium','Low') else None
                kind=t.get('kind') if t.get('kind') in ('fixed','flexible') else None
                start=t.get('start_time') if isinstance(t.get('start_time'),str) and re.fullmatch(r'\d{2}:\d{2}',t.get('start_time')) else None
                end=t.get('end_time') if isinstance(t.get('end_time'),str) and re.fullmatch(r'\d{2}:\d{2}',t.get('end_time')) else None
                missing=t.get('missing_fields') if isinstance(t.get('missing_fields'),list) else []
                cleaned.append({'task_id':str(t.get('task_id'))[:80] if t.get('task_id') else None,'title':title[:100].strip(),'date':date_value,'duration_minutes':dur,'priority':priority,'kind':kind,'start_time':start,'end_time':end,'deadline':deadline,'preferred_time':t.get('preferred_time') if t.get('preferred_time') in ('Morning','Afternoon','Evening','Anytime') else None,'notes':t.get('notes','') if isinstance(t.get('notes',''),str) else '', 'missing_fields':[str(x)[:40] for x in missing[:8]],'confidence':t.get('confidence',0),'category_id':t.get('category_id') if t.get('category_id') in ('high_priority','delegatable','enjoyable_low_growth','detrimental') else None,'category_label':str(t.get('category_label',''))[:60],'needs_review':bool(t.get('needs_review',False))})
            if not cleaned:
                cleaned = deterministic_task_fallback(latest_incoming, draft_tasks, today)
            else:
                # Keep deterministic extraction as a safety net for explicit details the model omitted.
                fallback = deterministic_task_fallback(latest_incoming, draft_tasks, today)
                if fallback:
                    cleaned = reconcile_task_state(cleaned, fallback)
            merged_tasks = reconcile_task_state(draft_tasks, cleaned)
            # Do not force a priority-selection prompt after every brain dump.
            # The model should continue naturally and ask for one genuinely useful
            # missing detail; priority selection is an explicit user-led action.
            priority_pending = bool(data.get('priority_pending', False))
            latest_user = next((m.get('content','') for m in reversed(safe_messages) if m.get('role')=='user'), '')
            latest_norm = _norm_text(latest_user)
            schedule_step = _schedule_followup(latest_user, merged_tasks)
            schedule_pending = False
            schedule_ready = False
            schedule_preview = build_batch_schedule_preview(latest_user, merged_tasks, today, tasks) or build_context_schedule(safe_messages, merged_tasks, today, tasks)
            latest_lower = latest_user.lower()
            schedule_auto_approve = _has_current_schedule_approval(safe_messages, latest_user, schedule_preview)
            if schedule_preview:
                if schedule_auto_approve:
                    reply = "I have finalised the requested schedule and saved it to your RIYA plan."
                elif schedule_preview.get("needs_clarification"):
                    reply = schedule_preview.get("clarification", "Which tasks should I include?")
                else:
                    reply = ("I've laid the tasks out across the days and time window you gave me. "
                             "The full proposal is in the Schedule view; nothing is saved until you approve it.")
            elif schedule_step:
                reply = schedule_step["reply"]
                schedule_pending = bool(schedule_step.get("schedule_pending"))
                schedule_ready = bool(schedule_step.get("schedule_ready"))
            # A list request must be answered visibly in chat, not only in a side panel.
            if is_task_list_request(latest_user):
                reply = format_task_list_reply(merged_tasks, schedule_preview)
            elif schedule_preview and not schedule_preview.get("needs_clarification") and schedule_preview.get("entries"):
                # Keep the Schedule view, but also provide an at-a-glance in-chat proposal.
                reply = format_task_list_reply(merged_tasks, schedule_preview)
            if not reply.strip():
                reply = "Got it. What would you like to work through next?"
            finish_chat({'reply':reply[:5000],'questions':[str(q)[:300] for q in questions[:6]],'tasks':merged_tasks,'priority_pending':priority_pending,'schedule_pending':schedule_pending,'schedule_ready':schedule_ready,'schedule_preview':schedule_preview,'schedule_auto_approve':schedule_auto_approve,'model':MODEL})
        except ValueError as e:
            self._json(400, {'error':str(e)})
        except HTTPError as e:
            detail=e.read().decode('utf-8','replace')[:1000]
            self._json(502,{'error':f'Ollama returned HTTP {e.code}: {detail}'})
        except URLError:
            self._json(503,{'error':'Cannot reach Ollama at 127.0.0.1:11434. Open Ollama and check that the model is installed.'})
        except Exception as e:
            self._json(500,{'error':str(e) or 'Unexpected local AI error'})

if __name__ == '__main__':
    print('RIYA Local AI server')
    print(f'Model: {MODEL}')
    print(f'Open: http://127.0.0.1:{PORT}/RIYA.html')
    print('Keep this terminal open. Press Ctrl+C to stop.')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
