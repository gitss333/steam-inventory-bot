import re
import logging
from typing import Optional
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import config
from steam_api import SteamInventoryFetcher, SteamAPIError, item_hash
from database import db

logger = logging.getLogger(__name__)


# Парсинг SteamID64 из URL
def extract_steamid64(url: str) -> Optional[str]:
    patterns = [
        r'profiles/(\d{17})',
        r'steamid=(\d{17})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# Inline-клавиатура с играми
def get_games_keyboard() -> InlineKeyboardMarkup:
    games = [("CS2", 730), ("Dota 2", 570), ("TF2", 440)]
    keyboard = [[InlineKeyboardButton(text=name, callback_data=f"game_{appid}")]
                for name, appid in games]
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


class InventoryBot:
    def __init__(self, bot: Bot, dp: Dispatcher):
        self.bot = bot
        self.dp = dp
        self.pending_additions = {}
        self._register_handlers()

    def _register_handlers(self):
        logger.info("📝 Регистрация handler'ов...")

        # 1. Callback query (inline кнопки)
        self.dp.callback_query(F.data.startswith("game_"))(self.on_game_selected)
        self.dp.callback_query(F.data == "cancel")(self.on_cancel)

        # 2. Команды
        self.dp.message(CommandStart())(self.cmd_start)
        self.dp.message(Command("add"))(self.cmd_add)
        self.dp.message(Command("list"))(self.cmd_list)
        self.dp.message(Command("remove"))(self.cmd_remove_prompt)

        # 3. Текстовые кнопки
        self.dp.message(F.text == "➕ Добавить")(self.on_add_button)
        self.dp.message(F.text == "📋 Мои отслеживания")(self.on_my_tracks)

        # 4. ССЫЛКИ STEAM (исправлено!)
        self.dp.message(F.text.contains('steamcommunity.com'))(self.on_steam_link)

        # 5. Все остальные сообщения (отладка)
        self.dp.message(self.on_debug_message)

        logger.info("✅ Все handler'ы зарегистрированы")

    async def cmd_start(self, message: types.Message):
        logger.info(f"📩 /start от {message.from_user.id}")
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="➕ Добавить")],
            [KeyboardButton(text="📋 Мои отслеживания")]
        ], resize_keyboard=True)
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Я отслеживаю изменения в инвентарях Steam.\n\n"
            "🔹 Нажмите '➕ Добавить' и отправьте ссылку на инвентарь\n"
            "🔹 Получайте уведомления о новых предметах\n\n"
            "Команды:\n"
            "/add — добавить вручную\n"
            "/list — показать отслеживаемые\n"
            "/remove — удалить из отслеживания",
            reply_markup=kb
        )

    async def cmd_add(self, message: types.Message):
        logger.info(f"📩 /add от {message.from_user.id}")
        await message.answer(
            "🔗 Отправьте ссылку на инвентарь Steam:\n"
            "Пример: `https://steamcommunity.com/profiles/76561199109461098/inventory/`",
            parse_mode="Markdown"
        )
        self.pending_additions[message.from_user.id] = {"url": None, "game": None}

    async def on_add_button(self, message: types.Message):
        logger.info(f"📩 Кнопка '➕ Добавить' от {message.from_user.id}")
        await self.cmd_add(message)

    async def on_my_tracks(self, message: types.Message):
        logger.info(f"📩 Кнопка '📋 Мои отслеживания' от {message.from_user.id}")
        await self.cmd_list(message)

    async def on_steam_link(self, message: types.Message):
        logger.info(f"📎 ССЫЛКА ПОЛУЧЕНА: {message.text}")
        try:
            tg_id = message.from_user.id
            steamid64 = extract_steamid64(message.text)

            logger.info(f"🔍 Извлечен SteamID64: {steamid64}")

            if not steamid64:
                await message.answer(
                    "❌ Не удалось распознать SteamID.\n\n"
                    "Проверьте ссылку. Пример правильной:\n"
                    "`https://steamcommunity.com/profiles/76561199109461098/inventory/`",
                    parse_mode="Markdown"
                )
                return

            self.pending_additions[tg_id] = {
                "url": message.text,
                "steamid64": steamid64,
                "game": None
            }

            await message.answer(
                f"✅ SteamID: `{steamid64}`\n\n"
                "Для какой игры отслеживать инвентарь?",
                reply_markup=get_games_keyboard(),
                parse_mode="Markdown"
            )
            logger.info(f"✅ Отправлены кнопки выбора игры для {steamid64}")

        except Exception as e:
            logger.error(f"❌ Ошибка в on_steam_link: {e}", exc_info=True)
            await message.answer(f"❌ Произошла ошибка: {e}")

        if not steamid64:
            await message.answer("❌ Не удалось распознать SteamID. Проверьте ссылку.")
            return

        self.pending_additions[tg_id] = {"url": message.text, "steamid64": steamid64, "game": None}

        await message.answer(
            f"✅ SteamID: `{steamid64}`\n\n"
            "Для какой игры отслеживать инвентарь?",
            reply_markup=get_games_keyboard(),
            parse_mode="Markdown"
        )

    async def on_game_selected(self, callback: types.CallbackQuery):
        tg_id = callback.from_user.id
        logger.info(f"🎮 Выбрана игра: {callback.data} от {tg_id}")

        if tg_id not in self.pending_additions:
            await callback.answer("⚠️ Сессия истекла. Начните сначала.", show_alert=True)
            return

        if callback.data == "cancel":
            del self.pending_additions[tg_id]
            await callback.message.edit_text("❌ Отменено.")
            return

        appid = int(callback.data.split("_")[1])
        data = self.pending_additions[tg_id]
        steamid64 = data["steamid64"]

        success = await db.add_tracked_user(tg_id, steamid64, appid)

        if success:
            async with SteamInventoryFetcher(proxy=config.PROXY_URL) as fetcher:
                try:
                    inv_data = await fetcher.fetch_inventory(steamid64, appid)
                    hashes = {item_hash(item) for item in inv_data.get("assets", [])}
                    await db.save_item_hashes(steamid64, appid, hashes)
                    logger.info(f"✅ Инициализирован снапшот для {steamid64}/{appid}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось инициализировать снапшот: {e}")

            game_name = next((n for n, a in [("CS2", 730), ("Dota 2", 570), ("TF2", 440)] if a == appid), str(appid))
            await callback.message.edit_text(
                f"✅ Начал отслеживать инвентарь {steamid64}\n"
                f"🎮 Игра: {game_name}\n\n"
                "Уведомления будут приходить при появлении новых предметов! 🎁"
            )
        else:
            await callback.message.edit_text("❌ Уже отслеживается или ошибка БД.")

        del self.pending_additions[tg_id]
        await callback.answer()

    async def on_cancel(self, callback: types.CallbackQuery):
        tg_id = callback.from_user.id
        if tg_id in self.pending_additions:
            del self.pending_additions[tg_id]
        await callback.message.edit_text("❌ Отменено.")
        await callback.answer()

    async def cmd_list(self, message: types.Message):
        logger.info(f"📩 /list от {message.from_user.id}")
        tracked = await db.get_tracked_users(tg_user_id=message.from_user.id)
        if not tracked:
            await message.answer("📭 Вы пока ничего не отслеживаете.\nНажмите '➕ Добавить', чтобы начать.")
            return

        text = "📋 **Вы отслеживаете:**\n\n"
        for tg_id, steamid64, appid, contextid in tracked:
            game = next((n for n, a in [("CS2", 730), ("Dota 2", 570), ("TF2", 440), ("Rust", 252490)] if a == appid),
                        f"AppID:{appid}")
            text += f"• `{steamid64}` — {game}\n"

        text += "\nЧтобы удалить: `/remove 76561199109461098 730`"
        await message.answer(text, parse_mode="Markdown")

    async def cmd_remove_prompt(self, message: types.Message):
        await message.answer(
            "🗑️ Формат: `/remove <SteamID64> [AppID]`\n"
            "Пример: `/remove 76561199109461098 730`\n\n"
            "AppID по умолчанию: 730 (CS2)",
            parse_mode="Markdown"
        )



    async def send_new_items_notification(self, tg_user_id: int, steamid64: str,
                                          appid: int, new_items: list):
        game = next((n for n, a in [("CS2", 730), ("Dota 2", 570), ("TF2", 440)] if a == appid), f"AppID:{appid}")

        text = f"🎁 **Новые предметы!**\n👤 `{steamid64}` | 🎮 {game}\n\n"

        for item in new_items[:config.MAX_ITEMS_PER_NOTIFICATION]:
            name = item.get('display_name', f"Item #{item.get('classid')}")
            text += f"• {name}\n"

        if len(new_items) > config.MAX_ITEMS_PER_NOTIFICATION:
            text += f"\n_... и ещё {len(new_items) - config.MAX_ITEMS_PER_NOTIFICATION} предметов_"

        await self.bot.send_message(tg_user_id, text, parse_mode="Markdown")

    async def on_debug_message(self, message: types.Message):
        """Показывает все необработанные сообщения"""
        text = message.text or "(пустое сообщение)"
        logger.warning(f"⚠️ НЕОБРАБОТАНО: '{text[:100]}'")
        logger.warning(f"   От пользователя: {message.from_user.id}")
        logger.warning(f"   Тип: {type(text)}")

        # Проверяем, есть ли ссылка
        if 'steam' in text.lower():
            logger.warning("   ⚠️ Содержит 'steam', но не обработано!")