from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

import database as db
from config import ADMIN_IDS, BOT_NAME, CHANNEL_ID


async def membership_ok(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status not in ("left", "kicked")
    except TelegramBadRequest:
        return False


async def evaluate_access(bot: Bot, user_id: int) -> str:
    """خروجی: banned | maintenance | join | refer | ok"""
    user = await db.get_user(user_id)
    if user and user["is_banned"]:
        return "banned"
    if user_id in ADMIN_IDS:
        return "ok"
    if await db.maintenance_on():
        return "maintenance"
    if not await membership_ok(bot, user_id):
        return "join"
    await db.credit_referral_if_needed(user_id)
    required = await db.required_referrals()
    count = await db.referral_count(user_id)
    if count < required:
        return "refer"
    if user and not user["unlock_announced"]:
        await db.mark_unlock_announced(user_id)
        await _notify_admins_unlock(bot, user, count)
    return "ok"


async def _notify_admins_unlock(bot: Bot, user, count: int):
    text = (
        f"🎉 <b>یک کاربر {BOT_NAME} را فعال کرد!</b>\n\n"
        f"👤 {escape(user['full_name'])}\n"
        f"🆔 <code>{user['user_id']}</code>\n"
        f"👥 معرفی‌ها: {count}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


async def answer_long(message: Message, text: str, limit: int = 4000):
    """پیام‌های بلندتر از حد تلگرام را به چند بخش می‌شکند."""
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        await message.answer(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        await message.answer(text)
