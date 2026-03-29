"""
Helpers for reading normalized text input from text or transcribed voice updates.
"""
from telegram import Update
from telegram.ext import ContextTypes

INPUT_TEXT_OVERRIDE_KEY = "_input_text_override"


def get_input_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    strip: bool = False,
) -> str | None:
    """Return the effective text for the current update."""
    override = context.user_data.get(INPUT_TEXT_OVERRIDE_KEY)
    if override is not None:
        text = override
    else:
        text = update.message.text if update.message else None

    if text is None:
        return None

    return text.strip() if strip else text


def set_input_text_override(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Temporarily override message text for the current flow."""
    context.user_data[INPUT_TEXT_OVERRIDE_KEY] = text


def clear_input_text_override(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the temporary text override."""
    context.user_data.pop(INPUT_TEXT_OVERRIDE_KEY, None)
