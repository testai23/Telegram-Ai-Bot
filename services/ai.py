import logging
import random
from urllib.parse import quote

import aiohttp

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_active_model: str | None = None


def _endpoint(model: str) -> str:
    return f"{GEMINI_API_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"


def _model_score(name: str) -> int:
    n = name.lower()
    if any(bad in n for bad in ("image", "tts", "embed", "aqa", "robotics")):
        return -1
    score = 0
    if "flash" in n:
        score += 10
    if "lite" in n:
        score += 5
    if "pro" in n:
        score += 2
    return score


async def _detect_model(session: aiohttp.ClientSession) -> str | None:
    """بهترین مدل فعال را از خود API می‌پرسد تا با منقضی شدن مدل‌ها ربات نخوابد."""
    global _active_model
    try:
        async with session.get(
            f"{GEMINI_API_BASE}?key={GEMINI_API_KEY}&pageSize=200",
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
        best, best_score = None, 0
        for m in data.get("models", []):
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            name = m["name"].split("/")[-1]
            score = _model_score(name)
            if score > best_score:
                best, best_score = name, score
        if best:
            _active_model = best
            logger.info("Gemini auto-selected model: %s", best)
        return best
    except Exception:
        logger.exception("Gemini model detection failed")
        return None


async def _call_gemini(session: aiohttp.ClientSession, model: str, payload: dict):
    async with session.post(
        _endpoint(model), json=payload, timeout=aiohttp.ClientTimeout(total=60)
    ) as resp:
        body = await resp.text()
        try:
            data = await resp.json()
        except Exception:
            data = None
        return resp.status, data, body

SYSTEM_PROMPT = (
    "You are a helpful assistant inside a Telegram bot. "
    "Always answer in the same language the user writes in (usually Persian). "
    "Keep answers clear and not too long."
)

IMAGE_SIZES = {
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
}

_histories: dict[int, list[dict]] = {}
MAX_HISTORY = 10  # آخرین پیام‌های نگهداری‌شده برای هر کاربر


async def gemini_chat(user_id: int, text: str) -> str:
    history = _histories.setdefault(user_id, [])
    history.append({"role": "user", "parts": [{"text": text}]})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history[-MAX_HISTORY:],
    }

    try:
        async with aiohttp.ClientSession() as session:
            model = _active_model or GEMINI_MODEL
            status, data, body = await _call_gemini(session, model, payload)

            if status == 404:  # مدل منقضی شده؛ یک مدل فعال را خودکار پیدا کن
                logger.warning("Gemini model %s unavailable, auto-detecting...", model)
                new_model = await _detect_model(session)
                if new_model and new_model != model:
                    status, data, body = await _call_gemini(session, new_model, payload)

            if status != 200:
                logger.error("Gemini HTTP %s: %s", status, body[:500])
                history.pop()
                return "⚠️ خطایی در ارتباط با هوش مصنوعی رخ داد. لطفاً کمی بعد دوباره تلاش کن."
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        logger.exception("Gemini request failed")
        history.pop()
        return "⚠️ خطایی در ارتباط با هوش مصنوعی رخ داد. لطفاً کمی بعد دوباره تلاش کن."

    history.append({"role": "model", "parts": [{"text": reply}]})
    del history[:-MAX_HISTORY]
    return reply


def clear_history(user_id: int):
    _histories.pop(user_id, None)


def image_url(prompt: str, ratio: str = "1:1") -> str:
    width, height = IMAGE_SIZES.get(ratio, IMAGE_SIZES["1:1"])
    safe_prompt = quote(prompt[:500])
    seed = random.randint(1, 999_999)
    return (
        f"https://image.pollinations.ai/prompt/{safe_prompt}"
        f"?width={width}&height={height}&nologo=true&model=flux&seed={seed}"
    )
