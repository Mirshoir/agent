from datetime import datetime
from typing import Any, Callable


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def build_ai_action(
    *,
    business_id: str = "",
    customer_id: str = "",
    platform: str = "",
    channel: str = "",
    action_type: str = "",
    input_message: str = "",
    ai_decision: dict | None = None,
    confidence: float | None = None,
    tool_used: str = "",
    reply_sent: str = "",
    handoff_required: bool = False,
    manager_corrected: bool = False,
) -> dict:
    decision = dict(ai_decision or {})
    return {
        "business_id": normalize_text(business_id),
        "customer_id": normalize_text(customer_id),
        "platform": normalize_text(platform).lower(),
        "channel": normalize_text(channel).lower(),
        "action_type": normalize_text(action_type) or "agent_decision",
        "input_message": normalize_text(input_message)[:4000],
        "ai_decision": decision,
        "confidence": float(confidence if confidence is not None else decision.get("confidence") or 0),
        "tool_used": normalize_text(tool_used),
        "reply_sent": normalize_text(reply_sent)[:4000],
        "handoff_required": bool(handoff_required or (decision.get("handoff") or {}).get("handoff_required")),
        "manager_corrected": bool(manager_corrected),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def save_ai_action(
    supabase_client: Any,
    action: dict,
    *,
    fallback_writer: Callable[[dict], None] | None = None,
) -> dict:
    try:
        supabase_client.table("ai_actions").insert(action).execute()
        return {"saved": True, "target": "ai_actions"}
    except Exception as exc:
        if fallback_writer:
            fallback_writer(action)
            return {"saved": True, "target": "workspace_state", "warning": str(exc)}
        return {"saved": False, "target": "ai_actions", "error": str(exc)}
