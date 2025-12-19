"""
Scheduled reminder jobs.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List

from telegram.ext import ContextTypes

from src.config import settings
from src.db.engine import get_session
from src.db.models import Contact
from src.db.repositories.contacts import ContactRepository

logger = logging.getLogger(__name__)


async def morning_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Morning reminder job - runs at 11:00 MSK daily.
    Sends reminders for contacts due today.
    """
    today = date.today()
    logger.info(f"Running morning reminder job for {today}")

    async with get_session() as session:
        repo = ContactRepository(session)
        due_contacts = await repo.get_due_today(today)

        if not due_contacts:
            logger.info("No contacts due today")
            return

        # Group contacts by user_id
        user_contacts: Dict[int, List[Contact]] = {}
        for contact in due_contacts:
            if contact.user_id not in user_contacts:
                user_contacts[contact.user_id] = []
            user_contacts[contact.user_id].append(contact)

        # Send reminders to each user
        for user_id, contacts in user_contacts.items():
            message_parts = ["☀️ *Доброе утро!* Сегодня стоит написать:\n"]

            for c in contacts:
                desc = ""
                if c.description:
                    desc = f" — {c.description[:30]}..." if len(c.description) > 30 else f" — {c.description}"
                message_parts.append(f"• @{c.username}{desc}")

            message_parts.append("\n💡 Отметить: `я написал @username`")

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="\n".join(message_parts),
                    parse_mode="Markdown",
                )
                logger.info(f"Sent morning reminder to user {user_id} for {len(contacts)} contacts")

                # Log reminder sent for each contact
                for c in contacts:
                    await repo.add_history(c.id, "reminder_sent", "Morning reminder")

            except Exception as e:
                logger.error(f"Failed to send morning reminder to {user_id}: {e}")


async def evening_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Evening reminder job - runs at 19:00 MSK daily.
    Reminds about contacts that were due today but not yet contacted.
    """
    today = date.today()
    logger.info(f"Running evening reminder job for {today}")

    async with get_session() as session:
        repo = ContactRepository(session)
        overdue = await repo.get_overdue_not_contacted(today)

        if not overdue:
            logger.info("No overdue contacts")
            return

        # Group contacts by user_id
        user_contacts: Dict[int, List[Contact]] = {}
        for contact in overdue:
            if contact.user_id not in user_contacts:
                user_contacts[contact.user_id] = []
            user_contacts[contact.user_id].append(contact)

        # Send reminders to each user
        for user_id, contacts in user_contacts.items():
            message_parts = ["🌙 *Вечернее напоминание!*\n"]
            message_parts.append("Ты ещё не отметил, что связался с:\n")

            for c in contacts:
                message_parts.append(f"• @{c.username}")

            message_parts.append("\n✅ Если написал: `я написал @username`")
            message_parts.append("⏸️ Поставить на паузу: `pause @username`")

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="\n".join(message_parts),
                    parse_mode="Markdown",
                )
                logger.info(f"Sent evening reminder to user {user_id} for {len(contacts)} contacts")

            except Exception as e:
                logger.error(f"Failed to send evening reminder to {user_id}: {e}")


async def weekly_stats_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Weekly statistics job - runs on Sunday at 10:00 MSK.
    Sends weekly summary to users.
    """
    logger.info("Running weekly stats job")

    async with get_session() as session:
        repo = ContactRepository(session)

        # Get all unique user IDs from contacts
        from sqlalchemy import select, distinct
        from src.db.models import Contact

        result = await session.execute(select(distinct(Contact.user_id)))
        user_ids = [row[0] for row in result.fetchall()]

        for user_id in user_ids:
            try:
                # Get stats
                contacts = await repo.get_all_for_user(user_id)
                total_contacts = len(contacts)
                active_contacts = len([c for c in contacts if c.status == "active"])
                paused_contacts = len([c for c in contacts if c.status == "paused"])

                # Contacted this week
                contacted_count = await repo.get_contacts_contacted_this_week(user_id)

                # Build message
                message_parts = ["📊 *Твоя неделя в цифрах:*\n"]
                message_parts.append(f"👥 Всего контактов: {total_contacts}")
                message_parts.append(f"✅ Активных: {active_contacts}")
                if paused_contacts:
                    message_parts.append(f"⏸️ На паузе: {paused_contacts}")
                message_parts.append(f"\n📨 Связался на этой неделе: {contacted_count}")

                # Motivation
                if contacted_count == 0:
                    message_parts.append("\n💡 На этой неделе ещё не было контактов. Самое время кому-то написать!")
                elif contacted_count >= active_contacts and active_contacts > 0:
                    message_parts.append("\n🎉 Отлично! Ты связался со всеми активными контактами!")
                else:
                    message_parts.append("\n👍 Хороший прогресс! Продолжай поддерживать связи.")

                await context.bot.send_message(
                    chat_id=user_id,
                    text="\n".join(message_parts),
                    parse_mode="Markdown",
                )
                logger.info(f"Sent weekly stats to user {user_id}")

            except Exception as e:
                logger.error(f"Failed to send weekly stats to {user_id}: {e}")
