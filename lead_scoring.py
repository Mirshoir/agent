from datetime import datetime
from typing import Any


LEAD_STAGES = [
    "new",
    "engaged",
    "interested",
    "qualified",
    "hot",
    "handoff_required",
    "won",
    "lost",
]

STAGE_LABELS = {
    "new": "New",
    "engaged": "Engaged",
    "interested": "Interested",
    "qualified": "Qualified",
    "hot": "Hot Lead",
    "handoff_required": "Needs Human Attention",
    "won": "Won",
    "lost": "Lost",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _normalized_stage(value: str) -> str:
    stage = str(value or "").strip().lower()
    legacy = {
        "negotiation": "hot",
        "needs_human": "handoff_required",
        "handoff": "handoff_required",
    }
    stage = legacy.get(stage, stage)
    return stage if stage in LEAD_STAGES else "new"


def _message_text(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("content") or row.get("text") or row.get("message_text") or "")
    return str(row or "")


def _direction(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("direction") or "").lower()
    return ""


def _media_type(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("media_type") or row.get("mediaType") or "").lower()
    return ""


def _is_customer_reply(row: Any) -> bool:
    direction = _direction(row)
    return not direction or direction == "inbound"


def score_lead(
    *,
    current_state: dict | None = None,
    intent_result: dict | None = None,
    message_text: str = "",
    media_type: str = "",
    media_match: dict | None = None,
    recent_messages: list | None = None,
) -> dict:
    state = dict(current_state or {})
    intent = dict(intent_result or {})
    signals = dict(intent.get("signals") or {})
    intents = set(intent.get("intents") or [])
    rows = list(recent_messages or [])

    if message_text or media_type:
        rows.append({"direction": "inbound", "content": message_text, "media_type": media_type})

    inbound_rows = [row for row in rows if _is_customer_reply(row)]
    combined_text = " ".join(_message_text(row).lower() for row in inbound_rows)
    media_seen = bool(media_type) or any(_media_type(row) in {"photo", "image", "video", "file"} for row in inbound_rows)
    media_verified = bool(media_match and (media_match.get("top_match_code") or media_match.get("top_product_code")))

    score = 0
    reasons: list[str] = []

    reply_count = min(len([row for row in inbound_rows if _message_text(row).strip()]), 3)
    if reply_count:
        score += reply_count * 10
        reasons.append(f"+{reply_count * 10} customer replies")

    if signals.get("price_question") or "price_question" in intents:
        score += 15
        reasons.append("+15 asks price")
    if signals.get("size_color_question") or "size_color_question" in intents:
        score += 15
        reasons.append("+15 asks size/color")
    if media_seen:
        score += 20
        reasons.append("+20 sends product media")
    if signals.get("phone_provided") or state.get("phone_collected") or state.get("phone"):
        score += 30
        reasons.append("+30 gives phone number")
    if signals.get("order_intent") or "order_intent" in intents:
        score += 40
        reasons.append("+40 ready to order")
    if signals.get("wholesale_intent") or "wholesale_intent" in intents:
        score += 50
        reasons.append("+50 wholesale/bulk intent")
    if signals.get("delivery_question") or "delivery_question" in intents:
        score += 10
        reasons.append("+10 asks delivery")
    if signals.get("catalog_request") or "catalog_request" in intents:
        score += 10
        reasons.append("+10 asks catalog")
    if media_verified:
        score += 10
        reasons.append("+10 product match verified")

    score = max(_safe_int(state.get("score")), min(100, score))

    previous_stage = _normalized_stage(state.get("stage"))
    stage = "new"
    if signals.get("lost_signal") or "lost_signal" in intents:
        stage = "lost"
    elif signals.get("won_signal") or "won_signal" in intents or previous_stage == "won":
        stage = "won"
    elif signals.get("human_request") or signals.get("complaint") or signals.get("payment_question"):
        stage = "handoff_required"
    elif score >= 80 or signals.get("order_intent") or signals.get("wholesale_intent"):
        stage = "hot"
    elif score >= 55 or state.get("phone_collected") or state.get("phone"):
        stage = "qualified"
    elif score >= 30 or signals.get("price_question") or signals.get("size_color_question") or media_seen:
        stage = "interested"
    elif reply_count:
        stage = "engaged"

    if previous_stage in {"qualified", "hot", "handoff_required", "won"} and stage not in {"lost", "won", "handoff_required"}:
        stage_rank = {name: index for index, name in enumerate(LEAD_STAGES)}
        stage = previous_stage if stage_rank.get(previous_stage, 0) > stage_rank.get(stage, 0) else stage

    if stage == "handoff_required":
        score = max(score, 70)
    if stage == "hot":
        score = max(score, 80)

    return {
        "score": min(100, score),
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage.title()),
        "reasons": reasons[:8],
        "signals": {
            "reply_count": reply_count,
            "asks_price": bool(signals.get("price_question")),
            "asks_size_color": bool(signals.get("size_color_question")),
            "sent_product_media": bool(media_seen),
            "phone_provided": bool(signals.get("phone_provided") or state.get("phone")),
            "order_intent": bool(signals.get("order_intent")),
            "wholesale_intent": bool(signals.get("wholesale_intent")),
            "delivery_question": bool(signals.get("delivery_question")),
            "catalog_request": bool(signals.get("catalog_request")),
            "media_verified": bool(media_verified),
        },
        "summary": build_lead_summary(stage, score, reasons),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def build_lead_summary(stage: str, score: int, reasons: list[str] | None = None) -> str:
    label = STAGE_LABELS.get(stage, stage.title())
    clean_reasons = [str(item).lstrip("+").strip() for item in (reasons or []) if str(item).strip()]
    if clean_reasons:
        return f"{label}. Score {score}. Signals: {', '.join(clean_reasons[:3])}."
    return f"{label}. Score {score}."
