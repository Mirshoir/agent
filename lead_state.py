import re
from datetime import datetime
from typing import Any


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", normalize_text(value))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("8") and len(digits) == 10:
        digits = f"998{digits[1:]}"
    if digits.startswith("998") and len(digits) >= 12:
        return digits[:12]
    return digits


def extract_phone_candidates(text: str) -> list[str]:
    source = normalize_text(text)
    phones: list[str] = []
    for pattern in (r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)", r"(?<!\d)\d{7,15}(?!\d)"):
        for match in re.finditer(pattern, source):
            phone = normalize_phone(match.group(0))
            if 7 <= len(phone) <= 15 and phone not in phones:
                phones.append(phone)
    return phones


def _looks_like_name(value: str) -> bool:
    text = normalize_text(value)
    if not text or len(text) > 70 or re.search(r"\d", text):
        return False
    tokens = [item for item in re.split(r"\s+", text) if item]
    if not 1 <= len(tokens) <= 4:
        return False
    bad = {"salom", "hello", "price", "narx", "katalog", "catalog", "rahmat", "спасибо"}
    if text.lower() in bad:
        return False
    return all(re.fullmatch(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}", token) for token in tokens)


def extract_name_candidate(text: str, customer_name_hint: str = "") -> str:
    source = normalize_text(text)
    patterns = [
        r"(?:ismim|mening ismim|my name is|name is|меня зовут|mening ismim[:\-]?)\s+([A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}(?:\s+[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳʼ'`-]{2,}){0,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            candidate = normalize_text(match.group(1)).strip(" ,.!?:;")
            if _looks_like_name(candidate):
                return candidate
    hint = normalize_text(customer_name_hint)
    if _looks_like_name(hint) and not re.fullmatch(r"(instagram|telegram|whatsapp)?\s*(client|user)?\s*\d+", hint.lower()):
        return hint
    if _looks_like_name(source):
        return source
    return ""


def normalize_lead_state(state: dict | None = None) -> dict:
    source = dict(state or {})
    phone = normalize_phone(source.get("phone"))
    name = normalize_text(source.get("customer_name") or source.get("name"))
    score = max(0, min(100, int(float(source.get("score") or source.get("lead_score") or 0))))
    stage = normalize_text(source.get("stage") or "new").lower()
    if stage == "negotiation":
        stage = "hot"
    if stage == "handoff":
        stage = "handoff_required"
    if stage not in {"new", "engaged", "interested", "qualified", "hot", "handoff_required", "won", "lost"}:
        stage = "new"
    return {
        **source,
        "phone": phone,
        "customer_name": name,
        "phone_collected": bool(source.get("phone_collected") or phone),
        "name_collected": bool(source.get("name_collected") or name),
        "score": score,
        "lead_score": score,
        "stage": stage,
        "handoff_required": bool(source.get("handoff_required") or stage == "handoff_required"),
    }


def update_lead_state(
    *,
    existing_state: dict | None = None,
    business_id: str = "",
    platform: str = "",
    channel: str = "",
    customer_id: str = "",
    customer_name_hint: str = "",
    message_text: str = "",
    message_id: str = "",
    intent_result: dict | None = None,
    qualification: dict | None = None,
    handoff: dict | None = None,
    media_match: dict | None = None,
) -> dict:
    state = normalize_lead_state(existing_state)
    intent = dict(intent_result or {})
    qualification = dict(qualification or {})
    handoff = dict(handoff or {})
    now = datetime.utcnow().isoformat() + "Z"

    phones = extract_phone_candidates(message_text)
    if phones:
        state["phone"] = phones[0]
        state["phone_collected"] = True

    name = extract_name_candidate(message_text, customer_name_hint)
    if name:
        state["customer_name"] = name
        state["name_collected"] = True

    signals = dict(qualification.get("signals") or {})
    media_code = normalize_text(
        (media_match or {}).get("top_match_code")
        or (media_match or {}).get("top_product_code")
        or (media_match or {}).get("top_match_model")
    )
    if media_code:
        state["product_interest"] = media_code
    elif intent.get("primary_intent") in {"catalog_request", "price_question", "product_interest", "product_photo"}:
        state["product_interest"] = state.get("product_interest") or normalize_text(message_text)[:180]

    state.update(
        {
            "business_id": normalize_text(business_id),
            "platform": normalize_text(platform).lower(),
            "channel": normalize_text(channel).lower(),
            "customer_id": normalize_text(customer_id),
            "last_message_id": normalize_text(message_id),
            "last_message_text": normalize_text(message_text)[:500],
            "last_lead_update": now,
            "last_message_at": now,
            "primary_intent": intent.get("primary_intent", "general"),
            "intents": intent.get("intents", []),
            "intent_confidence": intent.get("confidence", 0),
            "language": intent.get("language", ""),
            "score": qualification.get("score", state.get("score", 0)),
            "lead_score": qualification.get("score", state.get("score", 0)),
            "stage": qualification.get("stage", state.get("stage", "new")),
            "stage_label": qualification.get("stage_label", ""),
            "score_reasons": qualification.get("reasons", []),
            "signals": signals,
            "qualification_summary": qualification.get("summary", ""),
            "handoff_required": bool(handoff.get("handoff_required")),
            "handoff_reason": handoff.get("reason", ""),
            "handoff_reasons": handoff.get("reasons", []),
            "handoff_priority": handoff.get("priority", "none"),
            "manager_note": handoff.get("manager_note", ""),
            "updated_at": now,
        }
    )
    return normalize_lead_state(state)
