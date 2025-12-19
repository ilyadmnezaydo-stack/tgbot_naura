"""
Frequency and date parsing utilities.
Parses Russian text for reminder frequencies and dates.
"""
import re
from datetime import date, timedelta
from typing import Optional, Tuple

# Mapping frequency type to days
FREQUENCY_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}

# Russian weekday names to weekday numbers (0 = Monday)
WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6,
}


def parse_frequency(text: str) -> Optional[Tuple[str, Optional[int]]]:
    """
    Parse frequency from Russian text.

    Returns:
        Tuple of (frequency_type, custom_days) or None if not recognized.

    Examples:
        "каждый день" -> ("daily", None)
        "раз в неделю" -> ("weekly", None)
        "раз в 2 недели" -> ("biweekly", None)
        "раз в месяц" -> ("monthly", None)
        "через 10 дней" -> ("custom", 10)
        "каждые 5 дней" -> ("custom", 5)
        "один раз" -> ("one_time", None)
        "разово" -> ("one_time", None)
    """
    text = text.lower().strip()

    # One-time reminders
    if any(word in text for word in ["один раз", "разово", "однократно"]):
        return ("one_time", None)

    # Daily
    if any(word in text for word in ["каждый день", "ежедневно"]):
        return ("daily", None)

    # Weekly
    if any(word in text for word in ["каждую неделю", "еженедельно", "раз в неделю"]):
        return ("weekly", None)

    # Biweekly
    if any(
        word in text
        for word in ["раз в две недели", "каждые две недели", "раз в 2 недели", "каждые 2 недели"]
    ):
        return ("biweekly", None)

    # Monthly
    if any(word in text for word in ["каждый месяц", "ежемесячно", "раз в месяц"]):
        return ("monthly", None)

    # Custom interval: "через X дней" or "каждые X дней"
    custom_match = re.search(
        r"(?:через|каждые?)\s+(\d+)\s+(?:дней|дня|день)", text
    )
    if custom_match:
        days = int(custom_match.group(1))
        return ("custom", days)

    return None


def parse_date(text: str) -> Optional[date]:
    """
    Parse date from Russian text or date format.

    Supports:
        - "завтра", "послезавтра"
        - "через X дней"
        - "dd.mm" or "dd.mm.yyyy" or "dd/mm" or "dd/mm/yyyy"
        - Weekday names (понедельник, вторник, etc.)

    Returns:
        date object or None if not recognized.
    """
    text = text.lower().strip()
    today = date.today()

    # Relative dates
    if "сегодня" in text:
        return today

    if "завтра" in text:
        return today + timedelta(days=1)

    if "послезавтра" in text:
        return today + timedelta(days=2)

    # "через X дней"
    days_match = re.search(r"через\s+(\d+)\s+(?:дней|дня|день)", text)
    if days_match:
        return today + timedelta(days=int(days_match.group(1)))

    # Weekday names
    for weekday_name, weekday_num in WEEKDAYS.items():
        if weekday_name in text:
            days_ahead = weekday_num - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            return today + timedelta(days=days_ahead)

    # Date formats: dd.mm or dd.mm.yyyy or dd/mm or dd/mm/yyyy
    date_match = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year_str = date_match.group(3)

        if year_str:
            year = int(year_str)
            if year < 100:
                year += 2000
        else:
            year = today.year

        try:
            result = date(year, month, day)
            # If date is in past for current year and year wasn't specified,
            # assume next year
            if result < today and not year_str:
                result = date(year + 1, month, day)
            return result
        except ValueError:
            return None

    return None


def calculate_next_reminder(
    frequency: str,
    custom_days: Optional[int] = None,
    from_date: Optional[date] = None,
) -> date:
    """
    Calculate the next reminder date based on frequency.

    Args:
        frequency: One of "daily", "weekly", "biweekly", "monthly", "custom"
        custom_days: Number of days for custom frequency
        from_date: Base date (defaults to today)

    Returns:
        Next reminder date
    """
    base_date = from_date or date.today()

    if frequency == "custom" and custom_days:
        return base_date + timedelta(days=custom_days)

    days = FREQUENCY_DAYS.get(frequency, 14)  # Default biweekly
    return base_date + timedelta(days=days)


def format_frequency(frequency: str, custom_days: Optional[int] = None) -> str:
    """
    Format frequency for display in Russian.
    """
    freq_names = {
        "daily": "каждый день",
        "weekly": "раз в неделю",
        "biweekly": "раз в 2 недели",
        "monthly": "раз в месяц",
        "one_time": "однократно",
    }

    if frequency == "custom" and custom_days:
        if custom_days == 1:
            return "каждый день"
        elif custom_days % 7 == 0:
            weeks = custom_days // 7
            if weeks == 1:
                return "раз в неделю"
            elif weeks == 2:
                return "раз в 2 недели"
            else:
                return f"каждые {weeks} недель"
        else:
            return f"каждые {custom_days} дней"

    return freq_names.get(frequency, frequency)
