"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 5.0
Полная переработка с новыми функциями:
- Мини-игры (5 видов)
- Расширенный уход за драконом
- Сложное приготовление кофе
- Система сна вместо чтения
- Улучшенный статус
- Система уведомлений
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Optional, List
import re

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
    coffee_minigame = State()
    sleep_choice = State()
    care_action = State()
    minigame_state = State()

# ==================== КЛАССЫ И УТИЛИТЫ ====================
class RateLimiter:
    """Ограничитель частоты действий с уведомлениями"""
    def __init__(self):
        self.user_actions: Dict[str, datetime] = {}
        self.user_notifications: Dict[int, Dict[str, datetime]] = {}
        self.user_feeding_times: Dict[int, List[datetime]] = {}
    
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
    
    def can_send_notification(self, user_id: int, notification_type: str, hours: int = 24) -> bool:
        """Можно ли отправить уведомление"""
        now = datetime.now()
        
        if user_id not in self.user_notifications:
            self.user_notifications[user_id] = {}
        
        if notification_type in self.user_notifications[user_id]:
            last_time = self.user_notifications[user_id][notification_type]
            if now - last_time < timedelta(hours=hours):
                return False
        
        self.user_notifications[user_id][notification_type] = now
        return True
    
    def record_feeding_time(self, user_id: int):
        """Записывает время кормления"""
        now = datetime.now()
        if user_id not in self.user_feeding_times:
            self.user_feeding_times[user_id] = []
        self.user_feeding_times[user_id].append(now)
        
        # Храним только последние 7 дней
        week_ago = now - timedelta(days=7)
        self.user_feeding_times[user_id] = [
            t for t in self.user_feeding_times[user_id] if t > week_ago
        ]
    
    def get_feeding_pattern(self, user_id: int) -> Optional[str]:
        """Определяет паттерн кормления пользователя"""
        if user_id not in self.user_feeding_times or len(self.user_feeding_times[user_id]) < 3:
            return None
        
        times = self.user_feeding_times[user_id]
        morning_feedings = sum(1 for t in times if 8 <= t.hour <= 10)
        
        if morning_feedings >= len(times) * 0.7:  # 70% кормлений утром
            return "morning"
        return None
    
    def clear_old_entries(self):
        """Очищает старые записи"""
        now = datetime.now()
        
        # Очистка действий
        to_delete = []
        for key, time in self.user_actions.items():
            if now - time > timedelta(hours=24):
                to_delete.append(key)
        
        for key in to_delete:
            del self.user_actions[key]

class MinigameManager:
    """Менеджер мини-игр"""
    
    @staticmethod
    def guess_number_game() -> dict:
        """Игра 'Угадай число'"""
        secret = random.randint(1, 10)
        hints = [
            f"Я загадал число от 1 до 10...",
            f"Подсказка: число {'чётное' if secret % 2 == 0 else 'нечётное'}",
            f"Ещё подсказка: число больше {secret//2}"
        ]
        return {
            "type": "guess",
            "secret": secret,
            "hints": hints,
            "reward": {"gold": 15, "mood": 25, "energy": -15}
        }
    
    @staticmethod
    def coffee_art_game() -> dict:
        """Игра 'Кофейный арт'"""
        patterns = ["❤️", "⭐", "🐉", "☕", "✨", "🌈"]
        target_pattern = random.sample(patterns, 3)
        
        return {
            "type": "coffee_art",
            "target": target_pattern,
            "patterns": patterns,
            "description": "Повтори последовательность узоров на кофейной пенке!",
            "reward": {"gold": 20, "mood": 30, "coffee_skill": 5, "energy": -20}
        }
    
    @staticmethod
    def find_differences_game() -> dict:
        """Игра 'Найди отличия'"""
        differences = random.randint(3, 7)
        return {
            "type": "find_diff",
            "differences": differences,
            "description": f"Найди {differences} отличий в двух картинках!",
            "reward": {"gold": 10, "mood": 20, "energy": -10}
        }
    
    @staticmethod
    def card_duel_game() -> dict:
        """Игра 'Карточная дуэль'"""
        cards = ["А", "К", "Д", "В", "10", "9"]
        player_card = random.choice(cards)
        dragon_card = random.choice(cards)
        
        card_values = {"А": 14, "К": 13, "Д": 12, "В": 11, "10": 10, "9": 9}
        
        return {
            "type": "card_duel",
            "player_card": player_card,
            "dragon_card": dragon_card,
            "card_values": card_values,
            "reward_win": {"gold": 25, "mood": 35, "energy": -15},
            "reward_lose": {"gold": 5, "mood": -10, "energy": -15}
        }
    
    @staticmethod
    def catch_cookie_game() -> dict:
        """Игра 'Лови печенье'"""
        cookies_to_catch = random.randint(5, 10)
        return {
            "type": "catch_cookie",
            "cookies": cookies_to_catch,
            "description": f"Поймай {cookies_to_catch} печений!",
            "reward": {"gold": 8 * cookies_to_catch, "mood": 15 + cookies_to_catch * 2, "energy": -12}
        }
    
    @staticmethod
    def dice_game() -> dict:
        """Игра в кости"""
        return {
            "type": "dice",
            "description": "Брось кости против дракона!",
            "reward_win": {"gold": 30, "mood": 40, "energy": -20},
            "reward_lose": {"gold": 10, "mood": -5, "energy": -20}
        }

def validate_dragon_name(name: str) -> tuple[bool, Optional[str]]:
    """Валидация имени дракона"""
    name = name.strip()
    
    if len(name) < 2:
        return False, "Имя должно быть хотя бы 2 символа"
    
    if len(name) > 20:
        return False, "Имя слишком длинное. Максимум 20 символов"
    
    if re.search(r'[<>{}[\]\\|`~!@#$%^&*()_+=]', name):
        return False, "Имя содержит недопустимые символы"
    
    return True, None

def create_progress_bar(value: int, length: int = 10) -> str:
    """Создает прогресс-бар с фиксированной шириной"""
    filled = min(max(0, int(value / 100 * length)), length)
    empty = length - filled
    return "█" * filled + "░" * empty

def escape_html(text: str) -> str:
    """Экранирует HTML-спецсимволы"""
    if not text:
        return ""
    text = str(text)
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )

def check_stat_full(stat_value: int, stat_name: str, dragon_trait: str = "") -> Optional[str]:
    """Проверяет, полный ли показатель и возвращает сообщение"""
    if stat_value >= 95:
        messages = {
            "кофе": [
                f"☕ Дракон отворачивается от кофе: 'Я уже полон кофеина!'",
                f"☕ {dragon_trait} качает головой: 'Ещё одна капля - и я взлечу!'",
                f"☕ Дракон показывает на свой животик: 'Кофе до краёв!'"
            ],
            "сон": [
                f"💤 Дракон уже сладко похрапывает...",
                f"💤 {dragon_trait} спит так крепко, что даже не шевелится",
                f"💤 Дракон в царстве снов, не беспокой его"
            ],
            "настроение": [
                f"😊 Дракон сияет от счастья! Он не может быть счастливее!",
                f"😊 {dragon_trait} прыгает от радости: 'Я самый счастливый дракон!'",
                f"😊 Улыбка дракона светит ярче солнца!"
            ],
            "аппетит": [
                f"🍪 Дракон отталкивает угощение: 'Я слишком сыт!'",
                f"🍪 {dragon_trait} показывает на круглый животик",
                f"🍪 'Нет-нет, я больше не могу!' - говорит дракон"
            ],
            "энергия": [
                f"⚡ Дракон полон энергии и носится по комнате!",
                f"⚡ {dragon_trait} излучает энергию: 'Я готов к чему угодно!'",
                f"⚡ Дракон слишком энергичен, чтобы сидеть на месте"
            ],
            "пушистость": [
                f"✨ Шёрстка дракона сияет и переливается!",
                f"✨ {dragon_trait} уже идеально ухожен",
                f"✨ Дракон блестит чистотой!"
            ]
        }
        
        if stat_name in messages:
            return random.choice(messages[stat_name])
    
    return None

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Статус"), KeyboardButton(text="☕ Кофе")],
            [KeyboardButton(text="😴 Сон"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🤗 Обнять"), KeyboardButton(text="✨ Уход")],
            [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="📦 Инвентарь")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📖 Помощь")]
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
    """Клавиатура магазина с новыми товарами"""
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
                InlineKeyboardButton(text="🍬 Мармелад", callback_data="shop_marmalade"),
                InlineKeyboardButton(text="8💰", callback_data="price_8")
            ],
            [
                InlineKeyboardButton(text="🎂 Пирожное", callback_data="shop_cake"),
                InlineKeyboardButton(text="12💰", callback_data="price_12")
            ],
            [
                InlineKeyboardButton(text="☁️ Зефир", callback_data="shop_marshmallow"),
                InlineKeyboardButton(text="7💰", callback_data="price_7")
            ],
            [
                InlineKeyboardButton(text="💆 Расческа", callback_data="shop_brush"),
                InlineKeyboardButton(text="25💰", callback_data="price_25")
            ],
            [
                InlineKeyboardButton(text="🧴 Шампунь", callback_data="shop_shampoo"),
                InlineKeyboardButton(text="30💰", callback_data="price_30")
            ],
            [
                InlineKeyboardButton(text="✂️ Ножницы", callback_data="shop_scissors"),
                InlineKeyboardButton(text="20💰", callback_data="price_20")
            ],
            [
                InlineKeyboardButton(text="🧸 Игрушка", callback_data="shop_toy"),
                InlineKeyboardButton(text="15💰", callback_data="price_15")
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
                InlineKeyboardButton(text="☕ Мокко", callback_data="coffee_mocha")
            ],
            [
                InlineKeyboardButton(text="🎮 Сделать арт", callback_data="coffee_art"),
                InlineKeyboardButton(text="« Назад", callback_data="coffee_back")
            ]
        ]
    )
    return keyboard

@lru_cache(maxsize=1)
def get_minigames_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура мини-игр"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess"),
                InlineKeyboardButton(text="🎯 Кофейный арт", callback_data="game_coffee_art")
            ],
            [
                InlineKeyboardButton(text="🧩 Найди отличия", callback_data="game_find_diff"),
                InlineKeyboardButton(text="🃏 Карточная дуэль", callback_data="game_card_duel")
            ],
            [
                InlineKeyboardButton(text="🍪 Лови печенье", callback_data="game_catch_cookie"),
                InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="game_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="game_close")
            ]
        ]
    )
    return keyboard

@lru_cache(maxsize=1)
def get_sleep_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для сна"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Почитать сказку", callback_data="sleep_read"),
                InlineKeyboardButton(text="💤 Лечь рядом", callback_data="sleep_lay")
            ],
            [
                InlineKeyboardButton(text="😘 Поцеловать в лобик", callback_data="sleep_kiss"),
                InlineKeyboardButton(text="🎵 Спеть колыбельную", callback_data="sleep_sing")
            ],
            [
                InlineKeyboardButton(text="🧸 Дать игрушку", callback_data="sleep_toy"),
                InlineKeyboardButton(text="🌙 Просто уложить", callback_data="sleep_simple")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="sleep_back")
            ]
        ]
    )
    return keyboard

def get_care_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    """Клавиатура ухода за драконом"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Основной уход (всегда доступен)
    row1 = []
    row1.append(InlineKeyboardButton(text="✨ Расчесать лапки", callback_data="care_brush_paws"))
    row1.append(InlineKeyboardButton(text="🛁 Протереть мордочку", callback_data="care_wipe_face"))
    keyboard.inline_keyboard.append(row1)
    
    row2 = []
    row2.append(InlineKeyboardButton(text="💅 Почистить когти", callback_data="care_clean_nails"))
    row2.append(InlineKeyboardButton(text="🦷 Почистить зубы", callback_data="care_clean_teeth"))
    keyboard.inline_keyboard.append(row2)
    
    # Уход с предметами
    row3 = []
    if inventory.get("расческа", 0) > 0:
        row3.append(InlineKeyboardButton(text="💆 Расчесать шерстку", callback_data="care_brush_fur"))
    if inventory.get("шампунь", 0) > 0:
        row3.append(InlineKeyboardButton(text="🧴 Искупать", callback_data="care_bath"))
    
    if row3:
        keyboard.inline_keyboard.append(row3)
    
    row4 = []
    if inventory.get("ножницы", 0) > 0:
        row4.append(InlineKeyboardButton(text="✂️ Подстричь когти", callback_data="care_trim_nails"))
    if inventory.get("игрушка", 0) > 0:
        row4.append(InlineKeyboardButton(text="🧸 Поиграть в уход", callback_data="care_play_groom"))
    
    if row4:
        keyboard.inline_keyboard.append(row4)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="« Назад", callback_data="care_back")
    ])
    
    return keyboard

@lru_cache(maxsize=1)
def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔔 Уведомления", callback_data="settings_notifications"),
                InlineKeyboardButton(text="🌙 Режим сна", callback_data="settings_sleep_mode")
            ],
            [
                InlineKeyboardButton(text="🎨 Внешний вид", callback_data="settings_appearance"),
                InlineKeyboardButton(text="🔊 Звуки", callback_data="settings_sounds")
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="settings_stats"),
                InlineKeyboardButton(text="🔄 Сброс данных", callback_data="settings_reset")
            ],
            [
                InlineKeyboardButton(text="💾 Экспорт данных", callback_data="settings_export"),
                InlineKeyboardButton(text="📖 Справка", callback_data="settings_help")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="settings_back")
            ]
        ]
    )
    return keyboard

def get_feed_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    """Клавиатура для кормления"""
    snack_items = {
        "печенье": "🍪 Печенье",
        "шоколад": "🍫 Шоколад", 
        "зефир": "☁️ Зефир",
        "пряник": "🎄 Пряник",
        "мармелад": "🍬 Мармелад",
        "пирожное": "🎂 Пирожное"
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

# Инициализация менеджеров
rate_limiter = RateLimiter()
minigame_manager = MinigameManager()

# ==================== НАЧАЛЬНЫЙ ЭКРАН И БАЗОВЫЕ КОМАНДЫ ====================
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
            f"обожают сны, игры и тёплые объятия.\n\n"
            
            f"<b>🐾 Тебе выпала честь стать хранителем одного из них!</b>\n\n"
            
            f"<b>📋 НОВЫЕ ВОЗМОЖНОСТИ 5.0:</b>\n"
            f"• 🎮 <b>5 мини-игр</b> с разными наградами\n"
            f"• ☕ <b>Сложное приготовление кофе</b> с мини-игрой\n"
            f"• 😴 <b>Система сна</b> с разными вариантами\n"
            f"• ✨ <b>Расширенный уход</b> с предметами\n"
            f"• 🔔 <b>Умные уведомления</b> по расписанию\n"
            f"• ⚙️ <b>Настройки</b> под себя\n\n"
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
        "<b>📚 КОМАНДЫ И ВОЗМОЖНОСТИ (v5.0)</b>\n\n"
        
        "<b>🐉 ОСНОВНОЕ</b>\n"
        "<code>/start</code> - начать игру\n"
        "<code>/help</code> - эта справка\n"
        "<code>/create</code> - создать дракона\n"
        "<code>/status</code> - статус дракона\n\n"
        
        "<b>😴 СОН И ОТДЫХ</b>\n"
        "<code>/sleep</code> - уложить дракона спать\n"
        "<code>/dream</code> - присниться дракону\n\n"
        
        "<b>❤ УХОД И ЗАБОТА</b>\n"
        "<code>/coffee</code> - приготовить кофе\n"
        "<code>/feed</code> - покормить сладостями\n"
        "<code>/hug</code> - обнять дракона\n"
        "<code>/care</code> - ухаживать за драконом\n\n"
        
        "<b>🎮 РАЗВЛЕЧЕНИЯ</b>\n"
        "<code>/games</code> - поиграть в игры\n"
        "<code>/play</code> - быстрая игра\n\n"
        
        "<b>💰 ЭКОНОМИКА</b>\n"
        "<code>/shop</code> - магазин товаров\n"
        "<code>/inventory</code> - инвентарь\n"
        "<code>/gold</code> - проверить золото\n\n"
        
        "<b>⚙️ НАСТРОЙКИ</b>\n"
        "<code>/settings</code> - настройки бота\n"
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
        
        # Начальный инвентарь
        initial_inventory = {
            "кофейные_зерна": 10,
            "печенье": 5,
            "шоколад": 2,
            "вода": 3,
            "зефир": 1,
            "пряник": 1
        }
        
        # Сохраняем инвентарь
        for item, count in initial_inventory.items():
            db.update_inventory(user_id, item, count)
        
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
            f"• 💧 Вода: <code>3</code>\n"
            f"• ☁️ Зефир: <code>1</code>\n"
            f"• 🎄 Пряник: <code>1</code>\n\n"
            
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

# ==================== СТАТУС ДРАКОНА (УЛУЧШЕННЫЙ) ====================
@dp.message(Command("status"))
@dp.message(F.text == "🐉 Статус")
async def cmd_status(message: types.Message):
    """Показать статус дракона - красивый интерфейс с выровненными полосками"""
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
        
        # Создаем прогресс-бары с фиксированной шириной
        coffee_bar = create_progress_bar(dragon.stats.get("кофе", 0))
        sleep_bar = create_progress_bar(dragon.stats.get("сон", 0))
        mood_bar = create_progress_bar(dragon.stats.get("настроение", 0))
        appetite_bar = create_progress_bar(dragon.stats.get("аппетит", 0))
        energy_bar = create_progress_bar(dragon.stats.get("энергия", 0))
        fluff_bar = create_progress_bar(dragon.stats.get("пушистость", 0))
        
        # Имена показателей с фиксированной шириной
        stat_names = {
            "кофе": "☕ Кофе",
            "сон": "💤 Сон", 
            "настроение": "😊 Настроение",
            "аппетит": "🍪 Аппетит",
            "энергия": "⚡ Энергия",
            "пушистость": "✨ Пушистость"
        }
        
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
        
        # Формируем текст статуса с выровненными полосками
        status_text = (
            f"<b>🐉 {escape_html(dragon.name)} [Уровень {dragon.level}]</b>\n"
            f"⭐ <b>Опыт:</b> <code>{dragon.experience}/100</code>\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n\n"
            
            f"🎭 <b>Характер:</b> <code>{dragon.character.get('основная_черта', 'неженка')}</code>\n\n"
            
            f"<b>📊 ПОКАЗАТЕЛИ:</b>\n"
        )
        
        # Добавляем все полоски с выравниванием
        stats_data = [
            ("кофе", coffee_bar, dragon.stats.get("кофе", 0)),
            ("сон", sleep_bar, dragon.stats.get("сон", 0)),
            ("настроение", mood_bar, dragon.stats.get("настроение", 0)),
            ("аппетит", appetite_bar, dragon.stats.get("аппетит", 0)),
            ("энергия", energy_bar, dragon.stats.get("энергия", 0)),
            ("пушистость", fluff_bar, dragon.stats.get("пушистость", 0))
        ]
        
        for stat_name, bar, value in stats_data:
            name_display = stat_names.get(stat_name, stat_name)
            status_text += f"{name_display}: <code>{bar}</code> <code>{value}%</code>\n"
        
        status_text += "\n"
        
        if warnings:
            status_text += f"<b>⚠️ ВНИМАНИЕ:</b>\n"
            for warning in warnings:
                status_text += f"• {warning}\n"
            status_text += "\n"
        
        # Добавляем время последнего действия
        last_action = db.get_last_action(user_id)
        if last_action:
            status_text += f"<b>🕐 Последнее действие:</b> <code>{last_action}</code>\n\n"
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 <i>Обновлено:</i> <code>{datetime.now().strftime('%H:%M')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

# ==================== ПРИГОТОВЛЕНИЕ КОФЕ (С МИНИ-ИГРОЙ) ====================
@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message):
    """Приготовить кофе - с проверкой на полноту"""
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
        
        # Проверяем, не полон ли уже кофе
        coffee_stat = dragon.stats.get("кофе", 0)
        full_message = check_stat_full(coffee_stat, "кофе", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
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
        
        if inventory.get("вода", 0) <= 0:
            await message.answer(
                "<b>❌ Не хватает воды!</b>\n\n"
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
            "• <b>Американо</b> - классический\n"
            "• <b>Мокко</b> - шоколадный кофе\n\n"
            "• <b>🎮 Кофейный арт</b> - мини-игра на пенке!\n\n"
            
            f"☕ <i>Зерен доступно:</i> <code>{inventory.get('кофейные_зерна', 0)}</code>\n"
            f"💧 <i>Воды доступно:</i> <code>{inventory.get('вода', 0)}</code>",
            parse_mode="HTML",
            reply_markup=get_coffee_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_coffee: {e}")
        await message.answer("<b>❌ Произошла ошибка при приготовлении кофе.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("coffee_"))
async def process_coffee_choice(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора кофе"""
    try:
        user_id = callback.from_user.id
        coffee_type = callback.data.replace("coffee_", "")
        
        if coffee_type == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        if coffee_type == "art":
            # Запускаем мини-игру кофейного арта
            await callback.message.edit_text(
                "<b>🎨 КОФЕЙНЫЙ АРТ - МИНИ-ИГРА</b>\n\n"
                "<i>✨ Создай узор на кофейной пенке!</i>\n"
                "Я покажу последовательность из 3 символов,\n"
                "а ты должен её запомнить и повторить!\n\n"
                "Готов? Начинаем через 3 секунды...",
                parse_mode="HTML"
            )
            
            await asyncio.sleep(3)
            
            # Создаем игру
            game = minigame_manager.coffee_art_game()
            await state.update_data(coffee_game=game)
            
            # Показываем последовательность
            pattern_display = "   ".join(game["target"])
            await callback.message.edit_text(
                f"<b>🎨 ЗАПОМНИ ПОСЛЕДОВАТЕЛЬНОСТЬ:</b>\n\n"
                f"<code>{pattern_display}</code>\n\n"
                "У тебя 5 секунд чтобы запомнить...",
                parse_mode="HTML"
            )
            
            await asyncio.sleep(5)
            
            # Запрашиваем повторение
            await callback.message.edit_text(
                f"<b>🎨 ПОВТОРИ ПОСЛЕДОВАТЕЛЬНОСТЬ</b>\n\n"
                f"<i>Отправь 3 символа через пробел, например:</i>\n"
                f"<code>❤️ ⭐ 🐉</code>\n\n"
                f"<b>Доступные символы:</b>\n"
                f"{'   '.join(game['patterns'])}",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.coffee_minigame)
            await callback.answer()
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Используем ресурсы
        db.update_inventory(user_id, "кофейные_зерна", -1)
        db.update_inventory(user_id, "вода", -1)
        
        # Применяем действие
        result = dragon.apply_action("кофе")
        
        # Особые эффекты для разных кофе
        coffee_effects = {
            "espresso": {"энергия": 15, "сон": -10, "кофе": 25},
            "latte": {"настроение": 10, "аппетит": 5, "кофе": 15},
            "cappuccino": {"пушистость": 8, "настроение": 12, "кофе": 18},
            "raf": {"настроение": 15, "сон": 8, "кофе": 20},
            "americano": {"кофе": 20, "энергия": 10},
            "mocha": {"настроение": 20, "аппетит": 10, "кофе": 15}
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
            "americano": "американо",
            "mocha": "мокко"
        }
        
        current_coffee = coffee_names.get(coffee_type, "")
        if current_coffee == dragon.favorites.get("кофе", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + 5)
            favorite_bonus = "<b>🎉 Это его любимый кофе! +20 к настроению, +5 к кофейному мастерству</b>\n"
        else:
            favorite_bonus = ""
        
        # Повышаем навык кофейного мастерства
        dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + 2)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Приготовил {current_coffee}")
        
        # Кофейные описания
        coffee_descriptions = {
            "espresso": "Ты приготовил <b>крепкий эспрессо!</b> Дракон бодр и весел ☕",
            "latte": "Нежный <b>латте с молочной пенкой</b> готов! Дракон мурлычет от удовольствия 🥰",
            "cappuccino": "Воздушный <b>капучино с корицей!</b> Аромат стоит на всю комнату ✨",
            "raf": "Сливочный <b>раф с ванилью!</b> Дракон в восторге 🌟",
            "americano": "Классический <b>американо!</b> Просто и вкусно 👍",
            "mocha": "Шоколадный <b>мокко!</b> Идеальное сочетание кофе и шоколада 🍫"
        }
        
        # Разные реакции
        reactions = [
            f"Дракон с удовольствием прихлёбывает кофе ☕",
            f"От аромата кофе у дракона загораются глаза ✨",
            f"Дракон облизывается после первого глотка 😋",
            f"{dragon.character.get('основная_черта', '').capitalize()} наслаждается каждым глотком 🥰"
        ]
        
        response = (
            f"{coffee_descriptions.get(coffee_type, 'Кофе готов')}\n"
            f"{random.choice(reactions)}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• ☕ Кофе: +{coffee_effects.get(coffee_type, {}).get('кофе', 0)}\n"
            f"• ⚡ Энергия: +{coffee_effects.get(coffee_type, {}).get('энергия', 0)}\n"
            f"• 😊 Настроение: +{coffee_effects.get(coffee_type, {}).get('настроение', 0)}\n"
            f"• 🎨 Кофейное мастерство: +2\n"
        )
        
        if favorite_bonus:
            response += f"\n{favorite_bonus}"
        
        if result.get("level_up"):
            response += f"\n<b>🎊 {result['message']}</b>"
        
        inventory = db.get_inventory(user_id)
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Осталось зерен:</i> <code>{inventory.get('кофейные_зерна', 0)}</code>\n"
            f"💧 <i>Осталось воды:</i> <code>{inventory.get('вода', 0)}</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(GameStates.coffee_minigame)
async def process_coffee_minigame(message: types.Message, state: FSMContext):
    """Обработка мини-игры кофейного арта"""
    try:
        user_id = message.from_user.id
        
        data = await state.get_data()
        game = data.get("coffee_game")
        
        if not game:
            await message.answer("❌ Игра не найдена")
            await state.clear()
            return
        
        # Получаем ответ пользователя
        user_pattern = message.text.strip().split()
        
        # Проверяем ответ
        if user_pattern == game["target"]:
            # Победа!
            dragon_data = db.get_dragon(user_id)
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
                
                # Используем ресурсы
                db.update_inventory(user_id, "кофейные_зерна", -1)
                db.update_inventory(user_id, "вода", -1)
                
                # Награда за победу
                dragon.gold += game["reward"]["gold"]
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + game["reward"]["mood"])
                dragon.stats["энергия"] = max(0, dragon.stats.get("энергия", 0) + game["reward"]["energy"])
                dragon.skills["кофейное_мастерство"] = min(100, 
                    dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"])
                
                # Проверяем, любимый ли это кофе
                if "латте" == dragon.favorites.get("кофе", ""):
                    dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
                    favorite_bonus = "\n<b>🎉 И на любимом кофе! +15 к настроению</b>"
                else:
                    favorite_bonus = ""
                
                db.update_dragon(user_id, dragon.to_dict())
                db.add_gold(user_id, game["reward"]["gold"])
                db.record_action(user_id, "Кофейный арт - победа")
                
                response = (
                    f"<b>🎉 ИДЕАЛЬНО! Прекрасный кофейный арт! 🎉</b>\n\n"
                    f"Дракон в восторге от твоего искусства на пенке! ✨\n\n"
                    
                    f"<b>🏆 НАГРАДА:</b>\n"
                    f"• 💰 Золото: +{game['reward']['gold']}\n"
                    f"• 😊 Настроение: +{game['reward']['mood']}\n"
                    f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill']}\n"
                    f"{favorite_bonus}"
                )
            else:
                response = "<b>❌ Дракон не найден</b>"
        else:
            # Поражение
            dragon_data = db.get_dragon(user_id)
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
                dragon.stats["настроение"] = max(0, dragon.stats.get("настроение", 0) - 10)
                db.update_dragon(user_id, dragon.to_dict())
                db.record_action(user_id, "Кофейный арт - поражение")
            
            correct_pattern = "   ".join(game["target"])
            response = (
                f"<b>😔 УВЫ, НЕПРАВИЛЬНО</b>\n\n"
                f"Правильная последовательность: <code>{correct_pattern}</code>\n\n"
                f"Дракон смотрит на бесформенную пенку и вздыхает...\n"
                f"<b>😊 Настроение: -10</b>"
            )
        
        inventory = db.get_inventory(user_id)
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Осталось зерен:</i> <code>{inventory.get('кофейные_зерна', 0)}</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_minigame: {e}")
        await message.answer("<b>❌ Произошла ошибка в мини-игре.</b>", parse_mode="HTML")
        await state.clear()

# ==================== СОН (ЗАМЕНА ЧТЕНИЯ) ====================
@dp.message(Command("sleep"))
@dp.message(F.text == "😴 Сон")
async def cmd_sleep(message: types.Message):
    """Уложить дракона спать"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "sleep", 30):
            await message.answer("<b>⏳ Дракон только что спал. Подожди немного 😴</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем, не хочет ли дракон спать
        sleep_stat = dragon.stats.get("сон", 0)
        full_message = check_stat_full(sleep_stat, "сон", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        # Для книгочея - особая логика
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "книгочей":
            # 30% шанс, что книгочей захочет, чтобы ему почитали
            if random.random() < 0.3:
                await message.answer(
                    "<b>📚 КНИГОЧЕЙ ХОЧЕТ СКАЗКУ!</b>\n\n"
                    f"✨ {dragon.name} трёт глазки и просит: 'Почитай мне сказку перед сном...'\n\n"
                    "Выбери действие:",
                    parse_mode="HTML",
                    reply_markup=get_sleep_keyboard()
                )
                return
        
        await message.answer(
            f"<b>😴 УКЛАДЫВАЕМ {escape_html(dragon.name)} СПАТЬ</b>\n\n"
            f"✨ <i>Дракон зевает и потягивается...</i>\n\n"
            f"<b>💡 Как уложить дракона?</b>\n"
            f"• 📖 Почитать сказку\n"
            f"• 💤 Лечь рядом\n"
            f"• 😘 Поцеловать в лобик\n"
            f"• 🎵 Спеть колыбельную\n"
            f"• 🧸 Дать игрушку\n"
            f"• 🌙 Просто уложить\n\n"
            f"💤 <i>Текущая сонливость:</i> <code>{sleep_stat}%</code>",
            parse_mode="HTML",
            reply_markup=get_sleep_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_sleep: {e}")
        await message.answer("<b>❌ Произошла ошибка при укладывании спать.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("sleep_"))
async def process_sleep(callback: types.CallbackQuery):
    """Обработка выбора действия для сна"""
    try:
        user_id = callback.from_user.id
        sleep_action = callback.data.replace("sleep_", "")
        
        if sleep_action == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Разные описания для разных действий
        sleep_descriptions = {
            "read": [
                f"📖 Ты читаешь {dragon.name} сказку о кофейных драконах...",
                f"📖 'Жили-были в кофейных горах...' - начинаешь ты сказку",
                f"📖 Дракон слушает сказку, медленно закрывая глазки"
            ],
            "lay": [
                f"💤 Ты ложишься рядом с {dragon.name}, обнимая его",
                f"💤 Дракон прижимается к тебе, ища тепла",
                f"💤 Рядом с тобой {dragon.name} чувствует себя в безопасности"
            ],
            "kiss": [
                f"😘 Ты нежно целуешь {dragon.name} в лобик",
                f"😘 Дракон мурлычет от нежности",
                f"😘 Поцелуй в лобик - лучший способ уложить дракона спать"
            ],
            "sing": [
                f"🎵 Ты напеваешь колыбельную для {dragon.name}",
                f"🎵 'Спи, моя радость, усни...' - поёшь ты тихо",
                f"🎵 Под твою колыбельную дракон быстро засыпает"
            ],
            "toy": [
                f"🧸 Ты даёшь {dragon.name} его любимую игрушку",
                f"🧸 Дракон обнимает игрушку и закрывает глаза",
                f"🧸 С игрушкой в лапках дракон засыпает быстрее"
            ],
            "simple": [
                f"🌙 Ты укладываешь {dragon.name} в его уютную лежанку",
                f"🌙 'Спокойной ночи' - говоришь ты, накрывая дракона одеялком",
                f"🌙 Дракон сворачивается калачиком и засыпает"
            ]
        }
        
        # Применяем действие
        result = dragon.apply_action("сон")
        
        # Бонусы для разных действий
        action_bonuses = {
            "read": {"сон": 25, "настроение": 15, "литературный_вкус": 5},
            "lay": {"сон": 20, "настроение": 20},
            "kiss": {"сон": 15, "настроение": 25},
            "sing": {"сон": 20, "настроение": 10},
            "toy": {"сон": 15, "настроение": 15},
            "simple": {"сон": 10, "настроение": 5}
        }
        
        if sleep_action in action_bonuses:
            for stat, bonus in action_bonuses[sleep_action].items():
                if stat in dragon.stats:
                    dragon.stats[stat] = min(100, dragon.stats[stat] + bonus)
                elif stat in dragon.skills:
                    dragon.skills[stat] = min(100, dragon.skills.get(stat, 0) + bonus)
        
        # Бонус для сонь
        if dragon.character.get("основная_черта") == "соня":
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 10)
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            character_bonus = "\n<b>😴 Соня обожает спать! +10 к сну, +15 к настроению</b>"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уложил спать ({sleep_action})")
        
        # Формируем ответ
        descriptions = sleep_descriptions.get(sleep_action, ["Дракон засыпает..."])
        response = (
            f"{random.choice(descriptions)}\n\n"
            
            f"<b>📊 ПОСЛЕ СНА:</b>\n"
            f"• 😴 Сон: +{action_bonuses.get(sleep_action, {}).get('сон', 0)}\n"
            f"• 😊 Настроение: +{action_bonuses.get(sleep_action, {}).get('настроение', 0)}\n"
        )
        
        if sleep_action == "read":
            response += f"• 📚 Литературный вкус: +5\n"
        
        response += character_bonus
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💤 <i>Теперь сонливость:</i> <code>{dragon.stats.get('сон', 0)}%</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_sleep: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== МИНИ-ИГРЫ (5 ВИДОВ) ====================
@dp.message(Command("games"))
@dp.message(F.text == "🎮 Игры")
async def cmd_games(message: types.Message):
    """Выбор мини-игр"""
    try:
        user_id = message.from_user.id
        
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
                "• Дайте ему отдохнуть 😴\n"
                "• Приготовьте кофе ☕",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await message.answer(
            "<b>🎮 ВЫБЕРИ МИНИ-ИГРУ</b>\n\n"
            
            "<b>✨ Доступные игры:</b>\n"
            "• 🔢 <b>Угадай число</b> - классическая игра\n"
            "• 🎯 <b>Кофейный арт</b> - запомни последовательность\n"
            "• 🧩 <b>Найди отличия</b> - внимание и зоркость\n"
            "• 🃏 <b>Карточная дуэль</b> - удача и стратегия\n"
            "• 🍪 <b>Лови печенье</b> - реакция и скорость\n"
            "• 🎲 <b>Кости</b> - простая азартная игра\n\n"
            
            f"⚡ <i>Энергия дракона:</i> <code>{dragon.stats.get('энергия', 0)}%</code>\n"
            f"🎭 <i>Характер:</i> <code>{dragon.character.get('основная_черта', '')}</code>",
            parse_mode="HTML",
            reply_markup=get_minigames_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_games: {e}")
        await message.answer("<b>❌ Произошла ошибка при выборе игр.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("game_"))
async def process_game_choice(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора мини-игры"""
    try:
        user_id = callback.from_user.id
        game_type = callback.data.replace("game_", "")
        
        if game_type in ["back", "close"]:
            if game_type == "close":
                await callback.message.delete()
            else:
                await callback.message.edit_text(
                    "<b>🎮 Возвращаемся...</b>",
                    parse_mode="HTML"
                )
            await callback.answer("↩️ Возвращаемся" if game_type == "back" else "❌ Закрыто")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверка ограничителя частоты для игр
        if not rate_limiter.can_perform_action(user_id, f"game_{game_type}", 60):
            await callback.answer("⏳ Слишком часто играешь в эту игру!")
            return
        
        # Тратим энергию
        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] - 20)
        db.update_dragon(user_id, dragon.to_dict())
        
        # Запускаем выбранную игру
        if game_type == "guess":
            game = minigame_manager.guess_number_game()
            await state.update_data(current_game=game)
            await state.set_state(GameStates.minigame_state)
            
            await callback.message.edit_text(
                f"<b>🔢 ИГРА: УГАДАЙ ЧИСЛО</b>\n\n"
                f"{game['hints'][0]}\n\n"
                f"<i>Отправь число от 1 до 10:</i>",
                parse_mode="HTML"
            )
            
        elif game_type == "coffee_art":
            game = minigame_manager.coffee_art_game()
            await state.update_data(current_game=game)
            
            # Показываем последовательность
            pattern_display = "   ".join(game["target"])
            await callback.message.edit_text(
                f"<b>🎨 ИГРА: КОФЕЙНЫЙ АРТ</b>\n\n"
                f"<i>{game['description']}</i>\n\n"
                f"<b>ЗАПОМНИ:</b> <code>{pattern_display}</code>\n\n"
                f"У тебя 5 секунд...",
                parse_mode="HTML"
            )
            
            await asyncio.sleep(5)
            
            await callback.message.edit_text(
                f"<b>🎨 ПОВТОРИ ПОСЛЕДОВАТЕЛЬНОСТЬ</b>\n\n"
                f"<i>Отправь 3 символа через пробел:</i>\n"
                f"<code>❤️ ⭐ 🐉</code>\n\n"
                f"<b>Доступные символы:</b>\n"
                f"{'   '.join(game['patterns'])}",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.minigame_state)
            
        elif game_type == "find_diff":
            game = minigame_manager.find_differences_game()
            await state.update_data(current_game=game)
            await state.set_state(GameStates.minigame_state)
            
            differences_emoji = "🔍 " * game["differences"]
            await callback.message.edit_text(
                f"<b>🧩 ИГРА: НАЙДИ ОТЛИЧИЯ</b>\n\n"
                f"{game['description']}\n\n"
                f"<i>Представь, что перед тобой две картинки с драконом.\n"
                f"Сколько отличий ты найдёшь?</i>\n\n"
                f"🔍 Отличий: {differences_emoji}\n\n"
                f"<b>Отправь число от {game['differences']-2} до {game['differences']+2}:</b>",
                parse_mode="HTML"
            )
            
        elif game_type == "card_duel":
            game = minigame_manager.card_duel_game()
            await state.update_data(current_game=game)
            
            # Немедленный результат для карточной дуэли
            player_value = game["card_values"][game["player_card"]]
            dragon_value = game["card_values"][game["dragon_card"]]
            
            if player_value > dragon_value:
                # Победа
                dragon.gold += game["reward_win"]["gold"]
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward_win"]["mood"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward_win"]["energy"])
                dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 5)
                
                result_text = (
                    f"<b>🎉 ПОБЕДА!</b>\n\n"
                    f"Твоя карта: <b>{game['player_card']}</b> ({player_value})\n"
                    f"Карта дракона: <b>{game['dragon_card']}</b> ({dragon_value})\n\n"
                    f"<b>🏆 НАГРАДА:</b>\n"
                    f"• 💰 Золото: +{game['reward_win']['gold']}\n"
                    f"• 😊 Настроение: +{game['reward_win']['mood']}\n"
                    f"• 🎮 Игровая эрудиция: +5\n"
                )
            elif player_value < dragon_value:
                # Поражение
                dragon.gold += game["reward_lose"]["gold"]
                dragon.stats["настроение"] = max(0, dragon.stats["настроение"] + game["reward_lose"]["mood"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward_lose"]["energy"])
                dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 2)
                
                result_text = (
                    f"<b>😔 ПОРАЖЕНИЕ</b>\n\n"
                    f"Твоя карта: <b>{game['player_card']}</b> ({player_value})\n"
                    f"Карта дракона: <b>{game['dragon_card']}</b> ({dragon_value})\n\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 💰 Золото: +{game['reward_lose']['gold']}\n"
                    f"• 😊 Настроение: {game['reward_lose']['mood']}\n"
                    f"• 🎮 Игровая эрудиция: +2\n"
                )
            else:
                # Ничья
                dragon.gold += 15
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
                dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 3)
                
                result_text = (
                    f"<b>🤝 НИЧЬЯ!</b>\n\n"
                    f"Обе карты: <b>{game['player_card']}</b> ({player_value})\n\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 💰 Золото: +15\n"
                    f"• 😊 Настроение: +10\n"
                    f"• 🎮 Игровая эрудиция: +3\n"
                )
            
            # Бонус для игрика
            if dragon.character.get("основная_черта") == "игрик":
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
                result_text += "\n<b>🎮 Игрик обожает игры! +10 к настроению</b>"
            
            db.update_dragon(user_id, dragon.to_dict())
            db.add_gold(user_id, dragon.gold - db.get_gold(user_id))
            db.record_action(user_id, f"Карточная дуэль - {'победа' if player_value > dragon_value else 'поражение' if player_value < dragon_value else 'ничья'}")
            
            result_text += (
                f"\n\n━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <i>Золото:</i> <code>{dragon.gold}</code>\n"
                f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>\n"
                f"⚡ <i>Энергия:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
            )
            
            await callback.message.edit_text(result_text, parse_mode="HTML")
            await callback.answer()
            return
            
        elif game_type == "catch_cookie":
            game = minigame_manager.catch_cookie_game()
            await state.update_data(current_game=game)
            await state.set_state(GameStates.minigame_state)
            
            await callback.message.edit_text(
                f"<b>🍪 ИГРА: ЛОВИ ПЕЧЕНЬЕ</b>\n\n"
                f"{game['description']}\n\n"
                f"<i>Представь, что печенья падают с неба!\n"
                f"Сколько ты успеешь поймать?</i>\n\n"
                f"<b>Отправь число от {game['cookies']-3} до {game['cookies']+3}:</b>",
                parse_mode="HTML"
            )
            
        elif game_type == "dice":
            game = minigame_manager.dice_game()
            await state.update_data(current_game=game)
            
            # Бросаем кости
            player_dice = random.randint(1, 6) + random.randint(1, 6)
            dragon_dice = random.randint(1, 6) + random.randint(1, 6)
            
            if player_dice > dragon_dice:
                # Победа
                dragon.gold += game["reward_win"]["gold"]
                dragon.stats["настройение"] = min(100, dragon.stats["настроение"] + game["reward_win"]["mood"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward_win"]["energy"])
                
                result_text = (
                    f"<b>🎲 РЕЗУЛЬТАТ КОСТЕЙ</b>\n\n"
                    f"Твои кости: <b>{player_dice}</b>\n"
                    f"Кости дракона: <b>{dragon_dice}</b>\n\n"
                    f"<b>🎉 ПОБЕДА!</b>\n\n"
                    f"<b>🏆 НАГРАДА:</b>\n"
                    f"• 💰 Золото: +{game['reward_win']['gold']}\n"
                    f"• 😊 Настроение: +{game['reward_win']['mood']}\n"
                )
            elif player_dice < dragon_dice:
                # Поражение
                dragon.gold += game["reward_lose"]["gold"]
                dragon.stats["настроение"] = max(0, dragon.stats["настроение"] + game["reward_lose"]["mood"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward_lose"]["energy"])
                
                result_text = (
                    f"<b>🎲 РЕЗУЛЬТАТ КОСТЕЙ</b>\n\n"
                    f"Твои кости: <b>{player_dice}</b>\n"
                    f"Кости дракона: <b>{dragon_dice}</b>\n\n"
                    f"<b>😔 ПОРАЖЕНИЕ</b>\n\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 💰 Золото: +{game['reward_lose']['gold']}\n"
                    f"• 😊 Настроение: {game['reward_lose']['mood']}\n"
                )
            else:
                # Ничья
                dragon.gold += 20
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
                
                result_text = (
                    f"<b>🎲 РЕЗУЛЬТАТ КОСТЕЙ</b>\n\n"
                    f"Твои кости: <b>{player_dice}</b>\n"
                    f"Кости дракона: <b>{dragon_dice}</b>\n\n"
                    f"<b>🤝 НИЧЬЯ!</b>\n\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 💰 Золото: +20\n"
                    f"• 😊 Настроение: +15\n"
                )
            
            db.update_dragon(user_id, dragon.to_dict())
            db.add_gold(user_id, dragon.gold - db.get_gold(user_id))
            db.record_action(user_id, f"Кости - {'победа' if player_dice > dragon_dice else 'поражение' if player_dice < dragon_dice else 'ничья'}")
            
            result_text += (
                f"\n\n━━━━━━━━━━━━━━━━━━━\n"
                f"💰 <i>Золото:</i> <code>{dragon.gold}</code>\n"
                f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
            )
            
            await callback.message.edit_text(result_text, parse_mode="HTML")
            await callback.answer()
            return
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_game_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(GameStates.minigame_state)
async def process_minigame_answer(message: types.Message, state: FSMContext):
    """Обработка ответов в мини-играх"""
    try:
        user_id = message.from_user.id
        user_answer = message.text.strip()
        
        data = await state.get_data()
        game = data.get("current_game")
        
        if not game:
            await message.answer("❌ Игра не найдена")
            await state.clear()
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("❌ Дракон не найден")
            await state.clear()
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обработка разных игр
        if game["type"] == "guess":
            try:
                guess = int(user_answer)
                if 1 <= guess <= 10:
                    if guess == game["secret"]:
                        # Победа
                        dragon.gold += game["reward"]["gold"]
                        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                        dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 3)
                        
                        result_text = (
                            f"<b>🎉 ПРАВИЛЬНО!</b> Загаданное число: <code>{game['secret']}</code>\n\n"
                            f"✨ <i>Дракон радостно подпрыгивает</i>\n\n"
                            
                            f"<b>🏆 НАГРАДА:</b>\n"
                            f"• 💰 Золото: +{game['reward']['gold']}\n"
                            f"• 😊 Настроение: +{game['reward']['mood']}\n"
                            f"• 🎮 Игровая эрудиция: +3\n"
                        )
                    else:
                        # Поражение
                        dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
                        dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 1)
                        
                        result_text = (
                            f"<b>😔 НЕ УГАДАЛ!</b> Загаданное число: <code>{game['secret']}</code>\n\n"
                            f"✨ <i>Дракон немного расстроился...</i>\n\n"
                            
                            f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                            f"• 😊 Настроение: -5\n"
                            f"• 🎮 Игровая эрудиция: +1\n"
                        )
                    
                    # Бонус для игрика
                    if dragon.character.get("основная_черта") == "игрик":
                        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
                        result_text += "\n\n<b>🎮 Игрик обожает игры! +10 к настроению</b>"
                else:
                    result_text = "<b>❌ Число должно быть от 1 до 10!</b>"
            except ValueError:
                result_text = "<b>❌ Введи число!</b>"
        
        elif game["type"] == "coffee_art":
            user_pattern = user_answer.split()
            if user_pattern == game["target"]:
                # Победа
                dragon.gold += game["reward"]["gold"]
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                dragon.skills["кофейное_мастерство"] = min(100, 
                    dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                
                result_text = (
                    f"<b>🎉 ИДЕАЛЬНО! Прекрасный кофейный арт! 🎉</b>\n\n"
                    f"Дракон в восторге от твоего искусства! ✨\n\n"
                    
                    f"<b>🏆 НАГРАДА:</b>\n"
                    f"• 💰 Золото: +{game['reward']['gold']}\n"
                    f"• 😊 Настроение: +{game['reward']['mood']}\n"
                    f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill']}\n"
                )
            else:
                # Поражение
                dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 10)
                dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + 1)
                
                correct_pattern = "   ".join(game["target"])
                result_text = (
                    f"<b>😔 УВЫ, НЕПРАВИЛЬНО</b>\n\n"
                    f"Правильная последовательность: <code>{correct_pattern}</code>\n\n"
                    f"Дракон смотрит на бесформенную пенку и вздыхает...\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 😊 Настроение: -10\n"
                    f"• 🎨 Кофейное мастерство: +1\n"
                )
        
        elif game["type"] == "find_diff":
            try:
                guess = int(user_answer)
                target = game["differences"]
                difference = abs(guess - target)
                
                if difference == 0:
                    # Идеально
                    dragon.gold += game["reward"]["gold"]
                    dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                    dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                    
                    result_text = (
                        f"<b>🎉 ИДЕАЛЬНО!</b> Правильное количество: <code>{target}</code>\n\n"
                        f"✨ <i>Дракон впечатлён твоей внимательностью!</i>\n\n"
                        
                        f"<b>🏆 НАГРАДА:</b>\n"
                        f"• 💰 Золото: +{game['reward']['gold']}\n"
                        f"• 😊 Настроение: +{game['reward']['mood']}\n"
                    )
                elif difference <= 1:
                    # Близко
                    dragon.gold += game["reward"]["gold"] // 2
                    dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"] // 2)
                    
                    result_text = (
                        f"<b>👍 БЛИЗКО!</b> Правильное количество: <code>{target}</code>\n"
                        f"Твой ответ: <code>{guess}</code>\n\n"
                        
                        f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                        f"• 💰 Золото: +{game['reward']['gold'] // 2}\n"
                        f"• 😊 Настроение: +{game['reward']['mood'] // 2}\n"
                    )
                else:
                    # Далеко
                    dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
                    
                    result_text = (
                        f"<b>😔 НЕ ОЧЕНЬ...</b> Правильное количество: <code>{target}</code>\n"
                        f"Твой ответ: <code>{guess}</code>\n\n"
                        
                        f"✨ <i>Дракон показывает тебе отличия</i>\n"
                        f"<b>😊 Настроение: -5</b>"
                    )
            except ValueError:
                result_text = "<b>❌ Введи число!</b>"
        
        elif game["type"] == "catch_cookie":
            try:
                guess = int(user_answer)
                target = game["cookies"]
                caught = min(guess, target * 2)  # Максимум в 2 раза больше цели
                
                if caught >= target:
                    # Успех
                    reward_multiplier = min(caught / target, 2.0)
                    gold_reward = int(game["reward"]["gold"] * reward_multiplier)
                    mood_reward = int(game["reward"]["mood"] * reward_multiplier)
                    
                    dragon.gold += gold_reward
                    dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + mood_reward)
                    dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                    
                    result_text = (
                        f"<b>🍪 УСПЕХ!</b> Нужно было поймать: <code>{target}</code>\n"
                        f"Ты поймал: <code>{caught}</code>\n\n"
                        
                        f"✨ <i>Дракон уплетает печенья!</i>\n\n"
                        
                        f"<b>🏆 НАГРАДА:</b>\n"
                        f"• 💰 Золото: +{gold_reward}\n"
                        f"• 😊 Настроение: +{mood_reward}\n"
                    )
                else:
                    # Неудача
                    dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
                    
                    result_text = (
                        f"<b>😔 МАЛОВАТО...</b> Нужно было поймать: <code>{target}</code>\n"
                        f"Ты поймал: <code>{caught}</code>\n\n"
                        
                        f"✨ <i>Дракон смотрит на пустую тарелку...</i>\n"
                        f"<b>😊 Настроение: -5</b>"
                    )
            except ValueError:
                result_text = "<b>❌ Введи число!</b>"
        
        else:
            result_text = "<b>❌ Неизвестная игра</b>"
        
        # Сохраняем изменения дракона
        db.update_dragon(user_id, dragon.to_dict())
        if "gold" in locals() and dragon.gold > db.get_gold(user_id):
            db.add_gold(user_id, dragon.gold - db.get_gold(user_id))
        
        db.record_action(user_id, f"Мини-игра: {game['type']}")
        
        # Добавляем статистику
        result_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <i>Золото:</i> <code>{dragon.gold}</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>\n"
            f"⚡ <i>Энергия:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
        )
        
        await message.answer(result_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_minigame_answer: {e}")
        await message.answer("<b>❌ Произошла ошибка в игре.</b>", parse_mode="HTML")
        await state.clear()

# ==================== УХОД ЗА ДРАКОНОМ (РАСШИРЕННЫЙ) ====================
@dp.message(Command("care"))
@dp.message(F.text == "✨ Уход")
async def cmd_care(message: types.Message):
    """Уход за драконом"""
    try:
        user_id = message.from_user.id
        
        # Проверка ограничителя частоты
        if not rate_limiter.can_perform_action(user_id, "care", 300):
            await message.answer("<b>✨ Дракон уже ухожен. Подожди немного</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем, не идеальная ли уже пушистость
        fluff_stat = dragon.stats.get("пушистость", 0)
        full_message = check_stat_full(fluff_stat, "пушистость", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        inventory = db.get_inventory(user_id)
        
        await message.answer(
            f"<b>✨ УХОД ЗА {escape_html(dragon.name)}</b>\n\n"
            
            f"✨ <i>Пушистость дракона:</i> <code>{fluff_stat}%</code>\n\n"
            
            f"<b>💡 Доступные действия:</b>\n"
            f"• ✨ Расчесать лапки (всегда)\n"
            f"• 🛁 Протереть мордочку (всегда)\n"
            f"• 💅 Почистить когти (всегда)\n"
            f"• 🦷 Почистить зубы (всегда)\n"
        )
        
        # Показываем доступные действия с предметами
        if inventory.get("расческа", 0) > 0:
            await message.answer(
                "• 💆 Расчесать шерстку (нужна расческа)\n",
                parse_mode="HTML"
            )
        
        if inventory.get("шампунь", 0) > 0:
            await message.answer(
                "• 🧴 Искупать (нужен шампунь)\n",
                parse_mode="HTML"
            )
        
        if inventory.get("ножницы", 0) > 0:
            await message.answer(
                "• ✂️ Подстричь когти (нужны ножницы)\n",
                parse_mode="HTML"
            )
        
        if inventory.get("игрушка", 0) > 0:
            await message.answer(
                "• 🧸 Поиграть в уход (нужна игрушка)\n",
                parse_mode="HTML"
            )
        
        await message.answer(
            "\n<b>🛍️ Нет предметов?</b> Купи в магазине!\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "<i>Выбери действие:</i>",
            parse_mode="HTML",
            reply_markup=get_care_keyboard(inventory)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_care: {e}")
        await message.answer("<b>❌ Произошла ошибка при уходе.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("care_"))
async def process_care(callback: types.CallbackQuery):
    """Обработка ухода за драконом"""
    try:
        user_id = callback.from_user.id
        care_action = callback.data.replace("care_", "")
        
        if care_action == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        # Проверяем наличие предметов для определенных действий
        item_requirements = {
            "brush_fur": ("расческа", "💆 Расчесать шерстку"),
            "bath": ("шампунь", "🧴 Искупать"),
            "trim_nails": ("ножницы", "✂️ Подстричь когти"),
            "play_groom": ("игрушка", "🧸 Поиграть в уход")
        }
        
        if care_action in item_requirements:
            item_name, action_name = item_requirements[care_action]
            if inventory.get(item_name, 0) <= 0:
                await callback.answer(
                    f"❌ Сначала купи {item_name} в магазине!",
                    show_alert=True
                )
                return
            
            # Используем предмет
            db.update_inventory(user_id, item_name, -1)
        
        # Применяем действие
        result = dragon.apply_action("уход")
        
        # Эффекты разных действий
        care_effects = {
            "brush_paws": {"пушистость": 10, "настроение": 5},
            "wipe_face": {"пушистость": 8, "настроение": 8},
            "clean_nails": {"пушистость": 12, "настроение": 3},
            "clean_teeth": {"пушистость": 5, "настроение": 10},
            "brush_fur": {"пушистость": 25, "настроение": 15},
            "bath": {"пушистость": 30, "настроение": 20, "энергия": -10},
            "trim_nails": {"пушистость": 15, "настроение": 5},
            "play_groom": {"пушистость": 20, "настроение": 25, "энергия": -5}
        }
        
        if care_action in care_effects:
            for stat, change in care_effects[care_action].items():
                if stat in dragon.stats:
                    dragon.stats[stat] = max(0, min(100, dragon.stats[stat] + change))
        
        # Бонус для чистюли
        if dragon.character.get("основная_черта") == "чистюля":
            dragon.stats["пушистость"] = min(100, dragon.stats["пушистость"] + 15)
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            character_bonus = "\n<b>✨ Чистюля сияет от счастья! +15 к пушистости, +20 к настроению</b>"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уход: {care_action}")
        
        # Описания действий
        care_descriptions = {
            "brush_paws": [
                f"✨ Ты аккуратно расчёсываешь лапки {dragon.name}",
                f"✨ Дракон поднимает лапки одну за другой",
                f"✨ После расчёсывания лапки дракона стали мягкими"
            ],
            "wipe_face": [
                f"🛁 Ты протираешь мордочку {dragon.name} влажной салфеткой",
                f"🛁 Дракон мурлычет, когда ты вытираешь ему мордочку",
                f"🛁 Мордочка дракона теперь чистая и сияющая"
            ],
            "clean_nails": [
                f"💅 Ты чистишь когти {dragon.name} специальной щёточкой",
                f"💅 Дракон терпеливо позволяет чистить каждый коготок",
                f"💅 Когти дракона теперь блестят и не цепляются"
            ],
            "clean_teeth": [
                f"🦷 Ты чистишь зубы {dragon.name} драконьей зубной пастой",
                f"🦷 Дракон открывает рот, показывая острые зубки",
                f"🦷 После чистки зубки дракона сияют белизной"
            ],
            "brush_fur": [
                f"💆 Ты расчёсываешь шерстку {dragon.name} специальной расчёской",
                f"💆 Дракон мурлычет от удовольствия, когда ты его расчёсываешь",
                f"💆 Шерстка дракона теперь блестит и переливается"
            ],
            "bath": [
                f"🧴 Ты купаешь {dragon.name} с ароматным шампунем",
                f"🧴 Дракон плещется в тёплой воде и пускает пузыри",
                f"🧴 После купания дракон пахнет цветами и свежестью"
            ],
            "trim_nails": [
                f"✂️ Ты аккуратно подстригаешь когти {dragon.name}",
                f"✂️ Дракон доверчиво даёт свои лапки",
                f"✂️ Теперь когти дракона идеальной длины"
            ],
            "play_groom": [
                f"🧸 Ты играешь с {dragon.name} во время ухода",
                f"🧸 Дракон весело прыгает, пока ты его причёсываешь",
                f"🧸 Уход превращается в весёлую игру"
            ]
        }
        
        descriptions = care_descriptions.get(care_action, ["Ты ухаживаешь за драконом"])
        
        response = (
            f"{random.choice(descriptions)}\n\n"
            
            f"<b>📊 РЕЗУЛЬТАТ УХОДА:</b>\n"
            f"• ✨ Пушистость: +{care_effects.get(care_action, {}).get('пушистость', 0)}\n"
            f"• 😊 Настроение: +{care_effects.get(care_action, {}).get('настроение', 0)}\n"
        )
        
        if care_action in ["bath", "play_groom"]:
            response += f"• ⚡ Энергия: {care_effects[care_action].get('энергия', 0)}\n"
        
        response += character_bonus
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Показываем оставшиеся предметы
        if care_action in item_requirements:
            item_name, _ = item_requirements[care_action]
            remaining = inventory.get(item_name, 0) - (1 if inventory.get(item_name, 0) > 0 else 0)
            response += f"\n\n📦 <i>Осталось {item_name}:</i> <code>{remaining}</code>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Текущая пушистость:</i> <code>{dragon.stats.get('пушистость', 0)}%</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_care: {e}")
        await callback.answer("❌ Произошла ошибка при уходе")

# ==================== МАГАЗИН (РАСШИРЕННЫЙ) ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message):
    """Магазин с новыми товарами"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        gold = db.get_gold(user_id)
        inventory = db.get_inventory(user_id)
        
        shop_text = (
            f"<b>🛍️ МАГАЗИН КОФЕЙНОГО ДРАКОНА v5.0</b>\n\n"
            
            f"💰 <b>ТВОЙ БАЛАНС:</b> <code>{gold} золота</code>\n\n"
            
            f"<b>📦 ТВОЙ ИНВЕНТАРЬ:</b>\n"
            f"• ☕ Зерна: <code>{inventory.get('кофейные_зерна', 0)}</code>\n"
            f"• 🍪 Печенье: <code>{inventory.get('печенье', 0)}</code>\n"
            f"• 🍫 Шоколад: <code>{inventory.get('шоколад', 0)}</code>\n"
            f"• 🍬 Мармелад: <code>{inventory.get('мармелад', 0)}</code>\n"
            f"• 🎂 Пирожное: <code>{inventory.get('пирожное', 0)}</code>\n"
            f"• ☁️ Зефир: <code>{inventory.get('зефир', 0)}</code>\n\n"
            
            f"<b>✨ ПРЕДМЕТЫ УХОДА:</b>\n"
            f"• 💆 Расческа: <code>{inventory.get('расческа', 0)}</code>\n"
            f"• 🧴 Шампунь: <code>{inventory.get('шампунь', 0)}</code>\n"
            f"• ✂️ Ножницы: <code>{inventory.get('ножницы', 0)}</code>\n"
            f"• 🧸 Игрушка: <code>{inventory.get('игрушка', 0)}</code>\n\n"
        )
        
        # Добавляем объяснение товаров
        shop_text += (
            f"<b>🛒 ТОВАРЫ ДЛЯ ПОКУПКИ:</b>\n"
            f"• ☕ Кофейные зерна - 10💰 (для кофе)\n"
            f"• 🍪 Печенье - 5💰 (кормление, +10 настроение)\n"
            f"• 🍫 Шоколад - 15💰 (кормление, +15 настроение)\n"
            f"• 🍬 Мармелад - 8💰 (кормление, +12 настроение)\n"
            f"• 🎂 Пирожное - 12💰 (кормление, +18 настроение)\n"
            f"• ☁️ Зефир - 7💰 (кормление, +8 настроение)\n"
            f"• 💆 Расческа - 25💰 (уход: расчесать шерстку)\n"
            f"• 🧴 Шампунь - 30💰 (уход: искупать дракона)\n"
            f"• ✂️ Ножницы - 20💰 (уход: подстричь когти)\n"
            f"• 🧸 Игрушка - 15💰 (сон и уход)\n\n"
        )
        
        shop_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Выбери товар для покупки:</i>"
        )
        
        await message.answer(shop_text, parse_mode="HTML", reply_markup=get_shop_keyboard())
        
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
        
        # Цены и названия товаров
        shop_items = {
            "coffee": {"price": 10, "name": "кофейные_зерна", "display": "☕ Кофейные зерна"},
            "cookie": {"price": 5, "name": "печенье", "display": "🍪 Печенье"},
            "chocolate": {"price": 15, "name": "шоколад", "display": "🍫 Шоколад"},
            "marmalade": {"price": 8, "name": "мармелад", "display": "🍬 Мармелад"},
            "cake": {"price": 12, "name": "пирожное", "display": "🎂 Пирожное"},
            "marshmallow": {"price": 7, "name": "зефир", "display": "☁️ Зефир"},
            "brush": {"price": 25, "name": "расческа", "display": "💆 Расческа"},
            "shampoo": {"price": 30, "name": "шампунь", "display": "🧴 Шампунь"},
            "scissors": {"price": 20, "name": "ножницы", "display": "✂️ Ножницы"},
            "toy": {"price": 15, "name": "игрушка", "display": "🧸 Игрушка"}
        }
        
        if action in shop_items:
            item = shop_items[action]
            price = item["price"]
            item_name = item["name"]
            display_name = item["display"]
            
            if gold >= price:
                # Покупаем
                db.add_gold(user_id, -price)
                db.update_inventory(user_id, item_name, 1)
                
                new_gold = gold - price
                inventory = db.get_inventory(user_id)
                
                await callback.message.edit_text(
                    f"<b>✅ ПОКУПКА СОВЕРШЕНА!</b>\n\n"
                    
                    f"✨ <i>Куплено:</i> {display_name}\n"
                    f"💰 <i>Цена:</i> <code>{price} золота</code>\n"
                    f"💰 <i>Остаток:</i> <code>{new_gold} золота</code>\n\n"
                    
                    f"<b>📦 ТЕПЕРЬ В ИНВЕНТАРЕ:</b>\n"
                    f"• {display_name}: <code>{inventory.get(item_name, 0)}</code>\n\n"
                    
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Хочешь купить что-нибудь ещё?</i>",
                    parse_mode="HTML",
                    reply_markup=get_shop_keyboard()
                )
                await callback.answer("✅ Покупка успешна!")
                
                # Записываем действие
                db.record_action(user_id, f"Купил {display_name}")
            else:
                await callback.answer(f"❌ Недостаточно золота! Нужно {price}💰, а у тебя {gold}💰", show_alert=True)
        else:
            await callback.answer("❌ Неизвестный товар")
            
    except Exception as e:
        logger.error(f"Ошибка в process_shop: {e}")
        await callback.answer("❌ Произошла ошибка при покупке")

# ==================== НАСТРОЙКИ ====================
@dp.message(Command("settings"))
@dp.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: types.Message):
    """Настройки бота"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        # Получаем текущие настройки пользователя
        user_settings = db.get_user_settings(user_id)
        
        settings_text = (
            f"<b>⚙️ НАСТРОЙКИ КОФЕЙНОГО ДРАКОНА</b>\n\n"
            
            f"<b>🔔 УВЕДОМЛЕНИЯ:</b>\n"
            f"• Утренние напоминания: <code>{'ВКЛ' if user_settings.get('morning_notifications', True) else 'ВЫКЛ'}</code>\n"
            f"• Вечерние напоминания: <code>{'ВКЛ' if user_settings.get('evening_notifications', True) else 'ВЫКЛ'}</code>\n"
            f"• Напоминания о кормлении: <code>{'ВКЛ' if user_settings.get('feeding_reminders', True) else 'ВЫКЛ'}</code>\n\n"
            
            f"<b>🌙 РЕЖИМ:</b>\n"
            f"• Ночной режим: <code>{'ВКЛ' if user_settings.get('night_mode', False) else 'ВЫКЛ'}</code>\n"
            f"• Тихий режим: <code>{'ВКЛ' if user_settings.get('quiet_mode', False) else 'ВЫКЛ'}</code>\n\n"
            
            f"<b>🎨 ВНЕШНИЙ ВИД:</b>\n"
            f"• Тема: <code>{user_settings.get('theme', 'Стандартная')}</code>\n"
            f"• Размер шрифта: <code>{user_settings.get('font_size', 'Средний')}</code>\n\n"
            
            f"<b>🔊 ЗВУКИ:</b>\n"
            f"• Звуки уведомлений: <code>{'ВКЛ' if user_settings.get('sound_effects', True) else 'ВЫКЛ'}</code>\n"
            f"• Фоновая музыка: <code>{'ВКЛ' if user_settings.get('background_music', False) else 'ВЫКЛ'}</code>\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Выбери настройку для изменения:</i>"
        )
        
        await message.answer(settings_text, parse_mode="HTML", reply_markup=get_settings_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_settings: {e}")
        await message.answer("<b>❌ Произошла ошибка при открытии настроек.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("settings_"))
async def process_settings(callback: types.CallbackQuery):
    """Обработка настроек"""
    try:
        user_id = callback.from_user.id
        setting = callback.data.replace("settings_", "")
        
        if setting == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        # Здесь будет логика изменения настроек
        # Пока просто показываем сообщение
        
        settings_descriptions = {
            "notifications": "🔔 Настройки уведомлений",
            "sleep_mode": "🌙 Режим сна дракона", 
            "appearance": "🎨 Внешний вид интерфейса",
            "sounds": "🔊 Звуки и музыка",
            "stats": "📊 Статистика использования",
            "reset": "🔄 Сброс данных (осторожно!)",
            "export": "💾 Экспорт данных дракона",
            "help": "📖 Помощь по настройкам"
        }
        
        description = settings_descriptions.get(setting, "Настройка")
        
        await callback.message.edit_text(
            f"<b>{description}</b>\n\n"
            f"<i>Эта функция находится в разработке...</i>\n\n"
            f"В будущих обновлениях здесь можно будет:\n"
            f"• Настраивать время уведомлений\n"
            f"• Менять тему интерфейса\n"
            f"• Включать/выключать звуки\n"
            f"• Экспортировать данные дракона\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Возвращаемся в меню настроек...</i>",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        
        await callback.answer("⚙️ Функция в разработке")
        
    except Exception as e:
        logger.error(f"Ошибка в process_settings: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== УВЕДОМЛЕНИЯ ====================
async def send_notifications():
    """Отправка умных уведомлений пользователям"""
    try:
        now = datetime.now()
        current_hour = now.hour
        
        # Получаем всех пользователей с драконами
        all_users = db.get_all_users_with_dragons()
        
        for user_id in all_users:
            try:
                dragon_data = db.get_dragon(user_id)
                if not dragon_data:
                    continue
                
                dragon = Dragon.from_dict(dragon_data)
                
                # Проверяем настройки уведомлений пользователя
                user_settings = db.get_user_settings(user_id)
                
                # Утренние уведомления (8-10 утра)
                if 8 <= current_hour <= 10:
                    if user_settings.get("morning_notifications", True):
                        # Проверяем, кормили ли сегодня дракона
                        today_feeding = False
                        feeding_pattern = rate_limiter.get_feeding_pattern(user_id)
                        
                        # Если пользователь обычно кормит утром, но сегодня еще не кормил
                        if feeding_pattern == "morning" and rate_limiter.can_send_notification(user_id, "morning_reminder"):
                            # 50% шанс на уведомление
                            if random.random() < 0.5:
                                messages = [
                                    f"☀️ Доброе утро! {dragon.name} просыпается и хочет кофе! ☕",
                                    f"🌅 {dragon.name} потягивается и смотрит на тебя: 'Кофе?'",
                                    f"✨ Утро! {dragon.character.get('основная_черта', '').capitalize()} ждёт своего утреннего кофе!"
                                ]
                                await bot.send_message(user_id, random.choice(messages))
                                continue
                
                # Вечерние уведомления (20-22 вечера)
                elif 20 <= current_hour <= 22:
                    if user_settings.get("evening_notifications", True):
                        # Проверяем, укладывали ли сегодня спать
                        if rate_limiter.can_send_notification(user_id, "evening_reminder"):
                            # 40% шанс на уведомление
                            if random.random() < 0.4:
                                messages = [
                                    f"🌙 {dragon.name} зевает и трёт глазки... Пора спать? 😴",
                                    f"✨ Вечер. {dragon.name} сворачивается калачиком и смотрит на тебя",
                                    f"💤 {dragon.character.get('основная_черта', '').capitalize()} уже клюёт носом..."
                                ]
                                await bot.send_message(user_id, random.choice(messages))
                                continue
                
                # Напоминания о кормлении (если долго не кормили)
                if user_settings.get("feeding_reminders", True):
                    # Проверяем, когда последний раз кормили
                    last_action = db.get_last_action_time(user_id, "feed")
                    if last_action:
                        hours_since_last_feed = (now - last_action).total_seconds() / 3600
                        if hours_since_last_feed > 6:  # Больше 6 часов
                            if rate_limiter.can_send_notification(user_id, "feeding_reminder", 4):
                                messages = [
                                    f"🍪 {dragon.name} урчит желудком... Пора покормить?",
                                    f"😋 {dragon.character.get('основная_черта', '').capitalize()} смотрит на тебя голодными глазками",
                                    f"🐾 {dragon.name} тычет носом в миску: 'Еды!'"
                                ]
                                await bot.send_message(user_id, random.choice(messages))
                                continue
                
                # Случайные заботливые сообщения
                if random.random() < 0.01:  # 1% шанс
                    if rate_limiter.can_send_notification(user_id, "random_care", 12):
                        messages = [
                            f"❤️ {dragon.name} думает о тебе и улыбается",
                            f"✨ {dragon.character.get('основная_черта', '').capitalize()} хочет сказать, что любит тебя!",
                            f"🐉 {dragon.name} свернулся калачиком и мечтает о тебе"
                        ]
                        await bot.send_message(user_id, random.choice(messages))
                        
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Ошибка в send_notifications: {e}")

# ==================== ОСТАЛЬНЫЕ КОМАНДЫ ====================
# Остальные команды (обнять, кормить, инвентарь и т.д.) остаются аналогичными
# Но с добавлением проверок на полноту показателей и новых реакций

@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона с проверкой на полноту настроения"""
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
        
        # Проверяем, не максимальное ли уже настроение
        mood_stat = dragon.stats.get("настроение", 0)
        full_message = check_stat_full(mood_stat, "настроение", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        # Применяем действие
        result = dragon.apply_action("обнимашки")
        
        # Бонус для неженки
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "неженка":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 5)
            character_bonus = "<b>🥰 Неженка обожает обнимашки! +20 к настроению, +5 к сну</b>\n"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, "Обнял дракона")
        
        # Разные реакции на объятия
        reactions = [
            f"Дракон <b>мурлычет от удовольствия</b> и прижимается к тебе 🐾",
            f"Дракон <b>обнимает тебя в ответ</b> своими мягкими лапками 🤗",
            f"Дракон <b>свернулся калачиком</b> у тебя на коленях и зажмурился от счастья 🥰",
            f"Дракон <b>трётся мордочкой</b> о тебя, показывая свою любовь 😊",
            f"Дракон тихо <b>урчит и закрывает глаза</b>, наслаждаясь моментом 😴",
            f"От объятий у дракона <b>загораются глазки</b> ✨",
            f"Дракон <b>виляет хвостом</b> от радости, когда ты его обнимаешь 🐉",
            f"От твоих объятий дракон <b>начинает светиться</b> от счастья 🌟"
        ]
        
        response = (
            f"{random.choice(reactions)}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
            f"• 💤 Сон: +{result['stat_changes'].get('сон', 0)}\n"
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

@dp.message(Command("feed"))
async def cmd_feed(message: types.Message):
    """Покормить дракона с новыми сладостями"""
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
        
        # Проверяем, не сыт ли уже дракон
        appetite_stat = dragon.stats.get("аппетит", 0)
        full_message = check_stat_full(appetite_stat, "аппетит", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        # Записываем время кормления для уведомлений
        rate_limiter.record_feeding_time(user_id)
        
        inventory = db.get_inventory(user_id)
        
        # Проверяем, что есть чем кормить
        available_snacks = []
        snack_list = ["печенье", "шоколад", "зефир", "пряник", "мармелад", "пирожное"]
        
        for snack_key in snack_list:
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
            f"😋 <i>Аппетит дракона:</i> <code>{appetite_stat}%</code>\n"
            f"😊 <i>Настроение дракона:</i> <code>{dragon.stats.get('настроение', 0)}%</code>",
            parse_mode="HTML",
            reply_markup=get_feed_keyboard(inventory)
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_feed: {e}")
        await message.answer("<b>❌ Произошла ошибка при кормлении.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("feed_"))
async def process_feed(callback: types.CallbackQuery):
    """Обработка кормления новыми сладостями"""
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
        
        # Разные эффекты для разных сладостей
        snack_effects = {
            "печенье": {"аппетит": -15, "настроение": 10, "энергия": 5},
            "шоколад": {"аппетит": -20, "настроение": 15, "сон": 5},
            "зефир": {"аппетит": -10, "настроение": 8, "пушистость": 2},
            "пряник": {"аппетит": -12, "настроение": 12, "энергия": 3},
            "мармелад": {"аппетит": -18, "настроение": 12, "сон": 3},
            "пирожное": {"аппетит": -25, "настроение": 18, "энергия": 8}
        }
        
        if snack_type in snack_effects:
            for stat, change in snack_effects[snack_type].items():
                if stat in dragon.stats:
                    if stat == "аппетит":
                        dragon.stats[stat] = max(0, dragon.stats[stat] + change)  # Аппетит уменьшается
                    else:
                        dragon.stats[stat] = min(100, dragon.stats[stat] + change)
        
        # Проверяем, любимая ли это сладость
        if snack_type == dragon.favorites.get("сладость", ""):
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            dragon.stats["аппетит"] = max(0, dragon.stats["аппетит"] - 10)  # Любимая еда лучше утоляет голод
            favorite_bonus = "<b>🎉 Это его любимая сладость! +20 к настроению, аппетит утолён лучше</b>\n"
        else:
            favorite_bonus = ""
        
        # Бонус для гурмана
        if dragon.character.get("основная_черта") == "гурман":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            favorite_bonus += "<b>🍫 Гурман оценил твой выбор! +15 к настроению</b>\n"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Покормил {snack_type}")
        
        # Описания сладостей
        snack_descriptions = {
            "печенье": "🍪 <b>Хрустящее печенье</b> с шоколадной крошкой",
            "шоколад": "🍫 <b>Сладкий шоколад</b> с орешками",
            "зефир": "☁️ <b>Воздушный зефир</b> в сахарной пудре", 
            "пряник": "🎄 <b>Ароматный пряник</b> с глазурью",
            "мармелад": "🍬 <b>Фруктовый мармелад</b> в форме дракончиков",
            "пирожное": "🎂 <b>Нежное пирожное</b> со взбитыми сливками"
        }
        
        # Разные реакции на еду
        eating_reactions = [
            f"Дракон с удовольствием уплетает угощение! 🐾",
            f"От вкуса у дракона загораются глазки! ✨",
            f"Дракон облизывается после каждого кусочка! 😋",
            f"{dragon.character.get('основная_черта', '').capitalize()} наслаждается каждым кусочком! 🥰",
            f"Дракон мурлычет от удовольствия, когда ест! 🐉"
        ]
        
        response = (
            f"{snack_descriptions.get(snack_type, 'Сладость')}\n"
            f"{random.choice(eating_reactions)}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 🍪 Аппетит: {snack_effects.get(snack_type, {}).get('аппетит', 0)}\n"
            f"• 😊 Настроение: +{snack_effects.get(snack_type, {}).get('настроение', 0)}\n"
        )
        
        # Добавляем дополнительные эффекты
        if snack_effects.get(snack_type, {}).get("энергия", 0) > 0:
            response += f"• ⚡ Энергия: +{snack_effects[snack_type]['энергия']}\n"
        if snack_effects.get(snack_type, {}).get("сон", 0) > 0:
            response += f"• 💤 Сон: +{snack_effects[snack_type]['сон']}\n"
        if snack_effects.get(snack_type, {}).get("пушистость", 0) > 0:
            response += f"• ✨ Пушистость: +{snack_effects[snack_type]['пушистость']}\n"
        
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

# ==================== ЗАПУСК БОТА С УВЕДОМЛЕНИЯМИ ====================
async def scheduled_notifications():
    """Планировщик уведомлений"""
    while True:
        try:
            await send_notifications()
            # Очищаем старые записи раз в день
            rate_limiter.clear_old_entries()
        except Exception as e:
            logger.error(f"Ошибка в scheduled_notifications: {e}")
        
        # Проверяем каждые 30 минут
        await asyncio.sleep(1800)

async def main():
    """Главная функция запуска бота"""
    logger.info("✨ Запуск бота Кофейный Дракон v5.0...")
    
    try:
        # Запускаем планировщик уведомлений
        asyncio.create_task(scheduled_notifications())
        
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