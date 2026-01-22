"""
AI-powered semantic search handler.
"""
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.handlers.callbacks import send_contact_card
from src.db.engine import get_session
from src.db.repositories.contacts import ContactRepository
from src.services.ai_service import AIService


async def perform_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, query: str
) -> None:
    """
    Perform search with given query (called from /search command).
    """
    user_id = update.effective_user.id

    async with get_session() as session:
        repo = ContactRepository(session)
        all_contacts = await repo.get_all_for_user(user_id)

        if not all_contacts:
            await update.message.reply_text(
                "У тебя пока нет контактов для поиска.\n"
                "Добавь первый: /add",
                parse_mode="HTML",
            )
            return

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Use AI to find matching contacts
        ai_service = AIService()
        matching = await ai_service.semantic_search(
            query=query, contacts=all_contacts
        )

        if not matching:
            await update.message.reply_text(
                "🔍 Не нашёл подходящих контактов.\n"
                "Попробуй изменить запрос или посмотри /list",
                parse_mode="HTML",
            )
            return

        await update.message.reply_text(
            f"🔍 <b>Найдено ({len(matching)}):</b>",
            parse_mode="HTML",
        )

        for contact in matching:
            await send_contact_card(update.message, contact)


