"""RIYA's editable four-pillar task classification foundation.

The classifier deliberately does not guess whether a person enjoys or dislikes
an activity. It uses user-confirmed attributes, and asks for review when those
attributes are missing. AI may suggest attributes later; user choices remain
higher priority than model suggestions.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "high_priority",
        "label": "High-priority",
        "description": "Things I enjoy doing and that contribute meaningfully to my growth across career, health, relationships, family, or other important areas.",
        "enjoyment": "enjoyable",
        "importance": "important",
        "growth_impact": "positive",
    },
    {
        "id": "delegatable",
        "label": "Delegatable",
        "description": "Important tasks I dislike doing and could hand to another person, employee, friend, or suitable AI assistant.",
        "enjoyment": "disliked",
        "importance": "important",
        "growth_impact": "any",
    },
    {
        "id": "enjoyable_low_growth",
        "label": "Enjoyable, low-growth",
        "description": "Activities I enjoy, but that do not contribute much to my longer-term growth.",
        "enjoyment": "enjoyable",
        "importance": "not_important",
        "growth_impact": "low_or_neutral",
    },
    {
        "id": "detrimental",
        "label": "Detrimental",
        "description": "Activities I dislike that negatively affect my growth, focus, wellbeing, or progress.",
        "enjoyment": "disliked",
        "importance": "any",
        "growth_impact": "negative",
    },
]
REQUIRED_IDS = tuple(x["id"] for x in DEFAULT_CATEGORIES)
VALID_ENJOYMENT = {"enjoyable", "disliked", "neutral", "unknown"}
VALID_IMPORTANCE = {"important", "not_important", "unknown"}
VALID_GROWTH = {"positive", "low_or_neutral", "negative", "unknown"}


def default_categories() -> list[dict[str, Any]]:
    return deepcopy(DEFAULT_CATEGORIES)


def validate_categories(value: Any) -> list[dict[str, Any]]:
    """Validate editable labels/descriptions while preserving the four pillars."""
    if not isinstance(value, list):
        raise ValueError("categories must be a list")
    by_id = {item.get("id"): item for item in value if isinstance(item, dict)}
    if set(by_id) != set(REQUIRED_IDS):
        raise ValueError("All four core categories must be present; their IDs cannot be changed.")
    clean = []
    for base in DEFAULT_CATEGORIES:
        item = by_id[base["id"]]
        label = item.get("label")
        description = item.get("description")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 60:
            raise ValueError(f"A valid label is required for {base['id']} (maximum 60 characters).")
        if not isinstance(description, str) or not description.strip() or len(description.strip()) > 500:
            raise ValueError(f"A valid description is required for {base['id']} (maximum 500 characters).")
        clean.append({**base, "label": label.strip(), "description": description.strip()})
    return clean


def classify_task(attributes: dict[str, Any], *, categories: list[dict[str, Any]] | None = None,
                  user_category: str | None = None) -> dict[str, Any]:
    """Classify from explicit/user-confirmed facts; never infer feelings from title."""
    categories = validate_categories(categories) if categories is not None else default_categories()
    category_map = {x["id"]: x for x in categories}
    if user_category:
        if user_category not in category_map:
            raise ValueError("user_category must match one of the four category IDs")
        chosen = category_map[user_category]
        return {"category_id": user_category, "category_label": chosen["label"],
                "confidence": 1.0, "needs_review": False, "source": "user_override",
                "reason": "Kept the category selected by the user."}

    if not isinstance(attributes, dict):
        raise ValueError("task attributes must be an object")
    enjoyment = attributes.get("enjoyment", "unknown")
    importance = attributes.get("importance", "unknown")
    growth = attributes.get("growth_impact", "unknown")
    delegatable = attributes.get("delegatable")
    if enjoyment not in VALID_ENJOYMENT:
        raise ValueError("enjoyment must be enjoyable, disliked, neutral, or unknown")
    if importance not in VALID_IMPORTANCE:
        raise ValueError("importance must be important, not_important, or unknown")
    if growth not in VALID_GROWTH:
        raise ValueError("growth_impact must be positive, low_or_neutral, negative, or unknown")
    if delegatable not in (None, True, False):
        raise ValueError("delegatable must be true, false, or null")

    chosen_id = None
    reason = ""
    # A disliked but important activity is the team's delegation principle.
    if enjoyment == "disliked" and importance == "important" and delegatable is not False:
        chosen_id = "delegatable"
        reason = "It is important, but you dislike doing it; consider delegating it."
    elif enjoyment == "enjoyable" and importance == "important" and growth == "positive":
        chosen_id = "high_priority"
        reason = "You enjoy it, it is important, and it contributes to your growth."
    elif enjoyment == "enjoyable" and importance == "not_important" and growth == "low_or_neutral":
        chosen_id = "enjoyable_low_growth"
        reason = "You enjoy it, but it has limited contribution to longer-term growth."
    elif enjoyment == "disliked" and growth == "negative":
        chosen_id = "detrimental"
        reason = "You dislike it and it negatively affects your growth or progress."

    if not chosen_id:
        missing = []
        if enjoyment in ("unknown", "neutral"):
            missing.append("whether you enjoy or dislike it")
        if importance == "unknown":
            missing.append("whether it is important")
        if growth == "unknown":
            missing.append("its impact on your growth")
        return {"category_id": None, "category_label": None, "confidence": 0.0,
                "needs_review": True, "source": "needs_user_input",
                "reason": "I need to understand " + (", ".join(missing) or "how this task fits your four categories") + "."}

    chosen = category_map[chosen_id]
    return {"category_id": chosen_id, "category_label": chosen["label"],
            "confidence": 0.9, "needs_review": False, "source": "rules_from_confirmed_facts",
            "reason": reason}
