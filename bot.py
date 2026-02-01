"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 3.2
Исправлено экранирование MarkdownV2 с сохранением форматирования
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.storage.memory import MemoryStorage

# Наши модули
import config
from database import db
from dragon_model import Dragon
from books import get_random_book, get_all_genres

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== СОСТОЯНИЯ FSM ====================
class GameStates(StatesGroup):
    waiting_for_guess = State()
    waiting_for_name = State()
    making_coffee = State()

# ==================== УТИЛИТЫ ====================
class RateLimiter:
    """Ограничитель частоты действий"""
    def __init__(self):
        self.user_actions: Dict[str, datetime] = {}
    
    def can_perform_action(self, user_id: int, action: str, cooldown_seconds: int = 30) -> bool:
        """Проверяет, можно ли выполнить действие"""
        now = datetime.now()
        key = f"{user_id}_{action}"
        
        if key in self.user_actions:
            last_time = self.user_actions[key]
            if now - last_time < timedelta(seconds=cooldown_seconds):
                return False
        
        self.user_actions[key] = now
        return True
    
    def clear_old_entries(self, max_age_hours: int = 24):
        """Очищает старые записи"""
        now = datetime.now()
        to_delete = []
        
        for key, time in self.user_actions.items():
            if now - time > timedelta(hours=max_age_hours):
                to_delete.append(key)
        
        for key in to_delete:
            del self.user_actions[key]

def validate_dragon_name(name: str) -> tuple[bool, Optional[str]]:
    """Валидация имени дракона"""
    name = name.strip()
    
    if len(name) < 2:
        return False, "Имя должно быть хотя бы 2 символа"
    
    if len(name) > 20:
        return False, "Имя слишком длинное. Максимум 20 символов"
    
    import re
    if re.search(r'[<>{}[\]\\|`~!@#$%^&*()_+=]', name):
        return False, "Имя содержит недопустимые символы"
    
    return True, None

def create_progress_bar(value: int, length: int = 10) -> str:
    """Создает прогресс-бар"""
    filled = min(max(0, int(value / 100 * length)), length)
    return "█" * filled + "░" * (length - filled)

def format_time_left(seconds: int) -> str:
    """Форматирует оставшееся время"""
    if seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        return f"{seconds // 60} мин"
    else:
        return f"{seconds // 3600} ч"

def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2, оставляя * для форматирования"""
    # Символы, которые всегда нужно экранировать
    # Не экранируем * и _ для форматирования
    escape_chars = r'[]()~`>#+\-=|{}.!'
    
    result = []
    for char in text:
        if char in escape_chars:
            result.append('\\' + char)
        elif char == '_':
            # Экранируем только одиночные подчёркивания
            result.append('\\' + char)
        else:
            result.append(char)
    
    return ''.join(result)

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Статус"), KeyboardButton(text="☕ Кофе")],
            [KeyboardButton(text="📖 Читать"), KeyboardButton(text="🎮 Играть")],
            [KeyboardButton(text="🤗 Обнять"), KeyboardButton(text="✨ Уход")],
            [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="📦 Инвентарь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 🐾"
    )
    return keyboard

def get_short_main_keyboard() -> ReplyKeyboardMarkup:
    """Короткая клавиатура для начального экрана"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Создать дракона"), KeyboardButton(text="📖 Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard

@lru_cache(maxsize=1)
def get_shop_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура магазина"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="☕ Зерна", callback_data="shop_coffee"),
                InlineKeyboardButton(text="10💰", callback_data="price_10")
            ],
            [
                InlineKeyboardButton(text="🍪 Печенье", callback_data="shop_cookie"),
                InlineKeyboardButton(text="5💰", callback_data="price_5")
            ],
            [
                InlineKeyboardButton(text="🍫 Шоколад", callback_data="shop_chocolate"),
                InlineKeyboardButton(text="15💰", callback_data="price_15")
            ],
            [
                InlineKeyboardButton(text="🎲 Кость", callback_data="shop_dice"),
                InlineKeyboardButton(text="20💰", callback_data="price_20")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

@lru_cache(maxsize=1)
def get_coffee_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для приготовления кофе"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="☕ Эспрессо", callback_data="coffee_espresso"),
                InlineKeyboardButton(text="☕ Латте", callback_data="coffee_latte")
            ],
            [
                InlineKeyboardButton(text="☕ Капучино", callback_data="coffee_cappuccino"),
                InlineKeyboardButton(text="☕ Раф", callback_data="coffee_raf")
            ],
            [
                InlineKeyboardButton(text="☕ Американо", callback_data="coffee_americano"),
                InlineKeyboardButton(text="« Назад", callback_data="coffee_back")
            ]
        ]
    )
    return keyboard

@lru_cache(maxsize=1)
def get_reading_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для чтения"""
    genres = get_all_genres()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Добавляем кнопки по 2 в ряд
    row = []
    for genre in genres:
        emoji = "📚"
        if genre == "фэнтези": emoji = "✨"
        elif genre == "приключения": emoji = "🗺️"
        elif genre == "сказки": emoji = "🏰"
        elif genre == "детектив": emoji = "🔍"
        elif genre == "поэзия": emoji = "✍️"
        
        row.append(InlineKeyboardButton(text=f"{emoji} {genre.capitalize()}", callback_data=f"read_{genre}"))
        if len(row) == 2:
            keyboard.inline_keyboard.append(row)
            row = []
    
    if row:
        keyboard.inline_keyboard.append(row)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🎲 Случайная книга", callback_data="read_random"),
        InlineKeyboardButton(text="« Назад", callback_data="read_back")
    ])
    
    return keyboard

def get_feed_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    """Клавиатура для кормления"""
    snack_items = {
        "печенье": "🍪 Печенье",
        "шоколад": "🍫 Шоколад", 
        "зефир": "☁️ Зефир",
        "пряник": "🎄 Пряник",
        "мармелад": "🍬 Мармелад"
    }
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    
    for snack_key, snack_name in snack_items.items():
        count = inventory.get(snack_key, 0)
        if count > 0:
            row.append(InlineKeyboardButton(
                text=f"{snack_name} ×{count}", 
                callback_data=f"feed_{snack_key}"
            ))
            if len(row) == 2:
                keyboard.inline_keyboard.append(row)
                row = []
    
    if row:
        keyboard.inline_keyboard.append(row)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="« Назад", callback_data="feed_back")
    ])
    
    return keyboard

# Инициализация ограничителя частоты
rate_limiter = RateLimiter()

# ==================== НАЧАЛЬНЫЙ ЭКРАН ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - красивое приветствие"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        # Создаем пользователя в базе
        db.create_user(user_id, username)
        
        # Проверяем, есть ли дракон
        has_dragon = db.dragon_exists(user_id)
        
        # Красивое приветствие
        welcome_text = (
            f"✨ *Добро пожаловать в мир Кофейных Драконов, {username}\\!* ✨\n\n"
            
            f"🌙 *В далёких горах, где растут волшебные кофейные деревья, "
            f"рождаются особенные драконы\\.* Они питаются ароматным кофе, "
            f"обожают книги, игры и тёплые объятия\\.\n\n"
            
            f"🐾 *Тебе выпала честь стать хранителем одного из них\\!*\n\n"
            
            f"📋 *Что тебя ждёт:*\n"
            f"• 🐉 Вырасти своего уникального дракона\n"
            f"• ☕ Открывай секреты кофейного искусства\n"
            f"• 📚 Читай книги и развивай литературный вкус\n"
            f"• 🎮 Играй в игры и зарабатывай золото\n"
            f"• ❤️ Стань лучшим хранителем в истории\n\n"
        )
        
        if has_dragon:
            welcome_text += f"*У тебя уже есть дракон\\!* 🎉\n"
            welcome_text += f"*Используй кнопку «🐉 Статус» чтобы проверить как он поживает\\.*"
            await message.answer(welcome_text, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        else:
            welcome_text += f"*Нажми «🐉 Создать дракона» чтобы начать приключение\\!*"
            await message.answer(
                welcome_text, 
                parse_mode="MarkdownV2",
                reply_markup=get_short_main_keyboard()
            )
        
        logger.info(f"Новый пользователь: {username} (ID: {user_id})")
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_start: {e}")
        await message.answer("❌ *Произошла ошибка при запуске бота\\.*", parse_mode="MarkdownV2")

@dp.message(Command("help"))
@dp.message(F.text == "📖 Помощь")
async def cmd_help(message: types.Message):
    """Команда /help - красивая справка"""
    help_text = (
        "📚 *КОМАНДЫ И ВОЗМОЖНОСТИ*\n\n"
        
        "🐉 *ОСНОВНОЕ*\n"
        "`/start` \\- начать игру\n"
        "`/help` \\- эта справка\n"
        "`/create` \\- создать дракона\n"
        "`/status` \\- статус дракона\n\n"
        
        "❤ *УХОД И ЗАБОТА*\n"
        "`/coffee` \\- приготовить кофе\n"
        "`/feed` \\- покормить сладостями\n"
        "`/hug` \\- обнять дракона\n"
        "`/clean` \\- ухаживать за драконом\n\n"
        
        "🎮 *РАЗВЛЕЧЕНИЯ*\n"
        "`/read` \\- почитать книгу\n"
        "`/play` \\- поиграть в игру\n\n"
        
        "💰 *ЭКОНОМИКА*\n"
        "`/shop` \\- магазин товаров\n"
        "`/inventory` \\- инвентарь\n"
        "`/gold` \\- проверить золото\n\n"
        
        "⚙️ *НАСТРОЙКИ*\n"
        "`/rename` \\- переименовать дракона\n"
        "`/stats` \\- подробная статистика\n"
        "`/achievements` \\- достижения\n\n"
        
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Используй кнопки внизу для быстрого доступа*"
    )
    
    keyboard = get_main_keyboard() if db.dragon_exists(message.from_user.id) else get_short_main_keyboard()
    await message.answer(help_text, parse_mode="MarkdownV2", reply_markup=keyboard)

@dp.message(Command("create"))
@dp.message(F.text == "🐉 Создать дракона")
async def cmd_create(message: types.Message, state: FSMContext):
    """Создание дракона - красивое оформление"""
    try:
        user_id = message.from_user.id
        
        # Проверяем, есть ли уже дракон
        if db.dragon_exists(user_id):
            await message.answer(
                "🎉 *У тебя уже есть дракон\\!*\n\n"
                "Используй кнопку «🐉 Статус» чтобы проверить как он поживает\n"
                "или «✨ Уход» чтобы позаботиться о нём\\.",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Красивое приглашение создать дракона
        await message.answer(
            "✨ *ВОЛШЕБСТВО НАЧИНАЕТСЯ\\.\\.\\.*\n\n"
            "В кофейных горах родилось новое яйцо, и из него вот\\-вот появится дракончик\n"
            "Вся его будущая судьба зависит от имени, которое ты ему дашь\\.\n\n"
            "📝 *Как назовёшь своего дракона\\?*\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Примеры имён:* Кофейка, Спаркли, Златопер, Лунарик\n"
            "• 2\\-20 символов\n"
            "• Без специальных знаков",
            parse_mode="MarkdownV2",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(GameStates.waiting_for_name)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_create: {e}")
        await message.answer("❌ *Произошла ошибка при создании дракона\\.*", parse_mode="MarkdownV2")

@dp.message(GameStates.waiting_for_name)
async def process_dragon_name(message: types.Message, state: FSMContext):
    """Обработка ввода имени дракона"""
    try:
        user_id = message.from_user.id
        dragon_name = message.text
        
        # Валидируем имя
        is_valid, error_message = validate_dragon_name(dragon_name)
        if not is_valid:
            await message.answer(
                f"❌ *{error_message}*\n\n"
                f"Попробуй другое имя:",
                parse_mode="MarkdownV2"
            )
            return
        
        # Создаем дракона
        dragon = Dragon(name=dragon_name)
        dragon_data = dragon.to_dict()
        
        # Сохраняем в базу
        success = db.create_dragon(user_id, dragon_data)
        
        if not success:
            await message.answer("❌ *Не удалось создать дракона\\. Попробуй еще раз\\.*", parse_mode="MarkdownV2")
            return
        
        # Получаем характер для приветствия
        character = dragon.character.get("основная_черта", "неженка")
        
        character_descriptions = {
            "кофеман": "Обожает кофе больше всего на свете ☕",
            "соня": "Любит поспать и вздремнуть после кофе 😴",
            "игрик": "Обожает игры и соревнования 🎮",
            "книгочей": "Проводит дни за чтением книг 📚",
            "неженка": "Требует много ласки и внимания 💖",
            "гурман": "Разбирается в кофе и сладостях 🍫",
            "чистюля": "Следит за своей чистотой ✨",
            "лентяй": "Не любит лишнюю активность 🛋️",
            "энерджайзер": "Всегда полон энергии ⚡",
            "философ": "Любит размышлять о жизни 🤔"
        }
        
        # Красивое сообщение о создании
        await message.answer(
            f"🎊 *ВОЛШЕБСТВО СВЕРШИЛОСЬ\\!* 🎊\n\n"
            f"✨ Из яйца появился *{dragon_name}* \\- твой кофейный дракон\\!\n\n"
            f"🎭 *Характер:* {character}\n"
            f"{character_descriptions.get(character, '')}\n\n"
            f"❤ *ЛЮБИМОЕ:*\n"
            f"• ☕ Кофе: `{dragon.favorites['кофе']}`\n"
            f"• 🍬 Сладость: `{dragon.favorites['сладость']}`\n"
            f"• 📚 Книги: `{dragon.favorites['жанр_книг']}`\n\n"
            f"📦 *НАЧАЛЬНЫЙ ИНВЕНТАРЬ:*\n"
            f"• ☕ Зерна: `10`\n"
            f"• 🍪 Печенье: `5`\n"
            f"• 🍫 Шоколад: `2`\n"
            f"• 💧 Вода: `3`\n\n"
            f"💰 *ЗОЛОТО:* `{dragon.gold}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"*Начни с того, что приготовь ему кофе* ☕\n"
            f"*Используй кнопки ниже для ухода* 🐾",
            parse_mode="MarkdownV2",
            reply_markup=get_main_keyboard()
        )
        
        logger.info(f"Создан дракон: {dragon_name} для пользователя {user_id}")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_dragon_name: {e}")
        await message.answer("❌ *Произошла ошибка при создании дракона\\.*", parse_mode="MarkdownV2")
        await state.clear()

# ==================== ОСНОВНЫЕ ДЕЙСТВИЯ ====================
@dp.message(Command("status"))
@dp.message(F.text == "🐉 Статус")
async def cmd_status(message: types.Message):
    """Показать статус дракона - красивый интерфейс"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer(
                "🐣 *У тебя еще нет дракона\\!*\n\n"
                "Нажми «🐉 Создать дракона» чтобы начать приключение\n"
                "или `/create` для создания дракона\\.",
                parse_mode="MarkdownV2",
                reply_markup=get_short_main_keyboard()
            )
            return
        
        dragon = Dragon.from_dict(dragon_data)
        dragon.update_over_time()
        
        # Создаем прогресс-бары
        coffee_bar = create_progress_bar(dragon.stats.get("кофе", 0))
        sleep_bar = create_progress_bar(dragon.stats.get("сон", 0))
        mood_bar = create_progress_bar(dragon.stats.get("настроение", 0))
        appetite_bar = create_progress_bar(dragon.stats.get("аппетит", 0))
        energy_bar = create_progress_bar(dragon.stats.get("энергия", 0))
        fluff_bar = create_progress_bar(dragon.stats.get("пушистость", 0))
        
        # Проверяем критические состояния
        warnings = []
        if dragon.stats.get("кофе", 70) < 20:
            warnings.append("☕ Срочно нужно кофе!")
        if dragon.stats.get("сон", 30) > 80:
            warnings.append("💤 Засыпает на ходу...")
        if dragon.stats.get("аппетит", 60) > 80:
            warnings.append("🍪 Очень голоден!")
        if dragon.stats.get("настроение", 80) < 30:
            warnings.append("😔 Грустит...")
        if dragon.stats.get("энергия", 75) < 20:
            warnings.append("⚡ Нет сил")
        if dragon.stats.get("пушистость", 90) < 30:
            warnings.append("✨ Нужен уход")
        
        status_text = (
            f"🐉 *{dragon.name}* \\[Уровень {dragon.level}\\]\n"
            f"⭐ *Опыт:* `{dragon.experience}/100`\n"
            f"💰 *Золото:* `{dragon.gold}`\n\n"
            
            f"🎭 *Характер:* `{dragon.character.get('основная_черта', 'неженка')}`\n\n"
            
            f"📊 *ПОКАЗАТЕЛИ:*\n"
            f"☕ Кофе:       `{coffee_bar}` `{dragon.stats.get('кофе', 0)}%`\n"
            f"💤 Сон:        `{sleep_bar}` `{dragon.stats.get('сон', 0)}%`\n"
            f"😊 Настроение: `{mood_bar}` `{dragon.stats.get('настроение', 0)}%`\n"
            f"🍪 Аппетит:    `{appetite_bar}` `{dragon.stats.get('аппетит', 0)}%`\n"
            f"⚡ Энергия:    `{energy_bar}` `{dragon.stats.get('энергия', 0)}%`\n"
            f"✨ Пушистость: `{fluff_bar}` `{dragon.stats.get('пушистость', 0)}%`\n\n"
            
            f"❤ *ЛЮБИМОЕ:*\n"
            f"• ☕ Кофе: `{dragon.favorites.get('кофе', 'эспрессо')}`\n"
            f"• 🍬 Сладость: `{dragon.favorites.get('сладость', 'печенье')}`\n"
            f"• 📚 Книги: `{dragon.favorites.get('жанр_книг', 'фэнтези')}`\n\n"
        )
        
        if warnings:
            status_text += f"⚠️ *ВНИМАНИЕ:*\n"
            for warning in warnings:
                status_text += f"• {warning}\n"
            status_text += "\n"
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 *Обновлено:* `{datetime.now().strftime('%H:%M')}`\n"
            f"⬇️ *Используй кнопки ниже для ухода*"
        )
        
        await message.answer(status_text, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("❌ *Произошла ошибка при получении статуса\\.*", parse_mode="MarkdownV2")

@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message):
    """Приготовить кофе - красивый интерфейс"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "coffee", 10):
            await message.answer("⏳ *Подожди немного перед следующим кофе* ☕", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем инвентарь
        inventory = db.get_inventory(user_id)
        if inventory.get("кофейные_зерна", 0) <= 0:
            await message.answer(
                "❌ *Не хватает кофейных зерен\\!*\n\n"
                "🛍️ *Зайди в магазин чтобы купить:*\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или `/shop`",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "☕ *ВЫБЕРИ КОФЕ*\n\n"
            "✨ *Варианты:*\n"
            "• *Эспрессо* \\- бодрящий и крепкий\n"
            "• *Латте* \\- нежный с молоком\n"
            "• *Капучино* \\- с воздушной пенкой\n"
            "• *Раф* \\- сливочный и сладкий\n"
            "• *Американо* \\- классический\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"☕ *Зерен доступно:* `{inventory.get('кофейные_зерна', 0)}`",
            parse_mode="MarkdownV2",
            reply_markup=get_coffee_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_coffee: {e}")
        await message.answer("❌ *Произошла ошибка при приготовлении кофе\\.*", parse_mode="MarkdownV2")

@dp.callback_query(F.data.startswith("coffee_"))
async def process_coffee_choice(callback: types.CallbackQuery):
    """Обработка выбора кофе"""
    try:
        user_id = callback.from_user.id
        coffee_type = callback.data.replace("coffee_", "")
        
        if coffee_type == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Используем зерна
        db.update_inventory(user_id, "кофейные_зерна", -1)
        
        # Применяем действие
        result = dragon.apply_action("кофе")
        
        # Особые эффекты
        coffee_effects = {
            "espresso": {"энергия": 10, "сон": -5},
            "latte": {"настроение": 5, "аппетит": 5},
            "cappuccino": {"пушистость": 5, "настроение": 5},
            "raf": {"настроение": 10, "сон": 5},
            "americano": {"кофе": 5, "энергия": 5}
        }
        
        if coffee_type in coffee_effects:
            for stat, change in coffee_effects[coffee_type].items():
                if stat in dragon.stats:
                    dragon.stats[stat] = max(0, min(100, dragon.stats[stat] + change))
        
        # Проверяем, любимый ли это кофе
        coffee_names = {
            "espresso": "эспрессо",
            "latte": "латте", 
            "cappuccino": "капучино",
            "raf": "раф",
            "americano": "американо"
        }
        
        current_coffee = coffee_names.get(coffee_type, "")
        if current_coffee == dragon.favorites.get("кофе", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            favorite_bonus = "🎉 *Это его любимый кофе\\!* \\+15 к настроению\n"
        else:
            favorite_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Кофейные описания
        coffee_descriptions = {
            "espresso": "Ты приготовил *крепкий эспрессо\\!* Дракон бодр и весел ☕",
            "latte": "Нежный *латте с молочной пенкой* готов\\! Дракон мурлычет от удовольствия 🥰",
            "cappuccino": "Воздушный *капучино с корицей\\!* Аромат стоит на всю комнату ✨",
            "raf": "Сливочный *раф с ванилью\\!* Дракон в восторге 🌟",
            "americano": "Классический *американо\\!* Просто и вкусно 👍"
        }
        
        response = (
            f"{coffee_descriptions.get(coffee_type, 'Кофе готов')}\n\n"
            
            f"📊 *ИЗМЕНЕНИЯ:*\n"
            f"• ☕ Кофе: \\+{result['stat_changes'].get('кофе', 0)}\n"
            f"• ⚡ Энергия: \\+{result['stat_changes'].get('энергия', 0)}\n"
            f"• 😊 Настроение: \\+{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ *Осталось зерен:* `{db.get_inventory(user_id).get('кофейные_зерна', 0)}`"
        )
        
        await callback.message.edit_text(response, parse_mode="MarkdownV2")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(Command("feed"))
async def cmd_feed(message: types.Message):
    """Покормить дракона"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "feed", 15):
            await message.answer("⏳ *Дракон еще не проголодался\\. Подожди немного* 🍪", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        # Проверяем, что есть чем кормить
        available_snacks = []
        for snack_key in ["печенье", "шоколад", "зефир", "пряник", "мармелад"]:
            if inventory.get(snack_key, 0) > 0:
                available_snacks.append(snack_key)
        
        if not available_snacks:
            await message.answer(
                "❌ *Нет сладостей для кормления\\!*\n\n"
                "🛍️ *Зайди в магазин чтобы купить:*\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или `/shop`",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "🍪 *ЧЕМ УГОСТИМ ДРАКОНА\\?*\n\n"
            "✨ *Выбери сладость из инвентаря:*\n\n"
            f"😊 *Настроение дракона:* `{dragon.stats.get('настроение', 0)}%`",
            parse_mode="MarkdownV2",
            reply_markup=get_feed_keyboard(inventory)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_feed: {e}")
        await message.answer("❌ *Произошла ошибка при кормлении\\.*", parse_mode="MarkdownV2")

@dp.callback_query(F.data.startswith("feed_"))
async def process_feed(callback: types.CallbackQuery):
    """Обработка кормления"""
    try:
        user_id = callback.from_user.id
        snack_type = callback.data.replace("feed_", "")
        
        if snack_type == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        # Проверяем, есть ли такая сладость
        inventory = db.get_inventory(user_id)
        if inventory.get(snack_type, 0) <= 0:
            await callback.answer("❌ Эта сладость закончилась")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Используем сладость
        db.update_inventory(user_id, snack_type, -1)
        
        # Применяем действие
        result = dragon.apply_action("кормление")
        
        # Проверяем, любимая ли это сладость
        if snack_type == dragon.favorites.get("сладость", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            favorite_bonus = "🎉 *Это его любимая сладость\\!* \\+20 к настроению\n"
        else:
            favorite_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Описания сладостей
        snack_descriptions = {
            "печенье": "🍪 *Хрустящее печенье*",
            "шоколад": "🍫 *Сладкий шоколад*",
            "зефир": "☁️ *Воздушный зефир*",
            "пряник": "🎄 *Ароматный пряник*",
            "мармелад": "🍬 *Фруктовый мармелад*"
        }
        
        response = (
            f"{snack_descriptions.get(snack_type, 'Сладость')}\n"
            f"Дракон с удовольствием уплетает угощение 🐾\n\n"
            
            f"📊 *ИЗМЕНЕНИЯ:*\n"
            f"• 🍪 Аппетит: {result['stat_changes'].get('аппетит', 0)}\n"
            f"• 😊 Настроение: \\+{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"🍬 *Осталось {snack_type}:* `{inventory.get(snack_type, 0) - 1}`"
        )
        
        await callback.message.edit_text(response, parse_mode="MarkdownV2")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_feed: {e}")
        await callback.answer("❌ Произошла ошибка при кормлении")

@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона - красивый интерфейс"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "hug", 5):
            await message.answer("⏳ *Не переусердствуй с объятиями\\! Подожди немного* 🤗", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Применяем действие
        result = dragon.apply_action("обнимашки")
        
        # Бонус для неженки
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "неженка":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            character_bonus = "🥰 *Неженка обожает обнимашки\\!* \\+15 к настроению\n"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Случайные реакции
        reactions = [
            "Дракон *мурлычет от удовольствия* 🐾",
            "Дракон *обнимает тебя в ответ* 🤗",
            "Дракон *свернулся калачиком* у тебя на коленях 🥰",
            "Дракон *трётся мордочкой* о тебя 😊",
            "Дракон тихо *урчит и закрывает глаза* 😴"
        ]
        
        response = (
            f"{random.choice(reactions)}\n\n"
            
            f"📊 *ИЗМЕНЕНИЯ:*\n"
            f"• 😊 Настроение: \\+{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"❤ *Текущее настроение:* `{dragon.stats.get('настроение', 0)}%`"
        )
        
        await message.answer(response, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_hug: {e}")
        await message.answer("❌ *Произошла ошибка при обнимашках\\.*", parse_mode="MarkdownV2")

@dp.message(Command("read"))
@dp.message(F.text == "📖 Читать")
async def cmd_read(message: types.Message):
    """Почитать книгу дракону"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "read", 30):
            await message.answer("⏳ *Дракону нужно время чтобы осмыслить прочитанное\\. Подожди немного* 📚", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем энергию
        if dragon.stats.get("энергия", 100) < 10:
            await message.answer(
                "😴 *Дракон слишком устал для чтения*\n\n"
                "💡 *Что сделать:*\n"
                "• Дайте ему отдохнуть\n"
                "• Приготовьте кофе ☕",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "📚 *ВЫБЕРИ ЖАНР КНИГИ*\n\n"
            "✨ *Жанры:*\n"
            "• 📚 *Фэнтези* \\- волшебные миры\n"
            "• 🏰 *Сказки* \\- добрые истории\n"
            "• 🗺️ *Приключения* \\- захватывающие путешествия\n"
            "• 🔍 *Детектив* \\- загадки и расследования\n"
            "• ✍️ *Поэзия* \\- стихи и рифмы\n\n"
            f"⚡ *Энергия дракона:* `{dragon.stats.get('энергия', 0)}%`",
            parse_mode="MarkdownV2",
            reply_markup=get_reading_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_read: {e}")
        await message.answer("❌ *Произошла ошибка при чтении\\.*", parse_mode="MarkdownV2")

@dp.callback_query(F.data.startswith("read_"))
async def process_read(callback: types.CallbackQuery):
    """Обработка чтения книги"""
    try:
        user_id = callback.from_user.id
        read_type = callback.data.replace("read_", "")
        
        if read_type == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Тратим энергию
        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] - 10)
        
        # Получаем книгу
        if read_type == "random":
            book = get_random_book()
        else:
            book = get_random_book(read_type)
        
        if not book:
            await callback.answer("❌ Книги не найдены")
            return
        
        # Применяем действие
        result = dragon.apply_action("чтение")
        
        # Проверяем, любимый ли это жанр
        if book.get("жанр", "") == dragon.favorites.get("жанр_книг", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            dragon.skills["литературный_вкус"] = min(100, dragon.skills.get("литературный_вкус", 0) + 5)
            favorite_bonus = "🎉 *Это его любимый жанр\\!* \\+15 к настроению, \\+5 к литературному вкусу\n"
        else:
            favorite_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Формируем ответ
        response = (
            f"📖 *{book.get('название', 'Неизвестная книга')}*\n"
            f"✍️ *Автор:* `{book.get('автор', 'Неизвестен')}`\n\n"
            
            f"📝 *О ЧЕМ КНИГА:*\n"
            f"{book.get('описание', 'Нет описания')}\n\n"
            
            f"🐉 *МНЕНИЕ ДРАКОНА:*\n"
            f"{book.get('комментарий_дракона', 'Интересно\\!')}\n\n"
            
            f"📊 *ПОСЛЕ ЧТЕНИЯ:*\n"
            f"• 😊 Настроение: \\+{result['stat_changes'].get('настроение', 0)}\n"
            f"• 📚 Литературный вкус: \\+2\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Энергия осталась:* `{dragon.stats.get('энергия', 0)}%`"
        )
        
        await callback.message.edit_text(response, parse_mode="MarkdownV2")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_read: {e}")
        await callback.answer("❌ Произошла ошибка при чтении")

@dp.message(Command("play"))
@dp.message(F.text == "🎮 Играть")
async def cmd_play(message: types.Message, state: FSMContext):
    """Поиграть с драконом"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "play", 20):
            await message.answer("⏳ *Дракон устал от игр\\. Дайте ему отдохнуть* 🎮", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем энергию
        if dragon.stats.get("энергия", 100) < 20:
            await message.answer(
                "😴 *Дракон слишком устал для игр*\n\n"
                "💡 *Что сделать:*\n"
                "• Дайте ему отдохнуть\n"
                "• Приготовьте кофе ☕",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Загадываем число для игры
        secret_number = random.randint(1, 5)
        
        await state.update_data(
            secret_number=secret_number,
            dragon_data=dragon.to_dict()
        )
        await state.set_state(GameStates.waiting_for_guess)
        
        # Тратим энергию
        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] - 20)
        db.update_dragon(user_id, dragon.to_dict())
        
        await message.answer(
            "🎮 *ИГРА: УГАДАЙ ЧИСЛО*\n\n"
            "✨ *Правила:*\n"
            "• Я загадал число от 1 до 5\n"
            "• Попробуй угадать\\!\n"
            "• За правильный ответ: \\+10💰 и \\+20 к настроению\n"
            "• За неправильный: \\-5 к настроению\n\n"
            f"⚡ *Потрачено энергии:* `20%`\n\n"
            f"🔢 *Отправь цифру от 1 до 5:*",
            parse_mode="MarkdownV2",
            reply_markup=ReplyKeyboardRemove()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_play: {e}")
        await message.answer("❌ *Произошла ошибка при запуске игры\\.*", parse_mode="MarkdownV2")

@dp.message(GameStates.waiting_for_guess)
async def process_game_guess(message: types.Message, state: FSMContext):
    """Обработка догадки в игре"""
    try:
        user_id = message.from_user.id
        
        try:
            guess = int(message.text.strip())
            if guess < 1 or guess > 5:
                await message.answer("❌ *Пожалуйста, введи число от 1 до 5*", parse_mode="MarkdownV2")
                return
        except ValueError:
            await message.answer("❌ *Пожалуйста, введи число от 1 до 5*", parse_mode="MarkdownV2")
            return
        
        # Получаем данные из состояния
        data = await state.get_data()
        secret_number = data["secret_number"]
        dragon_data = data["dragon_data"]
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Применяем действие
        result = dragon.apply_action("игра")
        
        # Определяем результат
        if guess == secret_number:
            # Победа
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            dragon.gold += 10
            db.add_gold(user_id, 10)
            
            response = (
                f"🎉 *ПРАВИЛЬНО\\!* Загаданное число: `{secret_number}`\n\n"
                f"✨ *Дракон радостно подпрыгивает*\n\n"
                
                f"🏆 *НАГРАДА:*\n"
                f"• 😊 Настроение: \\+20\n"
                f"• 💰 Золото: \\+10\n"
                f"• 🎮 Игровая эрудиция: \\+2"
            )
        else:
            # Поражение
            dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
            
            response = (
                f"😔 *НЕ УГАДАЛ\\!* Загаданное число: `{secret_number}`\n\n"
                f"✨ *Дракон немного расстроился\\.\\.\\. но это же игра*\n\n"
                
                f"📊 *РЕЗУЛЬТАТ:*\n"
                f"• 😊 Настроение: \\-5\n"
                f"• 🎮 Игровая эрудиция: \\+2"
            )
        
        # Бонус для игрика
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "игрик":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
            response += "\n\n🎮 *Игрик обожает игры\\!* \\+10 к настроению"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        if result.get("level_up"):
            response += f"\n\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Текущее золото:* `{db.get_gold(user_id)}`\n"
            f"😊 *Настроение дракона:* `{dragon.stats.get('настроение', 0)}%`"
        )
        
        await message.answer(response, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_game_guess: {e}")
        await message.answer("❌ *Произошла ошибка в игре\\.*", parse_mode="MarkdownV2")
        await state.clear()

@dp.message(Command("clean"))
@dp.message(F.text == "✨ Уход")
async def cmd_clean(message: types.Message):
    """Почистить или расчесать дракона"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "clean", 300):
            await message.answer("✨ *Дракон уже чист\\. Подожди немного*", parse_mode="MarkdownV2")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Применяем действие
        result = dragon.apply_action("расчесывание")
        
        # Бонус для чистюли
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "чистюля":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            character_bonus = "✨ *Чистюля сияет от счастья\\!* \\+20 к настроению\n"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Случайные реакции
        reactions = [
            "Дракон *блаженно закрывает глаза* пока ты его расчёсываешь ✨",
            "✨ *Шерстка дракона теперь блестит и переливается* 🌟",
            "Дракон *мурлычет наслаждаясь процедурой ухода* 😌",
            "✨ *После расчесывания дракон выглядит просто великолепно* 💫"
        ]
        
        response = (
            f"{random.choice(reactions)}\n\n"
            
            f"📊 *РЕЗУЛЬТАТ:*\n"
            f"• ✨ Пушистость: \\+{result['stat_changes'].get('пушистость', 0)}\n"
            f"• 😊 Настроение: \\+{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n🎊 *{result['message']}*"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"✨ *Текущая пушистость:* `{dragon.stats.get('пушистость', 0)}%`"
        )
        
        await message.answer(response, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_clean: {e}")
        await message.answer("❌ *Произошла ошибка при уходе\\.*", parse_mode="MarkdownV2")

# ==================== МАГАЗИН И ИНВЕНТАРЬ ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message):
    """Магазин с красивым интерфейсом"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        gold = db.get_gold(user_id)
        inventory = db.get_inventory(user_id)
        
        await message.answer(
            f"🛍️ *МАГАЗИН КОФЕЙНОГО ДРАКОНА*\n\n"
            
            f"💰 *ТВОЙ БАЛАНС:* `{gold} золота`\n\n"
            
            f"📦 *ТВОЙ ИНВЕНТАРЬ:*\n"
            f"• ☕ Зерна: `{inventory.get('кофейные_зерна', 0)}`\n"
            f"• 🍪 Печенье: `{inventory.get('печенье', 0)}`\n"
            f"• 🍫 Шоколад: `{inventory.get('шоколад', 0)}`\n"
            f"• 🎲 Кость: `{inventory.get('игральная_кость', 0)}`\n\n"
            
            f"🛒 *ТОВАРЫ:*\n"
            f"• ☕ Кофейные зерна \\- 10💰\n"
            f"• 🍪 Печенье \\- 5💰\n"
            f"• 🍫 Шоколад \\- 15💰\n"
            f"• 🎲 Игральная кость \\- 20💰\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"*Выбери товар для покупки:*",
            parse_mode="MarkdownV2",
            reply_markup=get_shop_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_shop: {e}")
        await message.answer("❌ *Произошла ошибка при открытии магазина\\.*", parse_mode="MarkdownV2")

@dp.callback_query(F.data.startswith("shop_"))
async def process_shop(callback: types.CallbackQuery):
    """Обработка покупок в магазине"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("shop_", "")
        
        if action == "close":
            await callback.message.delete()
            await callback.answer("🛍️ Магазин закрыт")
            return
        
        if action == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        gold = db.get_gold(user_id)
        
        # Цены товаров
        prices = {
            "coffee": 10,
            "cookie": 5,
            "chocolate": 15,
            "dice": 20
        }
        
        # Названия товаров в инвентаре
        item_names = {
            "coffee": "кофейные_зерна",
            "cookie": "печенье",
            "chocolate": "шоколад",
            "dice": "игральная_кость"
        }
        
        # Описания
        descriptions = {
            "coffee": "☕ Кофейные зерна",
            "cookie": "🍪 Печенье",
            "chocolate": "🍫 Шоколад",
            "dice": "🎲 Игральная кость"
        }
        
        if action in prices:
            price = prices[action]
            item_name = item_names[action]
            description = descriptions[action]
            
            if gold >= price:
                # Покупаем
                db.add_gold(user_id, -price)
                db.update_inventory(user_id, item_name, 1)
                
                new_gold = gold - price
                inventory = db.get_inventory(user_id)
                
                await callback.message.edit_text(
                    f"✅ *ПОКУПКА СОВЕРШЕНА\\!*\n\n"
                    
                    f"✨ *Куплено:* {description}\n"
                    f"💰 *Цена:* `{price} золота`\n"
                    f"💰 *Остаток:* `{new_gold} золота`\n\n"
                    
                    f"📦 *ТЕПЕРЬ В ИНВЕНТАРЕ:*\n"
                    f"• {description}: `{inventory.get(item_name, 0)}`\n\n"
                    
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"*Хочешь купить что\\-нибудь ещё\\?*",
                    parse_mode="MarkdownV2",
                    reply_markup=get_shop_keyboard()
                )
                await callback.answer("✅ Покупка успешна!")
            else:
                await callback.answer(f"❌ Недостаточно золота! Нужно {price}💰, а у тебя {gold}💰")
        else:
            await callback.answer("❌ Неизвестный товар")
            
    except Exception as e:
        logger.error(f"Ошибка в process_shop: {e}")
        await callback.answer("❌ Произошла ошибка при покупке")

@dp.message(Command("inventory"))
@dp.message(F.text == "📦 Инвентарь")
async def cmd_inventory(message: types.Message):
    """Показать инвентарь - красивый интерфейс"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        inventory = db.get_inventory(user_id)
        gold = db.get_gold(user_id)
        
        if not inventory:
            await message.answer(
                "📦 *ИНВЕНТАРЬ ПУСТ*\n\n"
                f"💰 *Золото:* `{gold}`\n\n"
                "🛍️ *Зайди в магазин чтобы купить что\\-нибудь:*\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или `/shop`",
                parse_mode="MarkdownV2",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Формируем список предметов
        items_text = "📦 *ТВОЙ ИНВЕНТАРЬ*\n\n"
        
        # Кофе и напитки
        coffee_items = []
        for item, count in inventory.items():
            if item in ["кофейные_зерна", "вода"]:
                emoji = "☕" if item == "кофейные_зерна" else "💧"
                name = "Кофейные зерна" if item == "кофейные_зерна" else "Вода"
                coffee_items.append(f"• {emoji} {name}: `{count}`")
        
        if coffee_items:
            items_text += "☕ *КОФЕ И НАПИТКИ:*\n" + "\n".join(coffee_items) + "\n\n"
        
        # Сладости
        snack_items = []
        snacks = ["печенье", "шоколад", "зефир", "пряник", "мармелад"]
        for item in snacks:
            count = inventory.get(item, 0)
            if count > 0:
                emoji = {
                    "печенье": "🍪",
                    "шоколад": "🍫",
                    "зефир": "☁️",
                    "пряник": "🎄",
                    "мармелад": "🍬"
                }.get(item, "•")
                name = item.capitalize()
                snack_items.append(f"• {emoji} {name}: `{count}`")
        
        if snack_items:
            items_text += "🍬 *СЛАДОСТИ:*\n" + "\n".join(snack_items) + "\n\n"
        
        # Игры и развлечения
        game_items = []
        if inventory.get("игральная_кость", 0) > 0:
            game_items.append(f"• 🎲 Игральная кость: `{inventory.get('игральная_кость', 0)}`")
        
        if game_items:
            items_text += "🎮 *ИГРЫ И РАЗВЛЕЧЕНИЯ:*\n" + "\n".join(game_items) + "\n\n"
        
        items_text += f"💰 *ЗОЛОТО:* `{gold}`\n\n"
        items_text += "━━━━━━━━━━━━━━━━━━━\n"
        items_text += "*Используй сладости для кормления дракона\\!* 🐾"
        
        await message.answer(items_text, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_inventory: {e}")
        await message.answer("❌ *Произошла ошибка при просмотре инвентаря\\.*", parse_mode="MarkdownV2")

@dp.message(Command("gold"))
async def cmd_gold(message: types.Message):
    """Показать количество золота"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        gold = db.get_gold(user_id)
        
        responses = [
            f"💰 *ТВОЁ ЗОЛОТО:* `{gold}`\n\n✨ *Золото можно заработать в играх или найти в книгах*",
            f"💰 *СОКРОВИЩА:* `{gold} золота`\n\n✨ *Продолжай заботиться о драконе и золото само придёт*",
            f"💰 *БОГАТСТВО:* `{gold} золотых монет`\n\n🛍️ *На что потратишь\\? Загляни в магазин*",
            f"💰 *КАЗНА:* `{gold} золота`\n\n✨ *С каждым днём твоё состояние растёт*"
        ]
        
        await message.answer(random.choice(responses), parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_gold: {e}")
        await message.answer("❌ *Произошла ошибка при проверке золота\\.*", parse_mode="MarkdownV2")

# ==================== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ====================
@dp.message(Command("rename"))
async def cmd_rename(message: types.Message, state: FSMContext):
    """Переименовать дракона"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        await message.answer(
            "✏️ *ПЕРЕИМЕНОВАНИЕ ДРАКОНА*\n\n"
            "✨ *Как ты хочешь назвать своего дракона\\?*\n\n"
            "💡 *Правила:*\n"
            "• 2\\-20 символов\n"
            "• Без специальных знаков\n\n"
            "📝 *Отправь новое имя:*",
            parse_mode="MarkdownV2",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(GameStates.waiting_for_name)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_rename: {e}")
        await message.answer("❌ *Произошла ошибка при переименовании\\.*", parse_mode="MarkdownV2")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Подробная статистика"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Навыки
        skills_text = "🎯 *НАВЫКИ ДРАКОНА*\n"
        for skill, value in dragon.skills.items():
            skill_name = skill.replace("_", " ").title()
            emoji = "☕" if "кофей" in skill else "📚" if "литератур" in skill else "🎮" if "игр" in skill else "🧶"
            bar = create_progress_bar(value)
            skills_text += f"{emoji} *{skill_name}:* `{bar}` `{value}%`\n"
        
        # Характер
        character_text = (
            f"🎭 *ХАРАКТЕР*\n"
            f"✨ *Основная черта:* `{dragon.character.get('основная_черта', 'неженка')}`\n"
            f"🌟 *Дополнительные:* `{', '.join(dragon.character.get('второстепенные', []))}`\n"
        )
        
        # Любимое
        favorites_text = (
            f"❤ *ЛЮБИМОЕ*\n"
            f"• ☕ *Кофе:* `{dragon.favorites.get('кофе', 'эспрессо')}`\n"
            f"• 🍬 *Сладость:* `{dragon.favorites.get('сладость', 'печенье')}`\n"
            f"• 📚 *Книги:* `{dragon.favorites.get('жанр_книг', 'фэнтези')}`\n"
            f"• 🎨 *Цвет:* `{dragon.favorites.get('цвет', 'синий')}`\n"
        )
        
        # Прогресс
        created_date = datetime.fromisoformat(dragon.created_at)
        days_with_dragon = (datetime.now() - created_date).days
        
        progress_text = (
            f"📊 *ПРОГРЕСС*\n"
            f"• 🎮 *Уровень:* `{dragon.level}`\n"
            f"• ⭐ *Опыт:* `{dragon.experience}/100`\n"
            f"• 💰 *Золото:* `{dragon.gold}`\n"
            f"• 📅 *Дней вместе:* `{days_with_dragon}`\n"
            f"• 🕐 *Создан:* `{created_date.strftime('%d\\.%m\\.%Y')}`\n"
        )
        
        response = (
            f"🐉 *ПОДРОБНАЯ СТАТИСТИКА {dragon.name}*\n\n"
            f"{progress_text}\n"
            f"{character_text}\n"
            f"{favorites_text}\n"
            f"{skills_text}\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"*Продолжай развивать навыки своего дракона\\!* 🚀"
        )
        
        await message.answer(response, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_stats: {e}")
        await message.answer("❌ *Произошла ошибка при получении статистики\\.*", parse_mode="MarkdownV2")

@dp.message(Command("achievements"))
async def cmd_achievements(message: types.Message):
    """Достижения"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("🐣 *Сначала создай дракона\\!*", parse_mode="MarkdownV2")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Определяем достижения
        achievements = []
        
        # По уровню
        if dragon.level >= 5:
            achievements.append("🎓 *Ученик* \\- достиг 5 уровня")
        if dragon.level >= 10:
            achievements.append("🏆 *Мастер* \\- достиг 10 уровня")
        if dragon.level >= 20:
            achievements.append("👑 *Легенда* \\- достиг 20 уровня")
        
        # По навыкам
        if dragon.skills.get("кофейное_мастерство", 0) >= 50:
            achievements.append("☕ *Бариста* \\- кофейное мастерство 50\\+")
        if dragon.skills.get("литературный_вкус", 0) >= 50:
            achievements.append("📚 *Библиофил* \\- литературный вкус 50\\+")
        if dragon.skills.get("игровая_эрудиция", 0) >= 50:
            achievements.append("🎮 *Геймер* \\- игровая эрудиция 50\\+")
        
        # По золоту
        if dragon.gold >= 100:
            achievements.append("💰 *Богач* \\- накопил 100\\+ золота")
        if dragon.gold >= 500:
            achievements.append("💎 *Миллионер* \\- накопил 500\\+ золота")
        
        # По времени
        created_date = datetime.fromisoformat(dragon.created_at)
        days_with_dragon = (datetime.now() - created_date).days
        
        if days_with_dragon >= 7:
            achievements.append("📅 *Неделя вместе* \\- 7 дней с драконом")
        if days_with_dragon >= 30:
            achievements.append("📅 *Месяц вместе* \\- 30 дней с драконом")
        if days_with_dragon >= 100:
            achievements.append("📅 *Вековой союз* \\- 100 дней с драконом")
        
        if achievements:
            achievements_text = "\n".join(achievements)
            response = (
                f"🏆 *ДОСТИЖЕНИЯ {dragon.name}*\n\n"
                f"{achievements_text}\n\n"
                f"✨ *Всего достижений:* `{len(achievements)}`"
            )
        else:
            response = (
                f"🏆 *ДОСТИЖЕНИЯ {dragon.name}*\n\n"
                f"✨ *Пока нет достижений*\n\n"
                f"💡 *Продолжай заботиться о драконе и достижения появятся\\!*"
            )
        
        await message.answer(response, parse_mode="MarkdownV2", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_achievements: {e}")
        await message.answer("❌ *Произошла ошибка при получении достижений\\.*", parse_mode="MarkdownV2")

# ==================== ОБРАБОТКА ОШИБОК ====================
@dp.message()
async def handle_other_messages(message: types.Message):
    """Обработка всех остальных сообщений"""
    response = (
        "🤔 *Я не понял команду*\n\n"
        "💡 *Используй кнопки внизу или команду* `/help` *для списка команд*\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🐾 *Если у тебя ещё нет дракона \\- нажми «🐉 Создать дракона»*"
    )
    
    keyboard = get_main_keyboard() if db.dragon_exists(message.from_user.id) else get_short_main_keyboard()
    await message.answer(response, parse_mode="MarkdownV2", reply_markup=keyboard)

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Главная функция запуска бота"""
    logger.info("✨ Запуск бота Кофейный Дракон...")
    
    try:
        # Очищаем старые записи ограничителя частоты
        rate_limiter.clear_old_entries()
        
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())