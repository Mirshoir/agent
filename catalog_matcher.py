import base64
import hashlib
import io
import json
import os
import re
import time

import requests
from supabase import create_client


def normalize_text(value):
    return str(value or "").strip()


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled", "enable"}


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
CATALOG_SUPABASE_URL = (
    os.getenv("CATALOG_SUPABASE_URL")
    or os.getenv("PRODUCT_CATALOG_SUPABASE_URL")
    or os.getenv("PRODUCT_MATCHER_SUPABASE_URL")
    or os.getenv("MILANA_CATALOG_SUPABASE_URL")
    or SUPABASE_URL
)
CATALOG_SUPABASE_SERVICE_KEY = (
    os.getenv("CATALOG_SUPABASE_SERVICE_KEY")
    or os.getenv("PRODUCT_CATALOG_SUPABASE_SERVICE_KEY")
    or os.getenv("PRODUCT_MATCHER_SUPABASE_SERVICE_KEY")
    or os.getenv("MILANA_CATALOG_SUPABASE_SERVICE_KEY")
    or SUPABASE_SERVICE_KEY
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

PRODUCT_MATCHER_LOCAL_ENABLED = env_bool("PRODUCT_MATCHER_LOCAL_ENABLED", True)
PRODUCT_MATCHER_LOCAL_CATALOG_TABLE = normalize_text(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_TABLE", "milana_products")) or "milana_products"
PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS = max(30, min(60 * 60, int(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS", "300"))))
PRODUCT_MATCHER_LOCAL_FETCH_LIMIT = max(50, min(3000, int(os.getenv("PRODUCT_MATCHER_LOCAL_FETCH_LIMIT", "1200"))))
PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS = max(3, min(40, int(os.getenv("PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS", "24"))))
PRODUCT_MATCHER_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_MIN_SCORE", "0.20"))))
PRODUCT_MATCHER_WEAK_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_WEAK_MIN_SCORE", "0.10"))))
PRODUCT_MATCHER_OPENAI_VISION_MODEL = normalize_text(os.getenv("PRODUCT_MATCHER_OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))) or "gpt-4.1-mini"
PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS = max(8, min(120, int(os.getenv("PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS", "20"))))
PRODUCT_MATCHER_OPENAI_VISION_DETAIL = normalize_text(os.getenv("PRODUCT_MATCHER_OPENAI_VISION_DETAIL", "low")).lower() or "low"

_supabase = None
_catalog_cache = {"loaded_at": 0.0, "rows": []}


def log(title, data=None):
    print("\n" + "=" * 80)
    print(title)
    if data is not None:
        print(data)
    print("=" * 80 + "\n")


def _client():
    global _supabase
    if _supabase is None:
        if not CATALOG_SUPABASE_URL or not CATALOG_SUPABASE_SERVICE_KEY:
            raise RuntimeError("Missing catalog Supabase credentials")
        _supabase = create_client(CATALOG_SUPABASE_URL, CATALOG_SUPABASE_SERVICE_KEY)
    return _supabase


def _extract_output_text(body: dict) -> str:
    text = normalize_text(body.get("output_text"))
    if text:
        return text
    output = body.get("output") if isinstance(body.get("output"), list) else []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), list) else []
        for chunk in content:
            if isinstance(chunk, dict):
                value = normalize_text(chunk.get("text"))
                if value:
                    return value
    return ""


def _extract_json_object(text: str) -> dict:
    raw = normalize_text(text)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def normalize_product_code(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9-]", "", normalize_text(value).upper())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def extract_codes_from_text(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    found = []
    for raw in re.findall(r"\b[A-Za-z]{1,4}-?\d{2,6}\b", text):
        code = normalize_product_code(raw)
        if code and code not in found:
            found.append(code)
    return found


def _parse_float_list(value, limit: int = 12) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        text = normalize_text(value)
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = re.findall(r"-?\d+(?:\.\d+)?", text)
        except Exception:
            items = re.findall(r"-?\d+(?:\.\d+)?", text)
    result = []
    for item in items[:limit]:
        try:
            result.append(float(item))
        except Exception:
            continue
    return result


def _sha256(media_bytes: bytes) -> str:
    return hashlib.sha256(media_bytes).hexdigest() if media_bytes else ""


def _signatures_from_bytes(media_bytes: bytes) -> list[list[float]]:
    if not media_bytes:
        return []
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return []

    try:
        image = Image.open(io.BytesIO(media_bytes)).convert("RGB").resize((128, 128))
        arr = np.asarray(image, dtype=np.float32)
    except Exception:
        return []

    signatures = []
    try:
        rgb_hist = []
        total_pixels = float(arr.shape[0] * arr.shape[1] * 3) or 1.0
        for channel in range(3):
            hist, _ = np.histogram(arr[:, :, channel], bins=4, range=(0, 255))
            rgb_hist.extend((hist.astype(np.float32) / total_pixels).tolist())
        signatures.append([float(x) for x in rgb_hist])
    except Exception:
        pass
    try:
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        lum_hist, _ = np.histogram(lum, bins=12, range=(0, 255))
        total = float(lum_hist.sum()) or 1.0
        signatures.append((lum_hist.astype(np.float32) / total).tolist())
    except Exception:
        pass
    return [sig for sig in signatures if len(sig) >= 6]


def _vector_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    if size < 4:
        return 0.0
    l = [float(x) for x in left[:size]]
    r = [float(x) for x in right[:size]]
    dot = sum(a * b for a, b in zip(l, r))
    left_norm = sum(a * a for a in l) ** 0.5
    right_norm = sum(b * b for b in r) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def download_media_for_matcher(media_url: str, access_token: str = "") -> tuple[bytes, str, str]:
    media_url = normalize_text(media_url)
    if not media_url:
        raise ValueError("Empty media URL")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
    }
    clean_token = normalize_text(access_token)
    if clean_token:
        headers["Authorization"] = f"Bearer {clean_token}"

    response = requests.get(media_url, timeout=30, stream=True, headers=headers)
    response.raise_for_status()

    content_type = normalize_text(response.headers.get("content-type")).split(";")[0].strip() or "application/octet-stream"
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > 20 * 1024 * 1024:
            raise ValueError("Media is too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ValueError("Downloaded media is empty")
    filename = f"media{os.path.splitext(content_type)[-1] or '.bin'}"
    return data, filename, content_type


def _get_local_catalog_rows(force_refresh: bool = False) -> list[dict]:
    now = time.time()
    cached_rows = _catalog_cache.get("rows") if isinstance(_catalog_cache, dict) else []
    loaded_at = _catalog_cache.get("loaded_at", 0.0) if isinstance(_catalog_cache, dict) else 0.0
    if not force_refresh and cached_rows and (now - float(loaded_at or 0.0)) < PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS:
        return cached_rows

    fields = "product_code,model_code,price,currency,combined_text,image_url,image_sha256,image_fingerprint,embedding_model,embedding_preview,source_pdf,page,card_index"
    try:
        res = (
            _client()
            .table(PRODUCT_MATCHER_LOCAL_CATALOG_TABLE)
            .select(fields)
            .limit(PRODUCT_MATCHER_LOCAL_FETCH_LIMIT)
            .execute()
        )
        rows = res.data if isinstance(res.data, list) else []
    except Exception as exc:
        same_database = normalize_text(CATALOG_SUPABASE_URL).rstrip("/") == normalize_text(SUPABASE_URL).rstrip("/")
        log("Local catalog fetch failed", {
            "table": PRODUCT_MATCHER_LOCAL_CATALOG_TABLE,
            "catalog_supabase_url": normalize_text(CATALOG_SUPABASE_URL).split("//")[-1].split(".")[0] if CATALOG_SUPABASE_URL else "",
            "same_as_business_database": same_database,
            "fix": "Set CATALOG_SUPABASE_URL and CATALOG_SUPABASE_SERVICE_KEY in Render." if same_database else "",
            "error": str(exc),
        })
        return cached_rows or []

    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_code = normalize_product_code(row.get("product_code"))
        model_code = normalize_product_code(row.get("model_code"))
        combined_text = normalize_text(row.get("combined_text"))
        if not (product_code or model_code or combined_text):
            continue
        normalized_rows.append({
            "product_code": product_code,
            "model_code": model_code,
            "price": normalize_text(row.get("price")),
            "currency": normalize_text(row.get("currency")),
            "combined_text": combined_text,
            "image_url": normalize_text(row.get("image_url")),
            "image_sha256": normalize_text(row.get("image_sha256")).lower(),
            "image_fingerprint": normalize_text(row.get("image_fingerprint")),
            "embedding_model": normalize_text(row.get("embedding_model")).lower(),
            "embedding_preview": normalize_text(row.get("embedding_preview")),
            "source_pdf": normalize_text(row.get("source_pdf")),
            "page": row.get("page"),
            "card_index": row.get("card_index"),
        })

    _catalog_cache["rows"] = normalized_rows
    _catalog_cache["loaded_at"] = now
    return normalized_rows


def _extract_media_vision_hints_local(media_bytes: bytes, mime_type: str, user_text: str) -> dict:
    if not OPENAI_API_KEY:
        return {}
    clean_mime = normalize_text(mime_type).split(";")[0].lower()
    if not clean_mime.startswith("image/"):
        return {}

    b64 = base64.b64encode(media_bytes).decode("ascii")
    prompt = {
        "task": "Identify product codes/models, garment details, colors, patterns, and useful keywords from this product image.",
        "customer_message": normalize_text(user_text),
        "output_format": {
            "product_codes": ["code strings"],
            "model_codes": ["model strings"],
            "keywords": ["short style/product keywords"],
            "colors": ["dominant colors"],
            "garment_type": "short product type label",
            "detected_text": "short OCR-like text seen on image",
            "confidence": "0..1",
        },
    }

    payload = {
        "model": PRODUCT_MATCHER_OPENAI_VISION_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Return ONLY JSON. Do not add markdown. Focus on codes, model identifiers, and concise retrieval keywords.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)},
                    {
                        "type": "input_image",
                        "image_url": f"data:{clean_mime};base64,{b64}",
                        "detail": PRODUCT_MATCHER_OPENAI_VISION_DETAIL,
                    },
                ],
            },
        ],
        "temperature": 0.0,
    }

    try:
        res = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=PRODUCT_MATCHER_OPENAI_VISION_TIMEOUT_SECONDS,
        )
        if not res.ok:
            return {}
        body = res.json()
    except Exception as exc:
        log("Local vision request error", str(exc))
        return {}

    raw_text = _extract_output_text(body)
    parsed = _extract_json_object(raw_text)
    parsed_codes = []
    for key in ("product_codes", "model_codes"):
        values = parsed.get(key)
        if isinstance(values, list):
            parsed_codes.extend(values)
    if isinstance(parsed.get("detected_text"), str):
        parsed_codes.extend(extract_codes_from_text(parsed.get("detected_text")))

    codes = []
    for code in parsed_codes:
        normalized = normalize_product_code(code)
        if normalized and normalized not in codes:
            codes.append(normalized)

    keywords = []
    raw_keywords = parsed.get("keywords")
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            token = normalize_text(item).lower()
            if token and token not in keywords:
                keywords.append(token)

    detected_text = normalize_text(parsed.get("detected_text"))
    if detected_text:
        for token in re.findall(r"[A-Za-z0-9'-]{3,}", detected_text.lower()):
            if token not in keywords:
                keywords.append(token)

    return {
        "codes": codes[:24],
        "keywords": keywords[:PRODUCT_MATCHER_LOCAL_MAX_KEYWORDS],
        "colors": [normalize_text(x).lower() for x in (parsed.get("colors") if isinstance(parsed.get("colors"), list) else [])][:8],
        "garment_type": normalize_text(parsed.get("garment_type")).lower(),
        "detected_text": detected_text,
        "confidence": float(parsed.get("confidence") or 0.0) if str(parsed.get("confidence") or "").strip() else 0.0,
    }


def _row_image_similarity_score(row: dict, media_sha256: str, media_signatures: list[list[float]]) -> float:
    row_sha256 = normalize_text(row.get("image_sha256")).lower()
    if row_sha256 and media_sha256 and row_sha256 == media_sha256:
        return 1.0

    row_signature = _parse_float_list(row.get("embedding_preview"), limit=12)
    if not row_signature:
        return 0.0

    best = 0.0
    for media_signature in media_signatures or []:
        best = max(best, _vector_similarity(row_signature, media_signature))
    return best


def _score_local_catalog_row(row: dict, code_set: set, keyword_set: set, media_sha256: str = "", media_signatures: list[list[float]] = None, vision: dict = None) -> tuple[float, dict]:
    code = normalize_product_code(row.get("product_code"))
    model = normalize_product_code(row.get("model_code"))
    text_blob = " ".join([
        normalize_text(row.get("combined_text")).upper(),
        code,
        model,
        normalize_text(row.get("image_fingerprint")).upper(),
    ])

    code_score = 0.0
    if code and code in code_set:
        code_score = 1.0
    elif model and model in code_set:
        code_score = 0.92

    keyword_hits = 0
    if keyword_set:
        lower_blob = text_blob.lower()
        for kw in keyword_set:
            if kw and kw in lower_blob:
                keyword_hits += 1
    keyword_score = 0.0
    if keyword_set:
        keyword_score = min(1.0, keyword_hits / max(1, min(6, len(keyword_set))))

    text_score = 0.0
    if code and code in text_blob:
        text_score = 1.0
    elif model and model in text_blob:
        text_score = 0.9

    image_score = _row_image_similarity_score(row, media_sha256, media_signatures or [])
    if vision and isinstance(vision, dict):
        row_text = normalize_text(row.get("combined_text")).lower()
        row_type_blob = f"{code} {model} {row_text}".lower()
        for color in vision.get("colors", []) or []:
            token = normalize_text(color).lower()
            if token and token in row_type_blob:
                image_score = max(image_score, 0.55)
        garment_type = normalize_text(vision.get("garment_type")).lower()
        if garment_type and garment_type in row_type_blob:
            image_score = max(image_score, 0.60)

    final_score = (0.54 * code_score) + (0.18 * keyword_score) + (0.08 * text_score) + (0.20 * image_score)
    parts = {
        "final": round(final_score, 6),
        "code": round(code_score, 6),
        "keyword": round(keyword_score, 6),
        "text": round(text_score, 6),
        "image": round(image_score, 6),
    }
    return final_score, parts


def build_product_match_reply(code: str, model: str, price: str, currency: str, top_score: float) -> str:
    code = normalize_text(code)
    model = normalize_text(model)
    price = normalize_text(price)
    currency = normalize_text(currency)
    label = code or model
    if code and model and model != code:
        label = f"{code}, model {model}"
    confidence_note = " O'xshash model deb ko'rinyapti." if top_score < PRODUCT_MATCHER_MIN_SCORE else ""
    if price:
        return f"Topdim:{confidence_note} {label or 'shu model'} narxi {price} {currency or '$'}. Qaysi razmer va nechta qop kerak?"
    return f"Topdim:{confidence_note} {label or 'shu model'} bo'yicha aniq narxni menejerimiz tekshirib beradi. Qaysi razmer va nechta qop kerak?"


def analyze_media_for_sales_reply_local(media_url: str, user_text: str, media_type: str = "", access_token: str = "") -> dict:
    if not PRODUCT_MATCHER_LOCAL_ENABLED:
        return {}
    media_type = normalize_text(media_type).lower()
    if media_type and media_type not in {"photo", "file", "image"}:
        return {}
    if not media_url:
        return {}

    try:
        media_bytes, _, mime_type = download_media_for_matcher(media_url, access_token=access_token)
    except Exception as exc:
        log("Local matcher download failed", {"error": str(exc)})
        return {}

    vision = _extract_media_vision_hints_local(media_bytes, mime_type, user_text)
    media_sha256 = _sha256(media_bytes)
    media_signatures = _signatures_from_bytes(media_bytes)

    extracted_codes = extract_codes_from_text(user_text)
    for code in vision.get("codes", []):
        if code not in extracted_codes:
            extracted_codes.append(code)
    code_set = {normalize_product_code(code) for code in extracted_codes if code}

    keyword_set = {normalize_text(x).lower() for x in re.findall(r"[A-Za-z0-9'-]{3,}", normalize_text(user_text))}
    for token in vision.get("keywords", []):
        clean = normalize_text(token).lower()
        if clean:
            keyword_set.add(clean)

    rows = _get_local_catalog_rows()
    if not rows:
        return {}
    exact_image_match = any(
        normalize_text(row.get("image_sha256")).lower()
        and normalize_text(row.get("image_sha256")).lower() == media_sha256
        for row in rows
    )

    scored = []
    for row in rows:
        score, parts = _score_local_catalog_row(
            row,
            code_set,
            keyword_set,
            media_sha256=media_sha256,
            media_signatures=media_signatures,
            vision=vision,
        )
        if score <= 0:
            continue
        scored.append({
            **row,
            "score": score,
            "components": parts,
        })

    scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    matches = scored[:3]
    if not matches:
        return {}

    top = matches[0]
    top_score = float(top.get("score") or 0.0)
    code = normalize_text(top.get("product_code"))
    model = normalize_text(top.get("model_code"))
    price = normalize_text(top.get("price"))
    currency = normalize_text(top.get("currency"))
    image_score = float((top.get("components") or {}).get("image") or 0.0)

    visual_evidence = exact_image_match or bool(code_set) or bool(vision.get("codes")) or bool(vision.get("keywords")) or bool(vision.get("garment_type"))
    accepted_by_score = top_score >= PRODUCT_MATCHER_MIN_SCORE and visual_evidence
    accepted_by_code = bool(code_set)
    accepted_by_image = image_score >= max(PRODUCT_MATCHER_WEAK_MIN_SCORE, 0.45) and visual_evidence
    accepted_weak_match = bool(code or model or price) and top_score >= PRODUCT_MATCHER_WEAK_MIN_SCORE and visual_evidence

    if not (accepted_by_score or accepted_by_code or accepted_by_image or accepted_weak_match):
        return {}

    alternatives = []
    for item in matches[1:3]:
        alt_code = normalize_text(item.get("product_code"))
        alt_model = normalize_text(item.get("model_code"))
        alt_score = float(item.get("score") or 0.0)
        if alt_code or alt_model:
            alternatives.append(f"{alt_code or alt_model} ({alt_score:.2f})")

    parts = []
    if code:
        parts.append(f"code={code}")
    if model:
        parts.append(f"model={model}")
    if price:
        parts.append(f"price={price} {currency}".strip())

    context_lines = [
        "Product media analysis (high-priority context for this customer message):",
        f"- Top match confidence: {top_score:.2f}",
    ]
    if parts:
        context_lines.append(f"- Top match details: {', '.join(parts)}")
    if code_set:
        context_lines.append(f"- Extracted codes from media/text: {', '.join(sorted(code_set)[:8])}")
    if alternatives:
        alternative_text = ", ".join(alternatives)
        context_lines.append(f"- Alternatives: {alternative_text}")
    context_lines.append("- Use this to answer product/price questions for the attached media.")

    return {
        "context": "\n".join(context_lines),
        "reply_hint": build_product_match_reply(code, model, price, currency, top_score),
        "top_score": top_score,
        "top_match_code": code,
        "top_match_model": model,
        "matches": matches,
    }
