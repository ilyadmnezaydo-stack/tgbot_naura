"""
Scheduled reminder jobs.
"""
import logging
from datetime import date
from types import SimpleNamespace
from typing import Dict, List

from telegram.ext import ContextTypes

from src.bot.handlers.callbacks import send_contact_card_to_chat
from src.bot.messages import format_birthday_badge
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository

logger = logging.getLogger(__name__)


def _group_contacts_by_user(contacts: list[SimpleNamespace]) -> Dict[int, List[SimpleNamespace]]:
    """Group a flat contact list by owner user_id."""
    grouped: Dict[int, List[SimpleNamespace]] = {}
    for contact in contacts:
        grouped.setdefault(contact.user_id, []).append(contact)
    return grouped


def _build_birthday_prefix(contact: SimpleNamespace, today: date) -> str:
    """Build a short birthday banner for a contact card."""
    birthday_text = format_birthday_badge(
        getattr(contact, "birthday_day", None),
        getattr(contact, "birthday_month", None),
        getattr(contact, "birthday_year", None),
        today=today,
    )
    if birthday_text:
        return f"🎂 <b>Сегодня день рождения</b>\n{birthday_text}"
    return "🎂 <b>Сегодня день рождения</b>"


async def morning_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Morning reminder job - runs at 11:00 MSK daily.
    Sends reminders for contacts due today.
    """
    today = date.today()
    logger.info(f"Running morning reminder job for {today}")

    client = await get_supabase()
    repo = ContactRepository(client)
    due_contacts = await repo.get_due_today(today)
    birthday_contacts = await repo.get_birthdays_for_date(today)

    if not due_contacts and not birthday_contacts:
        logger.info("No contacts due today and no birthdays today")
        return

    due_by_user = _group_contacts_by_user(due_contacts)
    birthdays_by_user = _group_contacts_by_user(birthday_contacts)
    all_user_ids = sorted(set(due_by_user) | set(birthdays_by_user))

    for user_id in all_user_ids:
        try:
            birthdays = birthdays_by_user.get(user_id, [])
            due_today = due_by_user.get(user_id, [])
            birthday_ids = {contact.id for contact in birthdays}
            regular_due = [contact for contact in due_today if contact.id not in birthday_ids]

            if birthdays:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🎂 <b>Сегодня есть день рождения</b>\nМожно поздравить:",
                    parse_mode="HTML",
                )
                for contact in birthdays:
                    await send_contact_card_to_chat(
                        context.bot,
                        user_id,
                        contact,
                        prefix=_build_birthday_prefix(contact, today),
                    )

            if regular_due:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="☀️ <b>Доброе утро!</b> Сегодня стоит написать:",
                    parse_mode="HTML",
                )
                for contact in regular_due:
                    await send_contact_card_to_chat(context.bot, user_id, contact)

            logger.info(
                "Sent morning notifications to user %s: birthdays=%s regular_due=%s",
                user_id,
                len(birthdays),
                len(regular_due),
            )

        except Exception as e:
            logger.error(f"Failed to send morning reminder to {user_id}: {e}")


async def evening_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Evening reminder job - runs at 19:00 MSK daily.
    Reminds about contacts that were due today but not yet contacted.
    """
    today = date.today()
    logger.info(f"Running evening reminder job for {today}")

    client = await get_supabase()
    repo = ContactRepository(client)
    overdue = await repo.get_overdue_not_contacted(today)

    if not overdue:
        logger.info("No overdue contacts")
        return

    user_contacts = _group_contacts_by_user(overdue)

    # Send reminders to each user
    for user_id, contacts in user_contacts.items():
        try:
            # Send header
            await context.bot.send_message(
                chat_id=user_id,
                text="🌙 <b>Вечернее напоминание!</b>\nТы ещё не отметил, что связался с:",
                parse_mode="HTML",
            )

            # Send each contact as a card with buttons
            for c in contacts:
                await send_contact_card_to_chat(context.bot, user_id, c)

            logger.info(f"Sent evening reminder to user {user_id} for {len(contacts)} contacts")

        except Exception as e:
            logger.error(f"Failed to send evening reminder to {user_id}: {e}")


async def weekly_stats_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Weekly statistics job - runs on Sunday at 10:00 MSK.
    Sends weekly summary to users.
    """
    logger.info("Running weekly stats job")

    client = await get_supabase()
    repo = ContactRepository(client)

    # Get all unique user IDs from contacts
    user_ids = await repo.get_all_unique_user_ids()

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
            message_parts = ["📊 <b>Твоя неделя в цифрах:</b>\n"]
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
                parse_mode="HTML",
            )
            logger.info(f"Sent weekly stats to user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send weekly stats to {user_id}: {e}")
