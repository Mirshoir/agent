import re
from typing import Any


def normalize_text(value: Any) -> str:
    text = str(value or "").replace("‘", "'").replace("’", "'").replace("ʼ", "'").replace("ʻ", "'")
    return re.sub(r"\s+", " ", text).strip()


def _detect_language(text: str) -> str:
    lower = normalize_text(text).lower()
    if re.search(r"[а-яё]", lower):
        return "ru"
    if any(word in lower for word in ["price", "delivery", "order", "manager", "hello"]):
        return "en"
    return "uz"


def handoff_customer_reply(user_text: str = "", reason: str = "", business: dict | None = None) -> str:
    lang = _detect_language(user_text)
    contact = normalize_text((business or {}).get("sales_phone") or (business or {}).get("telegram_admin"))
    if lang == "en":
        base = "A manager should review this, so I will pass it to the team now."
        return f"{base} Contact: {contact}" if contact else base
    if lang == "ru":
        base = "Это лучше проверит менеджер, я передам обращение команде."
        return f"{base} Контакт: {contact}" if contact else base
    return "Bu savolni menejer tekshirgani yaxshi. Hozir jamoaga yuboraman."


def decide_handoff(
    *,
    intent_result: dict | None = None,
    qualification: dict | None = None,
    business: dict | None = None,
    user_text: str = "",
    ai_confidence: float | None = None,
    media_match: dict | None = None,
    platform: str = "",
    channel: str = "",
) -> dict:
    intent = dict(intent_result or {})
    signals = dict(intent.get("signals") or {})
    intents = set(intent.get("intents") or [])
    qualification = dict(qualification or {})
    lowered = normalize_text(user_text).lower()

    reasons: list[str] = []
    priority = "normal"

    if signals.get("complaint") or "complaint" in intents:
        reasons.append("customer_angry_or_complaint")
        priority = "urgent"
    if signals.get("human_request") or "human_request" in intents:
        reasons.append("customer_asked_for_human")
        priority = "high"
    if signals.get("payment_question") or "payment_question" in intents:
        reasons.append("payment_or_contract_issue")
        priority = "high"
    if signals.get("wholesale_intent") or "wholesale_intent" in intents:
        reasons.append("wholesale_negotiation")
        priority = "high"
    if qualification.get("stage") == "hot" and qualification.get("score", 0) >= 90:
        reasons.append("expensive_or_high_value_order")
        priority = "high"
    if signals.get("order_intent") and (signals.get("phone_provided") or qualification.get("score", 0) >= 85):
        reasons.append("ready_to_buy_now")
        priority = "high"
    low_confidence_can_handoff = (
        ai_confidence is not None
        and ai_confidence < 0.45
        and intent.get("primary_intent") not in {"greeting", "general"}
        and not signals.get("greeting")
        and len(lowered) > 20
    )
    if low_confidence_can_handoff:
        reasons.append("bot_confidence_low")
        priority = "normal"

    if re.search(r"\b(?:card|karta|карта|hisob|schet|счет|contract|shartnoma|договор|tolov|to'lov|oplata|оплата)\b", lowered):
        if "payment_or_contract_issue" not in reasons:
            reasons.append("payment_or_contract_issue")
        priority = "high"

    if qualification.get("stage") == "handoff_required":
        if not reasons:
            reasons.append("handoff_stage")
        priority = "high" if priority == "normal" else priority

    handoff_required = bool(reasons)
    reason = reasons[0] if reasons else ""
    return {
        "handoff_required": handoff_required,
        "reason": reason,
        "reasons": reasons,
        "priority": priority if handoff_required else "none",
        "customer_reply": handoff_customer_reply(user_text, reason, business) if handoff_required else "",
        "manager_note": build_manager_note(reason, qualification, intent),
    }


def build_manager_note(reason: str, qualification: dict, intent: dict) -> str:
    if not reason:
        return ""
    score = qualification.get("score", 0)
    stage = qualification.get("stage_label") or qualification.get("stage") or "lead"
    primary = intent.get("primary_intent") or "message"
    return f"{stage}: {reason.replace('_', ' ')}. Lead score {score}. Intent: {primary}."
