"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 4.0
Используется HTML форматирование вместо MarkdownV2
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

def escape_html(text: str) -> str:
    """Экранирует HTML-спецсимволы"""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )

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
            f"<b>✨ Добро пожаловать в мир Кофейных Драконов, {escape_html(username)}! ✨</b>\n\n"
            
            f"<i>🌙 В далёких горах, где растут волшебные кофейные деревья, "
            f"рождаются особенные драконы.</i> Они питаются ароматным кофе, "
            f"обожают книги, игры и тёплые объятия.\n\n"
            
            f"<b>🐾 Тебе выпала честь стать хранителем одного из них!</b>\n\n"
            
            f"<b>📋 Что тебя ждёт:</b>\n"
            f"• 🐉 Вырасти своего уникального дракона\n"
            f"• ☕ Открывай секреты кофейного искусства\n"
            f"• 📚 Читай книги и развивай литературный вкус\n"
            f"• 🎮 Играй в игры и зарабатывай золото\n"
            f"• ❤️ Стань лучшим хранителем в истории\n\n"
        )
        
        if has_dragon:
            welcome_text += f"<b>У тебя уже есть дракон! 🎉</b>\n"
            welcome_text += f"<i>Используй кнопку «🐉 Статус» чтобы проверить как он поживает.</i>"
            await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        else:
            welcome_text += f"<b>Нажми «🐉 Создать дракона» чтобы начать приключение!</b>"
            await message.answer(
                welcome_text, 
                parse_mode="HTML",
                reply_markup=get_short_main_keyboard()
            )
        
        logger.info(f"Новый пользователь: {username} (ID: {user_id})")
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_start: {e}")
        await message.answer("<b>❌ Произошла ошибка при запуске бота.</b>", parse_mode="HTML")

@dp.message(Command("help"))
@dp.message(F.text == "📖 Помощь")
async def cmd_help(message: types.Message):
    """Команда /help - красивая справка"""
    help_text = (
        "<b>📚 КОМАНДЫ И ВОЗМОЖНОСТИ</b>\n\n"
        
        "<b>🐉 ОСНОВНОЕ</b>\n"
        "<code>/start</code> - начать игру\n"
        "<code>/help</code> - эта справка\n"
        "<code>/create</code> - создать дракона\n"
        "<code>/status</code> - статус дракона\n\n"
        
        "<b>❤ УХОД И ЗАБОТА</b>\n"
        "<code>/coffee</code> - приготовить кофе\n"
        "<code>/feed</code> - покормить сладостями\n"
        "<code>/hug</code> - обнять дракона\n"
        "<code>/clean</code> - ухаживать за драконом\n\n"
        
        "<b>🎮 РАЗВЛЕЧЕНИЯ</b>\n"
        "<code>/read</code> - почитать книгу\n"
        "<code>/play</code> - поиграть в игру\n\n"
        
        "<b>💰 ЭКОНОМИКА</b>\n"
        "<code>/shop</code> - магазин товаров\n"
        "<code>/inventory</code> - инвентарь\n"
        "<code>/gold</code> - проверить золото\n\n"
        
        "<b>⚙️ НАСТРОЙКИ</b>\n"
        "<code>/rename</code> - переименовать дракона\n"
        "<code>/stats</code> - подробная статистика\n"
        "<code>/achievements</code> - достижения\n\n"
        
        "━━━━━━━━━━━━━━━━━━━\n"
        "<i>💡 Используй кнопки внизу для быстрого доступа</i>"
    )
    
    keyboard = get_main_keyboard() if db.dragon_exists(message.from_user.id) else get_short_main_keyboard()
    await message.answer(help_text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(Command("create"))
@dp.message(F.text == "🐉 Создать дракона")
async def cmd_create(message: types.Message, state: FSMContext):
    """Создание дракона - красивое оформление"""
    try:
        user_id = message.from_user.id
        
        # Проверяем, есть ли уже дракон
        if db.dragon_exists(user_id):
            await message.answer(
                "<b>🎉 У тебя уже есть дракон!</b>\n\n"
                "<i>Используй кнопку «🐉 Статус» чтобы проверить как он поживает\n"
                "или «✨ Уход» чтобы позаботиться о нём.</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Красивое приглашение создать дракона
        await message.answer(
            "<b>✨ ВОЛШЕБСТВО НАЧИНАЕТСЯ...</b>\n\n"
            "<i>В кофейных горах родилось новое яйцо, и из него вот-вот появится дракончик\n"
            "Вся его будущая судьба зависит от имени, которое ты ему дашь.</i>\n\n"
            "<b>📝 Как назовёшь своего дракона?</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 Примеры имён: Кофейка, Спаркли, Златопер, Лунарик\n"
            "• 2-20 символов\n"
            "• Без специальных знаков</i>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(GameStates.waiting_for_name)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_create: {e}")
        await message.answer("<b>❌ Произошла ошибка при создании дракона.</b>", parse_mode="HTML")

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
                f"<b>❌ {error_message}</b>\n\n"
                f"Попробуй другое имя:",
                parse_mode="HTML"
            )
            return
        
        # Создаем дракона
        dragon = Dragon(name=dragon_name)
        dragon_data = dragon.to_dict()
        
        # Сохраняем в базу
        success = db.create_dragon(user_id, dragon_data)
        
        if not success:
            await message.answer("<b>❌ Не удалось создать дракона. Попробуй еще раз.</b>", parse_mode="HTML")
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
            f"<b>🎊 ВОЛШЕБСТВО СВЕРШИЛОСЬ! 🎊</b>\n\n"
            f"✨ Из яйца появился <b>{escape_html(dragon_name)}</b> - твой кофейный дракон!\n\n"
            f"<b>🎭 Характер:</b> {character}\n"
            f"{character_descriptions.get(character, '')}\n\n"
            
            f"<b>❤ ЛЮБИМОЕ:</b>\n"
            f"• ☕ Кофе: <code>{dragon.favorites['кофе']}</code>\n"
            f"• 🍬 Сладость: <code>{dragon.favorites['сладость']}</code>\n"
            f"• 📚 Книги: <code>{dragon.favorites['жанр_книг']}</code>\n\n"
            
            f"<b>📦 НАЧАЛЬНЫЙ ИНВЕНТАРЬ:</b>\n"
            f"• ☕ Зерна: <code>10</code>\n"
            f"• 🍪 Печенье: <code>5</code>\n"
            f"• 🍫 Шоколад: <code>2</code>\n"
            f"• 💧 Вода: <code>3</code>\n\n"
            
            f"<b>💰 ЗОЛОТО:</b> <code>{dragon.gold}</code>\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Начни с того, что приготовь ему кофе ☕</i>\n"
            f"<i>Используй кнопки ниже для ухода 🐾</i>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        
        logger.info(f"Создан дракон: {dragon_name} для пользователя {user_id}")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_dragon_name: {e}")
        await message.answer("<b>❌ Произошла ошибка при создании дракона.</b>", parse_mode="HTML")
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
                "<b>🐣 У тебя еще нет дракона!</b>\n\n"
                "<i>Нажми «🐉 Создать дракона» чтобы начать приключение\n"
                "или <code>/create</code> для создания дракона.</i>",
                parse_mode="HTML",
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
            f"<b>🐉 {escape_html(dragon.name)} [Уровень {dragon.level}]</b>\n"
            f"⭐ <b>Опыт:</b> <code>{dragon.experience}/100</code>\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n\n"
            
            f"🎭 <b>Характер:</b> <code>{dragon.character.get('основная_черта', 'неженка')}</code>\n\n"
            
            f"<b>📊 ПОКАЗАТЕЛИ:</b>\n"
            f"☕ Кофе:       <code>{coffee_bar}</code> <code>{dragon.stats.get('кофе', 0)}%</code>\n"
            f"💤 Сон:        <code>{sleep_bar}</code> <code>{dragon.stats.get('сон', 0)}%</code>\n"
            f"😊 Настроение: <code>{mood_bar}</code> <code>{dragon.stats.get('настроение', 0)}%</code>\n"
            f"🍪 Аппетит:    <code>{appetite_bar}</code> <code>{dragon.stats.get('аппетит', 0)}%</code>\n"
            f"⚡ Энергия:    <code>{energy_bar}</code> <code>{dragon.stats.get('энергия', 0)}%</code>\n"
            f"✨ Пушистость: <code>{fluff_bar}</code> <code>{dragon.stats.get('пушистость', 0)}%</code>\n\n"
            
            f"<b>❤ ЛЮБИМОЕ:</b>\n"
            f"• ☕ Кофе: <code>{dragon.favorites.get('кофе', 'эспрессо')}</code>\n"
            f"• 🍬 Сладость: <code>{dragon.favorites.get('сладость', 'печенье')}</code>\n"
            f"• 📚 Книги: <code>{dragon.favorites.get('жанр_книг', 'фэнтези')}</code>\n\n"
        )
        
        if warnings:
            status_text += f"<b>⚠️ ВНИМАНИЕ:</b>\n"
            for warning in warnings:
                status_text += f"• {warning}\n"
            status_text += "\n"
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 <i>Обновлено:</i> <code>{datetime.now().strftime('%H:%M')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message):
    """Приготовить кофе - красивый интерфейс"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "coffee", 10):
            await message.answer("<b>⏳ Подожди немного перед следующим кофе ☕</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем инвентарь
        inventory = db.get_inventory(user_id)
        if inventory.get("кофейные_зерна", 0) <= 0:
            await message.answer(
                "<b>❌ Не хватает кофейных зерен!</b>\n\n"
                "<b>🛍️ Зайди в магазин чтобы купить:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или <code>/shop</code>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "<b>☕ ВЫБЕРИ КОФЕ</b>\n\n"
            "<i>✨ Варианты:</i>\n"
            "• <b>Эспрессо</b> - бодрящий и крепкий\n"
            "• <b>Латте</b> - нежный с молоком\n"
            "• <b>Капучино</b> - с воздушной пенкой\n"
            "• <b>Раф</b> - сливочный и сладкий\n"
            "• <b>Американо</b> - классический\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Зерен доступно:</i> <code>{inventory.get('кофейные_зерна', 0)}</code>",
            parse_mode="HTML",
            reply_markup=get_coffee_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_coffee: {e}")
        await message.answer("<b>❌ Произошла ошибка при приготовлении кофе.</b>", parse_mode="HTML")

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
            favorite_bonus = "<b>🎉 Это его любимый кофе! +15 к настроению</b>\n"
        else:
            favorite_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Кофейные описания
        coffee_descriptions = {
            "espresso": "Ты приготовил <b>крепкий эспрессо!</b> Дракон бодр и весел ☕",
            "latte": "Нежный <b>латте с молочной пенкой</b> готов! Дракон мурлычет от удовольствия 🥰",
            "cappuccino": "Воздушный <b>капучино с корицей!</b> Аромат стоит на всю комнату ✨",
            "raf": "Сливочный <b>раф с ванилью!</b> Дракон в восторге 🌟",
            "americano": "Классический <b>американо!</b> Просто и вкусно 👍"
        }
        
        response = (
            f"{coffee_descriptions.get(coffee_type, 'Кофе готов')}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• ☕ Кофе: +{result['stat_changes'].get('кофе', 0)}\n"
            f"• ⚡ Энергия: +{result['stat_changes'].get('энергия', 0)}\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Осталось зерен:</i> <code>{db.get_inventory(user_id).get('кофейные_зерна', 0)}</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
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
            await message.answer("<b>⏳ Дракон еще не проголодался. Подожди немного 🍪</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
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
                "<b>❌ Нет сладостей для кормления!</b>\n\n"
                "<b>🛍️ Зайди в магазин чтобы купить:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или <code>/shop</code>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "<b>🍪 ЧЕМ УГОСТИМ ДРАКОНА?</b>\n\n"
            "<i>✨ Выбери сладость из инвентаря:</i>\n\n"
            f"😊 <i>Настроение дракона:</i> <code>{dragon.stats.get('настроение', 0)}%</code>",
            parse_mode="HTML",
            reply_markup=get_feed_keyboard(inventory)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_feed: {e}")
        await message.answer("<b>❌ Произошла ошибка при кормлении.</b>", parse_mode="HTML")

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
            favorite_bonus = "<b>🎉 Это его любимая сладость! +20 к настроению</b>\n"
        else:
            favorite_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Описания сладостей
        snack_descriptions = {
            "печенье": "🍪 <b>Хрустящее печенье</b>",
            "шоколад": "🍫 <b>Сладкий шоколад</b>",
            "зефир": "☁️ <b>Воздушный зефир</b>",
            "пряник": "🎄 <b>Ароматный пряник</b>",
            "мармелад": "🍬 <b>Фруктовый мармелад</b>"
        }
        
        response = (
            f"{snack_descriptions.get(snack_type, 'Сладость')}\n"
            f"Дракон с удовольствием уплетает угощение 🐾\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 🍪 Аппетит: {result['stat_changes'].get('аппетит', 0)}\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"🍬 <i>Осталось {snack_type}:</i> <code>{inventory.get(snack_type, 0) - 1}</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
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
            await message.answer("<b>⏳ Не переусердствуй с объятиями! Подожди немного 🤗</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Применяем действие
        result = dragon.apply_action("обнимашки")
        
        # Бонус для неженки
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "неженка":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            character_bonus = "<b>🥰 Неженка обожает обнимашки! +15 к настроению</b>\n"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Случайные реакции
        reactions = [
            "Дракон <b>мурлычет от удовольствия</b> 🐾",
            "Дракон <b>обнимает тебя в ответ</b> 🤗",
            "Дракон <b>свернулся калачиком</b> у тебя на коленях 🥰",
            "Дракон <b>трётся мордочкой</b> о тебя 😊",
            "Дракон тихо <b>урчит и закрывает глаза</b> 😴"
        ]
        
        response = (
            f"{random.choice(reactions)}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"❤ <i>Текущее настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_hug: {e}")
        await message.answer("<b>❌ Произошла ошибка при обнимашках.</b>", parse_mode="HTML")

@dp.message(Command("read"))
@dp.message(F.text == "📖 Читать")
async def cmd_read(message: types.Message):
    """Почитать книгу дракону"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "read", 30):
            await message.answer("<b>⏳ Дракону нужно время чтобы осмыслить прочитанное. Подожди немного 📚</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем энергию
        if dragon.stats.get("энергия", 100) < 10:
            await message.answer(
                "<b>😴 Дракон слишком устал для чтения</b>\n\n"
                "<i>💡 Что сделать:</i>\n"
                "• Дайте ему отдохнуть\n"
                "• Приготовьте кофе ☕",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "<b>📚 ВЫБЕРИ ЖАНР КНИГИ</b>\n\n"
            "<i>✨ Жанры:</i>\n"
            "• 📚 <b>Фэнтези</b> - волшебные миры\n"
            "• 🏰 <b>Сказки</b> - добрые истории\n"
            "• 🗺️ <b>Приключения</b> - захватывающие путешествия\n"
            "• 🔍 <b>Детектив</b> - загадки и расследования\n"
            "• ✍️ <b>Поэзия</b> - стихи и рифмы\n\n"
            f"⚡ <i>Энергия дракона:</i> <code>{dragon.stats.get('энергия', 0)}%</code>",
            parse_mode="HTML",
            reply_markup=get_reading_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_read: {e}")
        await message.answer("<b>❌ Произошла ошибка при чтении.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("read_"))
async def process_read(callback: types.CallbackQuery):
    """Обработка чтения книги - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
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
            # Для случайной книги определяем жанр
            book_genre = None
            for genre, books_list in BOOKS_DATABASE.items():
                if book in books_list:
                    book_genre = genre
                    break
        else:
            book = get_random_book(read_type)
            book_genre = read_type
        
        if not book:
            await callback.answer("❌ Книги не найдены")
            return
        
        # Применяем действие
        result = dragon.apply_action("чтение")
        
        # Проверяем, любимый ли это жанр
        if book_genre and book_genre == dragon.favorites.get("жанр_книг", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            dragon.skills["литературный_вкус"] = min(100, dragon.skills.get("литературный_вкус", 0) + 5)
            favorite_bonus = "<b>🎉 Это его любимый жанр! +15 к настроению, +5 к литературному вкусу</b>\n"
        else:
            favorite_bonus = ""
        
        # Улучшаем литературный вкус в любом случае
        dragon.skills["литературный_вкус"] = min(100, dragon.skills.get("литературный_вкус", 0) + 2)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Формируем ответ
        response = (
            f"<b>📖 {escape_html(book.get('название', 'Неизвестная книга'))}</b>\n"
            f"<i>✍️ Автор:</i> <code>{escape_html(book.get('автор', 'Неизвестен'))}</code>\n"
        )
        
        # Добавляем жанр книги, если он известен
        if book_genre:
            response += f"<i>📚 Жанр:</i> <code>{book_genre.capitalize()}</code>\n\n"
        else:
            response += "\n"
        
        response += (
            f"<b>📝 О ЧЕМ КНИГА:</b>\n"
            f"{book.get('описание', 'Нет описания')}\n\n"
            
            f"<b>🐉 МНЕНИЕ ДРАКОНА:</b>\n"
            f"{book.get('комментарий_дракона', 'Интересно!')}\n\n"
            
            f"<b>📊 ПОСЛЕ ЧТЕНИЯ:</b>\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
            f"• 📚 Литературный вкус: +2\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Энергия осталась:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
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
            await message.answer("<b>⏳ Дракон устал от игр. Дайте ему отдохнуть 🎮</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем энергию
        if dragon.stats.get("энергия", 100) < 20:
            await message.answer(
                "<b>😴 Дракон слишком устал для игр</b>\n\n"
                "<i>💡 Что сделать:</i>\n"
                "• Дайте ему отдохнуть\n"
                "• Приготовьте кофе ☕",
                parse_mode="HTML",
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
            "<b>🎮 ИГРА: УГАДАЙ ЧИСЛО</b>\n\n"
            "<i>✨ Правила:</i>\n"
            "• Я загадал число от 1 до 5\n"
            "• Попробуй угадать!\n"
            "• За правильный ответ: +10💰 и +20 к настроению\n"
            "• За неправильный: -5 к настроению\n\n"
            f"⚡ <i>Потрачено энергии:</i> <code>20%</code>\n\n"
            f"<b>🔢 Отправь цифру от 1 до 5:</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_play: {e}")
        await message.answer("<b>❌ Произошла ошибка при запуске игры.</b>", parse_mode="HTML")

@dp.message(GameStates.waiting_for_guess)
async def process_game_guess(message: types.Message, state: FSMContext):
    """Обработка догадки в игре"""
    try:
        user_id = message.from_user.id
        
        try:
            guess = int(message.text.strip())
            if guess < 1 or guess > 5:
                await message.answer("<b>❌ Пожалуйста, введи число от 1 до 5</b>", parse_mode="HTML")
                return
        except ValueError:
            await message.answer("<b>❌ Пожалуйста, введи число от 1 до 5</b>", parse_mode="HTML")
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
                f"<b>🎉 ПРАВИЛЬНО!</b> Загаданное число: <code>{secret_number}</code>\n\n"
                f"✨ <i>Дракон радостно подпрыгивает</i>\n\n"
                
                f"<b>🏆 НАГРАДА:</b>\n"
                f"• 😊 Настроение: +20\n"
                f"• 💰 Золото: +10\n"
                f"• 🎮 Игровая эрудиция: +2"
            )
        else:
            # Поражение
            dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
            
            response = (
                f"<b>😔 НЕ УГАДАЛ!</b> Загаданное число: <code>{secret_number}</code>\n\n"
                f"✨ <i>Дракон немного расстроился... но это же игра</i>\n\n"
                
                f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                f"• 😊 Настроение: -5\n"
                f"• 🎮 Игровая эрудиция: +2"
            )
        
        # Бонус для игрика
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "игрик":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
            response += "\n\n<b>🎮 Игрик обожает игры! +10 к настроению</b>"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <i>Текущее золото:</i> <code>{db.get_gold(user_id)}</code>\n"
            f"😊 <i>Настроение дракона:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_game_guess: {e}")
        await message.answer("<b>❌ Произошла ошибка в игре.</b>", parse_mode="HTML")
        await state.clear()

@dp.message(Command("clean"))
@dp.message(F.text == "✨ Уход")
async def cmd_clean(message: types.Message):
    """Почистить или расчесать дракона"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "clean", 300):
            await message.answer("<b>✨ Дракон уже чист. Подожди немного</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Применяем действие
        result = dragon.apply_action("расчесывание")
        
        # Бонус для чистюли
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "чистюля":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            character_bonus = "<b>✨ Чистюля сияет от счастья! +20 к настроению</b>\n"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        
        # Случайные реакции
        reactions = [
            "Дракон <b>блаженно закрывает глаза</b> пока ты его расчёсываешь ✨",
            "✨ <b>Шерстка дракона теперь блестит и переливается</b> 🌟",
            "Дракон <b>мурлычет наслаждаясь процедурой ухода</b> 😌",
            "✨ <b>После расчесывания дракон выглядит просто великолепно</b> 💫"
        ]
        
        response = (
            f"{random.choice(reactions)}\n\n"
            
            f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
            f"• ✨ Пушистость: +{result['stat_changes'].get('пушистость', 0)}\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Текущая пушистость:</i> <code>{dragon.stats.get('пушистость', 0)}%</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_clean: {e}")
        await message.answer("<b>❌ Произошла ошибка при уходе.</b>", parse_mode="HTML")

# ==================== МАГАЗИН И ИНВЕНТАРЬ ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message):
    """Магазин с красивым интерфейсом"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        gold = db.get_gold(user_id)
        inventory = db.get_inventory(user_id)
        
        await message.answer(
            f"<b>🛍️ МАГАЗИН КОФЕЙНОГО ДРАКОНА</b>\n\n"
            
            f"💰 <b>ТВОЙ БАЛАНС:</b> <code>{gold} золота</code>\n\n"
            
            f"<b>📦 ТВОЙ ИНВЕНТАРЬ:</b>\n"
            f"• ☕ Зерна: <code>{inventory.get('кофейные_зерна', 0)}</code>\n"
            f"• 🍪 Печенье: <code>{inventory.get('печенье', 0)}</code>\n"
            f"• 🍫 Шоколад: <code>{inventory.get('шоколад', 0)}</code>\n"
            f"• 🎲 Кость: <code>{inventory.get('игральная_кость', 0)}</code>\n\n"
            
            f"<b>🛒 ТОВАРЫ:</b>\n"
            f"• ☕ Кофейные зерна - 10💰\n"
            f"• 🍪 Печенье - 5💰\n"
            f"• 🍫 Шоколад - 15💰\n"
            f"• 🎲 Игральная кость - 20💰\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Выбери товар для покупки:</i>",
            parse_mode="HTML",
            reply_markup=get_shop_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_shop: {e}")
        await message.answer("<b>❌ Произошла ошибка при открытии магазина.</b>", parse_mode="HTML")

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
                    f"<b>✅ ПОКУПКА СОВЕРШЕНА!</b>\n\n"
                    
                    f"✨ <i>Куплено:</i> {description}\n"
                    f"💰 <i>Цена:</i> <code>{price} золота</code>\n"
                    f"💰 <i>Остаток:</i> <code>{new_gold} золота</code>\n\n"
                    
                    f"<b>📦 ТЕПЕРЬ В ИНВЕНТАРЕ:</b>\n"
                    f"• {description}: <code>{inventory.get(item_name, 0)}</code>\n\n"
                    
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Хочешь купить что-нибудь ещё?</i>",
                    parse_mode="HTML",
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
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        inventory = db.get_inventory(user_id)
        gold = db.get_gold(user_id)
        
        if not inventory:
            await message.answer(
                "<b>📦 ИНВЕНТАРЬ ПУСТ</b>\n\n"
                f"💰 <b>Золото:</b> <code>{gold}</code>\n\n"
                "<b>🛍️ Зайди в магазин чтобы купить что-нибудь:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или <code>/shop</code>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Формируем список предметов
        items_text = "<b>📦 ТВОЙ ИНВЕНТАРЬ</b>\n\n"
        
        # Кофе и напитки
        coffee_items = []
        for item, count in inventory.items():
            if item in ["кофейные_зерна", "вода"]:
                emoji = "☕" if item == "кофейные_зерна" else "💧"
                name = "Кофейные зерна" if item == "кофейные_зерна" else "Вода"
                coffee_items.append(f"• {emoji} {name}: <code>{count}</code>")
        
        if coffee_items:
            items_text += "<b>☕ КОФЕ И НАПИТКИ:</b>\n" + "\n".join(coffee_items) + "\n\n"
        
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
                snack_items.append(f"• {emoji} {name}: <code>{count}</code>")
        
        if snack_items:
            items_text += "<b>🍬 СЛАДОСТИ:</b>\n" + "\n".join(snack_items) + "\n\n"
        
        # Игры и развлечения
        game_items = []
        if inventory.get("игральная_кость", 0) > 0:
            game_items.append(f"• 🎲 Игральная кость: <code>{inventory.get('игральная_кость', 0)}</code>")
        
        if game_items:
            items_text += "<b>🎮 ИГРЫ И РАЗВЛЕЧЕНИЯ:</b>\n" + "\n".join(game_items) + "\n\n"
        
        items_text += f"💰 <b>ЗОЛОТО:</b> <code>{gold}</code>\n\n"
        items_text += "━━━━━━━━━━━━━━━━━━━\n"
        items_text += "<i>Используй сладости для кормления дракона! 🐾</i>"
        
        await message.answer(items_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_inventory: {e}")
        await message.answer("<b>❌ Произошла ошибка при просмотре инвентаря.</b>", parse_mode="HTML")

@dp.message(Command("gold"))
async def cmd_gold(message: types.Message):
    """Показать количество золота"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        gold = db.get_gold(user_id)
        
        responses = [
            f"💰 <b>ТВОЁ ЗОЛОТО:</b> <code>{gold}</code>\n\n✨ <i>Золото можно заработать в играх или найти в книгах</i>",
            f"💰 <b>СОКРОВИЩА:</b> <code>{gold} золота</code>\n\n✨ <i>Продолжай заботиться о драконе и золото само придёт</i>",
            f"💰 <b>БОГАТСТВО:</b> <code>{gold} золотых монет</code>\n\n🛍️ <i>На что потратишь? Загляни в магазин</i>",
            f"💰 <b>КАЗНА:</b> <code>{gold} золота</code>\n\n✨ <i>С каждым днём твоё состояние растёт</i>"
        ]
        
        await message.answer(random.choice(responses), parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_gold: {e}")
        await message.answer("<b>❌ Произошла ошибка при проверке золота.</b>", parse_mode="HTML")

# ==================== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ====================
@dp.message(Command("rename"))
async def cmd_rename(message: types.Message, state: FSMContext):
    """Переименовать дракона"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        await message.answer(
            "<b>✏️ ПЕРЕИМЕНОВАНИЕ ДРАКОНА</b>\n\n"
            "✨ <i>Как ты хочешь назвать своего дракона?</i>\n\n"
            "<b>💡 Правила:</b>\n"
            "• 2-20 символов\n"
            "• Без специальных знаков\n\n"
            "<b>📝 Отправь новое имя:</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(GameStates.waiting_for_name)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_rename: {e}")
        await message.answer("<b>❌ Произошла ошибка при переименовании.</b>", parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Подробная статистика"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Навыки
        skills_text = "<b>🎯 НАВЫКИ ДРАКОНА</b>\n"
        for skill, value in dragon.skills.items():
            skill_name = skill.replace("_", " ").title()
            emoji = "☕" if "кофей" in skill else "📚" if "литератур" in skill else "🎮" if "игр" in skill else "🧶"
            bar = create_progress_bar(value)
            skills_text += f"{emoji} <b>{skill_name}:</b> <code>{bar}</code> <code>{value}%</code>\n"
        
        # Характер
        character_text = (
            f"<b>🎭 ХАРАКТЕР</b>\n"
            f"✨ <i>Основная черта:</i> <code>{dragon.character.get('основная_черта', 'неженка')}</code>\n"
            f"🌟 <i>Дополнительные:</i> <code>{', '.join(dragon.character.get('второстепенные', []))}</code>\n"
        )
        
        # Любимое
        favorites_text = (
            f"<b>❤ ЛЮБИМОЕ</b>\n"
            f"• ☕ <i>Кофе:</i> <code>{dragon.favorites.get('кофе', 'эспрессо')}</code>\n"
            f"• 🍬 <i>Сладость:</i> <code>{dragon.favorites.get('сладость', 'печенье')}</code>\n"
            f"• 📚 <i>Книги:</i> <code>{dragon.favorites.get('жанр_книг', 'фэнтези')}</code>\n"
            f"• 🎨 <i>Цвет:</i> <code>{dragon.favorites.get('цвет', 'синий')}</code>\n"
        )
        
        # Прогресс
        created_date = datetime.fromisoformat(dragon.created_at)
        days_with_dragon = (datetime.now() - created_date).days
        
        progress_text = (
            f"<b>📊 ПРОГРЕСС</b>\n"
            f"• 🎮 <i>Уровень:</i> <code>{dragon.level}</code>\n"
            f"• ⭐ <i>Опыт:</i> <code>{dragon.experience}/100</code>\n"
            f"• 💰 <i>Золото:</i> <code>{dragon.gold}</code>\n"
            f"• 📅 <i>Дней вместе:</i> <code>{days_with_dragon}</code>\n"
            f"• 🕐 <i>Создан:</i> <code>{created_date.strftime('%d.%m.%Y')}</code>\n"
        )
        
        response = (
            f"<b>🐉 ПОДРОБНАЯ СТАТИСТИКА {escape_html(dragon.name)}</b>\n\n"
            f"{progress_text}\n"
            f"{character_text}\n"
            f"{favorites_text}\n"
            f"{skills_text}\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Продолжай развивать навыки своего дракона! 🚀</i>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_stats: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статистики.</b>", parse_mode="HTML")

@dp.message(Command("achievements"))
async def cmd_achievements(message: types.Message):
    """Достижения"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Определяем достижения
        achievements = []
        
        # По уровню
        if dragon.level >= 5:
            achievements.append("🎓 <b>Ученик</b> - достиг 5 уровня")
        if dragon.level >= 10:
            achievements.append("🏆 <b>Мастер</b> - достиг 10 уровня")
        if dragon.level >= 20:
            achievements.append("👑 <b>Легенда</b> - достиг 20 уровня")
        
        # По навыкам
        if dragon.skills.get("кофейное_мастерство", 0) >= 50:
            achievements.append("☕ <b>Бариста</b> - кофейное мастерство 50+")
        if dragon.skills.get("литературный_вкус", 0) >= 50:
            achievements.append("📚 <b>Библиофил</b> - литературный вкус 50+")
        if dragon.skills.get("игровая_эрудиция", 0) >= 50:
            achievements.append("🎮 <b>Геймер</b> - игровая эрудиция 50+")
        
        # По золоту
        if dragon.gold >= 100:
            achievements.append("💰 <b>Богач</b> - накопил 100+ золота")
        if dragon.gold >= 500:
            achievements.append("💎 <b>Миллионер</b> - накопил 500+ золота")
        
        # По времени
        created_date = datetime.fromisoformat(dragon.created_at)
        days_with_dragon = (datetime.now() - created_date).days
        
        if days_with_dragon >= 7:
            achievements.append("📅 <b>Неделя вместе</b> - 7 дней с драконом")
        if days_with_dragon >= 30:
            achievements.append("📅 <b>Месяц вместе</b> - 30 дней с драконом")
        if days_with_dragon >= 100:
            achievements.append("📅 <b>Вековой союз</b> - 100 дней с драконом")
        
        if achievements:
            achievements_text = "\n".join(achievements)
            response = (
                f"<b>🏆 ДОСТИЖЕНИЯ {escape_html(dragon.name)}</b>\n\n"
                f"{achievements_text}\n\n"
                f"✨ <i>Всего достижений:</i> <code>{len(achievements)}</code>"
            )
        else:
            response = (
                f"<b>🏆 ДОСТИЖЕНИЯ {escape_html(dragon.name)}</b>\n\n"
                f"✨ <i>Пока нет достижений</i>\n\n"
                f"💡 <i>Продолжай заботиться о драконе и достижения появятся!</i>"
            )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_achievements: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении достижений.</b>", parse_mode="HTML")

# ==================== ОБРАБОТКА ОШИБОК ====================
@dp.message()
async def handle_other_messages(message: types.Message):
    """Обработка всех остальных сообщений"""
    response = (
        "<b>🤔 Я не понял команду</b>\n\n"
        "💡 <i>Используй кнопки внизу или команду</i> <code>/help</code> <i>для списка команд</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🐾 <i>Если у тебя ещё нет дракона - нажми «🐉 Создать дракона»</i>"
    )
    
    keyboard = get_main_keyboard() if db.dragon_exists(message.from_user.id) else get_short_main_keyboard()
    await message.answer(response, parse_mode="HTML", reply_markup=keyboard)

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