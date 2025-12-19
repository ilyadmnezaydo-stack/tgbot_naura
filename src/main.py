"""
Main entry point for the Contact Reminder Bot.
"""
import asyncio
import logging
import sys

from telegram import BotCommand, Update

from src.bot.app import create_application
from src.db.engine import close_db, init_db

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

# Reduce noise from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    """Initialize resources after application is built"""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")

    # Register bot commands for menu
    commands = [
        BotCommand("start", "Начать работу"),
        BotCommand("menu", "Главное меню"),
        BotCommand("add", "Добавить контакт"),
        BotCommand("list", "Список контактов"),
        BotCommand("search", "Поиск контактов"),
        BotCommand("edit", "Редактировать контакт"),
        BotCommand("help", "Справка"),
        BotCommand("cancel", "Отменить операцию"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered")


async def post_shutdown(application) -> None:
    """Cleanup resources after shutdown"""
    logger.info("Closing database connections...")
    await close_db()
    logger.info("Database connections closed")


def main() -> None:
    """Main entry point"""
    logger.info("Starting Contact Reminder Bot...")

    # Create application
    application = create_application()

    # Add post-init and post-shutdown hooks
    application.post_init = post_init
    application.post_shutdown = post_shutdown

    # Run the bot
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Don't process old messages on restart
    )


if __name__ == "__main__":
    main()
