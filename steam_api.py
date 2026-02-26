import aiohttp
import hashlib
import asyncio
from typing import Optional, List, Dict
from config import config


def item_hash(item: dict) -> str:
    """Создаёт уникальный хеш предмета"""
    return hashlib.md5(
        f"{item.get('assetid')}_{item.get('classid')}_{item.get('instanceid')}".encode()
    ).hexdigest()


def format_item_name(item: dict, descriptions: List[dict] = None) -> str:
    """Форматирует название предмета для уведомления"""
    name = item.get('classid', 'Unknown Item')
    if descriptions:
        desc = next((d for d in descriptions if str(d.get('classid')) == str(item.get('classid'))), {})
        if desc.get('market_hash_name'):
            name = desc['market_hash_name']
        elif desc.get('name'):
            name = desc['name']
    return name


class SteamAPIError(Exception):
    pass


class SteamInventoryFetcher:
    BASE_URL = "https://steamcommunity.com/inventory"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(headers=self.HEADERS)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def fetch_inventory(self, steamid64: str, appid: int,
                              contextid: int = 2, count: int = 2000) -> Dict:
        """Получает инвентарь пользователя"""
        url = f"{self.BASE_URL}/{steamid64}/{appid}/{contextid}"
        params = {"l": "english", "count": count}

        for attempt in range(config.MAX_RETRY_ATTEMPTS):
            try:
                async with self._session.get(
                        url,
                        params=params,
                        proxy=self.proxy,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    if response.status == 429:
                        wait_time = (attempt + 1) * 30
                        print(f"⚠️ Rate limit (429). Ждём {wait_time}с...")
                        await asyncio.sleep(wait_time)
                        continue

                    if response.status == 403:
                        raise SteamAPIError("Инвентарь приватный или профиль скрыт 🔒")

                    if response.status != 200:
                        raise SteamAPIError(f"HTTP {response.status}")

                    data = await response.json()

                    if data.get('success') != 1:
                        if data.get('Error') or data.get('error'):
                            raise SteamAPIError(data.get('Error') or data.get('error'))
                        # Пустой инвентарь — это ОК
                        return {"assets": [], "descriptions": []}

                    return {
                        "assets": data.get("assets", []),
                        "descriptions": data.get("descriptions", []),
                        "more_items": data.get("more_items", False)
                    }

            except asyncio.TimeoutError:
                print(f"⏰ Таймаут (попытка {attempt + 1})")
            except aiohttp.ClientError as e:
                print(f"🌐 Ошибка сети: {e}")
            except Exception as e:
                print(f"❌ Ошибка: {e}")

            if attempt < config.MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(config.STEAM_REQUEST_DELAY * (attempt + 1))

        raise SteamAPIError("Не удалось получить инвентарь после нескольких попыток")

    async def get_new_items(self, steamid64: str, appid: int,
                            contextid: int = 2) -> List[Dict]:
        """Сравнивает текущий инвентарь с сохранённым и возвращает новые предметы"""
        from database import db

        data = await self.fetch_inventory(steamid64, appid, contextid)
        current_items = data.get("assets", [])
        descriptions = data.get("descriptions", [])

        current_hashes = {item_hash(item) for item in current_items}
        known_hashes = await db.get_item_hashes(steamid64, appid)

        new_hashes = current_hashes - known_hashes

        # Сохраняем все текущие хеши
        await db.save_item_hashes(steamid64, appid, current_hashes)

        # Возвращаем только новые предметы с форматированными названиями
        return [
            {
                **item,
                "display_name": format_item_name(item, descriptions)
            }
            for item in current_items
            if item_hash(item) in new_hashes
        ]