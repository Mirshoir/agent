import base64
import os
from typing import Any

import requests


GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.getenv("VIDEO_ANALYZER_GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))
GEMINI_FALLBACK_MODEL = os.getenv("VIDEO_ANALYZER_GEMINI_FALLBACK_MODEL", os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash"))
GEMINI_TIMEOUT = int(os.getenv("VIDEO_ANALYZER_GEMINI_TIMEOUT", os.getenv("GEMINI_TIMEOUT", "300")))
GEMINI_FALLBACK_TIMEOUT = int(os.getenv("VIDEO_ANALYZER_GEMINI_FALLBACK_TIMEOUT", os.getenv("GEMINI_FALLBACK_TIMEOUT", "80")))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("VIDEO_ANALYZER_GEMINI_MAX_OUTPUT_TOKENS", os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2200")))
VERIFY_SSL = os.getenv("SSL_VERIFY", "true").lower() not in {"0", "false", "no"}


class VideoAnalyzerError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def analyze_video_content(body: dict[str, Any], api_key: str = "") -> tuple[str, str]:
    gemini_key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        raise VideoAnalyzerError("GEMINI_API_KEY is not configured.", 401)

    description = clean_text(body.get("description", ""))
    brand = clean_text(body.get("brand", ""))
    niche = clean_text(body.get("niche", ""))
    details = clean_text(body.get("details", ""))
    duration = body.get("duration") or 0
    frames = body.get("frames") or []

    if not description and not details and not frames:
        raise VideoAnalyzerError("Add a description, details, or video frames for analysis.", 400)

    requested_model = clean_text(body.get("model", "")) or GEMINI_MODEL
    parts = [{"text": build_prompt(description, brand, niche, details, duration, len(frames))}]
    for frame in frames[:4]:
        parsed = parse_data_url_image(frame)
        if parsed:
            mime_type, encoded = parsed
            parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        },
    }

    try:
        return call_gemini(gemini_key, requested_model, payload, GEMINI_TIMEOUT), requested_model
    except requests.Timeout as exc:
        if not GEMINI_FALLBACK_MODEL or requested_model == GEMINI_FALLBACK_MODEL:
            raise VideoAnalyzerError("Gemini took too long to respond. Please try again.", 504)
        return call_gemini(gemini_key, GEMINI_FALLBACK_MODEL, payload, GEMINI_FALLBACK_TIMEOUT), GEMINI_FALLBACK_MODEL
    except VideoAnalyzerError as exc:
        if not should_retry_with_fallback(exc.status_code, requested_model):
            raise
        try:
            return call_gemini(gemini_key, GEMINI_FALLBACK_MODEL, payload, GEMINI_FALLBACK_TIMEOUT), GEMINI_FALLBACK_MODEL
        except VideoAnalyzerError:
            raise normalize_gemini_error(exc)


def call_gemini(api_key: str, model: str, payload: dict[str, Any], timeout: int) -> str:
    response = requests.post(
        GEMINI_API_URL_TEMPLATE.format(model=model),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload,
        timeout=timeout,
        verify=VERIFY_SSL,
    )
    if not response.ok:
        raise VideoAnalyzerError(extract_gemini_error_message(response), response.status_code)

    text = extract_gemini_text(response.json())
    if not text:
        raise VideoAnalyzerError("Gemini returned an empty response.", 502)
    return text


def should_retry_with_fallback(status_code: int, requested_model: str) -> bool:
    return bool(GEMINI_FALLBACK_MODEL) and requested_model != GEMINI_FALLBACK_MODEL and status_code in {429, 500, 502, 503, 504}


def normalize_gemini_error(error: VideoAnalyzerError) -> VideoAnalyzerError:
    if error.status_code in {429, 503}:
        return VideoAnalyzerError("Gemini is busy right now. Please try again in a minute.", error.status_code)
    if error.status_code in {500, 502, 504}:
        return VideoAnalyzerError("Gemini is temporarily unavailable. Please try again shortly.", error.status_code)
    return error


def extract_gemini_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:280] or f"Gemini API error {response.status_code}."

    error = data.get("error") or {}
    message = str(error.get("message") or "").strip()
    if not message:
        return f"Gemini API error {response.status_code}."
    return message[:280]


def build_prompt(description: str, brand: str, niche: str, details: str, duration: Any, frame_count: int) -> str:
    authority = details or description or niche or brand or "данные пользователя"
    visual_mode = (
        "Кадры видео предоставлены. Анализируй только то, что видно на кадрах, плюс текстовые данные."
        if frame_count
        else f"КАДРЫ ВИДЕО НЕ ПРЕДОСТАВЛЕНЫ. Делай анализ только по описанию и деталям. Главный факт: {authority}. Запрещено придумывать интерьер, мебель, постельное белье, производство, другие товары, локации или любые визуальные элементы, которых нет в описании и деталях."
    )

    return f"""Ты профессиональный эксперт по Instagram Reels, TikTok и YouTube Shorts, маркетолог, SMM-специалист и аналитик вирусного контента.

КРИТИЧЕСКОЕ ПРАВИЛО: не выдумывай факты. Если нет кадров, нельзя описывать то, чего нет в текстовых данных.
Не используй внешние знания или ассоциации о бренде. Название бренда может совпадать с другими компаниями. Истина только в данных пользователя.
Режим анализа: {visual_mode}

Проанализируй контент по доступным данным. Пиши только на русском языке. Ответ должен быть конкретным, продающим и полезным для владельца аккаунта.

Данные:
Бренд: {brand or "не указан"}
Ниша: {niche or "не указана"}
Текущее описание: {description or "не указано"}
Детали ролика: {details or "не указаны"}
Длительность: {duration} секунд
Кадров получено: {frame_count}

Единственная допустимая интерпретация темы: {niche or "ниша не указана"}; {details or description or "детали не указаны"}.

Формат ответа:

📹 Анализ видео
Определи основную тему ролика, целевую аудиторию, эмоции, главный посыл автора, интерес зрителю и удержание внимания.

📝 Анализ описания
Проверь соответствие ролику, понятность, вовлечение, слабые фразы, ошибки. Поставь оценку от 1 до 10.

🔗 Соответствие видео и описания
Поставь процент соответствия от 0 до 100%. Укажи, какие моменты не отражены и что нужно заменить.

❌ Ошибки
Коротким списком.

✅ Что хорошо
Коротким списком.

🚀 Улучшенное описание
Одна готовая версия для публикации.

🔥 Вирусные варианты
Короткая версия.
Средняя версия.
Подробная версия.
Версия для максимального вовлечения.

🏷 Лучшие хэштеги
Подбери хэштеги именно под этот ролик.

📈 Что повысит просмотры
Фразы для удержания, ключевые слова, триггеры любопытства, призывы к действию.

⭐ Дополнительные идеи
10 заголовков.
10 первых строк описания.
10 закрепленных комментариев.
Идеи для обложки.

⭐ Итоговая оценка контента
Оцени видео, описание, потенциал продаж и потенциал вирусности.
"""


def extract_gemini_text(data: dict[str, Any]) -> str:
    chunks = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:4000]


def parse_data_url_image(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    if not value.startswith("data:image/") or ";base64," not in value:
        return None

    header, encoded = value.split(",", 1)
    mime_type = header.split(";", 1)[0].replace("data:", "")

    try:
        base64.b64decode(encoded, validate=True)
    except Exception:
        return None

    return mime_type, encoded
