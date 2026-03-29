"""
Main entry point for the Contact Reminder Bot.
"""
import logging
import sys

from telegram import Update

from src.bot.app import create_application
from src.db.engine import close_db, init_db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    """Initialize resources after application is built."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Clear the visible slash-command menu: navigation is handled by the reply keyboard.
    await application.bot.set_my_commands([])
    logger.info("Bot command menu cleared")


async def post_shutdown(application) -> None:
    """Cleanup resources after shutdown."""
    logger.info("Closing database connections...")
    await close_db()
    logger.info("Database connections closed")


def main() -> None:
    """Main entry point."""
    logger.info("Starting Contact Reminder Bot...")

    application = create_application()
    application.post_init = post_init
    application.post_shutdown = post_shutdown

    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
