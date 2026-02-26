import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import config
from database import db
from steam_api import SteamInventoryFetcher, SteamAPIError
from telegram_bot import InventoryBot


class InventoryChecker:
    def __init__(self, bot_wrapper: InventoryBot):
        self.bot_wrapper = bot_wrapper
        self.scheduler = AsyncIOScheduler()
        self.fetcher = None

    async def start(self):
        self.fetcher = SteamInventoryFetcher(proxy=config.PROXY_URL)
        await self.fetcher.__aenter__()

        self.scheduler.add_job(
            self._check_all,
            'interval',
            minutes=config.CHECK_INTERVAL_MINUTES,
            id='inventory_check',
            replace_existing=True
        )
        self.scheduler.start()
        print(f"✅ Планировщик запущен (интервал: {config.CHECK_INTERVAL_MINUTES} мин)")

    async def stop(self):
        self.scheduler.shutdown()
        if self.fetcher:
            await self.fetcher.__aexit__(None, None, None)

    async def _check_all(self):
        """Проверяет все отслеживаемые инвентари"""
        print("🔄 Запуск проверки инвентарей...")

        # Группируем по SteamID+appid для избежания дубликатов запросов
        tracked = await db.get_tracked_users()
        targets = {(steamid64, appid) for _, steamid64, appid, _ in tracked}

        for steamid64, appid in targets:
            try:
                await asyncio.sleep(config.STEAM_REQUEST_DELAY)  # соблюдаем лимиты

                new_items = await self.fetcher.get_new_items(steamid64, appid)

                if new_items:
                    # Находим всех TG-пользователей, отслеживающих этот инвентарь
                    users = await db.get_tracked_users(steamid64=steamid64)
                    for tg_id, _, _, _ in users:
                        try:
                            await self.bot_wrapper.send_new_items_notification(
                                tg_id, steamid64, appid, new_items
                            )
                        except Exception as e:
                            print(f"❌ Ошибка отправки уведомления пользователю {tg_id}: {e}")

            except SteamAPIError as e:
                print(f"⚠️ SteamAPI ошибка для {steamid64}/{appid}: {e}")
            except Exception as e:
                print(f"❌ Ошибка проверки {steamid64}/{appid}: {e}")

        print("✅ Проверка завершена")