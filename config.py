import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "bot.db"))
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
    STEAM_REQUEST_DELAY: float = float(os.getenv("STEAM_REQUEST_DELAY", "3"))
    PROXY_URL: str | None = os.getenv("PROXY_URL")

    # Steam параметры по умолчанию
    DEFAULT_APPID: int = 730  # CS2
    DEFAULT_CONTEXTID: int = 2

    # Лимиты
    MAX_ITEMS_PER_NOTIFICATION: int = 10
    MAX_RETRY_ATTEMPTS: int = 3

    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ BOT_TOKEN не указан в .env файле!")
        # Создаём директорию для БД если нет
        db_path = Path(cls.DATABASE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)


config = Config