from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests
from PIL import Image, ImageOps
from supabase import create_client


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled", "enable"}


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
HARDCODED_CATALOG_SUPABASE_URL = "https://qldfdpatlpxikdrheasw.supabase.co"
HARDCODED_CATALOG_SUPABASE_SERVICE_KEY = "sb_secret_QdEFx16nHkpPuaSeJR8zrQ_lx8X8P7L"
CATALOG_SUPABASE_URL = HARDCODED_CATALOG_SUPABASE_URL
CATALOG_SUPABASE_SERVICE_KEY = HARDCODED_CATALOG_SUPABASE_SERVICE_KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VISION_MODEL = normalize_text(os.getenv("PRODUCT_MATCHER_GEMINI_VISION_MODEL", "gemini-2.5-pro")) or "gemini-2.5-pro"

PRODUCT_MATCHER_LOCAL_ENABLED = env_bool("PRODUCT_MATCHER_LOCAL_ENABLED", True)
PRODUCT_MATCHER_LOCAL_CATALOG_TABLE = normalize_text(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_TABLE", "milana_products")) or "milana_products"
PRODUCT_MATCHER_LOCAL_OVERRIDES_TABLE = normalize_text(os.getenv("PRODUCT_MATCHER_LOCAL_OVERRIDES_TABLE", "milana_product_overrides")) or "milana_product_overrides"
PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS = max(30, min(60 * 60, int(os.getenv("PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS", "300"))))
PRODUCT_MATCHER_LOCAL_FETCH_LIMIT = max(50, min(3000, int(os.getenv("PRODUCT_MATCHER_LOCAL_FETCH_LIMIT", "1200"))))
PRODUCT_MATCHER_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_MIN_SCORE", "0.20"))))
PRODUCT_MATCHER_WEAK_MIN_SCORE = max(0.0, min(1.0, float(os.getenv("PRODUCT_MATCHER_WEAK_MIN_SCORE", "0.10"))))
PRODUCT_MATCHER_TOP_K = max(1, min(12, int(os.getenv("PRODUCT_MATCHER_TOP_K", "8"))))
PRODUCT_MATCHER_MAX_MEDIA_MB = max(2, min(40, int(os.getenv("PRODUCT_MATCHER_MAX_MEDIA_MB", "20"))))
PRODUCT_MATCHER_TIMEOUT_SECONDS = max(10, min(180, int(os.getenv("PRODUCT_MATCHER_TIMEOUT_SECONDS", "90"))))
PRODUCT_MATCHER_CATALOG_SCOPE = normalize_text(os.getenv("PRODUCT_MATCHER_CATALOG_SCOPE", "all")).lower() or "all"

_supabase = None
_catalog_cache = {"loaded_at": 0.0, "rows": [], "stats": {}}


@dataclass
class ProductRecord:
    product_code: str
    model_code: str
    price: str
    currency: str
    combined_text: str
    image_url: str
    image_sha256: str
    image_fingerprint: str
    embedding_preview: list[float]
    source_pdf: str
    page: Any
    card_index: Any
    source: str
    catalog_group: str


@dataclass
class CustomerImageAnalysis:
    garment_type: str
    primary_color: str
    secondary_colors: list[str]
    pattern: str
    neckline: str
    sleeve_length: str
    closure: str
    visible_text: str
    visible_codes: list[str]
    notes: str


def log(title: str, data: Any = None) -> None:
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


def normalize_product_code(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9-]", "", normalize_text(value).upper())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def normalize_code(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def extract_codes_from_text(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    found: list[str] = []
    for raw in re.findall(r"\b[A-Za-z]{1,4}-?\d{2,6}\b", text):
        code = normalize_product_code(raw)
        if code and code not in found:
            found.append(code)
    return found


def derive_catalog_group(source_pdf: str | None) -> str:
    source = normalize_text(source_pdf).lower()
    if "kindergarten" in source:
        return "kids"
    if "man_premium" in source or "man premium" in source:
        return "men"
    if "products_in_stock" in source:
        return "women"
    if "staple_model_catalog" in source:
        return "mixed"
    return "unknown"


def _parse_float_list(value: Any, limit: int = 12) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        text = normalize_text(value)
        if not text:
            return []
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else re.findall(r"-?\d+(?:\.\d+)?", text)
        except Exception:
            items = re.findall(r"-?\d+(?:\.\d+)?", text)
    out = []
    for item in items[:limit]:
        try:
            out.append(float(item))
        except Exception:
            continue
    return out


def _get_local_catalog_rows(force_refresh: bool = False) -> list[ProductRecord]:
    now = time.time()
    if (
        not force_refresh
        and _catalog_cache["rows"]
        and (now - float(_catalog_cache.get("loaded_at") or 0.0)) < PRODUCT_MATCHER_LOCAL_CATALOG_CACHE_TTL_SECONDS
    ):
        return _catalog_cache["rows"]

    product_fields = "product_code,model_code,price,currency,combined_text,image_url,image_sha256,image_fingerprint,embedding_preview,source_pdf,page,card_index"
    override_fields = "product_code,model_code,price,currency,image_url,image_storage_path,source_pdf,page,card_index"
    products = (
        _client()
        .table(PRODUCT_MATCHER_LOCAL_CATALOG_TABLE)
        .select(product_fields)
        .limit(PRODUCT_MATCHER_LOCAL_FETCH_LIMIT)
        .execute()
    ).data or []
    overrides = (
        _client()
        .table(PRODUCT_MATCHER_LOCAL_OVERRIDES_TABLE)
        .select(override_fields)
        .limit(PRODUCT_MATCHER_LOCAL_FETCH_LIMIT)
        .execute()
    ).data or []

    override_map = {(normalize_text(r.get("product_code")), normalize_text(r.get("model_code"))): r for r in overrides if isinstance(r, dict)}
    rows: list[ProductRecord] = []
    seen_keys: set[tuple[str, str]] = set()
    override_only = 0

    for row in products:
        if not isinstance(row, dict):
            continue
        key = (normalize_text(row.get("product_code")), normalize_text(row.get("model_code")))
        merged = dict(row)
        override = override_map.get(key)
        if override:
            for field in ("price", "currency", "image_url", "source_pdf"):
                if override.get(field) is not None:
                    merged[field] = override[field]
        seen_keys.add(key)
        rows.append(
            ProductRecord(
                product_code=normalize_product_code(merged.get("product_code")),
                model_code=normalize_product_code(merged.get("model_code")),
                price=normalize_text(merged.get("price")),
                currency=normalize_text(merged.get("currency")),
                combined_text=normalize_text(merged.get("combined_text")),
                image_url=normalize_text(merged.get("image_url")),
                image_sha256=normalize_text(merged.get("image_sha256")).lower(),
                image_fingerprint=normalize_text(merged.get("image_fingerprint")),
                embedding_preview=_parse_float_list(merged.get("embedding_preview"), limit=12),
                source_pdf=normalize_text(merged.get("source_pdf")),
                page=merged.get("page"),
                card_index=merged.get("card_index"),
                source="milana_products",
                catalog_group=derive_catalog_group(merged.get("source_pdf")),
            )
        )

    for row in overrides:
        if not isinstance(row, dict):
            continue
        key = (normalize_text(row.get("product_code")), normalize_text(row.get("model_code")))
        if key in seen_keys:
            continue
        rows.append(
            ProductRecord(
                product_code=normalize_product_code(row.get("product_code")),
                model_code=normalize_product_code(row.get("model_code")),
                price=normalize_text(row.get("price")),
                currency=normalize_text(row.get("currency")),
                combined_text="",
                image_url=normalize_text(row.get("image_url")),
                image_sha256="",
                image_fingerprint=normalize_text(row.get("image_storage_path")),
                embedding_preview=[],
                source_pdf=normalize_text(row.get("source_pdf")),
                page=row.get("page"),
                card_index=row.get("card_index"),
                source="milana_product_overrides",
                catalog_group=derive_catalog_group(row.get("source_pdf")),
            )
        )
        override_only += 1

    _catalog_cache["rows"] = rows
    _catalog_cache["loaded_at"] = now
    _catalog_cache["stats"] = {
        "base_table_rows": len(products),
        "override_table_rows": len(overrides),
        "override_only_products": override_only,
        "unique_searchable_products": len(rows),
    }
    return rows


def get_catalog_stats() -> dict[str, int]:
    _get_local_catalog_rows()
    return dict(_catalog_cache.get("stats") or {})


def download_media_for_matcher(media_url: str, access_token: str = "") -> tuple[bytes, str, str]:
    media_url = normalize_text(media_url)
    if not media_url:
        raise ValueError("Empty media URL")
    limit_bytes = PRODUCT_MATCHER_MAX_MEDIA_MB * 1024 * 1024
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    if normalize_text(access_token):
        headers["Authorization"] = f"Bearer {normalize_text(access_token)}"
    response = requests.get(media_url, timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 30), stream=True, headers=headers)
    if response.status_code == 403 and normalize_text(access_token):
        sep = "&" if "?" in media_url else "?"
        response = requests.get(f"{media_url}{sep}access_token={normalize_text(access_token)}", timeout=min(PRODUCT_MATCHER_TIMEOUT_SECONDS, 30), stream=True)
    response.raise_for_status()
    content_type = normalize_text(response.headers.get("content-type")).split(";")[0].strip() or "application/octet-stream"
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit_bytes:
            raise ValueError(f"Media is too large (> {PRODUCT_MATCHER_MAX_MEDIA_MB} MB)")
        chunks.append(chunk)
    data = b"".join(chunks)
    filename = f"media{os.path.splitext(content_type)[-1] or '.bin'}"
    return data, filename, content_type


def detect_mime_type(image_bytes: bytes) -> str:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image_format = (image.format or "").upper()
    if image_format == "PNG":
        return "image/png"
    if image_format == "WEBP":
        return "image/webp"
    return "image/jpeg"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def crop_focus_region(image_bytes: bytes, mode: str) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        if mode == "customer":
            box = (int(width * 0.12), int(height * 0.18), int(width * 0.88), height)
        else:
            box = (int(width * 0.1), int(height * 0.12), int(width * 0.9), height)
        cropped = image.crop(box)
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=92)
        return buf.getvalue()


def crop_code_region(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        box = (0, int(height * 0.08), int(width * 0.42), int(height * 0.88))
        cropped = image.crop(box)
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=95)
        return buf.getvalue()


def compute_color_histogram(image_bytes: bytes) -> list[float]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = ImageOps.exif_transpose(image).convert("RGB").resize((256, 256))
        channels = rgb.split()
    hist: list[float] = []
    for channel in channels:
        bins = channel.histogram()
        for start in range(0, 256, 64):
            hist.append(sum(bins[start : start + 64]))
    norm = math.sqrt(sum(v * v for v in hist))
    return hist if not norm else [v / norm for v in hist]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    return sum(a * b for a, b in zip(left, right))


def filter_products_by_scope(products: list[ProductRecord], scope: str) -> list[ProductRecord]:
    scope = normalize_text(scope).lower() or "all"
    if scope == "all":
        return products
    return [product for product in products if product.catalog_group == scope]


def build_database_counts(all_products: list[ProductRecord], scoped_products: list[ProductRecord], visual_products: list[ProductRecord]) -> dict[str, int]:
    stats = get_catalog_stats()
    return {
        "base_table_rows": stats.get("base_table_rows", 0),
        "override_table_rows": stats.get("override_table_rows", 0),
        "override_only_products": stats.get("override_only_products", 0),
        "unique_searchable_products": stats.get("unique_searchable_products", len(all_products)),
        "all_products": len(all_products),
        "scope_products": len(scoped_products),
        "scope_products_with_images": len(visual_products),
        "scope_products_without_images": len(scoped_products) - len(visual_products),
    }


def normalize_blob(value: str | None) -> str:
    value = normalize_text(value).upper().replace(">", " ").replace("/", " ").replace("_", " ")
    value = re.sub(r"[^A-Z0-9\\s-]", " ", value)
    return " ".join(value.split())


def extract_codes_from_blob(value: str | None) -> set[str]:
    return {normalize_code(x) for x in re.findall(r"\b[A-Z]{1,4}-?\d{2,6}\b", normalize_blob(value)) if normalize_code(x)}


def find_exact_code_matches(analysis: CustomerImageAnalysis, products: list[ProductRecord]) -> list[ProductRecord]:
    codes = {normalize_code(code) for code in analysis.visible_codes if normalize_code(code)}
    if not codes:
        return []
    matches: list[ProductRecord] = []
    seen: set[tuple[str, str]] = set()
    for product in products:
        key = (product.product_code, product.model_code)
        if key in seen:
            continue
        if (
            normalize_code(product.product_code) in codes
            or normalize_code(product.model_code) in codes
            or codes.intersection(extract_codes_from_blob(product.combined_text))
        ):
            matches.append(product)
            seen.add(key)
    return matches


def has_strong_visible_codes(analysis: CustomerImageAnalysis) -> bool:
    return any(re.fullmatch(r"[A-Z]{1,4}-?\d{2,6}", normalize_text(code).upper()) for code in analysis.visible_codes)


def build_code_not_found_reply(analysis: CustomerImageAnalysis) -> str:
    visible_codes = [normalize_product_code(code) for code in analysis.visible_codes if normalize_product_code(code)]
    if visible_codes:
        return (
            f"Rasmda {', '.join(visible_codes[:2])} kodi ko'rinmoqda, lekin bu model hozirgi katalog bazamizda topilmadi. "
            "Aniq narx va mavjudlikni menejerimiz tekshirib beradi."
        )
    return "Rasmdagi model kodi katalog bazamizda topilmadi. Aniq narx va mavjudlikni menejerimiz tekshirib beradi."


def requested_garment_hint(user_text: str) -> str:
    text = normalize_text(user_text).lower()
    garment_map = {
        "tshirt": ["futbolka", "fudbolka", "footballka", "майка", "футболка", "t-shirt", "tee", "shirt"],
        "pants": ["shim", "брюки", "штаны", "pants", "trousers"],
        "shorts": ["shortik", "shorti", "shorts", "шорты"],
        "hoodie": ["hudie", "hoodie", "tolstovka", "худи"],
        "dress": ["ko'ylak", "kuylak", "платье", "dress"],
        "pajama": ["pijama", "pyjama", "pajama", "пижама"],
    }
    for label, keywords in garment_map.items():
        if any(keyword in text for keyword in keywords):
            return label
    return ""


def rank_by_embedding(query_embedding: list[float], products: list[ProductRecord], limit: int) -> list[ProductRecord]:
    scored = [(cosine_similarity(query_embedding, product.embedding_preview), product) for product in products]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in scored[:limit]]


def rank_by_text_signals(analysis: CustomerImageAnalysis, products: list[ProductRecord], limit: int) -> list[ProductRecord]:
    codes = {normalize_code(code) for code in analysis.visible_codes if normalize_code(code)}
    tokens = normalize_blob(" ".join([
        analysis.garment_type,
        analysis.primary_color,
        " ".join(analysis.secondary_colors),
        analysis.pattern,
        analysis.neckline,
        analysis.sleeve_length,
        analysis.closure,
        analysis.visible_text,
        " ".join(analysis.visible_codes),
        analysis.notes,
    ])).split()
    scored = []
    for product in products:
        blob = normalize_blob(" ".join([product.product_code, product.model_code, product.combined_text]))
        score = 0.0
        for code in codes:
            if code and code in normalize_code(blob):
                score += 60.0
        for token in tokens:
            if len(token) > 2 and token in blob:
                score += 1.3
        scored.append((score, product))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [product for _, product in scored[:limit]]


def build_candidate_shortlist(query_embedding: list[float], analysis: CustomerImageAnalysis, products: list[ProductRecord], limit: int) -> list[ProductRecord]:
    embedding_ranked = rank_by_embedding(query_embedding, products, max(limit, 24))
    text_ranked = rank_by_text_signals(analysis, products, max(limit, 24))
    scores: dict[tuple[str, str], float] = {}
    by_key: dict[tuple[str, str], ProductRecord] = {}
    for idx, product in enumerate(embedding_ranked):
        key = (product.product_code, product.model_code)
        by_key[key] = product
        scores[key] = scores.get(key, 0.0) + (len(embedding_ranked) - idx) * 0.35
    for idx, product in enumerate(text_ranked):
        key = (product.product_code, product.model_code)
        by_key[key] = product
        scores[key] = scores.get(key, 0.0) + (len(text_ranked) - idx) * 1.0
    keys = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [by_key[key] for key in keys[:limit]]


def merge_exact_matches_into_shortlist(exact_matches: list[ProductRecord], shortlist: list[ProductRecord], limit: int) -> list[ProductRecord]:
    merged: list[ProductRecord] = []
    seen: set[tuple[str, str]] = set()
    for product in exact_matches + shortlist:
        key = (product.product_code, product.model_code)
        if key in seen:
            continue
        merged.append(product)
        seen.add(key)
        if len(merged) >= limit:
            break
    return merged


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            text = normalize_text(part.get("text"))
            if text:
                return text
    return ""


def _gemini_post(payload: dict[str, Any], attempts: int = 3) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        return {}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_VISION_MODEL}:generateContent"
    last_body: dict[str, Any] = {}
    for attempt in range(attempts):
        try:
            res = requests.post(url, params={"key": GEMINI_API_KEY}, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
            body = res.json() if res.content else {}
            last_body = body if isinstance(body, dict) else {}
            if res.ok:
                return last_body
            if res.status_code not in {429, 500, 503, 504}:
                return last_body
            time.sleep(1.2 * (attempt + 1))
        except Exception as exc:
            last_body = {"error": str(exc)}
            time.sleep(1.2 * (attempt + 1))
    return last_body


def analyze_customer_image(image_bytes: bytes, user_text: str = "") -> CustomerImageAnalysis:
    crop = crop_focus_region(image_bytes, mode="customer")
    code_crop = crop_code_region(image_bytes)
    payload = {
        "contents": [{
            "parts": [
                {"text": (
                    "Extract garment attributes and any visible product text/codes. "
                    f"The customer message is: {normalize_text(user_text) or '(none)'}. "
                    "If the customer mentions a specific item like t-shirt, pants, shorts, dress, or hoodie, focus on that item only. "
                    "Ignore nearby products on the same catalog page unless the customer is clearly asking about them. "
                    "Prioritize OCR from catalog labels, especially MODEL and CODE values printed on the image. "
                    "Use all image crops. Focus on the garment only, not the person's face or room. Return JSON."
                )},
                {"inlineData": {"mimeType": detect_mime_type(image_bytes), "data": _b64(image_bytes)}},
                {"inlineData": {"mimeType": detect_mime_type(crop), "data": _b64(crop)}},
                {"inlineData": {"mimeType": detect_mime_type(code_crop), "data": _b64(code_crop)}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {
                    "garment_type": {"type": "string"},
                    "primary_color": {"type": "string"},
                    "secondary_colors": {"type": "array", "items": {"type": "string"}},
                    "pattern": {"type": "string"},
                    "neckline": {"type": "string"},
                    "sleeve_length": {"type": "string"},
                    "closure": {"type": "string"},
                    "visible_text": {"type": "string"},
                    "visible_codes": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["garment_type", "primary_color", "secondary_colors", "pattern", "neckline", "sleeve_length", "closure", "visible_text", "visible_codes", "notes"],
            },
        },
    }
    body = _gemini_post(payload)
    text = _extract_gemini_text(body)
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = {}
    return CustomerImageAnalysis(
        garment_type=normalize_text(parsed.get("garment_type")),
        primary_color=normalize_text(parsed.get("primary_color")),
        secondary_colors=parsed.get("secondary_colors") if isinstance(parsed.get("secondary_colors"), list) else [],
        pattern=normalize_text(parsed.get("pattern")),
        neckline=normalize_text(parsed.get("neckline")),
        sleeve_length=normalize_text(parsed.get("sleeve_length")),
        closure=normalize_text(parsed.get("closure")),
        visible_text=normalize_text(parsed.get("visible_text")),
        visible_codes=[normalize_text(x) for x in (parsed.get("visible_codes") if isinstance(parsed.get("visible_codes"), list) else [])],
        notes=normalize_text(parsed.get("notes")),
    )


def rerank_with_gemini(query_image_bytes: bytes, shortlist: list[ProductRecord], analysis: CustomerImageAnalysis, user_text: str = "") -> tuple[ProductRecord | None, str | None]:
    if not shortlist:
        return None, None
    query_crop = crop_focus_region(query_image_bytes, mode="customer")
    parts: list[dict[str, Any]] = [
        {"text": (
            "Match the customer garment to exactly one catalog candidate. "
            f"The customer asked: {normalize_text(user_text) or '(no text)'}\n"
            "If the message refers to a specific garment like t-shirt, pants, shorts, dress, or hoodie, match that garment only. "
            "Do not select a nearby different product from the same catalog page. "
            "Ignore the person's gender presentation, face, body shape, pose, and room. "
            "Match only the garment. Return JSON with selected_index, confidence, and reason.\n"
            f"Customer analysis: {json.dumps(asdict(analysis), ensure_ascii=True)}"
        )},
        {"inlineData": {"mimeType": detect_mime_type(query_image_bytes), "data": _b64(query_image_bytes)}},
        {"inlineData": {"mimeType": detect_mime_type(query_crop), "data": _b64(query_crop)}},
    ]
    for idx, product in enumerate(shortlist):
        parts.append({"text": f"Candidate {idx}. product_code={product.product_code}. model_code={product.model_code}. catalog_group={product.catalog_group}. catalog_text={product.combined_text[:400]}"})
        if product.image_url:
            try:
                image_bytes, _, _ = download_media_for_matcher(product.image_url)
                parts.append({"inlineData": {"mimeType": detect_mime_type(image_bytes), "data": _b64(image_bytes)}})
            except Exception:
                continue
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {
                    "selected_index": {"type": "integer"},
                    "confidence": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["selected_index", "confidence", "reason"],
            },
        },
    }
    body = _gemini_post(payload)
    if body.get("error"):
        return None, normalize_text(body.get("error"))
    text = _extract_gemini_text(body)
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = {}
    idx = parsed.get("selected_index")
    if not isinstance(idx, int) or idx < 0 or idx >= len(shortlist):
        return None, None
    return shortlist[idx], None


def verify_candidate_with_gemini(query_image_bytes: bytes, candidate: ProductRecord, analysis: CustomerImageAnalysis, user_text: str = "") -> tuple[bool, str]:
    if not candidate.image_url:
        return True, ""
    try:
        candidate_bytes, _, _ = download_media_for_matcher(candidate.image_url)
    except Exception as exc:
        return True, f"candidate image unavailable: {exc}"

    query_crop = crop_focus_region(query_image_bytes, mode="customer")
    payload = {
        "contents": [{
            "parts": [
                {"text": (
                    "Decide whether the catalog candidate is the same garment the customer is asking about. "
                    f"Customer message: {normalize_text(user_text) or '(no text)'}\n"
                    "If the customer is asking about a specific garment like a t-shirt, do not approve a different nearby item such as pants or shorts. "
                    "Return JSON with matches_target_item (true/false) and reason.\n"
                    f"Customer analysis: {json.dumps(asdict(analysis), ensure_ascii=True)}\n"
                    f"Candidate product_code={candidate.product_code}, model_code={candidate.model_code}, catalog_group={candidate.catalog_group}, catalog_text={candidate.combined_text[:400]}"
                )},
                {"inlineData": {"mimeType": detect_mime_type(query_image_bytes), "data": _b64(query_image_bytes)}},
                {"inlineData": {"mimeType": detect_mime_type(query_crop), "data": _b64(query_crop)}},
                {"inlineData": {"mimeType": detect_mime_type(candidate_bytes), "data": _b64(candidate_bytes)}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {
                    "matches_target_item": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["matches_target_item", "reason"],
            },
        },
    }
    body = _gemini_post(payload)
    text = _extract_gemini_text(body)
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = {}
    return bool(parsed.get("matches_target_item")), normalize_text(parsed.get("reason"))


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
        media_bytes, _, _ = download_media_for_matcher(media_url, access_token=access_token)
    except Exception as exc:
        log("catalog_matcher download failed", {"error": str(exc)})
        return {}

    all_products = _get_local_catalog_rows()
    scoped_products = filter_products_by_scope(all_products, PRODUCT_MATCHER_CATALOG_SCOPE)
    visual_products = [product for product in scoped_products if product.image_url]
    if not scoped_products:
        return {}

    analysis = analyze_customer_image(media_bytes, user_text=user_text)
    garment_hint = requested_garment_hint(user_text)
    exact_matches = find_exact_code_matches(analysis, scoped_products)
    matches: list[ProductRecord] = []
    warning = ""
    top: ProductRecord | None = None
    top_score = 0.0
    strategy = ""
    if len(exact_matches) == 1:
        exact_match = exact_matches[0]
        exact_ok, exact_reason = verify_candidate_with_gemini(media_bytes, exact_match, analysis, user_text=user_text) if garment_hint else (True, "")
        if exact_ok:
            top = exact_match
            top_score = 1.0
            strategy = "exact_code_match"
            matches = [top]
            warning = ""
        else:
            exact_matches = []
            warning = f"Exact code candidate rejected for the requested item: {exact_reason or 'target garment mismatch'}"
            top = None
            top_score = 0.0
            strategy = ""
            matches = []
    elif has_strong_visible_codes(analysis) and not exact_matches:
        db_counts = build_database_counts(all_products, scoped_products, visual_products)
        warning = "Visible product codes were extracted from the image, but those codes do not exist in the current catalog database."
        return {
            "context": "\n".join([
                "Product media analysis (high-priority context for this customer message):",
                "- Match strategy: code_not_found",
                f"- Catalog scope: {PRODUCT_MATCHER_CATALOG_SCOPE}",
                f"- Extracted codes from media: {', '.join(analysis.visible_codes[:8])}",
                f"- Warning: {warning}",
                f"- Catalog coverage: {json.dumps(db_counts, ensure_ascii=False)}",
                "- Do not invent another product code, model, or price. Tell the customer the model needs manual verification.",
            ]),
            "reply_hint": build_code_not_found_reply(analysis),
            "top_score": 0.0,
            "top_match_code": "",
            "top_match_model": "",
            "matches": [],
            "analysis": asdict(analysis),
            "database_counts": db_counts,
            "match_strategy": "code_not_found",
            "model_warning": warning,
        }
    if not matches:
        if not visual_products:
            return {}
        query_embedding = compute_color_histogram(media_bytes)
        shortlist = build_candidate_shortlist(query_embedding, analysis, visual_products, max(PRODUCT_MATCHER_TOP_K, 6))
        if exact_matches:
            shortlist = merge_exact_matches_into_shortlist(exact_matches, shortlist, max(PRODUCT_MATCHER_TOP_K, 6))
        top, rerank_warning = rerank_with_gemini(media_bytes, shortlist, analysis, user_text=user_text)
        if top is None:
            top = shortlist[0]
            rerank_warning = rerank_warning or "Gemini rerank unavailable; used shortlist fallback."
        if warning and rerank_warning:
            warning = f"{warning}; {rerank_warning}"
        else:
            warning = warning or rerank_warning or ""
        top_score = 0.6 if warning else 0.9
        strategy = "vision_rerank"
        matches = shortlist[:PRODUCT_MATCHER_TOP_K]

    if top is None:
        return {}

    code = normalize_text(top.product_code)
    model = normalize_text(top.model_code)
    price = normalize_text(top.price)
    currency = normalize_text(top.currency)
    parts = []
    if code:
        parts.append(f"code={code}")
    if model:
        parts.append(f"model={model}")
    if price:
        parts.append(f"price={price} {currency}".strip())
    context_lines = [
        "Product media analysis (high-priority context for this customer message):",
        f"- Match strategy: {strategy}",
        f"- Catalog scope: {PRODUCT_MATCHER_CATALOG_SCOPE}",
        f"- Top match confidence: {top_score:.2f}",
    ]
    if parts:
        context_lines.append(f"- Top match details: {', '.join(parts)}")
    if analysis.visible_codes:
        context_lines.append(f"- Extracted codes from media: {', '.join(analysis.visible_codes[:8])}")
    if warning:
        context_lines.append(f"- Warning: {warning}")
    db_counts = build_database_counts(all_products, scoped_products, visual_products)
    context_lines.append(f"- Catalog coverage: {json.dumps(db_counts, ensure_ascii=False)}")
    context_lines.append("- Use this to answer product/price questions for the attached media.")

    match_rows = []
    for product in matches[:PRODUCT_MATCHER_TOP_K]:
        match_rows.append({
            "product_code": product.product_code,
            "model_code": product.model_code,
            "price": product.price,
            "currency": product.currency,
            "image_url": product.image_url,
            "catalog_group": product.catalog_group,
            "source_pdf": product.source_pdf,
            "score": top_score if product == top else 0.0,
        })

    return {
        "context": "\n".join(context_lines),
        "reply_hint": build_product_match_reply(code, model, price, currency, top_score),
        "top_score": top_score,
        "top_match_code": code,
        "top_match_model": model,
        "matches": match_rows,
        "analysis": asdict(analysis),
        "database_counts": db_counts,
        "match_strategy": strategy,
        "model_warning": warning or None,
    }


def analyze_media_for_sales_reply(media_url: str, user_text: str, media_type: str = "", access_token: str = "") -> dict:
    return analyze_media_for_sales_reply_local(
        media_url=media_url,
        user_text=user_text,
        media_type=media_type,
        access_token=access_token,
    )
