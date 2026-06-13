from typing import Any

from handoff import decide_handoff
from intent_classifier import classify_intent
from lead_scoring import score_lead
from lead_state import update_lead_state


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def run_agent_cycle(
    *,
    business: dict | None = None,
    business_id: str = "",
    platform: str = "",
    channel: str = "",
    customer_id: str = "",
    customer_name: str = "",
    message_text: str = "",
    message_id: str = "",
    media_type: str = "",
    media_match: dict | None = None,
    recent_messages: list | None = None,
    existing_lead_state: dict | None = None,
) -> dict:
    intent = classify_intent(
        message_text,
        platform=platform,
        channel=channel,
        media_type=media_type,
        media_match=media_match,
    )
    qualification = score_lead(
        current_state=existing_lead_state,
        intent_result=intent,
        message_text=message_text,
        media_type=media_type,
        media_match=media_match,
        recent_messages=recent_messages or [],
    )
    handoff = decide_handoff(
        intent_result=intent,
        qualification=qualification,
        business=business or {},
        user_text=message_text,
        ai_confidence=float(intent.get("confidence") or 0),
        media_match=media_match,
        platform=platform,
        channel=channel,
    )
    if handoff.get("handoff_required"):
        qualification["stage"] = "handoff_required"
        qualification["stage_label"] = "Needs Human Attention"
        qualification["score"] = max(int(qualification.get("score") or 0), 70)

    lead_state = update_lead_state(
        existing_state=existing_lead_state,
        business_id=business_id or (business or {}).get("id", ""),
        platform=platform,
        channel=channel,
        customer_id=customer_id,
        customer_name_hint=customer_name,
        message_text=message_text,
        message_id=message_id,
        intent_result=intent,
        qualification=qualification,
        handoff=handoff,
        media_match=media_match,
    )

    actions = [
        {
            "type": "update_crm",
            "stage": lead_state.get("stage"),
            "score": lead_state.get("score"),
        }
    ]
    if should_use_product_matcher(intent, media_type):
        actions.append({"type": "use_product_matcher"})
    if handoff.get("handoff_required"):
        actions.append(
            {
                "type": "handoff_to_human",
                "reason": handoff.get("reason"),
                "priority": handoff.get("priority"),
            }
        )
    else:
        actions.append({"type": "reply_to_customer"})

    return {
        "cycle": "perceive_reason_act",
        "perception": {
            "platform": normalize_text(platform).lower(),
            "channel": normalize_text(channel).lower(),
            "has_media": bool(media_type),
            "media_type": normalize_text(media_type).lower(),
            "message_id": normalize_text(message_id),
        },
        "intent": intent,
        "qualification": qualification,
        "handoff": handoff,
        "lead_state": lead_state,
        "actions": actions,
        "next_best_action": "handoff_to_human" if handoff.get("handoff_required") else "reply_to_customer",
        "ai_should_reply": True,
        "confidence": min(float(intent.get("confidence") or 0.0), 0.98),
        "reply_context": build_agent_reply_context(intent, qualification, handoff, lead_state),
    }


def should_use_product_matcher(intent: dict, media_type: str = "") -> bool:
    entities = dict(intent.get("entities") or {})
    if entities.get("has_media"):
        return True
    return normalize_text(media_type).lower() in {"photo", "image", "video", "file"}


def build_agent_reply_context(intent: dict, qualification: dict, handoff: dict, lead_state: dict) -> str:
    lines = [
        "Autonomous sales-agent decision context:",
        f"- Detected intent: {intent.get('primary_intent', 'general')} (confidence {intent.get('confidence', 0)}).",
        f"- Lead stage: {qualification.get('stage', 'new')}; score: {qualification.get('score', 0)}.",
    ]
    if qualification.get("reasons"):
        lines.append(f"- Lead score reasons: {', '.join(qualification.get('reasons', [])[:4])}.")
    if lead_state.get("phone_collected"):
        lines.append("- Customer phone is already collected; do not ask for it again.")
    if lead_state.get("name_collected"):
        lines.append("- Customer name is already collected; do not ask for it again.")
    if handoff.get("handoff_required"):
        lines.extend(
            [
                f"- Human handoff required: {handoff.get('reason', 'review needed')}.",
                "- Reply briefly that a manager will check, then stop deeper negotiation.",
            ]
        )
    else:
        lines.append("- AI may handle this message if it can answer from business facts.")
    return "\n".join(lines)
