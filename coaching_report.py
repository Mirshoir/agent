from collections import Counter
from datetime import datetime, timedelta
from typing import Any


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_dt(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def build_daily_coaching_report(
    *,
    business: dict | None = None,
    lead_states: list[dict] | None = None,
    ai_actions: list[dict] | None = None,
    messages: list[dict] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.utcnow()
    leads = [item for item in (lead_states or []) if isinstance(item, dict)]
    actions = [item for item in (ai_actions or []) if isinstance(item, dict)]
    rows = [item for item in (messages or []) if isinstance(item, dict)]

    hot_leads = [lead for lead in leads if lead.get("stage") in {"hot", "handoff_required"}]
    missing_price = [
        row for row in rows
        if any(word in normalize_text(row.get("content")).lower() for word in ["narx", "price", "qancha", "цена", "сколько"])
        and not any(char.isdigit() for char in normalize_text(row.get("content")))
    ]
    waited_hot = []
    for lead in hot_leads:
        updated = _parse_dt(lead.get("updated_at") or lead.get("last_message_at"))
        if updated and now - updated > timedelta(minutes=20) and lead.get("stage") != "won":
            waited_hot.append(lead)

    low_conf = [action for action in actions if float(action.get("confidence") or 0) < 0.45]
    handoffs = [action for action in actions if action.get("handoff_required")]
    corrections = [action for action in actions if action.get("manager_corrected")]
    ignored = [
        lead for lead in leads
        if lead.get("stage") in {"engaged", "interested", "qualified"} and not lead.get("phone_collected")
    ]

    product_counter = Counter()
    for lead in leads:
        interest = normalize_text(lead.get("product_interest")).lower()
        if interest:
            product_counter[interest[:60]] += 1

    problems = []
    if missing_price:
        problems.append(f"{len(missing_price)} customers asked price but exact catalog price may be missing.")
    if waited_hot:
        problems.append(f"{len(waited_hot)} hot leads waited more than 20 minutes.")
    if low_conf:
        problems.append(f"{len(low_conf)} low-confidence AI decisions need review.")
    if corrections:
        problems.append(f"{len(corrections)} manager corrections were recorded.")
    if ignored:
        problems.append(f"{len(ignored)} interested leads still need phone/contact collection.")

    recommendations = []
    if missing_price:
        recommendations.append("Add or verify price data for the most requested products.")
    if waited_hot:
        recommendations.append("Manager should contact hot leads immediately.")
    if low_conf:
        recommendations.append("Review low-confidence replies and add missing FAQ/business rules.")
    if product_counter:
        top = ", ".join(item for item, _ in product_counter.most_common(3))
        recommendations.append(f"Prioritize catalog content for: {top}.")
    if not recommendations:
        recommendations.append("Keep monitoring hot leads and update catalog gaps daily.")

    return {
        "generated_at": now.isoformat() + "Z",
        "business_id": normalize_text((business or {}).get("id")),
        "business_name": normalize_text((business or {}).get("business_name")),
        "metrics": {
            "total_leads": len(leads),
            "hot_leads": len(hot_leads),
            "handoffs": len(handoffs),
            "low_confidence_actions": len(low_conf),
            "manager_corrections": len(corrections),
            "phone_numbers_collected": sum(1 for lead in leads if lead.get("phone_collected")),
        },
        "top_products": [{"name": item, "count": count} for item, count in product_counter.most_common(5)],
        "problems": problems or ["No major sales-agent issues found today."],
        "recommended_fixes": recommendations,
    }


def coaching_report_text(report: dict) -> str:
    problems = "\n".join(f"- {item}" for item in report.get("problems", []))
    fixes = "\n".join(f"- {item}" for item in report.get("recommended_fixes", []))
    return f"Today's problems:\n{problems}\n\nRecommended fixes:\n{fixes}"
