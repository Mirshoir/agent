import re
from typing import Any


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def compact_lower(value: Any) -> str:
    return normalize_text(value).lower().replace("‘", "'").replace("’", "'").replace("ʼ", "'").replace("ʻ", "'")


def detect_language(text: str) -> str:
    lowered = compact_lower(text)
    if not lowered:
        return ""
    if re.search(r"[а-яёқўғҳіәіңұүқөһ]", lowered):
        if any(word in lowered for word in ["цена", "сколько", "заказ", "доставка", "оплата", "менеджер"]):
            return "ru"
        if any(word in lowered for word in ["сәлем", "баға", "жеткізу", "тапсырыс"]):
            return "kk"
        return "uz"
    uz_markers = {
        "salom", "assalomu", "narx", "qancha", "yetkaz", "buyurtma", "olaman",
        "katalog", "mahsulot", "menejer", "ismim", "telefon", "optom",
    }
    en_markers = {
        "hello", "price", "delivery", "shipping", "order", "buy", "catalog",
        "manager", "phone", "wholesale", "size", "color",
    }
    if any(word in lowered for word in uz_markers):
        return "uz"
    if any(word in lowered for word in en_markers):
        return "en"
    return ""


def find_phone_numbers(text: str) -> list[str]:
    source = normalize_text(text)
    phones: list[str] = []
    for pattern in (r"(?<!\d)(?:\+?\d[\d\s().-]{6,}\d)(?!\d)", r"(?<!\d)\d{7,15}(?!\d)"):
        for match in re.finditer(pattern, source):
            digits = re.sub(r"\D+", "", match.group(0))
            if digits.startswith("00"):
                digits = digits[2:]
            if digits.startswith("8") and len(digits) == 10:
                digits = f"998{digits[1:]}"
            if 7 <= len(digits) <= 15 and digits not in phones:
                phones.append(digits)
    return phones


INTENT_KEYWORDS = {
    "greeting": [
        "hi", "hello", "hey", "salom", "assalomu", "alaykum", "здравствуйте", "привет", "сәлем",
    ],
    "catalog_request": [
        "catalog", "katalog", "katalok", "каталог", "mahsulotlar", "products", "tovar", "товары", "modellari",
    ],
    "price_question": [
        "price", "prices", "how much", "cost", "narx", "narxi", "qancha", "qanchadan", "necha pul",
        "nechpul", "цена", "цены", "сколько", "стоимость", "баға",
    ],
    "size_color_question": [
        "size", "sizes", "color", "colour", "rang", "razmer", "razmeri", "olcham", "o'lcham",
        "размер", "цвет", "размеры", "ranglari",
    ],
    "delivery_question": [
        "delivery", "shipping", "ship", "yetkaz", "dostavka", "доставка", "доставк", "kargo", "cargo",
        "pochta", "почта", "manzil", "address",
    ],
    "payment_question": [
        "payment", "pay", "card", "click", "payme", "cash", "oplata", "оплата", "карта", "karta",
        "pul otkaz", "to'lov", "to'lovda", "tolov", "tolovda",
    ],
    "product_interest": [
        "bormi", "available", "mavjud", "model", "mahsulot", "product", "tovar", "товар", "есть",
        "xalat", "pijama", "kiyim", "dress", "sumka",
    ],
    "order_intent": [
        "order", "buy", "purchase", "i want", "ready", "olaman", "olmoqchiman", "buyurtma",
        "zakaz", "zakaz qil", "оформить", "заказ", "куплю", "беру", "сатып аламын",
    ],
    "wholesale_intent": [
        "wholesale", "bulk", "optom", "optum", "optoviy", "оптом", "оптов", "ko'p olsam", "kop olsam",
        "diler", "distributor", "party", "partiya",
    ],
    "human_request": [
        "manager", "operator", "human", "person", "admin", "menejer", "odam", "real", "менеджер",
        "оператор", "человек", "админ",
    ],
    "complaint": [
        "angry", "bad", "wrong", "complaint", "not happy", "yoqmadi", "yomon", "xato", "norozi",
        "жалоба", "плохо", "не доволен", "ошибка", "недоволен",
    ],
    "stop": [
        "stop", "bas", "kerak emas", "kerakmas", "unsubscribe", "yozma", "не пишите", "стоп", "хватит",
    ],
    "won_signal": [
        "received", "thank you", "thanks", "rahmat", "oldim", "keldi", "спасибо", "получил", "получила",
    ],
    "lost_signal": [
        "cancel", "not now", "later", "keyin", "keyinroq", "olmayman", "qimmat", "дорого", "отмена",
        "не надо", "не нужно",
    ],
}


WEIGHTS = {
    "greeting": 0.25,
    "catalog_request": 0.68,
    "price_question": 0.82,
    "size_color_question": 0.74,
    "delivery_question": 0.72,
    "payment_question": 0.76,
    "product_interest": 0.70,
    "order_intent": 0.90,
    "wholesale_intent": 0.92,
    "human_request": 0.86,
    "complaint": 0.88,
    "stop": 0.88,
    "won_signal": 0.82,
    "lost_signal": 0.76,
}


def _keyword_hit(text: str, phrase: str) -> bool:
    phrase = phrase.lower()
    if " " in phrase or "'" in phrase:
        return phrase in text
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def classify_intent(
    text: str,
    *,
    platform: str = "",
    channel: str = "",
    media_type: str = "",
    media_match: dict | None = None,
) -> dict:
    lowered = compact_lower(text)
    phones = find_phone_numbers(text)
    intents: list[str] = []
    signals: dict[str, bool] = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        hit = any(_keyword_hit(lowered, keyword) for keyword in keywords)
        signals[intent] = hit
        if hit:
            intents.append(intent)

    has_media = bool(normalize_text(media_type)) and normalize_text(media_type).lower() not in {"text", "unknown"}
    media_verified = bool(media_match and (media_match.get("top_match_code") or media_match.get("top_product_code")))
    if has_media:
        intents.append("product_photo")
        signals["product_photo"] = True
    else:
        signals["product_photo"] = False

    if phones:
        intents.append("phone_provided")
        signals["phone_provided"] = True
    else:
        signals["phone_provided"] = False

    if media_verified:
        intents.append("product_match_verified")
        signals["product_match_verified"] = True
    else:
        signals["product_match_verified"] = False

    # Buying intent can be terse in DMs: "1 ta", "2 qop", "10 pcs".
    if re.search(r"\b\d+\s*(ta|dona|pcs|piece|pieces|qop|mesh?ok|мешок|kg|кг)\b", lowered):
        if "order_intent" not in intents:
            intents.append("order_intent")
        signals["quantity_mentioned"] = True
    else:
        signals["quantity_mentioned"] = False

    priority = [
        "complaint", "human_request", "payment_question", "wholesale_intent", "order_intent",
        "phone_provided", "price_question", "size_color_question", "delivery_question",
        "product_photo", "catalog_request", "product_interest", "lost_signal", "won_signal", "greeting",
    ]
    primary = next((intent for intent in priority if intent in intents), "general")
    confidence = WEIGHTS.get(primary, 0.45)
    if len(intents) >= 2:
        confidence = min(0.96, confidence + 0.06)
    if not lowered and has_media:
        confidence = max(confidence, 0.70)
    if not lowered and not has_media:
        confidence = 0.20

    return {
        "primary_intent": primary,
        "intents": list(dict.fromkeys(intents)) or ["general"],
        "confidence": round(confidence, 2),
        "language": detect_language(text),
        "platform": normalize_text(platform).lower(),
        "channel": normalize_text(channel).lower(),
        "signals": signals,
        "entities": {
            "phones": phones,
            "has_media": has_media,
            "media_type": normalize_text(media_type).lower(),
            "media_verified": media_verified,
        },
    }
