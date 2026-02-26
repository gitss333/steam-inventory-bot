import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import config
from database import db
from telegram_bot import InventoryBot
from scheduler import InventoryChecker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("main")


async def main():
    # Валидация конфига
    config.validate()

    # Инициализация
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Подключение к БД
    await db.connect()
    logger.info("✅ Подключено к базе данных")

    # Бот
    bot_wrapper = InventoryBot(bot, dp)

    # Планировщик
    checker = InventoryChecker(bot_wrapper)

    # Graceful shutdown
    async def on_shutdown():
        logger.info("🔄 Завершение работы...")
        await checker.stop()
        await db.close()
        await bot.session.close()
        logger.info("👋 Работа завершена")

    dp.shutdown.register(on_shutdown)

    # Запуск
    await checker.start()

    logger.info("🤖 Бот запущен! Polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Прервано пользователем")
    except Exception as e:
        logging.exception(f"❌ Критическая ошибка: {e}")