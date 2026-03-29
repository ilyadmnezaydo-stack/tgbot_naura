"""
Owner-only analytics dashboard handlers.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, datetime, timedelta
from html import escape

import pytz
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ContextTypes

from src.bot.keyboards import (
    get_main_reply_keyboard,
    get_owner_dashboard_keyboard,
    is_owner_user,
)
from src.bot.messages import format_owner_dashboard_access_denied
from src.config import settings
from src.db.engine import get_supabase
from src.db.repositories.contacts import ContactRepository
from src.db.repositories.users import UserRepository
from src.services.analytics_service import (
    AnalyticsEvent,
    ButtonUsageStat,
    get_button_click_stats,
    get_user_last_seen_map,
    list_analytics_events,
)
from src.services.contact_notes_service import ContactNoteEntry, list_contact_notes
from src.services.payment_support_service import DonationPayment, list_donation_payments
from src.services.support_service import SupportTicket, list_support_tickets


DASHBOARD_SECTION_LABELS = {
    "overview": "Сводка",
    "users": "Пользователи",
    "contacts": "Контакты",
    "buttons": "Кнопки",
    "notes": "Заметки",
    "support": "Поддержка",
    "donations": "Донаты",
}
DASHBOARD_PERIOD_LABELS = {
    "day": "день",
    "week": "неделя",
    "month": "месяц",
    "all": "всё время",
}
DEFAULT_DASHBOARD_SECTION = "overview"
DEFAULT_DASHBOARD_PERIOD = "week"


def _is_owner(user_id: int) -> bool:
    """Return whether the current user is allowed to view owner analytics."""
    return is_owner_user(user_id)


def _timezone():
    return pytz.timezone(settings.TIMEZONE)


def _now() -> datetime:
    return datetime.now(_timezone())


def _normalize_section(value: str | None) -> str:
    return value if value in DASHBOARD_SECTION_LABELS else DEFAULT_DASHBOARD_SECTION


def _normalize_period(value: str | None) -> str:
    return value if value in DASHBOARD_PERIOD_LABELS else DEFAULT_DASHBOARD_PERIOD


def _to_local_datetime(value: datetime | None, tz) -> datetime | None:
    if not value:
        return None
    if value.tzinfo:
        return value.astimezone(tz)
    return tz.localize(value)


def _datetime_in_period(value: datetime | None, period: str, now: datetime) -> bool:
    if value is None:
        return False

    dt = _to_local_datetime(value, now.tzinfo)
    if dt is None:
        return False

    if period == "all":
        return True
    if period == "day":
        return dt.date() == now.date()
    if period == "week":
        return dt >= now - timedelta(days=7)
    if period == "month":
        return dt >= now - timedelta(days=30)
    return False


def _date_in_period(value: date | None, period: str, now: datetime) -> bool:
    if value is None:
        return False

    today = now.date()
    if period == "all":
        return True
    if period == "day":
        return value == today
    if period == "week":
        return value >= today - timedelta(days=7)
    if period == "month":
        return value >= today - timedelta(days=30)
    return False


def _period_label(period: str) -> str:
    return DASHBOARD_PERIOD_LABELS.get(period, DASHBOARD_PERIOD_LABELS[DEFAULT_DASHBOARD_PERIOD])


def _safe_pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "0%"
    return f"{(part / whole) * 100:.0f}%"


def _avg(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _format_datetime(value: datetime | None) -> str:
    if not value:
        return "—"
    local_dt = _to_local_datetime(value, _timezone())
    return local_dt.strftime("%d.%m.%Y %H:%M") if local_dt else "—"


def _format_duration(delta: timedelta | None) -> str:
    if not delta:
        return "—"
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "< 1 мин"

    total_minutes = total_seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    days, hours = divmod(hours, 24)

    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def _format_user_label(user) -> str:
    if not user:
        return "Неизвестный пользователь"
    if getattr(user, "username", None):
        return f"@{escape(user.username)}"
    if getattr(user, "first_name", None):
        return f"{escape(user.first_name)} <code>{user.id}</code>"
    return f"<code>{user.id}</code>"


def _format_contact_label(contact) -> str:
    if not contact:
        return "Удалённый контакт"
    if getattr(contact, "display_name", None):
        display_name = contact.display_name.strip()
        if display_name and display_name.lower() != (contact.username or "").strip().lower():
            return f"{escape(display_name)} (@{escape(contact.username)})"
    if getattr(contact, "username", None):
        return f"@{escape(contact.username)}"
    return f"<code>{contact.id}</code>"


def _normalize_button_label(label: str) -> str:
    return {
        "⭐ Поддержка": "⭐ Поддержать",
        "Контакт: Добавить записку": "Контакт: Добавить заметку",
    }.get(label, label)


def _is_dashboard_button_key(button_key: str | None) -> bool:
    if not button_key:
        return False
    return button_key.startswith("reply:owner_dashboard") or button_key.startswith(
        "callback:owner_dashboard"
    )


def _build_button_stats_from_events(events: list[AnalyticsEvent]) -> list[ButtonUsageStat]:
    grouped: dict[str, ButtonUsageStat] = {}
    for event in events:
        if (
            event.event_type != "button_click"
            or not event.button_key
            or _is_dashboard_button_key(event.button_key)
        ):
            continue

        stat = grouped.get(event.button_key)
        if not stat:
            grouped[event.button_key] = ButtonUsageStat(
                key=event.button_key,
                label=event.label or event.button_key,
                count=1,
                last_clicked_at=event.occurred_at,
            )
            continue

        stat.count += 1
        stat.label = event.label or stat.label
        if not stat.last_clicked_at or event.occurred_at > stat.last_clicked_at:
            stat.last_clicked_at = event.occurred_at

    stats = list(grouped.values())
    stats.sort(key=lambda item: (-item.count, item.label.lower()))
    return stats


def _split_button_stats(
    stats: list[ButtonUsageStat],
) -> tuple[list[ButtonUsageStat], list[ButtonUsageStat]]:
    reply_stats = [stat for stat in stats if stat.key.startswith("reply:")]
    inline_stats = [stat for stat in stats if stat.key.startswith("callback:")]
    return reply_stats, inline_stats


def _format_ranked_stats(
    stats: list[ButtonUsageStat],
    *,
    limit: int = 5,
    empty_text: str,
) -> list[str]:
    if not stats:
        return [empty_text]
    return [
        f"{index}. {escape(_normalize_button_label(stat.label))} — <b>{stat.count}</b>"
        for index, stat in enumerate(stats[:limit], start=1)
    ]


def _format_ranked_counter(
    counter: Counter,
    *,
    limit: int = 5,
    render_label,
    empty_text: str,
) -> list[str]:
    if not counter:
        return [empty_text]

    lines: list[str] = []
    for index, (key, count) in enumerate(counter.most_common(limit), start=1):
        lines.append(f"{index}. {render_label(key)} — <b>{count}</b>")
    return lines


def _parse_dashboard_callback(data: str | None) -> tuple[str, str]:
    if data == "owner_dashboard:refresh":
        return DEFAULT_DASHBOARD_SECTION, DEFAULT_DASHBOARD_PERIOD

    parts = (data or "").split(":")
    if len(parts) >= 4 and parts[1] == "refresh":
        return _normalize_section(parts[2]), _normalize_period(parts[3])
    if len(parts) >= 3:
        return _normalize_section(parts[1]), _normalize_period(parts[2])
    return DEFAULT_DASHBOARD_SECTION, DEFAULT_DASHBOARD_PERIOD


async def _load_dashboard_dataset() -> dict:
    client = await get_supabase()
    user_repo = UserRepository(client)
    contact_repo = ContactRepository(client)

    (
        users,
        contacts,
        notes,
        tickets,
        donations,
        events,
        button_stats,
        user_last_seen,
    ) = await asyncio.gather(
        user_repo.get_all(),
        contact_repo.get_all(),
        list_contact_notes(),
        list_support_tickets(),
        list_donation_payments(),
        list_analytics_events(),
        get_button_click_stats(),
        get_user_last_seen_map(),
    )

    return {
        "users": users,
        "contacts": contacts,
        "notes": notes,
        "tickets": tickets,
        "donations": donations,
        "events": events,
        "button_stats": button_stats,
        "user_last_seen": user_last_seen,
    }


def _build_overview_section(context: dict) -> list[str]:
    users = context["users"]
    contacts = context["contacts"]
    notes_in_period = context["notes_in_period"]
    tickets_in_period = context["tickets_in_period"]
    donations_in_period = context["donations_in_period"]
    active_user_ids_period = context["active_user_ids_period"]
    button_stats_period = context["button_stats_period"]
    queue_now = context["queue_now"]
    overdue_now = context["overdue_now"]
    contacts_by_status = context["contacts_by_status"]
    new_users_period = context["new_users_period"]
    new_contacts_period = context["new_contacts_period"]
    contacted_period = context["contacted_period"]
    ai_resolved_period = context["ai_resolved_period"]
    escalated_period = context["escalated_period"]
    donation_stars_period = context["donation_stars_period"]
    top_button_stat = button_stats_period[0] if button_stats_period else None

    return [
        "📊 <b>Админ-дашборд</b>",
        f"Раздел: <b>{DASHBOARD_SECTION_LABELS['overview']}</b> • Период: <b>{_period_label(context['period'])}</b>",
        "",
        "<b>Пульс бота</b>",
        f"• Пользователи: <b>{len(users)}</b> всего, <b>{len(active_user_ids_period)}</b> активных, <b>{new_users_period}</b> новых",
        f"• Контакты: <b>{len(contacts)}</b> всего, <b>{new_contacts_period}</b> новых, <b>{contacted_period}</b> отмечено",
        f"• Заметки: <b>{len(notes_in_period)}</b> за период",
        f"• Поддержка: <b>{len(tickets_in_period)}</b> вопросов, AI закрыл <b>{ai_resolved_period}</b>, человеку ушло <b>{escalated_period}</b>",
        f"• Донаты: <b>{len(donations_in_period)}</b> платежей на <b>{donation_stars_period}</b> Stars",
        f"• Нажатия: <b>{sum(stat.count for stat in button_stats_period)}</b> кликов по кнопкам",
        "",
        "<b>Текущее состояние</b>",
        f"• Активные напоминания: <b>{contacts_by_status.get('active', 0)}</b>",
        f"• Разовые напоминания: <b>{contacts_by_status.get('one_time', 0)}</b>",
        f"• На паузе: <b>{contacts_by_status.get('paused', 0)}</b>",
        f"• Просроченные контакты: <b>{overdue_now}</b>",
        f"• Очередь поддержки сейчас: <b>{queue_now}</b>",
        "",
        "<b>Быстрые акценты</b>",
        (
            f"• Самая кликабельная кнопка: <b>{escape(_normalize_button_label(top_button_stat.label))}</b> ({top_button_stat.count})"
            if top_button_stat
            else "• Детальная история кликов только начала собираться."
        ),
        f"• Покрытие заметками: <b>{_safe_pct(context['contacts_with_notes'], max(len(contacts), 1))}</b>",
        f"• Пользователи с контактами: <b>{context['users_with_contacts']}</b> из <b>{len(users)}</b>",
        "",
        f"Обновлено: {_format_datetime(context['now'])}",
    ]


def _build_users_section(context: dict) -> list[str]:
    users = context["users"]
    total_users = len(users)
    active_users = len(context["active_user_ids_period"])
    users_with_contacts = context["users_with_contacts"]
    users_without_contacts = max(total_users - users_with_contacts, 0)
    never_seen_users = max(total_users - len(context["user_last_seen"]), 0)
    quiet_30d = context["quiet_users_30d"]
    contact_counts_by_user = context["contact_counts_by_user"]
    per_user_counts = list(contact_counts_by_user.values())
    avg_contacts_all = (sum(per_user_counts) / total_users) if total_users else 0
    avg_contacts_active = sum(per_user_counts) / len(per_user_counts) if per_user_counts else 0

    lines = [
        "👤 <b>Пользователи</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Зарегистрировано: <b>{total_users}</b>",
        f"• Активных за период: <b>{active_users}</b> ({_safe_pct(active_users, max(total_users, 1))})",
        f"• Новых за период: <b>{context['new_users_period']}</b>",
        f"• С хотя бы 1 контактом: <b>{users_with_contacts}</b>",
        f"• Пока без контактов: <b>{users_without_contacts}</b>",
        f"• Не видно в аналитике: <b>{never_seen_users}</b>",
        f"• Тихие 30+ дней: <b>{quiet_30d}</b>",
        f"• Среднее контактов на пользователя: <b>{avg_contacts_all:.1f}</b>",
        f"• Среднее среди тех, кто ведёт базу: <b>{avg_contacts_active:.1f}</b>",
        "",
        "<b>Топ по числу контактов</b>",
    ]
    lines.extend(
        _format_ranked_counter(
            contact_counts_by_user,
            render_label=lambda user_id: _format_user_label(context["users_by_id"].get(user_id)),
            empty_text="Пока ни у кого нет сохранённых контактов.",
        )
    )

    lines.extend(["", "<b>Топ по активности в боте</b>"])
    lines.extend(
        _format_ranked_counter(
            context["activity_counts_period"],
            render_label=lambda user_id: _format_user_label(context["users_by_id"].get(user_id)),
            empty_text="Для выбранного периода ещё нет событий активности.",
        )
    )
    return lines


def _build_contacts_section(context: dict) -> list[str]:
    contacts = context["contacts"]
    total_contacts = len(contacts)
    contacts_by_status = context["contacts_by_status"]
    lines = [
        "👥 <b>Контакты</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Всего контактов: <b>{total_contacts}</b>",
        f"• Новых за период: <b>{context['new_contacts_period']}</b>",
        f"• Отмечено общения за период: <b>{context['contacted_period']}</b>",
        f"• Активных: <b>{contacts_by_status.get('active', 0)}</b>",
        f"• Разовых: <b>{contacts_by_status.get('one_time', 0)}</b>",
        f"• На паузе: <b>{contacts_by_status.get('paused', 0)}</b>",
        f"• Никогда не отмечались: <b>{context['never_contacted_count']}</b>",
        f"• С заметками: <b>{context['contacts_with_notes']}</b> ({_safe_pct(context['contacts_with_notes'], max(total_contacts, 1))})",
        f"• Просроченных сейчас: <b>{context['overdue_now']}</b>",
        f"• К контакту сегодня: <b>{context['due_today']}</b>",
        f"• К контакту за 7 дней: <b>{context['due_next_7_days']}</b>",
        f"• К контакту за 30 дней: <b>{context['due_next_30_days']}</b>",
        "",
        "<b>Топ владельцев по размеру базы</b>",
    ]
    lines.extend(
        _format_ranked_counter(
            context["contact_counts_by_user"],
            render_label=lambda user_id: _format_user_label(context["users_by_id"].get(user_id)),
            empty_text="Контактов пока нет.",
        )
    )

    lines.extend(["", "<b>Популярные теги</b>"])
    lines.extend(
        _format_ranked_counter(
            context["tag_counter"],
            render_label=lambda tag: escape(tag),
            empty_text="Теги ещё не использовались.",
        )
    )
    return lines


def _build_buttons_section(context: dict) -> list[str]:
    button_stats_period = context["button_stats_period"]
    reply_stats, inline_stats = _split_button_stats(button_stats_period)
    total_clicks = sum(stat.count for stat in button_stats_period)
    unique_clickers = len(context["button_click_users_period"])
    latest_click_at = max(
        (stat.last_clicked_at for stat in button_stats_period if stat.last_clicked_at),
        default=None,
    )

    lines = [
        "🧭 <b>Кнопки и сценарии</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Всего нажатий: <b>{total_clicks}</b>",
        f"• Уникальных пользователей: <b>{unique_clickers}</b>",
        f"• Reply-клавиатура: <b>{sum(stat.count for stat in reply_stats)}</b>",
        f"• Inline-кнопки: <b>{sum(stat.count for stat in inline_stats)}</b>",
        f"• Последний клик: <b>{_format_datetime(latest_click_at)}</b>",
        f"• Всего известных кнопок all-time: <b>{len(context['button_stats_all_time'])}</b>",
        "",
        "<b>Топ кнопок</b>",
    ]
    lines.extend(
        _format_ranked_stats(
            button_stats_period,
            empty_text="Для этого периода детальная история кликов ещё не накопилась.",
        )
    )

    lines.extend(["", "<b>Топ reply-кнопок</b>"])
    lines.extend(
        _format_ranked_stats(
            reply_stats,
            empty_text="Reply-кнопки в выбранный период не нажимали.",
        )
    )

    lines.extend(["", "<b>Топ inline-кнопок</b>"])
    lines.extend(
        _format_ranked_stats(
            inline_stats,
            empty_text="Inline-кнопки в выбранный период не нажимали.",
        )
    )
    return lines


def _build_notes_section(context: dict) -> list[str]:
    notes = context["notes"]
    notes_in_period = context["notes_in_period"]
    note_lengths_period = [len(note.text.strip()) for note in notes_in_period if note.text.strip()]
    note_lengths_all = [len(note.text.strip()) for note in notes if note.text.strip()]
    recent_note = max((note.created_at for note in notes), default=None)
    top_note_counter = context["note_counts_period"] or context["note_counts_all_time"]

    lines = [
        "📝 <b>Заметки</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Всего заметок: <b>{len(notes)}</b>",
        f"• Новых за период: <b>{len(notes_in_period)}</b>",
        f"• Контактов с хотя бы 1 заметкой: <b>{context['contacts_with_notes']}</b>",
        f"• Покрытие базы заметками: <b>{_safe_pct(context['contacts_with_notes'], max(len(context['contacts']), 1))}</b>",
        f"• Средняя длина за период: <b>{_avg(note_lengths_period):.0f}</b> симв.",
        f"• Средняя длина all-time: <b>{_avg(note_lengths_all):.0f}</b> симв.",
        f"• Длинных заметок 120+ симв.: <b>{sum(1 for length in note_lengths_all if length >= 120)}</b>",
        f"• Последняя заметка: <b>{_format_datetime(recent_note)}</b>",
        "",
        "<b>Контакты, о которых пишут чаще</b>",
    ]
    lines.extend(
        _format_ranked_counter(
            top_note_counter,
            render_label=lambda contact_id: _format_contact_label(context["contacts_by_id"].get(contact_id)),
            empty_text="Заметок пока нет.",
        )
    )
    return lines


def _build_support_section(context: dict) -> list[str]:
    tickets = context["tickets"]
    tickets_in_period = context["tickets_in_period"]
    response_times = context["response_times_period"]
    human_answered = context["human_answered_period"]
    helped_period = context["helped_period"]
    escalated_period = context["escalated_period"]

    average_response = (
        sum(response_times, timedelta()) / len(response_times) if response_times else None
    )

    lines = [
        "💬 <b>Поддержка</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Всего тикетов: <b>{len(tickets)}</b>",
        f"• Новых за период: <b>{len(tickets_in_period)}</b>",
        f"• AI закрыл за период: <b>{context['ai_resolved_period']}</b>",
        f"• Эскалировано человеку: <b>{escalated_period}</b>",
        f"• Ответов админа за период: <b>{human_answered}</b>",
        f"• Подтверждений «помогло»: <b>{helped_period}</b>",
        f"• Уточняющих вопросов: <b>{context['followups_period']}</b>",
        f"• Игнорировано: <b>{context['ignored_period']}</b>",
        f"• Сейчас в очереди: <b>{context['queue_now']}</b>",
        f"• Пользователей в поддержке за период: <b>{context['support_users_period']}</b>",
        f"• Среднее время ответа: <b>{_format_duration(average_response)}</b>",
        (
            f"• Конверсия ответа по эскалациям: <b>{_safe_pct(human_answered, max(escalated_period, 1))}</b>"
            if escalated_period
            else "• Эскалаций в выбранный период не было."
        ),
        "",
        "<b>Текущий статус очереди</b>",
    ]
    lines.extend(
        _format_ranked_counter(
            context["queue_status_counter"],
            render_label=lambda status: escape(context["support_status_labels"].get(status, status)),
            empty_text="Открытых тикетов сейчас нет.",
        )
    )
    return lines


def _build_donations_section(context: dict) -> list[str]:
    donations = context["donations"]
    donations_in_period = context["donations_in_period"]
    total_stars = sum(payment.amount for payment in donations)
    period_stars = sum(payment.amount for payment in donations_in_period)
    period_avg = _avg([payment.amount for payment in donations_in_period])
    biggest_all_time = max((payment.amount for payment in donations), default=0)
    biggest_period = max((payment.amount for payment in donations_in_period), default=0)
    repeat_donors = sum(1 for count in context["donation_counts_by_user"].values() if count > 1)
    latest_donation = max((payment.created_at for payment in donations), default=None)

    lines = [
        "⭐ <b>Донаты</b>",
        f"Период: <b>{_period_label(context['period'])}</b>",
        "",
        f"• Всего платежей: <b>{len(donations)}</b>",
        f"• Всего Stars: <b>{total_stars}</b>",
        f"• Платежей за период: <b>{len(donations_in_period)}</b>",
        f"• Stars за период: <b>{period_stars}</b>",
        f"• Уникальных доноров all-time: <b>{len(context['donation_amounts_by_user'])}</b>",
        f"• Уникальных доноров за период: <b>{context['donors_period']}</b>",
        f"• Средний чек за период: <b>{period_avg:.1f}</b> Stars",
        f"• Максимальный донат all-time: <b>{biggest_all_time}</b> Stars",
        f"• Максимальный донат за период: <b>{biggest_period}</b> Stars",
        f"• Повторных доноров: <b>{repeat_donors}</b>",
        f"• Последний донат: <b>{_format_datetime(latest_donation)}</b>",
        "",
        "<b>Топ доноров по Stars</b>",
    ]
    lines.extend(
        _format_ranked_counter(
            context["donation_amounts_by_user"],
            render_label=lambda user_id: _format_user_label(context["users_by_id"].get(user_id)),
            empty_text="Донатов пока не было.",
        )
    )
    return lines


def _build_dashboard_lines(section: str, context: dict) -> list[str]:
    if section == "users":
        return _build_users_section(context)
    if section == "contacts":
        return _build_contacts_section(context)
    if section == "buttons":
        return _build_buttons_section(context)
    if section == "notes":
        return _build_notes_section(context)
    if section == "support":
        return _build_support_section(context)
    if section == "donations":
        return _build_donations_section(context)
    return _build_overview_section(context)


async def _build_dashboard_text(section: str, period: str) -> str:
    now = _now()
    dataset = await _load_dashboard_dataset()

    users = dataset["users"]
    contacts = dataset["contacts"]
    notes: list[ContactNoteEntry] = dataset["notes"]
    tickets: list[SupportTicket] = dataset["tickets"]
    donations: list[DonationPayment] = dataset["donations"]
    events: list[AnalyticsEvent] = dataset["events"]
    button_stats_all_time: list[ButtonUsageStat] = dataset["button_stats"]
    user_last_seen: dict[int, datetime] = dataset["user_last_seen"]
    button_stats_all_time = [
        stat for stat in button_stats_all_time if not _is_dashboard_button_key(stat.key)
    ]

    users_by_id = {user.id: user for user in users}
    contacts_by_id = {str(contact.id): contact for contact in contacts}
    contact_counts_by_user = Counter(contact.user_id for contact in contacts)
    activity_counts_period = Counter(
        event.user_id for event in events if _datetime_in_period(event.occurred_at, period, now)
    )
    active_user_ids_period = {
        user_id
        for user_id, seen_at in user_last_seen.items()
        if _datetime_in_period(seen_at, period, now)
    }
    if not activity_counts_period and active_user_ids_period:
        activity_counts_period = Counter({user_id: 1 for user_id in active_user_ids_period})

    notes_in_period = [note for note in notes if _datetime_in_period(note.created_at, period, now)]
    tickets_in_period = [ticket for ticket in tickets if _datetime_in_period(ticket.created_at, period, now)]
    donations_in_period = [
        payment for payment in donations if _datetime_in_period(payment.created_at, period, now)
    ]
    new_users_period = sum(
        1 for user in users if _datetime_in_period(getattr(user, "created_at", None), period, now)
    )
    new_contacts_period = sum(
        1 for contact in contacts if _datetime_in_period(getattr(contact, "created_at", None), period, now)
    )
    contacted_period = sum(
        1
        for contact in contacts
        if _datetime_in_period(getattr(contact, "last_contacted_at", None), period, now)
    )

    contacts_by_status = Counter(getattr(contact, "status", "unknown") or "unknown" for contact in contacts)
    contacts_with_notes = len({note.contact_id for note in notes})
    never_contacted_count = sum(1 for contact in contacts if getattr(contact, "last_contacted_at", None) is None)
    due_today = 0
    due_next_7_days = 0
    due_next_30_days = 0
    overdue_now = 0
    today = now.date()

    for contact in contacts:
        status = getattr(contact, "status", None)
        next_date = getattr(contact, "next_reminder_date", None)
        last_contacted_at = getattr(contact, "last_contacted_at", None)
        if status not in {"active", "one_time"} or not next_date:
            continue

        if next_date == today:
            due_today += 1
        if today <= next_date <= today + timedelta(days=7):
            due_next_7_days += 1
        if today <= next_date <= today + timedelta(days=30):
            due_next_30_days += 1

        due_datetime = datetime.combine(next_date, datetime.min.time())
        due_datetime = now.tzinfo.localize(due_datetime)
        last_contacted_local = _to_local_datetime(last_contacted_at, now.tzinfo)
        if next_date < today and (last_contacted_local is None or last_contacted_local < due_datetime):
            overdue_now += 1

    tag_counter = Counter()
    for contact in contacts:
        for tag in getattr(contact, "tags", []) or []:
            clean_tag = (tag or "").strip()
            if clean_tag:
                tag_counter[clean_tag] += 1

    if period == "all":
        button_stats_period = button_stats_all_time
    else:
        button_stats_period = _build_button_stats_from_events(
            [event for event in events if _datetime_in_period(event.occurred_at, period, now)]
        )
        if not button_stats_period and button_stats_all_time:
            button_stats_period = [
                stat
                for stat in button_stats_all_time
                if _datetime_in_period(stat.last_clicked_at, period, now)
            ]

    button_click_users_period = set()
    for event in events:
        if event.event_type != "button_click" or _is_dashboard_button_key(event.button_key):
            continue
        if period != "all" and not _datetime_in_period(event.occurred_at, period, now):
            continue
        button_click_users_period.add(event.user_id)
    if not button_click_users_period and button_stats_period:
        button_click_users_period = set(active_user_ids_period or user_last_seen.keys())

    note_counts_all_time = Counter(note.contact_id for note in notes)
    note_counts_period = Counter(note.contact_id for note in notes_in_period)

    support_queue_statuses = {"pending_admin", "awaiting_admin_reply", "followup_requested"}
    queue_now = sum(1 for ticket in tickets if ticket.status in support_queue_statuses)
    queue_status_counter = Counter(
        ticket.status for ticket in tickets if ticket.status in support_queue_statuses
    )

    ai_resolved_period = sum(1 for ticket in tickets_in_period if ticket.status == "ai_answered")
    escalated_period = sum(1 for ticket in tickets_in_period if ticket.status != "ai_answered")
    followups_period = sum(1 for ticket in tickets_in_period if ticket.source == "followup")
    ignored_period = sum(
        1
        for ticket in tickets
        if ticket.status == "ignored" and _datetime_in_period(ticket.updated_at, period, now)
    )
    human_answered_period = sum(
        1
        for ticket in tickets
        if ticket.answered_at and _datetime_in_period(ticket.answered_at, period, now)
    )
    helped_period = sum(
        1
        for ticket in tickets
        if ticket.feedback == "helped" and _datetime_in_period(ticket.updated_at, period, now)
    )
    response_times_period = [
        ticket.answered_at - ticket.created_at
        for ticket in tickets
        if ticket.answered_at
        and ticket.answered_at >= ticket.created_at
        and _datetime_in_period(ticket.answered_at, period, now)
    ]
    support_users_period = len({ticket.user_id for ticket in tickets_in_period})

    donation_counts_by_user = Counter(payment.user_id for payment in donations)
    donation_amounts_by_user = Counter()
    for payment in donations:
        donation_amounts_by_user[payment.user_id] += payment.amount
    donors_period = len({payment.user_id for payment in donations_in_period})
    donation_stars_period = sum(payment.amount for payment in donations_in_period)

    quiet_users_30d = 0
    for user in users:
        last_seen = user_last_seen.get(user.id)
        if not last_seen or not _datetime_in_period(last_seen, "month", now):
            quiet_users_30d += 1

    support_status_labels = {
        "pending_admin": "Ждут ответа",
        "awaiting_admin_reply": "Админ печатает ответ",
        "followup_requested": "Ждут уточнение",
    }

    context = {
        "section": section,
        "period": period,
        "now": now,
        "users": users,
        "users_by_id": users_by_id,
        "contacts": contacts,
        "contacts_by_id": contacts_by_id,
        "notes": notes,
        "tickets": tickets,
        "donations": donations,
        "button_stats_all_time": button_stats_all_time,
        "button_stats_period": button_stats_period,
        "user_last_seen": user_last_seen,
        "active_user_ids_period": active_user_ids_period,
        "activity_counts_period": activity_counts_period,
        "contact_counts_by_user": contact_counts_by_user,
        "contacts_by_status": contacts_by_status,
        "contacts_with_notes": contacts_with_notes,
        "never_contacted_count": never_contacted_count,
        "new_users_period": new_users_period,
        "new_contacts_period": new_contacts_period,
        "contacted_period": contacted_period,
        "due_today": due_today,
        "due_next_7_days": due_next_7_days,
        "due_next_30_days": due_next_30_days,
        "overdue_now": overdue_now,
        "tag_counter": tag_counter,
        "notes_in_period": notes_in_period,
        "note_counts_all_time": note_counts_all_time,
        "note_counts_period": note_counts_period,
        "tickets_in_period": tickets_in_period,
        "queue_now": queue_now,
        "queue_status_counter": queue_status_counter,
        "ai_resolved_period": ai_resolved_period,
        "escalated_period": escalated_period,
        "followups_period": followups_period,
        "ignored_period": ignored_period,
        "human_answered_period": human_answered_period,
        "helped_period": helped_period,
        "response_times_period": response_times_period,
        "support_users_period": support_users_period,
        "support_status_labels": support_status_labels,
        "donations_in_period": donations_in_period,
        "donation_counts_by_user": donation_counts_by_user,
        "donation_amounts_by_user": donation_amounts_by_user,
        "donation_stars_period": donation_stars_period,
        "donors_period": donors_period,
        "button_click_users_period": button_click_users_period,
        "users_with_contacts": len(contact_counts_by_user),
        "quiet_users_30d": quiet_users_30d,
    }

    return "\n".join(_build_dashboard_lines(section, context))


async def owner_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the owner analytics dashboard via a hidden slash command."""
    user_id = update.effective_user.id

    if not _is_owner(user_id):
        await update.message.reply_text(
            format_owner_dashboard_access_denied(),
            reply_markup=get_main_reply_keyboard(user_id),
        )
        return

    section = DEFAULT_DASHBOARD_SECTION
    period = DEFAULT_DASHBOARD_PERIOD
    text = await _build_dashboard_text(section, period)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=get_owner_dashboard_keyboard(section, period),
    )


async def _safe_edit_dashboard_message(query, text: str, section: str, period: str) -> None:
    """Edit dashboard message without surfacing harmless Telegram errors to the user."""
    try:
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_owner_dashboard_keyboard(section, period),
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def refresh_owner_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh the owner analytics dashboard in-place."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if not _is_owner(user_id):
        await query.message.edit_text(format_owner_dashboard_access_denied())
        return

    section, period = _parse_dashboard_callback(query.data)
    text = await _build_dashboard_text(section, period)
    await _safe_edit_dashboard_message(query, text, section, period)


def get_owner_handlers() -> list:
    """Return hidden handlers for owner analytics dashboard."""
    return [
        CommandHandler("owner", owner_dashboard_command),
    ]
