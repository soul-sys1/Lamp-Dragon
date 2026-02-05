"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 7.0
ПОЛНОСТЬЮ ПЕРЕРАБОТАННАЯ ВЕРСИЯ
- Сообщения пользователя не удаляются
- Только развернутые сообщения
- Отдельное кормление
- Новая анти-спам система
- Выровненная статистика
"""
import asyncio
import logging
import random
import re
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Tuple, Any
import traceback

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
from aiogram.exceptions import TelegramAPIError

import config
from database import get_db
from dragon_model import Dragon
from books import get_random_book, get_all_genres

# Настройка логирования в UTC
logging.Formatter.converter = lambda *args: datetime.now(timezone.utc).timetuple()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S %Z'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация базы данных
db = get_db()

# ==================== СОСТОЯНИЯ FSM ====================
class GameStates(StatesGroup):
    waiting_for_guess = State()
    waiting_for_name = State()
    making_coffee = State()
    coffee_additions = State()
    coffee_snack = State()
    sleep_choice = State()
    care_action = State()
    minigame_state = State()
    book_reading = State()
    help_section = State()
    shop_main = State()
    shop_coffee = State()
    shop_sweets = State()
    shop_care = State()
    inventory_main = State()
    feed_action = State()  # Новое состояние для кормления

# ==================== КЛАССЫ И УТИЛИТЫ ====================
class RateLimiter:
    """Новый RateLimiter - проверяет только спам"""
    def __init__(self):
        self.user_actions: Dict[int, List[Tuple[str, datetime]]] = {}
        self.spam_warnings: Dict[int, Dict[str, datetime]] = {}
    
    def check_spam(self, user_id: int, action: str) -> Tuple[bool, Optional[str]]:
        """Проверяет спам (5+ действий за 3 секунды)"""
        now = datetime.now(timezone.utc)
        
        # Инициализируем список действий для пользователя
        if user_id not in self.user_actions:
            self.user_actions[user_id] = []
        
        # Добавляем текущее действие
        self.user_actions[user_id].append((action, now))
        
        # Очищаем старые записи (старше 5 секунд)
        cutoff_time = now - timedelta(seconds=5)
        self.user_actions[user_id] = [
            (act, t) for act, t in self.user_actions[user_id] 
            if t > cutoff_time
        ]
        
        # Подсчитываем количество одинаковых действий за последние 3 секунды
        recent_cutoff = now - timedelta(seconds=3)
        recent_same_actions = [
            (act, t) for act, t in self.user_actions[user_id] 
            if act == action and t > recent_cutoff
        ]
        
        # Если 5+ одинаковых действий за 3 секунды - это спам
        if len(recent_same_actions) >= 5:
            # Проверяем, когда было последнее предупреждение
            warning_key = f"{user_id}_{action}"
            if warning_key in self.spam_warnings:
                last_warning = self.spam_warnings[warning_key]
                if now - last_warning < timedelta(minutes=1):
                    # Уже предупреждали недавно
                    return False, None
            
            # Записываем время предупреждения
            self.spam_warnings[warning_key] = now
            
            # Генерируем жалобное сообщение в зависимости от действия
            spam_messages = {
                "hug": [
                    "💖 Ой-ой, полегче! Мои косточки хрустят от такого количества обнимашек!",
                    "💖 Так много объятий за раз! Давай немного переведём дух...",
                    "💖 Ты меня задушишь в объятиях! Давай помедленнее..."
                ],
                "coffee": [
                    "☕ Столько кофе за раз?! У меня уже крылышки дрожат!",
                    "☕ Ещё одна чашка и я взлечу к облакам без всяких крыльев!",
                    "☕ Мой кофейный датчик показывает перегрузку!"
                ],
                "sleep": [
                    "😴 Я только что проснулся! Не заставляй меня снова спать!",
                    "😴 Так много сна вредно для драконьего здоровья!",
                    "😴 Давай сначала чем-нибудь займёмся, а потом спать?"
                ],
                "care": [
                    "✨ Я уже сияю как новенький! Можно отдохнуть от процедур?",
                    "✨ Так часто ухаживать - моя шёрстка может стереться!",
                    "✨ Давай сделаем перерыв в спа-процедурах?"
                ],
                "feed": [
                    "🍪 Ой-ой, мой животик уже полный! Не могу больше кушать!",
                    "🍪 Так много сладостей за раз - у меня зубы заболят!",
                    "🍪 Я уже сыт до отвала! Давай сделаем перерыв?"
                ],
                "game": [
                    "🎮 Столько игр за раз! У меня голова кружится!",
                    "🎮 Давай немного отдохнём между играми?",
                    "🎮 Мои драконьи мозги перегреваются от такого количества игр!"
                ]
            }
            
            action_type = "hug" if "hug" in action else \
                         "coffee" if "coffee" in action else \
                         "sleep" if "sleep" in action else \
                         "care" if "care" in action else \
                         "feed" if "feed" in action else \
                         "game" if "game" in action else "default"
            
            message = random.choice(spam_messages.get(action_type, ["Слишком быстро! Давай помедленнее..."]))
            return False, message
        
        return True, None
    
    def clear_old_entries(self):
        """Очищает старые записи"""
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        
        # Очищаем старые действия
        for user_id in list(self.user_actions.keys()):
            self.user_actions[user_id] = [
                (act, t) for act, t in self.user_actions[user_id]
                if t > hour_ago
            ]
            if not self.user_actions[user_id]:
                del self.user_actions[user_id]
        
        # Очищаем старые предупреждения
        keys_to_delete = []
        for key, last_time in self.spam_warnings.items():
            if last_time < hour_ago:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del self.spam_warnings[key]

class CharacterPersonality:
    """Глубоко проработанные характеры драконов"""
    
    @staticmethod
    def get_character_description(character_trait: str) -> Dict:
        """Возвращает полное описание характера"""
        descriptions = {
            "кофеман": {
                "name": "☕ Кофеман",
                "description": "Рождён среди кофейных плантаций волшебных гор, этот дракон чувствует кофе на расстоянии мили!",
                "features": [
                    "☕ Обожает экспериментировать с разными сортами",
                    "⚡ Быстро теряет энергию без кофейной подпитки",
                    "💬 Может часами рассказывать о методах заварки"
                ],
                "advice": "Всегда держите запас кофейных зёрен!",
                "emoji": "☕"
            },
            "книгочей": {
                "name": "📚 Книгочей",
                "description": "Выращен в древней библиотеке драконьего знания, этот дракон прочитал больше книг, чем звёзд на небе.",
                "features": [
                    "📖 Обожает, когда ему читают перед сном",
                    "🧠 Быстро учится и запоминает прочитанное",
                    "💭 Часто цитирует любимые произведения"
                ],
                "advice": "Читайте ему каждый вечер - он это обожает!",
                "emoji": "📚"
            },
            "неженка": {
                "name": "💖 Неженка",
                "description": "Самый ласковый дракон во всём королевстве! Рождённый из облака нежности и заботы.",
                "features": [
                    "💕 Требует минимум 3 обнимашки в день",
                    "😢 Быстро грустит без внимания",
                    "✨ Расцветает от ласковых слов"
                ],
                "advice": "Не скупитесь на ласку и внимание!",
                "emoji": "💖"
            },
            "чистюля": {
                "name": "✨ Чистюля",
                "description": "Блестит и сверкает, как только что отполированный алмаз! Этот дракон следит за чистотой тщательно.",
                "features": [
                    "✨ Быстро замечает малейшую пыль на себе",
                    "🛁 Обожает водные процедуры и уход",
                    "👃 Чувствителен к запахам"
                ],
                "advice": "Регулярно ухаживайте за его шёрсткой!",
                "emoji": "✨"
            },
            "гурман": {
                "name": "🍰 Гурман",
                "description": "Настоящий ценитель изысканных вкусов! Этот дракон родился на кухне волшебного замка.",
                "features": [
                    "👨‍🍳 Критично оценивает каждое угощение",
                    "💎 Ценит качественные ингредиенты",
                    "💰 Даёт больше золота за любимые лакомства"
                ],
                "advice": "Угощайте его только лучшими сладостями!",
                "emoji": "🍰"
            },
            "игрик": {
                "name": "🎮 Игрик",
                "description": "Энергия и азарт в одном драконьем теле! Рождённый в игровой вселенной.",
                "features": [
                    "🎯 Чаще инициирует мини-игры",
                    "⚡ Меньше устаёт от активностей",
                    "🏆 Обожает соревнования и победы"
                ],
                "advice": "Играйте с ним каждый день!",
                "emoji": "🎮"
            },
            "соня": {
                "name": "😴 Соня",
                "description": "Мастер сладких снов и пушистых облаков! Этот дракон спит так крепко, что иногда приснится самому себе.",
                "features": [
                    "💤 Чаще хочет спать и отдыхать",
                    "⚡ Быстрее восстанавливает энергию во сне",
                    "🌙 Может заснуть в самых неожиданных местах"
                ],
                "advice": "Не будите его без крайней необходимости!",
                "emoji": "😴"
            },
            "энерджайзер": {
                "name": "⚡ Энерджайзер",
                "description": "Живая электростанция драконьего мира! Рождённый во время грозы, он накопил много энергии.",
                "features": [
                    "⚡ Медленнее теряет энергию",
                    "🏃 Чаще инициирует активные действия",
                    "🎢 Может 'перевозбудиться' от кофе"
                ],
                "advice": "Давайте ему много активностей!",
                "emoji": "⚡"
            },
            "философ": {
                "name": "🤔 Философ",
                "description": "Мудрец драконьего племени! Рождённый под древним дубом мудрости.",
                "features": [
                    "💭 Задаёт глубокие вопросы",
                    "😌 Реже теряет настроение",
                    "📜 Любит размышлять о жизни"
                ],
                "advice": "Обсуждайте с ним важные темы!",
                "emoji": "🤔"
            },
            "исследователь": {
                "name": "🔍 Исследователь",
                "description": "Неутомимый искатель тайн и загадок! Рождённый с картой в лапках.",
                "features": [
                    "🔎 Задаёт любопытные вопросы",
                    "💎 Чаще находит случайные предметы",
                    "📈 Бонус к опыту от новых действий"
                ],
                "advice": "Поощряйте его любознательность!",
                "emoji": "🔍"
            }
        }
        return descriptions.get(character_trait, descriptions["неженка"])
    
    @staticmethod
    def get_character_message(character_trait: str, situation: str, dragon_name: str) -> str:
        """Возвращает сообщение в зависимости от характера и ситуации"""
        messages = {
            "кофеман": {
                "spam": f"☕ {dragon_name} отстраняет чашку: 'Слишком много кофе за раз! Давай помедленнее...'",
                "max_stat": f"☕ {dragon_name} показывает на свой полный животик: 'Я уже наполнен ароматным кофе до краёв!'"
            },
            "книгочей": {
                "spam": f"📚 {dragon_name} прячет книгу: 'Давай не будем торопиться! Каждое действие должно быть осознанным.'",
                "max_stat": f"📚 {dragon_name} улыбается: 'Я уже абсолютно счастлив! Может, почитаем вместо этого?'"
            },
            "неженка": {
                "spam": f"💖 {dragon_name} отстраняется: 'Ой, так много ласки за раз! Давай помедленнее, я нежный!'",
                "max_stat": f"💖 {dragon_name} сияет: 'Я уже самый любимый и обнимаемый дракон на свете!'"
            },
            "чистюля": {
                "spam": f"✨ {dragon_name} отпрыгивает: 'Слишком много процедур за раз! Моя шёрстка устала!'",
                "max_stat": f"✨ {dragon_name} сверкает: 'Я уже идеально чист и ухожен! Можно отдохнуть?'"
            },
            "гурман": {
                "spam": f"🍰 {dragon_name} отворачивается: 'Слишком много еды! Надо наслаждаться каждым кусочком медленно!'",
                "max_stat": f"🍰 {dragon_name} поглаживает живот: 'Я так сыт, что не могу пошевелиться! Время переваривать...'"
            },
            "игрик": {
                "spam": f"🎮 {dragon_name} закрывает глаза: 'Слишком много игр! Мои драконьи мозги перегреваются!'",
                "max_stat": f"🎮 {dragon_name} прыгает на месте: 'Я уже на пике энергии! Давай потратим её на что-то грандиозное!'"
            },
            "соня": {
                "spam": f"😴 {dragon_name} зевает: 'Так часто спать вредно! Давай сначала чем-нибудь займёмся?'",
                "max_stat": f"😴 {dragon_name} потягивается: 'Я так выспался, что готов горы свернуть! Давай действовать!'"
            },
            "энерджайзер": {
                "spam": f"⚡ {dragon_name} дрожит: 'Слишком много активности! Мои крылья устали!'",
                "max_stat": f"⚡ {dragon_name} искрится: 'Я заряжен на 1000%! Нужно срочно куда-то деть эту энергию!'"
            },
            "философ": {
                "spam": f"🤔 {dragon_name} задумчиво: 'Поспешность - враг совершенства. Давай не торопиться?'",
                "max_stat": f"🤔 {dragon_name} улыбается: 'Я достиг гармонии и баланса. Всё и так прекрасно!'"
            },
            "исследователь": {
                "spam": f"🔍 {dragon_name} отвлекается: 'Слишком много нового за раз! Давай исследовать постепенно.'",
                "max_stat": f"🔍 {dragon_name} оглядывается: 'Я уже всё исследовал вокруг! Нужны новые горизонты!'"
            }
        }
        
        character_msgs = messages.get(character_trait, messages["неженка"])
        return character_msgs.get(situation, f"{dragon_name} смотрит на вас.")

# ==================== УТИЛИТЫ ====================
def validate_dragon_name(name: str) -> Tuple[bool, Optional[str]]:
    name = name.strip()
    
    if len(name) < 2:
        return False, "Имя должно быть хотя бы 2 символа"
    
    if len(name) > 20:
        return False, "Имя слишком длинное. Максимум 20 символов"
    
    if re.search(r'[<>{}[\]\\|`~!@#$%^&*()_+=]', name):
        return False, "Имя содержит недопустимые символы"
    
    return True, None

def create_progress_bar(value: int, length: int = 10) -> str:
    filled = min(max(0, int(value / 100 * length)), length)
    empty = length - filled
    return "█" * filled + "░" * empty

def escape_html(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )

def check_stat_max(stat_value: int, stat_name: str, dragon_trait: str = "") -> Optional[str]:
    """Проверяет только если стат на максимуме (95-100%)"""
    if stat_value >= 95:
        messages = {
            "кофе": [
                f"☕ Дракон отворачивается от чашки: 'Мой кофейный датчик показывает 100%!'",
                f"☕ {dragon_trait} покачивает головой: 'Ещё одна капля - и я взлечу к облакам!'"
            ],
            "сон": [
                f"💤 {dragon_trait} потягивается: 'Я так выспался, что готов горы свернуть!'",
                f"💤 Дракон полон энергии и бодрости!"
            ],
            "настроение": [
                f"😊 Дракон сияет ярче тысячи солнц! Он не может быть счастливее!",
                f"😊 {dragon_trait} танцует от радости: 'Я самый счастливый дракон во вселенной!'"
            ],
            "аппетит": [
                f"🍪 {dragon_trait} показывает на свой довольный животик",
                f"🍪 Дракон совершенно сыт и доволен!"
            ],
            "энергия": [
                f"⚡ Дракон носится по комнате, оставляя за собой светящийся след!",
                f"⚡ {dragon_trait} излучает столько энергии, что лампочки мигают!"
            ],
            "пушистость": [
                f"✨ Шёрстка дракона сияет и переливается всеми цветами радуги!",
                f"✨ {dragon_trait} уже идеально ухожен - ни одной спутанной шерстинки!"
            ]
        }
        
        if stat_name in messages:
            return random.choice(messages[stat_name])
    
    return None

def format_stat_line(stat_name: str, stat_value: int) -> str:
    """Форматирует строку статистики с одинаковыми отступами"""
    stat_names = {
        "кофе": "☕ Кофе",
        "сон": "💤 Бодрость",
        "настроение": "😊 Настроение",
        "аппетит": "🍪 Сытость",
        "энергия": "⚡ Энергия",
        "пушистость": "✨ Пушистость"
    }
    
    name = stat_names.get(stat_name, stat_name)
    # ВСЕ строки одинаковой длины - 12 символов
    padded_name = name.ljust(12)
    bar = create_progress_bar(stat_value)
    
    return f"{padded_name}: <code>{bar}</code> <code>{stat_value}%</code>"

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Статус"), KeyboardButton(text="☕ Кофе")],
            [KeyboardButton(text="😴 Сон"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🤗 Обнять"), KeyboardButton(text="✨ Уход")],
            [KeyboardButton(text="🍪 Покормить"), KeyboardButton(text="🛍️ Магазин")],  # Добавлено кормление
            [KeyboardButton(text="📦 Инвентарь"), KeyboardButton(text="📖 Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 🐾"
    )
    return keyboard

def get_short_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Создать дракона"), KeyboardButton(text="📖 Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard

def get_shop_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☕ Кофе и ингредиенты", callback_data="shop_coffee")],
            [InlineKeyboardButton(text="🍪 Сладости и угощения", callback_data="shop_sweets")],
            [InlineKeyboardButton(text="✨ Предметы для ухода", callback_data="shop_care")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")]
        ]
    )
    return keyboard

def get_coffee_shop_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☕ Кофейные зёрна (10💰)", callback_data="buy_coffee_beans")],
            [InlineKeyboardButton(text="🍫 Шоколадные чипсы (8💰)", callback_data="buy_chocolate_chips")],
            [InlineKeyboardButton(text="🍯 Медовый сироп (12💰)", callback_data="buy_honey_syrup")],
            [InlineKeyboardButton(text="🍦 Ванильное мороженое (15💰)", callback_data="buy_vanilla_icecream")],
            [InlineKeyboardButton(text="🍭 Карамельный сироп (10💰)", callback_data="buy_caramel_syrup")],
            [InlineKeyboardButton(text="🌰 Фундук молотый (18💰)", callback_data="buy_hazelnut")],
            [
                InlineKeyboardButton(text="« Назад в магазин", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

def get_sweets_shop_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍪 Печенье с изюмом (5💰)", callback_data="buy_cookie_raisin")],
            [InlineKeyboardButton(text="🍫 Шоколадная плитка (15💰)", callback_data="buy_chocolate_bar")],
            [InlineKeyboardButton(text="☁️ Ванильный зефир (7💰)", callback_data="buy_vanilla_marshmallow")],
            [InlineKeyboardButton(text="🎄 Имбирный пряник (8💰)", callback_data="buy_gingerbread")],
            [InlineKeyboardButton(text="🍬 Фруктовый мармелад (10💰)", callback_data="buy_fruit_marmalade")],
            [InlineKeyboardButton(text="🎂 Шоколадное пирожное (20💰)", callback_data="buy_chocolate_cake")],
            [InlineKeyboardButton(text="🍩 Сладкий пончик (12💰)", callback_data="buy_donut")],
            [
                InlineKeyboardButton(text="« Назад в магазин", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

def get_care_shop_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💆 Драконья расчёска (25💰)", callback_data="buy_dragon_brush")],
            [InlineKeyboardButton(text="🧴 Волшебный шампунь (30💰)", callback_data="buy_magic_shampoo")],
            [InlineKeyboardButton(text="✂️ Золотые ножницы (35💰)", callback_data="buy_golden_scissors")],
            [InlineKeyboardButton(text="🧸 Плюшевый дракончик (40💰)", callback_data="buy_plush_dragon")],
            [InlineKeyboardButton(text="🛁 Ароматная соль (20💰)", callback_data="buy_aromatic_salt")],
            [InlineKeyboardButton(text="💅 Лак для когтей (28💰)", callback_data="buy_nail_polish")],
            [
                InlineKeyboardButton(text="« Назад в магазин", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

def get_coffee_keyboard() -> InlineKeyboardMarkup:
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
                InlineKeyboardButton(text="« Назад", callback_data="coffee_back")
            ]
        ]
    )
    return keyboard

def get_coffee_additions_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍫 Шоколад", callback_data="add_chocolate"),
                InlineKeyboardButton(text="🍯 Мёд", callback_data="add_honey")
            ],
            [
                InlineKeyboardButton(text="🍦 Мороженое", callback_data="add_icecream"),
                InlineKeyboardButton(text="🍭 Сироп", callback_data="add_syrup")
            ],
            [
                InlineKeyboardButton(text="⏩ Без добавок", callback_data="add_none"),
                InlineKeyboardButton(text="« Назад", callback_data="add_back")
            ]
        ]
    )
    return keyboard

def get_coffee_snack_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    inventory_map = {
        "cookie_raisin": "cookie",
        "chocolate_bar": "chocolate",
        "vanilla_marshmallow": "marshmallow",
        "gingerbread": "gingerbread",
        "fruit_marmalade": "marmalade",
        "chocolate_cake": "cake",
        "donut": "donut"
    }
    
    snack_items = {
        "cookie_raisin": "🍪 Печенье",
        "chocolate_bar": "🍫 Шоколад", 
        "vanilla_marshmallow": "☁️ Зефир",
        "gingerbread": "🎄 Пряник",
        "fruit_marmalade": "🍬 Мармелад",
        "chocolate_cake": "🎂 Пирожное",
        "donut": "🍩 Пончик"
    }
    
    row = []
    for snack_key, snack_name in snack_items.items():
        inv_key = inventory_map[snack_key]
        count = inventory.get(inv_key, 0)
        if isinstance(count, (int, float)) and count > 0:
            row.append(InlineKeyboardButton(
                text=f"{snack_name} ×{int(count)}", 
                callback_data=f"snack_{snack_key}"
            ))
            if len(row) == 2:
                keyboard.inline_keyboard.append(row)
                row = []
    
    if row:
        keyboard.inline_keyboard.append(row)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="⏩ Без сладостей", callback_data="snack_none"),
        InlineKeyboardButton(text="« Назад", callback_data="snack_back")
    ])
    
    return keyboard

def get_feed_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    """Клавиатура для отдельного кормления"""
    inventory_map = {
        "cookie_raisin": "cookie",
        "chocolate_bar": "chocolate",
        "vanilla_marshmallow": "marshmallow",
        "gingerbread": "gingerbread",
        "fruit_marmalade": "marmalade",
        "chocolate_cake": "cake",
        "donut": "donut"
    }
    
    snack_items = {
        "cookie_raisin": "🍪 Печенье",
        "chocolate_bar": "🍫 Шоколад", 
        "vanilla_marshmallow": "☁️ Зефир",
        "gingerbread": "🎄 Пряник",
        "fruit_marmalade": "🍬 Мармелад",
        "chocolate_cake": "🎂 Пирожное",
        "donut": "🍩 Пончик"
    }
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    
    for snack_key, snack_name in snack_items.items():
        inv_key = inventory_map[snack_key]
        count = inventory.get(inv_key, 0)
        if isinstance(count, (int, float)) and count > 0:
            row.append(InlineKeyboardButton(
                text=f"{snack_name} ×{int(count)}", 
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

def get_minigames_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess")],
            [InlineKeyboardButton(text="« Назад", callback_data="game_back")]
        ]
    )
    return keyboard

def get_sleep_keyboard() -> InlineKeyboardMarkup:
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    row1 = []
    row1.append(InlineKeyboardButton(text="✨ Расчесать лапки", callback_data="care_brush_paws"))
    row1.append(InlineKeyboardButton(text="🛁 Протереть мордочку", callback_data="care_wipe_face"))
    keyboard.inline_keyboard.append(row1)
    
    row2 = []
    row2.append(InlineKeyboardButton(text="💅 Почистить когти", callback_data="care_clean_nails"))
    row2.append(InlineKeyboardButton(text="🦷 Почистить зубы", callback_data="care_clean_teeth"))
    keyboard.inline_keyboard.append(row2)
    
    row3 = []
    if inventory.get("dragon_brush", 0) > 0:
        row3.append(InlineKeyboardButton(text="💆 Расчесать шерстку", callback_data="care_brush_fur"))
    if inventory.get("magic_shampoo", 0) > 0:
        row3.append(InlineKeyboardButton(text="🧴 Искупать с шампунем", callback_data="care_bath_shampoo"))
    
    if row3:
        keyboard.inline_keyboard.append(row3)
    
    row4 = []
    if inventory.get("golden_scissors", 0) > 0:
        row4.append(InlineKeyboardButton(text="✂️ Подстричь когти ножницами", callback_data="care_trim_nails_scissors"))
    if inventory.get("plush_dragon", 0) > 0:
        row4.append(InlineKeyboardButton(text="🧸 Играть с игрушкой", callback_data="care_play_toy"))
    
    if row4:
        keyboard.inline_keyboard.append(row4)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="« Назад", callback_data="care_back")
    ])
    
    return keyboard

def get_notifications_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔔 Включить", callback_data="notif_on"),
                InlineKeyboardButton(text="🔕 Выключить", callback_data="notif_off")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="notif_back")
            ]
        ]
    )
    return keyboard

def get_inventory_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍪 Сладости", callback_data="inv_snacks"),
                InlineKeyboardButton(text="✨ Уход", callback_data="inv_care")
            ],
            [
                InlineKeyboardButton(text="☕ Ингредиенты", callback_data="inv_ingredients"),
                InlineKeyboardButton(text="🧸 Прочее", callback_data="inv_other")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="inv_back")
            ]
        ]
    )
    return keyboard

def get_help_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все команды", callback_data="help_commands")],
            [InlineKeyboardButton(text="🎭 Все характеры", callback_data="help_characters")],
            [InlineKeyboardButton(text="« Назад", callback_data="help_back")]
        ]
    )
    return keyboard

def get_characters_list_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="☕ Кофеман", callback_data="char_cofeman"),
                InlineKeyboardButton(text="📚 Книгочей", callback_data="char_bookworm")
            ],
            [
                InlineKeyboardButton(text="💖 Неженка", callback_data="char_tender"),
                InlineKeyboardButton(text="✨ Чистюля", callback_data="char_clean")
            ],
            [
                InlineKeyboardButton(text="🍰 Гурман", callback_data="char_gourmet"),
                InlineKeyboardButton(text="🎮 Игрик", callback_data="char_gamer")
            ],
            [
                InlineKeyboardButton(text="😴 Соня", callback_data="char_sleeper"),
                InlineKeyboardButton(text="⚡ Энерджайзер", callback_data="char_energizer")
            ],
            [
                InlineKeyboardButton(text="🤔 Философ", callback_data="char_philosopher"),
                InlineKeyboardButton(text="🔍 Исследователь", callback_data="char_explorer")
            ],
            [
                InlineKeyboardButton(text="« Назад в помощь", callback_data="char_back")
            ]
        ]
    )
    return keyboard

# ==================== УТИЛИТЫ ДЛЯ КОФЕ ====================
def get_coffee_name(coffee_type: str) -> str:
    names = {
        "espresso": "Эспрессо",
        "latte": "Латте",
        "cappuccino": "Капучино",
        "raf": "Раф",
        "americano": "Американо",
        "mocha": "Мокко"
    }
    return names.get(coffee_type, "Кофе")

def get_addition_name(addition: str) -> str:
    names = {
        "chocolate": "шоколадом",
        "honey": "мёдом",
        "icecream": "мороженым",
        "syrup": "сиропом",
        "none": "без добавок"
    }
    return names.get(addition, f"добавкой '{addition}'")

def get_snack_name(snack: str) -> str:
    names = {
        "cookie_raisin": "печеньем",
        "chocolate_bar": "шоколадом",
        "vanilla_marshmallow": "зефиром",
        "gingerbread": "пряником",
        "fruit_marmalade": "мармеладом",
        "chocolate_cake": "пирожным",
        "donut": "пончиком",
        "none": ""
    }
    return names.get(snack, "")

# Инициализация менеджеров
rate_limiter = RateLimiter()
minigame_manager = type('obj', (object,), {
    'guess_number_game': lambda: {
        "type": "guess",
        "secret": random.randint(1, 20),
        "hints": [
            "🐉 Дракон задумал число от 1 до 20 и хитренько улыбается...",
            f"📝 Подсказка: это число {'чётное' if random.choice([True, False]) else 'нечётное'}",
            f"🎯 Число находится в диапазоне {random.randint(1, 10)}-{random.randint(11, 20)}"
        ],
        "attempts": 3,
        "reward": {"gold": 20, "mood": 30, "energy": -10}
    }
})()

# ==================== ДЕТАЛЬНЫЕ ОПИСАНИЯ ДЕЙСТВИЙ ====================
class ActionDescriptions:
    @staticmethod
    def get_hug_scene(dragon_name: str, dragon_trait: str) -> str:
        scenes = [
            f"Вы застали {dragon_name} сидящим на высоком стуле и пытающимся дотянуться до чашки с кофе на верхней полке. "
            f"Он машет маленькими лапками, но всё тщетно. Вы подходите, мягко обнимаете его и поднимаете на ручки. "
            f"{dragon_name} радостно хватает чашку и мурлычет от счастья, прижимаясь к вам! 🐾☕\n\n"
            f"Его глазки сияют от радости, а хвостик весело подрагивает. Кажется, в этот момент он самый счастливый дракон во всём королевстве. "
            f"Вы чувствуете, как его маленькое тельце полностью расслабляется в ваших объятиях.",
            
            f"{dragon_name} уютно устроился на диване и смотрит телевизор, где показывают документальный фильм о драконах. "
            f"Вы садитесь рядом и нежно обнимаете его. Дракон поворачивает голову, его глазки светятся от радости, "
            f"и он забирается к вам на колени, продолжая смотреть фильм вместе с вами. 📺🐉\n\n"
            f"Он уютно сворачивается калачиком, положив голову вам на руку. Его дыхание становится ровным и спокойным, "
            f"а время будто замедляется. Вы гладите его по спинке, чувствуя, как мягкая шёрстка переливается под вашими пальцами.",
            
            f"Вы находите {dragon_name} в углу комнаты, где он играет с мячиком. Он так увлечён, что не замечает вас. "
            f"Вы тихо подходите сзади и обнимаете его. Дракон вздрагивает от неожиданности, но, поняв, что это вы, "
            f"радостно виляет хвостом и обнимает вас в ответ своими мягкими лапками. 🎾✨\n\n"
            f"Его маленькие крылышки трепещут от возбуждения, а в глазах читается безграничная радость. "
            f"Он прижимается к вам всем телом, мурлыча как котёнок. Кажется, эта неожиданная ласка сделала его день.",
            
            f"{dragon_name} сидит у окна и грустно смотрит на дождь за стеклом. Вы подходите и обнимаете его сзади, "
            f"прижимая к себе. Дракон оборачивается, и в его глазах появляется искорка счастья. "
            f"Он прижимается к вам, и вместе вы смотрите на падающие капли. 🌧️🤗\n\n"
            f"Его грусть постепенно растворяется в вашем объятии. Он поворачивается и обнимает вас в ответ, "
            f"зарываясь мордочкой в вашу одежду. Дождь за окном теперь кажется не таким уж и печальным, "
            f"ведь в комнате тепло и уютно от вашей взаимной ласки.",
            
            f"Вы застали {dragon_name} за попыткой сделать утреннюю зарядку. Он неуклюже пытается приседать, "
            f"но постоянно теряет равновесие. Вы смеётесь и обнимаете его. "
            f"Дракон смущённо хрюкает, но затем начинает смеяться вместе с вами! 💪😄\n\n"
            f"Ваше объятие прерывает его спортивные неудачи, но наполняет комнату смехом и радостью. "
            f"Он обнимает вас в ответ, и вы вместе валитесь на мягкий ковёр, продолжая смеяться. "
            f"Иногда лучшая зарядка - это зарядка хорошего настроения!"
        ]
        return random.choice(scenes)
    
    @staticmethod
    def get_coffee_scene(dragon_name: str, coffee_type: str, addition: str, snack: str) -> str:
        coffee_name = get_coffee_name(coffee_type)
        addition_name = get_addition_name(addition)
        snack_name = get_snack_name(snack)
        
        scenes = [
            f"Вы начинаете готовить {coffee_name} {f'с {addition_name} ' if addition != 'none' else ''}для {dragon_name}. "
            f"Аромат свежего кофе заполняет комнату, и дракон нетерпеливо переминается с лапки на лапку. "
            f"Он внимательно наблюдает за каждым вашим движением: как вы перемалываете зёрна, как струйка горячей воды "
            f"проходит через кофе, как поднимается ароматная пенка...\n\n"
            f"Наконец, напиток готов. Вы аккуратно наливаете его в любимую чашку дракона - ту, что с изображением летящего дракончика. "
            f"{dragon_name} осторожно берёт чашку в лапки, делает первый глоток и замирает. "
            f"На его мордочке появляется блаженная улыбка.{f' Вы также достаёте {snack_name} и ставите перед ним.' if snack != 'none' else ''}\n\n"
            f"'Вкуснее всего, когда ты готовишь!' - говорит он, делая ещё один глоток. Его глазки закрываются от наслаждения, "
            f"а хвостик медленно виляет в такт его довольному мурлыканью.",
            
            f"Сегодня вы решили порадовать {dragon_name} особенным {coffee_name}{f' с {addition_name}' if addition != 'none' else ''}. "
            f"Дракон сидит на кухонном столе, свесив лапки, и с интересом наблюдает за процессом. "
            f"Вы показываете ему все ингредиенты, объясняя тонкости приготовления. {dragon_name} кивает, будто понимает каждое слово.\n\n"
            f"Когда напиток готов, вы подаёте его с особенным изяществом. {dragon_name} обнюхивает пар, поднимающийся от чашки, "
            f"и его нос радостно подрагивает.{f' Рядом вы кладёте {snack_name}, аккуратно разложенный на маленькой тарелочке.' if snack != 'none' else ''}\n\n"
            f"Он делает первый маленький глоток, затем второй, побольше. 'Идеальная температура, идеальный вкус!' - оценивает он. "
            f"Вы видите, как напряжение покидает его маленькое тельце, заменяясь уютным спокойствием.",
            
            f"Вы создаёте для {dragon_name} настоящий кофейный шедевр - {coffee_name}{f' с {addition_name}' if addition != 'none' else ''}. "
            f"Каждое движение выверено: пенка получается идеальной консистенции, температура как надо, "
            f"аромат разносится по всей комнате. {dragon_name} уже сидит на своём специальном стульчике, "
            f"постукивая коготками в ожидании.\n\n"
            f"Наконец, вы ставите перед ним чашку. Он заглядывает внутрь, и его глазки расширяются от восхищения.{f' Вы также подаёте {snack_name}, красиво оформленный.' if snack != 'none' else ''}\n\n"
            f"'Это именно то, что нужно для прекрасного дня!' - говорит он, пробуя напиток. "
            f"Вы садитесь рядом, и какое-то время вы просто молча наслаждаетесь моментом: вы - своим умением приготовить, "
            f"а он - результатом ваших стараний."
        ]
        return random.choice(scenes)
    
    @staticmethod
    def get_sleep_scene(dragon_name: str, action: str, book_title: str = None, book_content: str = None) -> str:
        if action == "read" and book_title and book_content:
            book_content = escape_html(book_content[:200]) + "..."
            
            return (
                f"Вы усаживаетесь в удобное кресло, а {dragon_name} укладывается у вас на коленях, уютно устроившись. "
                f"Вы открываете книгу '{book_title}' и начинаете читать:\n\n"
                f"<i>{book_content}</i>\n\n"
                f"{dragon_name} внимательно слушает, его глазки медленно закрываются. Вы гладите его по голове, "
                f"продолжая читать спокойным, убаюкивающим голосом. К концу второй страницы его дыхание становится ровным, "
                f"а тело полностью расслабляется. 📖😴\n\n"
                f"Вы аккуратно закрываете книгу, но продолжаете сидеть ещё несколько минут, наслаждаясь моментом покоя. "
                f"{dragon_name} тихо посапывает, изредка вздрагивая во сне, вероятно, продолжая приключения из услышанной истории."
            )
        
        elif action == "lay":
            return (
                f"Вы ложитесь рядом с {dragon_name} на большую мягкую кровать. Дракон сразу прижимается к вам, "
                f"ища самое тёплое место. Вы обнимаете его и начинаете нежно гладить по спинке. 🛏️💕\n\n"
                f"Его шёрстка мягкая и тёплая под вашими пальцами. {dragon_name} мурлычет от удовольствия, "
                f"зарывается мордочкой в вашу руку. Постепенно его мурлыканье становится тише, дыхание - глубже и ровнее. "
                f"Вы чувствуете, как его маленькое тельце полностью расслабляется в ваших объятиях.\n\n"
                f"Совсем скоро он засыпает, но вы ещё какое-то время лежите рядом, слушая его ровное дыхание. "
                f"Тепло его тела согревает вас, создавая неповторимое ощущение уюта и защищённости."
            )
        
        elif action == "kiss":
            scenes = [
                f"Вы подходите к кроватке, где {dragon_name} уже уютно устроился, укрывшись мягким облачным одеялом. "
                f"Его глазки медленно закрываются, но, услышав ваши шаги, он приоткрывает один глаз. "
                f"Вы наклоняетесь и нежно целуете его в лобик. 🌙😘\n\n"
                f"{dragon_name} тихо мурлычет и засыпает с улыбкой. Вы поправляете одеяло, натягивая его до самого подбородка дракончика. "
                f"Ещё один лёгкий поцелуй - и вы отходите на цыпочках, оставляя его сладко спать в лунном свете, "
                f"пробивающемся сквозь окно.",
                
                f"{dragon_name} лежит на боку, обняв свою любимую игрушку. Он уже почти спит, но, почувствовав ваше присутствие, "
                f"приоткрывает глаза. Вы садитесь на край кровати, гладите его по голове и целуете в лобик. 🧸💤\n\n"
                f"Дракон счастливо вздыхает и крепче прижимает игрушку. 'Спокойной ночи,' - шепчете вы ему. "
                f"'Спокойной...' - еле слышно отвечает он, уже наполовину во сне. Вы ещё минутку сидите рядом, "
                f"пока его дыхание не становится совершенно ровным, а затем тихо выходите из комнаты."
            ]
            return random.choice(scenes)
        
        elif action == "sing":
            return (
                f"Вы садитесь рядом с {dragon_name} и начинаете тихо напевать колыбельную. Ваш голос мягкий и убаюкивающий, "
                f"мелодия знакомая с детства. 🎶😴\n\n"
                f"{dragon_name} прикрывает глазки, его дыхание становится глубже. Вы гладите его по голове в такт песне, "
                f"а он тихо мурлычет в ответ. Постепенно мурлыканье стихает, песня затихает, остаётся лишь тихое напевание. "
                f"Вы видите, как его лапки расслабляются, хвостик перестаёт подрагивать.\n\n"
                f"Когда песня заканчивается, {dragon_name} уже спит крепким сном. Вы ещё немного сидите рядом, "
                f"наслаждаясь моментом покоя, а затем аккуратно накрываете его одеялом и выходите из комнаты."
            )
        
        elif action == "toy":
            return (
                f"Вы даёте {dragon_name} его любимую игрушку - маленького плюшевого дракончика. "
                f"Он радостно хватает её и прижимает к себе. 🧸💤\n\n"
                f"'С ней мне снятся самые сладкие сны,' - шепчет он вам, укладываясь поудобнее. "
                f"Вы поправляете одеяло, гладите его по спинке. {dragon_name} обнимает игрушку покрепче, "
                f"закрывает глазки и почти сразу же засыпает, улыбаясь во сне.\n\n"
                f"Вы стоите рядом ещё несколько минут, наблюдая, как его грудь равномерно поднимается и опускается. "
                f"Игрушка надёжно зажата в его лапках - верный спутник в царстве снов."
            )
        
        else:  # simple
            return (
                f"Вы укладываете {dragon_name} в его уютную кроватку, поправляете одеяло так, чтобы ему было максимально комфортно. 🌙\n\n"
                f"'Спокойной ночи, малыш,' - говорите вы, гладя его по голове. "
                f"'Спокойной ночи,' - отвечает он, зевая. Вы выключаете свет, оставляя только ночник, "
                f"который отбрасывает мягкие тени на стены.\n\n"
                f"Через несколько минут вы заглядываете в комнату - {dragon_name} уже спит, свернувшись калачиком. "
                f"Его дыхание ровное и спокойное, а на мордочке - выражение полного умиротворения."
            )
    
    @staticmethod
    def get_care_scene(dragon_name: str, action: str) -> str:
        if action == "brush_paws":
            return (
                f"Вы берёте специальную мягкую щёточку и усаживаете {dragon_name} перед собой. "
                f"Он доверчиво протягивает вам первую лапку. ✨🐾\n\n"
                f"Вы аккуратно расчёсываете каждую лапку, удаляя пылинки и распутывая маленькие колтунки. "
                f"{dragon_name} мурлычет от удовольствия и подставляет то одну, то другую лапку, явно наслаждаясь процессом. "
                f"После каждой лапки он внимательно её осматривает, кивает одобрительно и протягивает следующую.\n\n"
                f"Когда все четыре лапки сияют чистотой, {dragon_name} радостно топает на месте, демонстрируя результат. "
                f"'Спасибо! Теперь я могу гордиться своими лапками!' - говорит он, счастливо виляя хвостом."
            )
        
        elif action == "wipe_face":
            return (
                f"Вы берёте мягкую салфетку, смоченную тёплой водой, и нежно протираете мордочку {dragon_name}. 🛁😊\n\n"
                f"Сначала он немного морщится от неожиданности, но потом закрывает глазки от удовольствия. "
                f"Вы аккуратно протираете область вокруг глаз, носик, щёчки. {dragon_name} сидит неподвижно, "
                f"наслаждаясь заботой.\n\n"
                f"'Как приятно быть чистеньким!' - говорит он, когда вы заканчиваете. "
                f"Его мордочка сияет, глазки блестят. Он поворачивает голову из стороны в сторону, "
                f"показывая свою чистоту со всех ракурсов, явно довольный результатом."
            )
        
        elif action == "clean_nails":
            return (
                f"Вы усаживаете {dragon_name} на специальную подушечку для ухода и берёте инструмент для чистки коготков. 💅✨\n\n"
                f"Он терпеливо сидит и наблюдает за вашими действиями. Вы аккуратно чистите каждый коготок, "
                f"удаляя скопившуюся грязь. {dragon_name} иногда подрагивает, когда вы касаетесь особенно чувствительных мест, "
                f"но в целом ведёт себя очень спокойно и доверчиво.\n\n"
                f"После процедуры он внимательно осматривает свои коготки, постукивает ими по столу. "
                f"'Идеально! Теперь я не буду царапаться, когда буду играть!' - радуется он, демонстрируя свои чистые коготки."
            )
        
        elif action == "clean_teeth":
            return (
                f"Вы готовите специальную драконью зубную щётку и пасту с мятным вкусом. {dragon_name} с интересом наблюдает. 🦷🌟\n\n"
                f"Он открывает ротик, и вы аккуратно чистите каждый зубок. Паста пенится, издавая свежий мятный аромат. "
                f"{dragon_name} старается не двигаться, хотя иногда невольно морщится от необычных ощущений.\n\n"
                f"После чистки он полощет ротик водой и широко улыбается вам. "
                f"'Посмотри, какие они белые и блестящие!' - говорит он, демонстрируя свою идеальную улыбку. "
                f"Вы тоже не можете не улыбнуться в ответ - его радость заразительна."
            )
        
        elif action == "brush_fur":
            return (
                f"Вы берёте драконью расчёску - красивую, с ручкой из полированного дерева и частыми зубьями. "
                f"{dragon_name} радостно подбегает и садится перед вами. 💆✨\n\n"
                f"Вы начинаете аккуратно расчёсывать его шёрстку, начиная с головы и двигаясь к хвосту. "
                f"С каждым движением расчёски шёрстка становится всё более блестящей и пушистой. "
                f"{dragon_name} мурлычет от удовольствия, иногда подставляя особенно любимые места для расчёсывания.\n\n"
                f"Когда вы заканчиваете, он встаёт и отряхивается. Его шёрстка переливается на свету, "
                f"каждая шерстинка лежит идеально. 'Я сияю как новенький!' - радуется он, кружась на месте."
            )
        
        elif action == "bath_shampoo":
            return (
                f"Вы набираете в маленькую ванночку тёплую воду и добавляете волшебный шампунь, который пахнет цветами и мёдом. 🧴🌈\n\n"
                f"{dragon_name} осторожно залезает в воду. Сначала он немного напряжён, но тёплая вода и приятный аромат быстро расслабляют его. "
                f"Вы аккуратно намыливаете его шёрстку, массируя каждую часть тела. Пена становится всё больше, "
                f"и вскоре {dragon_name} выглядит как пушистое облачко с торчащими ушками.\n\n"
                f"После тщательного ополаскивания вы заворачиваете его в мягкое полотенце. "
                f"Его шёрстка сияет чистотой, пахнет цветами и свежестью. "
                f"'Я никогда не чувствовал себя таким чистым!' - говорит он, довольный."
            )
        
        elif action == "trim_nails_scissors":
            return (
                f"Вы берёте золотые ножницы - специальные, для ухода за драконьими когтями. {dragon_name} с интересом их рассматривает. ✂️💎\n\n"
                f"Он доверчиво даёт вам свои лапки одну за другой. Вы аккуратно подстригаете кончики коготков, "
                f"стараясь не задеть живую часть. {dragon_name} сидит очень спокойно, хотя иногда вздрагивает от щелчка ножниц.\n\n"
                f"Когда все коготки подстрижены, он осматривает их. 'Идеальная форма! Теперь я не буду цепляться за ковёр!' - радуется он. "
                f"Он пробует постучать коготками по столу - звук стал мягче и аккуратнее."
            )
        
        elif action == "play_toy":
            return (
                f"Вы достаёте плюшевого дракончика - лучшего друга {dragon_name}. Его глазки сразу загораются. 🧸🎉\n\n"
                f"Вы начинаете играть: бросаете игрушку, {dragon_name} ловит её и приносит обратно. "
                f"Потом вы играете в перетягивание - он хватает игрушку зубами и тянет на себя, а вы слегка сопротивляетесь. "
                f"Он радостно рычит, его хвост весело виляет, глазки сияют азартом.\n\n"
                f"После активной игры {dragon_name} падает на пол рядом с игрушкой, тяжело дыша, но счастливо улыбаясь. "
                f"'Это было потрясающе! Давай ещё поиграем завтра!' - говорит он, обнимая плюшевого друга."
            )
        
        else:
            return f"Вы ухаживаете за {dragon_name}, и он явно наслаждается вашим вниманием. ✨"
    
    @staticmethod
    def get_feed_scene(dragon_name: str, snack_type: str) -> str:
        snack_names = {
            "cookie_raisin": "печенье с изюмом",
            "chocolate_bar": "шоколадную плитку",
            "vanilla_marshmallow": "ванильный зефир",
            "gingerbread": "имбирный пряник",
            "fruit_marmalade": "фруктовый мармелад",
            "chocolate_cake": "шоколадное пирожное",
            "donut": "сладкий пончик"
        }
        
        snack = snack_names.get(snack_type, "угощение")
        
        scenes = [
            f"Вы достаёте из кармана {snack} и показываете {dragon_name}. "
            f"Его глазки загораются, носик радостно подрагивает, улавливая сладкий аромат. 🍪✨\n\n"
            f"Он осторожно подходит, обнюхивает угощение, а затем аккуратно берёт его из ваших рук. "
            f"Сначала он откусывает маленький кусочек, пробуя вкус, а затем с наслаждением уплетает остальное, "
            f"мурлыча от удовольствия и виляя хвостиком.\n\n"
            f"После трапезы он облизывает лапки, стараясь не пропустить ни крошки, "
            f"а затем с благодарностью смотрит на вас. 'Спасибо! Это было невероятно вкусно!' - говорит он, "
            f"и вы видите, как его настроение заметно улучшается.",
            
            f"Вы кладёте {snack} на маленькую тарелочку и ставите перед {dragon_name}. "
            f"Он с интересом склоняется над угощением, внимательно его изучая. 🍰🐉\n\n"
            f"Сначала он отламывает маленький кусочек, пробует его, задумчиво жуёт. Потом ещё один. "
            f"И вот он уже ест с явным удовольствием, закрывая глазки от наслаждения. "
            f"Каждый кусочек он пережёвывает медленно, словно стараясь продлить удовольствие.\n\n"
            f"Когда от {snack} не остаётся и следа, {dragon_name} довольным взглядом окидывает тарелку, "
            f"потом смотрит на вас. 'Вкуснее ничего не ел! Ты знаешь, как меня порадовать!' "
            f"Он облизывает губы, на его мордочке - выражение полного счастья.",
            
            f"Вы преподносите {snack} {dragon_name} как особый подарок. Он принимает его с благоговением, "
            f"держа аккуратно в обеих лапках. 🎁🌟\n\n"
            f"Не спеша, смакуя каждый момент, он начинает есть. Вы видите, как его щёчки двигаются в такт жеванию, "
            f"как он иногда прикрывает глазки, полностью погружаясь в вкусовые ощущения. "
            f"Это не просто еда - это целый ритуал наслаждения.\n\n"
            f"Закончив, {dragon_name} аккуратно кладёт крошки обратно на тарелочку (чистюля же!) "
            f"и смотрит на вас сияющим взглядом. 'Это было... волшебно! Спасибо тебе!' "
            f"Он подходит и нежно трётся мордочкой о вашу руку в знак благодарности."
        ]
        
        return random.choice(scenes)

# ==================== МИДЛВАРЫ И ОБРАБОТЧИКИ ОШИБОК ====================
async def error_handler(update: types.Update, exception: Exception):
    try:
        if isinstance(exception, TelegramAPIError):
            logger.error(f"Telegram API error: {exception}")
        else:
            logger.error(f"Unhandled exception: {exception}\n{traceback.format_exc()}")
        
        try:
            if update and hasattr(update, 'message') and update.message:
                await update.message.answer(
                    "<b>⚠️ Произошла непредвиденная ошибка.</b>\n\n"
                    "<i>Пожалуйста, попробуйте ещё раз или используйте команду /start</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
        except:
            pass
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")
    
    return True

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "<b>ℹ️ Нет активных действий для отмены.</b>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return
    
    await state.clear()
    await message.answer(
        "<b>✅ Действие отменено.</b>\n\n"
        "<i>Вы можете начать заново с помощью кнопок меню.</i>",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

# ==================== НАЧАЛЬНЫЙ ЭКРАН И БАЗОВЫЕ КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        db.create_user(user_id, username)
        has_dragon = db.dragon_exists(user_id)
        
        welcome_text = (
            f"<b>✨ Добро пожаловать в мир Кофейных Драконов, {escape_html(username)}! ✨</b>\n\n"
            
            f"<i>🌙 В далёких горах, где растут волшебные кофейные деревья, "
            f"рождаются особенные драконы.</i> Они питаются ароматным кофе, "
            f"обожают сны, игры и тёплые объятия.\n\n"
            
            f"<b>🐾 Тебе выпала честь стать хранителем одного из них!</b>\n\n"
            
            f"<b>📋 ВОЗМОЖНОСТИ 7.0:</b>\n"
            f"• 🎭 <b>10 уникальных характеров</b> с глубокой проработкой\n"
            f"• 🍪 <b>Новая система кормления</b> отдельным действием\n"
            f"• 📖 <b>Только развёрнутые сцены</b> - больше погружения\n"
            f"• 🛡️ <b>Умная анти-спам система</b> с жалобами дракона\n"
            f"• 📊 <b>Выровненная статистика</b> - удобный просмотр\n\n"
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
async def cmd_help(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        # НЕ УДАЛЯЕМ сообщение пользователя
        
        has_dragon = db.dragon_exists(user_id)
        
        help_text = (
            "<b>📚 КОМАНДЫ И ХАРАКТЕРЫ (v7.0)</b>\n\n"
            
            "<b>🐉 ОСНОВНЫЕ КОМАНДЫ:</b>\n"
            "<code>/start</code> - начать игру\n"
            "<code>/help</code> - эта справка\n"
            "<code>/create</code> - создать дракона\n"
            "<code>/status</code> - статус дракона\n"
            "<code>/cancel</code> - отменить текущее действие\n\n"
            
            "<b>🍪 НОВОЕ: КОРМЛЕНИЕ</b>\n"
            "<code>/feed</code> - покормить дракона отдельно (повышает сытость)\n\n"
            
            "<b>😴 СОН И ОТДЫХ</b>\n"
            "<code>/sleep</code> - уложить дракона спать с разными сценами\n\n"
            
            "<b>❤ УХОД И ЗАБОТА</b>\n"
            "<code>/coffee</code> - приготовить кофе с добавками и угощениями\n"
            "<code>/hug</code> - обнять дракона в разных ситуациях\n"
            "<code>/care</code> - ухаживать за драконом\n\n"
            
            "<b>🎮 РАЗВЛЕЧЕНИЯ</b>\n"
            "<code>/games</code> - поиграть в игру\n\n"
            
            "<b>💰 ЭКОНОМИКА</b>\n"
            "<code>/shop</code> - магазин товаров\n"
            "<code>/inventory</code> - инвентарь\n\n"
            
            "<b>🔕 НАСТРОЙКИ</b>\n"
            "<code>/notifications</code> - управление уведомлениями\n\n"
            
            "━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 Используй кнопки внизу для быстрого доступа</i>\n"
            "<i>👇 Или выбери раздел помощи:</i>"
        )
        
        # Отправляем новое сообщение вместо редактирования
        await message.answer(help_text, parse_mode="HTML", reply_markup=get_help_keyboard())
        await state.set_state(GameStates.help_section)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_help: {e}")
        await message.answer("<b>❌ Произошла ошибка при показе помощи.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.help_section, F.data.startswith("help_"))
async def process_help_section(callback: types.CallbackQuery, state: FSMContext):
    try:
        action = callback.data.replace("help_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        if action == "commands":
            commands_text = (
                "<b>📋 ВСЕ КОМАНДЫ БОТА</b>\n\n"
                
                "<b>🐉 ОСНОВНЫЕ:</b>\n"
                "<code>/start</code> - начать игру\n"
                "<code>/help</code> - помощь\n"
                "<code>/create</code> - создать дракона\n"
                "<code>/status</code> - статус дракона\n"
                "<code>/cancel</code> - отменить текущее действие\n\n"
                
                "<b>🍪 НОВОЕ: КОРМЛЕНИЕ</b>\n"
                "<code>/feed</code> - покормить дракона сладостями\n\n"
                
                "<b>☕ КОФЕ И ЕДА:</b>\n"
                "<code>/coffee</code> - приготовить кофе с угощением\n\n"
                
                "<b>😴 ОТДЫХ И УХОД:</b>\n"
                "<code>/sleep</code> - уложить спать\n"
                "<code>/hug</code> - обнять дракона\n"
                "<code>/care</code> - ухаживать за драконом\n\n"
                
                "<b>🎮 РАЗВЛЕЧЕНИЯ:</b>\n"
                "<code>/games</code> - мини-игры\n\n"
                
                "<b>💰 ЭКОНОМИКА:</b>\n"
                "<code>/shop</code> - магазин\n"
                "<code>/inventory</code> - инвентарь\n\n"
                
                "<b>🔕 НАСТРОЙКИ:</b>\n"
                "<code>/notifications</code> - уведомления\n\n"
                
                "━━━━━━━━━━━━━━━━━━━\n"
                "<i>💡 Также используй кнопки меню для быстрого доступа!</i>"
            )
            
            # Редактируем сообщение (только в меню помощи для удобства навигации)
            await callback.message.edit_text(
                commands_text,
                parse_mode="HTML",
                reply_markup=get_help_keyboard()
            )
            
        elif action == "characters":
            characters_intro = (
                "<b>🎭 ВСЕ ХАРАКТЕРЫ ДРАКОНОВ</b>\n\n"
                
                "<i>✨ Каждый дракон обладает уникальным характером,\n"
                "который влияет на его поведение, реакции и предпочтения!</i>\n\n"
                
                "👇 <b>Выбери характер, чтобы узнать о нём подробнее:</b>\n\n"
                
                "• ☕ <b>Кофеман</b> - обожает кофе и разбирается в сортах\n"
                "• 📚 <b>Книгочей</b> - живёт в мире книг и историй\n"
                "• 💖 <b>Неженка</b> - требует много ласки и внимания\n"
                "• ✨ <b>Чистюля</b> - следит за чистотой и уходом\n"
                "• 🍰 <b>Гурман</b> - ценитель изысканных вкусов\n"
                "• 🎮 <b>Игрик</b> - обожает игры и соревнования\n"
                "• 😴 <b>Соня</b> - мастер сладких снов и отдыха\n"
                "• ⚡ <b>Энерджайзер</b> - живая электростанция\n"
                "• 🤔 <b>Философ</b> - мудрец драконьего мира\n"
                "• 🔍 <b>Исследователь</b> - искатель тайн и загадок\n\n"
                
                "<i>💡 Характер определяется при создании дракона\n"
                "и остаётся с ним на всю жизнь!</i>"
            )
            
            await callback.message.edit_text(
                characters_intro,
                parse_mode="HTML",
                reply_markup=get_characters_list_keyboard()
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_help_section: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(GameStates.help_section, F.data.startswith("char_"))
async def process_character_detail(callback: types.CallbackQuery, state: FSMContext):
    try:
        action = callback.data.replace("char_", "")
        
        if action == "back":
            await callback.message.edit_text(
                "<b>📚 Помощь</b>\n\nВыберите раздел:",
                parse_mode="HTML",
                reply_markup=get_help_keyboard()
            )
            await state.set_state(GameStates.help_section)
            await callback.answer("↩️ Возвращаемся в помощь")
            return
        
        character_map = {
            "cofeman": "кофеман",
            "bookworm": "книгочей",
            "tender": "неженка",
            "clean": "чистюля",
            "gourmet": "гурман",
            "gamer": "игрик",
            "sleeper": "соня",
            "energizer": "энерджайзер",
            "philosopher": "философ",
            "explorer": "исследователь"
        }
        
        character_trait = character_map.get(action, "неженка")
        char_info = CharacterPersonality.get_character_description(character_trait)
        
        character_text = (
            f"<b>{char_info['emoji']} {char_info['name']}</b>\n\n"
            
            f"<i>{char_info['description']}</i>\n\n"
            
            f"<b>🎯 ОСОБЕННОСТИ:</b>\n"
        )
        
        for feature in char_info['features']:
            character_text += f"• {feature}\n"
        
        character_text += f"\n<b>💡 СОВЕТ ХРАНИТЕЛЮ:</b>\n{char_info['advice']}\n\n"
        
        character_text += (
            "━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 Этот характер будет влиять на все действия дракона,\n"
            "его реакции в уведомленияи и предпочтения в еде и уходе!</i>"
        )
        
        await callback.message.edit_text(
            character_text,
            parse_mode="HTML",
            reply_markup=get_characters_list_keyboard()
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_character_detail: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(Command("create"))
@dp.message(F.text == "🐉 Создать дракона")
async def cmd_create(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        if db.dragon_exists(user_id):
            await message.answer(
                "<b>🎉 У тебя уже есть дракон!</b>\n\n"
                "<i>Используй кнопку «🐉 Статус» чтобы проверить как он поживает\n"
                "или «✨ Уход» чтобы позаботиться о нём.</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
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
        await state.clear()
        await message.answer("<b>❌ Произошла ошибка при создании дракона.</b>", parse_mode="HTML")

@dp.message(GameStates.waiting_for_name)
async def process_dragon_name(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        dragon_name = message.text
        
        is_valid, error_message = validate_dragon_name(dragon_name)
        if not is_valid:
            await message.answer(
                f"<b>❌ {error_message}</b>\n\n"
                f"Попробуй другое имя:",
                parse_mode="HTML"
            )
            return
        
        dragon = Dragon(name=dragon_name)
        dragon_data = dragon.to_dict()
        
        success = db.create_dragon(user_id, dragon_data)
        
        if not success:
            await message.answer("<b>❌ Не удалось создать дракона. Попробуй еще раз.</b>", parse_mode="HTML")
            await state.clear()
            return
        
        initial_inventory = {
            "coffee_beans": 10,
            "cookie": 5,
            "chocolate": 2,
            "marshmallow": 1,
            "gingerbread": 1
        }
        
        for item, count in initial_inventory.items():
            db.update_inventory(user_id, item, count)
        
        character = dragon.character.get("основная_черта", "неженка")
        char_info = CharacterPersonality.get_character_description(character)
        
        await message.answer(
            f"<b>🎊 ВОЛШЕБСТВО СВЕРШИЛОСЬ! 🎊</b>\n\n"
            f"✨ Из яйца появился <b>{escape_html(dragon_name)}</b> - твой кофейный дракон!\n\n"
            
            f"<b>{char_info['emoji']} ХАРАКТЕР:</b> {char_info['name']}\n"
            f"<i>{char_info['description']}</i>\n\n"
            
            f"<b>🎯 КЛЮЧЕВЫЕ ОСОБЕННОСТИ:</b>\n"
            f"• {char_info['features'][0]}\n"
            f"• {char_info['features'][1]}\n\n"
            
            f"<b>❤ ЛЮБИМОЕ:</b>\n"
            f"• ☕ Кофе: <code>{dragon.favorites['кофе']}</code>\n"
            f"• 🍬 Сладость: <code>{dragon.favorites['сладость']}</code>\n"
            f"• 📚 Книги: <code>{dragon.favorites['жанр_книг']}</code>\n\n"
            
            f"<b>💰 ЗОЛОТО:</b> <code>{dragon.gold}</code>\n\n"
            
            f"<b>💡 СОВЕТ:</b> {char_info['advice']}\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Начни с того, что приготовь ему кофе ☕</i>\n"
            f"<i>Используй кнопки ниже для ухода 🐾</i>",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        
        logger.info(f"Создан дракон: {dragon_name} ({character}) для пользователя {user_id}")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_dragon_name: {e}")
        await state.clear()
        await message.answer("<b>❌ Произошла ошибка при создании дракона.</b>", parse_mode="HTML")

# ==================== СТАТУС ДРАКОНА ====================
@dp.message(Command("status"))
@dp.message(F.text == "🐉 Статус")
async def cmd_status(message: types.Message):
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
        
        # Обновляем показатели с уменьшением на 5% в час
        dragon.update_over_time()
        
        db.update_dragon(user_id, dragon.to_dict())
        
        character_trait = dragon.character.get("основная_черта", "неженка")
        char_info = CharacterPersonality.get_character_description(character_trait)
        
        now = datetime.now(timezone.utc)
        
        status_text = (
            f"<b>{char_info['emoji']} {escape_html(dragon.name)}</b> "
            f"[Уровень {dragon.level}]\n"
            f"🎭 <b>Характер:</b> <code>{char_info['name']}</code>\n\n"
            
            f"⭐ <b>Опыт:</b> <code>{dragon.experience}/100</code>\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n\n"
            
            f"<b>📊 ПОКАЗАТЕЛИ (уменьшаются на 5%/час):</b>\n"
        )
        
        stats_data = [
            ("кофе", dragon.stats.get("кофе", 0)),
            ("сон", dragon.stats.get("сон", 0)),
            ("настроение", dragon.stats.get("настроение", 0)),
            ("аппетит", dragon.stats.get("аппетит", 0)),
            ("энергия", dragon.stats.get("энергия", 0)),
            ("пушистость", dragon.stats.get("пушистость", 0))
        ]
        
        for stat_name, stat_value in stats_data:
            status_text += format_stat_line(stat_name, stat_value) + "\n"
        
        status_text += "\n"
        
        # Характерное сообщение
        hour = now.hour
        
        if 6 <= hour <= 11:
            situation = "morning"
        elif 18 <= hour <= 23:
            situation = "bedtime" if character_trait == "книгочей" else "morning"
        else:
            situation = "morning"
            
        character_message = CharacterPersonality.get_character_message(
            character_trait, 
            situation,
            dragon.name
        )
        
        status_text += f"<i>💬 {character_message}</i>\n\n"
        
        warnings = []
        if dragon.stats.get("кофе", 70) < 30:
            warnings.append("☕ Нужно срочно попить кофе!")
        if dragon.stats.get("сон", 50) < 30:
            warnings.append("💤 Дракон с трудом держит глазки открытыми...")
        if dragon.stats.get("аппетит", 50) < 30:
            warnings.append("🍪 Пора подкрепиться!")
        if dragon.stats.get("настроение", 80) < 30:
            warnings.append("😔 Дракон грустит... нужна ласка")
        if dragon.stats.get("энергия", 75) < 20:
            warnings.append("⚡ Нужно отдохнуть или выпить кофе")
        if dragon.stats.get("пушистость", 90) < 30:
            warnings.append("✨ Пора причесаться!")
        
        if warnings:
            status_text += f"<b>⚠️ ВНИМАНИЕ:</b>\n"
            for warning in warnings:
                status_text += f"• {warning}\n"
            status_text += "\n"
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 <i>Текущее время (UTC):</i> <code>{now.strftime('%H:%M:%S')}</code>\n"
            f"📅 <i>Дата:</i> <code>{now.strftime('%d.%m.%Y')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        # Отправляем новое сообщение статуса
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

# ==================== ОБНЯТЬ ====================
@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_hug, spam_message = rate_limiter.check_spam(user_id, "hug")
        if not can_hug and spam_message:
            await message.answer(
                f"<b>🤗 {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующими объятиями</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем максимум настроения
        mood_stat = dragon.stats.get("настроение", 0)
        if mood_stat >= 95:
            max_message = check_stat_max(mood_stat, "настроение", dragon.character.get("основная_черта", ""))
            if max_message:
                await message.answer(
                    f"<b>{max_message}</b>\n\n"
                    f"<i>💡 Может, сделаем что-то другое?</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        # Применяем действие
        result = dragon.apply_action("обнимашки")
        
        character_trait = dragon.character.get("основная_черта", "")
        
        # Характерный бонус
        if character_trait == "неженка":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 25)
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 10)
            character_bonus = "<b>💖 Неженка обожает обнимашки! +25 к настроению, +10 к бодрости</b>\n"
        elif character_trait == "энерджайзер":
            dragon.stats["энергия"] = min(100, dragon.stats["энергия"] + 15)
            character_bonus = "<b>⚡ Энерджайзер заряжается от объятий! +15 к энергии</b>\n"
        elif character_trait == "соня":
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 20)
            character_bonus = "<b>😴 Соне в объятиях тепло и уютно! +20 к бодрости</b>\n"
        else:
            character_bonus = ""
        
        # Получаем развёрнутую сцену обнимашек
        scene = ActionDescriptions.get_hug_scene(dragon.name, character_trait)
        
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, "Обнял дракона")
        
        response = (
            f"{scene}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}%\n"
            f"• 💤 Бодрость: +{result['stat_changes'].get('сон', 0)}%\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Добавляем характерное сообщение
        hug_message = CharacterPersonality.get_character_message(
            character_trait,
            "hug_time",
            dragon.name
        )
        response += f"\n\n<i>💬 {hug_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"❤ <i>Текущее настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        # Отправляем новое сообщение с развёрнутой сценой
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_hug: {e}")
        await message.answer("<b>❌ Произошла ошибка при обнимашках.</b>", parse_mode="HTML")

# ==================== КОФЕ ====================
@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_coffee, spam_message = rate_limiter.check_spam(user_id, "coffee")
        if not can_coffee and spam_message:
            await message.answer(
                f"<b>☕ {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующим кофе</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем максимум кофе
        coffee_stat = dragon.stats.get("кофе", 0)
        if coffee_stat >= 95:
            max_message = check_stat_max(coffee_stat, "кофе", dragon.character.get("основная_черта", ""))
            if max_message:
                await message.answer(
                    f"<b>{max_message}</b>\n\n"
                    f"<i>💡 Может, сделаем что-то другое?</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        inventory = db.get_inventory(user_id)
        
        # Проверяем кофейные зёрна
        coffee_beans = inventory.get("coffee_beans", 0)
        if coffee_beans <= 0:
            await message.answer(
                "<b>❌ Нет кофейных зёрен!</b>\n\n"
                "<b>🛍️ Купи в магазине:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или <code>/shop</code>\n\n"
                "<i>💡 Кофейные зёрна можно купить в категории «Кофе и ингредиенты»</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "coffee_time",
            dragon.name
        )
        
        # Отправляем новое сообщение с выбором кофе
        await message.answer(
            f"<b>☕ ПРИГОТОВЬ КОФЕ ДЛЯ {escape_html(dragon.name)}</b>\n\n"
            f"{char_message}\n\n"
            
            f"✨ <i>Кофейный показатель:</i> <code>{coffee_stat}%</code>\n\n"
            
            f"<b>💡 Выбери напиток:</b>\n"
            f"• ☕ <b>Эспрессо</b> - классический крепкий кофе\n"
            f"• ☕ <b>Латте</b> - с молоком и нежной пенкой\n"
            f"• ☕ <b>Капучино</b> - воздушная пенка и молоко\n"
            f"• ☕ <b>Раф</b> - с ванильным сахаром и сливками\n"
            f"• ☕ <b>Американо</b> - эспрессо с водой\n"
            f"• ☕ <b>Мокко</b> - с шоколадом и молоком\n\n"
            
            f"<b>📦 Кофейные зёрна:</b> <code>{coffee_beans}</code>\n"
            f"<b>🎭 Характер:</b> <code>{character_trait}</code>\n\n"
            
            f"<i>Любимый кофе дракона: {dragon.favorites.get('кофе', 'латте')}</i>",
            parse_mode="HTML",
            reply_markup=get_coffee_keyboard()
        )
        
        await state.set_state(GameStates.making_coffee)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_coffee: {e}")
        await message.answer("<b>❌ Произошла ошибка при приготовлении кофе.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.making_coffee, F.data.startswith("coffee_"))
async def process_coffee_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("coffee_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        # Используем кофейные зерна
        inventory = db.get_inventory(user_id)
        coffee_beans = inventory.get("coffee_beans", 0)
        if coffee_beans <= 0:
            await callback.answer("❌ Нет кофейных зёрен!")
            return
        
        # Уменьшаем количество кофейных зёрен
        db.update_inventory(user_id, "coffee_beans", -1)
        
        await state.update_data(coffee_type=action)
        
        # Проверяем, есть ли добавки в инвентаре
        inventory = db.get_inventory(user_id)
        has_additions = any(inventory.get(item, 0) > 0 for item in [
            "chocolate_chips", "honey_syrup", "vanilla_icecream", "caramel_syrup", "hazelnut"
        ])
        
        if has_additions:
            additions_text = ""
            if inventory.get("chocolate_chips", 0) > 0:
                additions_text += f"• 🍫 Шоколадные чипсы: {inventory['chocolate_chips']} шт.\n"
            if inventory.get("honey_syrup", 0) > 0:
                additions_text += f"• 🍯 Медовый сироп: {inventory['honey_syrup']} шт.\n"
            if inventory.get("vanilla_icecream", 0) > 0:
                additions_text += f"• 🍦 Ванильное мороженое: {inventory['vanilla_icecream']} шт.\n"
            if inventory.get("caramel_syrup", 0) > 0:
                additions_text += f"• 🍭 Карамельный сироп: {inventory['caramel_syrup']} шт.\n"
            if inventory.get("hazelnut", 0) > 0:
                additions_text += f"• 🌰 Фундук: {inventory['hazelnut']} шт.\n"
            
            # Редактируем сообщение (для удобства навигации)
            await callback.message.edit_text(
                f"<b>☕ Выбран {get_coffee_name(action)} для {escape_html(dragon.name)}</b>\n\n"
                f"✨ <i>Теперь выбери добавку (или пропусти):</i>\n\n"
                f"<b>📦 Доступные добавки:</b>\n"
                f"{additions_text}\n"
                f"<i>💡 Добавки улучшают настроение дракона!</i>",
                parse_mode="HTML",
                reply_markup=get_coffee_additions_keyboard()
            )
            await state.set_state(GameStates.coffee_additions)
        else:
            # Если нет добавок, переходим сразу к сладостям
            await state.update_data(addition="none")
            await process_coffee_additions_no_additions(callback, state)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(GameStates.coffee_additions, F.data.startswith("add_"))
async def process_coffee_additions(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("add_", "")
        
        if action == "back":
            data = await state.get_data()
            dragon_data = data.get("dragon_data")
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
                inventory = db.get_inventory(user_id)
                coffee_beans = inventory.get("coffee_beans", 0)
                
                # Редактируем сообщение (для удобства навигации)
                await callback.message.edit_text(
                    f"<b>☕ ПРИГОТОВЬ КОФЕ ДЛЯ {escape_html(dragon.name)}</b>\n\n"
                    f"{CharacterPersonality.get_character_message(dragon.character.get('основная_черта', ''), 'coffee_time', dragon.name)}\n\n"
                    f"✨ <i>Кофейный показатель:</i> <code>{dragon.stats.get('кофе', 0)}%</code>\n\n"
                    f"<b>💡 Выбери напиток:</b>\n"
                    f"• ☕ <b>Эспрессо</b> - классический крепкий кофе\n"
                    f"• ☕ <b>Латте</b> - с молоком и нежной пенкой\n"
                    f"• ☕ <b>Капучино</b> - воздушная пенка и молоко\n"
                    f"• ☕ <b>Раф</b> - с ванильным сахаром и сливками\n"
                    f"• ☕ <b>Американо</b> - эспрессо с водой\n"
                    f"• ☕ <b>Мокко</b> - с шоколадом и молоком\n\n"
                    f"<b>📦 Кофейные зёрна:</b> <code>{coffee_beans}</code>",
                    parse_mode="HTML",
                    reply_markup=get_coffee_keyboard()
                )
                await state.set_state(GameStates.making_coffee)
            return
        
        # Используем добавку если выбрана
        if action != "none":
            addition_map = {
                "chocolate": "chocolate_chips",
                "honey": "honey_syrup",
                "icecream": "vanilla_icecream",
                "syrup": "caramel_syrup"
            }
            
            addition_item = addition_map.get(action)
            if addition_item:
                inventory = db.get_inventory(user_id)
                if inventory.get(addition_item, 0) <= 0:
                    await callback.answer("❌ Нет этой добавки!")
                    return
                
                db.update_inventory(user_id, addition_item, -1)
        
        await state.update_data(addition=action)
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем наличие сладостей
        inventory = db.get_inventory(user_id)
        has_snacks = any(inventory.get(item, 0) > 0 for item in [
            "cookie", "chocolate", "marshmallow", "gingerbread", "marmalade", "cake", "donut"
        ])
        
        if has_snacks:
            snacks_text = ""
            if inventory.get("cookie", 0) > 0:
                snacks_text += f"• 🍪 Печенье: {inventory['cookie']} шт.\n"
            if inventory.get("chocolate", 0) > 0:
                snacks_text += f"• 🍫 Шоколад: {inventory['chocolate']} шт.\n"
            if inventory.get("marshmallow", 0) > 0:
                snacks_text += f"• ☁️ Зефир: {inventory['marshmallow']} шт.\n"
            if inventory.get("gingerbread", 0) > 0:
                snacks_text += f"• 🎄 Пряник: {inventory['gingerbread']} шт.\n"
            if inventory.get("marmalade", 0) > 0:
                snacks_text += f"• 🍬 Мармелад: {inventory['marmalade']} шт.\n"
            if inventory.get("cake", 0) > 0:
                snacks_text += f"• 🎂 Пирожное: {inventory['cake']} шт.\n"
            if inventory.get("donut", 0) > 0:
                snacks_text += f"• 🍩 Пончик: {inventory['donut']} шт.\n"
            
            # Редактируем сообщение (для удобства навигации)
            await callback.message.edit_text(
                f"<b>☕ {get_coffee_name(data.get('coffee_type', 'espresso'))} с {get_addition_name(action)} готов!</b>\n\n"
                f"✨ <i>Теперь выбери сладость (или пропусти):</i>\n\n"
                f"<b>📦 Доступные сладости:</b>\n"
                f"{snacks_text}\n"
                f"<i>💡 Сладости улучшают настроение и сытость дракона!</i>",
                parse_mode="HTML",
                reply_markup=get_coffee_snack_keyboard(inventory)
            )
            await state.set_state(GameStates.coffee_snack)
        else:
            # Если нет сладостей, завершаем приготовление
            await state.update_data(snack="none")
            await finish_coffee_preparation(callback, state)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_additions: {e}")
        await callback.answer("❌ Произошла ошибка")

async def process_coffee_additions_no_additions(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        dragon = Dragon.from_dict(dragon_data)
        
        inventory = db.get_inventory(user_id)
        has_snacks = any(inventory.get(item, 0) > 0 for item in [
            "cookie", "chocolate", "marshmallow", "gingerbread", "marmalade", "cake", "donut"
        ])
        
        if has_snacks:
            snacks_text = ""
            if inventory.get("cookie", 0) > 0:
                snacks_text += f"• 🍪 Печенье: {inventory['cookie']} шт.\n"
            if inventory.get("chocolate", 0) > 0:
                snacks_text += f"• 🍫 Шоколад: {inventory['chocolate']} шт.\n"
            if inventory.get("marshmallow", 0) > 0:
                snacks_text += f"• ☁️ Зефир: {inventory['marshmallow']} шт.\n"
            if inventory.get("gingerbread", 0) > 0:
                snacks_text += f"• 🎄 Пряник: {inventory['gingerbread']} шт.\n"
            if inventory.get("marmalade", 0) > 0:
                snacks_text += f"• 🍬 Мармелад: {inventory['marmalade']} шт.\n"
            if inventory.get("cake", 0) > 0:
                snacks_text += f"• 🎂 Пирожное: {inventory['cake']} шт.\n"
            if inventory.get("donut", 0) > 0:
                snacks_text += f"• 🍩 Пончик: {inventory['donut']} шт.\n"
            
            # Редактируем сообщение (для удобства навигации)
            await callback.message.edit_text(
                f"<b>☕ {get_coffee_name(data.get('coffee_type', 'espresso'))} готов!</b>\n\n"
                f"✨ <i>Теперь выбери сладость (или пропусти):</i>\n\n"
                f"<b>📦 Доступные сладости:</b>\n"
                f"{snacks_text}\n"
                f"<i>💡 Сладости улучшают настроение и сытость дракона!</i>",
                parse_mode="HTML",
                reply_markup=get_coffee_snack_keyboard(inventory)
            )
            await state.set_state(GameStates.coffee_snack)
        else:
            await state.update_data(snack="none")
            await finish_coffee_preparation(callback, state)
            
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_additions_no_additions: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(GameStates.coffee_snack, F.data.startswith("snack_"))
async def process_coffee_snack(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("snack_", "")
        
        if action == "back":
            data = await state.get_data()
            dragon_data = data.get("dragon_data")
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
                inventory = db.get_inventory(user_id)
                
                # Редактируем сообщение (для удобства навигации)
                await callback.message.edit_text(
                    f"<b>☕ {get_coffee_name(data.get('coffee_type', 'espresso'))} с {get_addition_name(data.get('addition', 'none'))} готов!</b>\n\n"
                    f"✨ <i>Теперь выбери сладость (или пропусти):</i>\n\n"
                    f"<b>📦 Доступные сладости:</b>\n",
                    parse_mode="HTML",
                    reply_markup=get_coffee_snack_keyboard(inventory)
                )
            return
        
        # Маппинг callback-данных на названия в инвентаре
        snack_map = {
            "cookie_raisin": "cookie",
            "chocolate_bar": "chocolate",
            "vanilla_marshmallow": "marshmallow",
            "gingerbread": "gingerbread",
            "fruit_marmalade": "marmalade",
            "chocolate_cake": "cake",
            "donut": "donut"
        }
        
        # Используем сладость если выбрана
        if action != "none":
            snack_item = snack_map.get(action)
            if snack_item:
                inventory = db.get_inventory(user_id)
                if inventory.get(snack_item, 0) <= 0:
                    await callback.answer("❌ Нет этой сладости!")
                    return
                
                db.update_inventory(user_id, snack_item, -1)
        
        await state.update_data(snack=action)
        await finish_coffee_preparation(callback, state)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_coffee_snack: {e}")
        await callback.answer("❌ Произошла ошибка")

async def finish_coffee_preparation(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        data = await state.get_data()
        
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        coffee_type = data.get("coffee_type", "espresso")
        addition = data.get("addition", "none")
        snack = data.get("snack", "none")
        
        # Применяем действие
        result = dragon.apply_action("кофе")
        
        # Бонусы за добавки и сладости
        mood_bonus = 0
        appetite_bonus = 0
        
        if addition != "none":
            mood_bonus += 10
            if addition == "honey" and dragon.character.get("основная_черта") == "гурман":
                mood_bonus += 5
        
        if snack != "none":
            mood_bonus += 15
            appetite_bonus += 25  # НОВОЕ: сладости повышают сытость
            
            # Проверяем, является ли сладость любимой
            snack_names = {
                "cookie_raisin": "печенье",
                "chocolate_bar": "шоколад",
                "vanilla_marshmallow": "зефир",
                "gingerbread": "пряник",
                "fruit_marmalade": "мармелад",
                "chocolate_cake": "пирожное",
                "donut": "пончик"
            }
            
            current_snack = snack_names.get(snack, "")
            if current_snack == dragon.favorites.get("сладость", ""):
                mood_bonus += 10
                appetite_bonus += 15  # Любимая сладость сильнее насыщает
        
        # Применяем бонусы
        dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + mood_bonus)
        dragon.stats["аппетит"] = min(100, dragon.stats.get("аппетит", 0) + appetite_bonus)  # НОВОЕ
        
        # Особый бонус за любимый кофе
        if coffee_type == dragon.favorites.get("кофе", ""):
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
            dragon.stats["энергия"] = min(100, dragon.stats.get("энергия", 0) + 10)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Приготовил {get_coffee_name(coffee_type)}")
        
        # Получаем развёрнутую сцену приготовления кофе
        scene = ActionDescriptions.get_coffee_scene(
            dragon.name,
            coffee_type,
            addition,
            snack
        )
        
        # Характерное сообщение
        character_trait = dragon.character.get("основная_черта", "")
        char_message = ""
        
        if coffee_type == dragon.favorites.get("кофе", ""):
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "favorite_coffee",
                dragon.name
            )
        elif mood_bonus >= 20:
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "happy",
                dragon.name
            )
        else:
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "morning",
                dragon.name
            )
        
        response = (
            f"{scene}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• ☕ Кофе: +{result['stat_changes'].get('кофе', 0)}%\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0) + mood_bonus}%\n"
            f"• ⚡ Энергия: +{result['stat_changes'].get('энергия', 0)}%\n"
            f"• 🍪 Сытость: +{appetite_bonus}%\n"  # НОВОЕ
        )
        
        if addition != "none" or snack != "none":
            response += f"\n<b>✨ БОНУСЫ:</b>\n"
            if addition != "none":
                response += f"• Добавка: +10 к настроению\n"
            if snack != "none":
                response += f"• Сладость: +15 к настроению, +25 к сытости\n"
            if coffee_type == dragon.favorites.get("кофе", ""):
                response += f"• Любимый кофе: +15 к настроению, +10 к энергии\n"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Текущий показатель кофе:</i> <code>{dragon.stats.get('кофе', 0)}%</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>\n"
            f"🍪 <i>Сытость:</i> <code>{dragon.stats.get('аппетит', 0)}%</code>"
        )
        
        # Отправляем новое сообщение с развёрнутой сценой
        await callback.message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.answer("✅ Кофе готово!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в finish_coffee_preparation: {e}")
        await callback.answer("❌ Произошла ошибка при приготовлении кофе")

# ==================== НОВОЕ: КОРМЛЕНИЕ ====================
@dp.message(Command("feed"))
@dp.message(F.text == "🍪 Покормить")
async def cmd_feed(message: types.Message, state: FSMContext):
    """Отдельное кормление дракона"""
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_feed, spam_message = rate_limiter.check_spam(user_id, "feed")
        if not can_feed and spam_message:
            await message.answer(
                f"<b>🍪 {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующим кормлением</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем максимум сытости
        appetite_stat = dragon.stats.get("аппетит", 0)
        if appetite_stat >= 95:
            max_message = check_stat_max(appetite_stat, "аппетит", dragon.character.get("основная_черта", ""))
            if max_message:
                await message.answer(
                    f"<b>{max_message}</b>\n\n"
                    f"<i>💡 Может, сделаем что-то другое?</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        inventory = db.get_inventory(user_id)
        
        # Проверяем наличие сладостей
        has_snacks = any(inventory.get(item, 0) > 0 for item in [
            "cookie", "chocolate", "marshmallow", "gingerbread", "marmalade", "cake", "donut"
        ])
        
        if not has_snacks:
            await message.answer(
                "<b>❌ Нет сладостей!</b>\n\n"
                "<b>🛍️ Купи в магазине:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Выбери категорию «Сладости и угощения»\n\n"
                "<i>💡 Сладости повышают сытость и настроение дракона!</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "treat_time",
            dragon.name
        )
        
        # Отправляем новое сообщение с выбором сладости
        await message.answer(
            f"<b>🍪 ПОКОРМИТЬ {escape_html(dragon.name)}</b>\n\n"
            f"{char_message}\n\n"
            
            f"✨ <i>Текущая сытость:</i> <code>{appetite_stat}%</code>\n\n"
            
            f"<b>💡 Выбери угощение:</b>\n"
            f"<i>Сладости повышают сытость и настроение дракона!</i>\n\n"
            
            f"<b>🎭 Характер:</b> <code>{character_trait}</code>\n"
            f"<i>Любимая сладость: {dragon.favorites.get('сладость', 'печенье')}</i>",
            parse_mode="HTML",
            reply_markup=get_feed_keyboard(inventory)
        )
        
        await state.set_state(GameStates.feed_action)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_feed: {e}")
        await message.answer("<b>❌ Произошла ошибка при кормлении.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.feed_action, F.data.startswith("feed_"))
async def process_feed_action(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора сладости для кормления"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("feed_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        # Маппинг callback-данных на названия в инвентаре
        snack_map = {
            "cookie_raisin": "cookie",
            "chocolate_bar": "chocolate",
            "vanilla_marshmallow": "marshmallow",
            "gingerbread": "gingerbread",
            "fruit_marmalade": "marmalade",
            "chocolate_cake": "cake",
            "donut": "donut"
        }
        
        snack_item = snack_map.get(action)
        if not snack_item:
            await callback.answer("❌ Неизвестная сладость")
            return
        
        # Используем сладость
        inventory = db.get_inventory(user_id)
        if inventory.get(snack_item, 0) <= 0:
            await callback.answer("❌ Нет этой сладости!")
            return
        
        db.update_inventory(user_id, snack_item, -1)
        
        # Применяем действие
        result = dragon.apply_action("кормление")
        
        # Бонусы за кормление
        appetite_bonus = 30  # Базовая сытость от кормления
        mood_bonus = 20     # Базовая радость от кормления
        
        # Проверяем, является ли сладость любимой
        snack_names = {
            "cookie_raisin": "печенье",
            "chocolate_bar": "шоколад",
            "vanilla_marshmallow": "зефир",
            "gingerbread": "пряник",
            "fruit_marmalade": "мармелад",
            "chocolate_cake": "пирожное",
            "donut": "пончик"
        }
        
        current_snack = snack_names.get(action, "")
        if current_snack == dragon.favorites.get("сладость", ""):
            appetite_bonus += 20  # Любимая сладость сильнее насыщает
            mood_bonus += 15      # И сильнее радует
        
        # Бонус для гурмана
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "гурман":
            appetite_bonus += 10
            mood_bonus += 10
        
        # Применяем бонусы
        dragon.stats["аппетит"] = min(100, dragon.stats.get("аппетит", 0) + appetite_bonus)
        dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + mood_bonus)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Покормил дракона ({action})")
        
        # Получаем развёрнутую сцену кормления
        scene = ActionDescriptions.get_feed_scene(dragon.name, action)
        
        response = (
            f"{scene}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 🍪 Сытость: +{appetite_bonus}%\n"
            f"• 😊 Настроение: +{mood_bonus}%\n"
        )
        
        # Дополнительные бонусы
        bonus_text = ""
        if current_snack == dragon.favorites.get("сладость", ""):
            bonus_text += f"• 💖 Любимая сладость: +20 к сытости, +15 к настроению\n"
        if character_trait == "гурман":
            bonus_text += f"• 🍰 Гурман ценит угощение: +10 к сытости, +10 к настроению\n"
        
        if bonus_text:
            response += f"\n<b>✨ БОНУСЫ:</b>\n{bonus_text}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Характерное сообщение
        if current_snack == dragon.favorites.get("сладость", ""):
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "favorite_food",
                dragon.name
            )
        else:
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "happy",
                dragon.name
            )
        
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"🍪 <i>Текущая сытость:</i> <code>{dragon.stats.get('аппетит', 0)}%</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        # Отправляем новое сообщение с развёрнутой сценой
        await callback.message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.answer("✅ Дракон накормлен!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_feed_action: {e}")
        await callback.answer("❌ Произошла ошибка при кормлении")

# ==================== СОН И ЧТЕНИЕ СКАЗОК ====================
@dp.message(Command("sleep"))
@dp.message(F.text == "😴 Сон")
async def cmd_sleep(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_sleep, spam_message = rate_limiter.check_spam(user_id, "sleep")
        if not can_sleep and spam_message:
            await message.answer(
                f"<b>😴 {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующим сном</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем максимум бодрости
        sleep_stat = dragon.stats.get("сон", 0)
        if sleep_stat >= 95:
            max_message = check_stat_max(sleep_stat, "сон", dragon.character.get("основная_черта", ""))
            if max_message:
                await message.answer(
                    f"<b>{max_message}</b>\n\n"
                    f"<i>💡 Может, сделаем что-то другое?</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "bedtime" if character_trait == "книгочей" else "nap_time",
            dragon.name
        )
        
        # Отправляем новое сообщение с выбором способа уложить спать
        await message.answer(
            f"<b>😴 УЛОЖИТЬ {escape_html(dragon.name)} СПАТЬ</b>\n\n"
            f"{char_message}\n\n"
            f"✨ <i>Бодрость:</i> <code>{sleep_stat}%</code>\n\n"
            f"<b>💡 Выбери способ уложить дракона:</b>\n"
            f"• 📖 <b>Почитать сказку</b> - убаюкать историей\n"
            f"• 💤 <b>Лечь рядом</b> - согреть своим теплом\n"
            f"• 😘 <b>Поцеловать в лобик</b> - нежный поцелуй\n"
            f"• 🎵 <b>Спеть колыбельную</b> - успокаивающая мелодия\n"
            f"• 🧸 <b>Дать игрушку</b> - для сладких снов\n"
            f"• 🌙 <b>Просто уложить</b> - стандартный способ\n\n"
            f"<i>💡 Книгочею особенно понравится чтение сказки!</i>",
            parse_mode="HTML",
            reply_markup=get_sleep_keyboard()
        )
        
        await state.set_state(GameStates.sleep_choice)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_sleep: {e}")
        await message.answer("<b>❌ Произошла ошибка при укладывании спать.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.sleep_choice, F.data.startswith("sleep_"))
async def process_sleep_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("sleep_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        character_trait = dragon.character.get("основная_черта", "")
        
        # Применяем действие в зависимости от выбора
        if action == "read":
            # Чтение сказки
            result = dragon.apply_action("сон")
            
            # Получаем случайную книгу
            favorite_genre = dragon.favorites.get("жанр_книг", "сказка")
            book = get_random_book(favorite_genre)
            
            if not book or 'title' not in book or 'content' not in book:
                logger.warning(f"Книга не найдена или имеет некорректный формат: {book}")
                book = {
                    "title": "Сказка о драконе", 
                    "content": "Жил-был маленький дракон, который любил кофе и объятия..."
                }
            else:
                # ЭКРАНИРОВАТЬ HTML
                book["title"] = escape_html(book["title"])
                book["content"] = escape_html(book["content"])
            
            # Бонус для книгочея
            if character_trait == "книгочей":
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 20)
                dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 15)
                bonus_text = "<b>📚 Книгочей обожает сказки! +20 к настроению, +15 к бодрости</b>\n"
            else:
                bonus_text = ""
            
            # Получаем развёрнутую сцену чтения книги
            scene = ActionDescriptions.get_sleep_scene(
                dragon.name,
                action,
                book["title"],
                book["content"]
            )
            
        elif action == "lay":
            # Лечь рядом
            result = dragon.apply_action("сон")
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 10)
            bonus_text = "<b>💤 Тепло хранителя: +10 к настроению</b>\n"
            scene = ActionDescriptions.get_sleep_scene(dragon.name, action)
            
        elif action == "kiss":
            # Поцеловать в лобик
            result = dragon.apply_action("сон")
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
            bonus_text = "<b>😘 Нежный поцелуй: +15 к настроению</b>\n"
            scene = ActionDescriptions.get_sleep_scene(dragon.name, action)
            
        elif action == "sing":
            # Спеть колыбельную
            result = dragon.apply_action("сон")
            dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 10)
            bonus_text = "<b>🎵 Колыбельная: +10 к бодрости</b>\n"
            scene = ActionDescriptions.get_sleep_scene(dragon.name, action)
            
        elif action == "toy":
            # Дать игрушку
            result = dragon.apply_action("сон")
            inventory = db.get_inventory(user_id)
            if inventory.get("plush_dragon", 0) > 0 or inventory.get("toy", 0) > 0:
                bonus_text = "<b>🧸 С игрушкой: +20 к бодрости</b>\n"
                dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 20)
                scene = ActionDescriptions.get_sleep_scene(dragon.name, action)
            else:
                bonus_text = ""
                scene = ActionDescriptions.get_sleep_scene(dragon.name, "simple")
                
        else:  # simple
            # Просто уложить
            result = dragon.apply_action("сон")
            bonus_text = ""
            scene = ActionDescriptions.get_sleep_scene(dragon.name, action)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уложил дракона спать ({action})")
        
        response = f"{scene}\n\n"
        response += f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
        response += f"• 💤 Бодрость: +{result['stat_changes'].get('сон', 0)}%\n"
        response += f"• ⚡ Энергия: +{result['stat_changes'].get('энергия', 0)}%\n"
        
        if bonus_text:
            response += f"\n{bonus_text}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Характерное сообщение
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "well_rested",
            dragon.name
        )
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💤 <i>Текущая бодрость:</i> <code>{dragon.stats.get('сон', 0)}%</code>\n"
            f"⚡ <i>Энергия:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
        )
        
        # Отправляем новое сообщение с развёрнутой сценой
        await callback.message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.answer("✅ Дракон спит сладко!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_sleep_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== УХОД ====================
@dp.message(Command("care"))
@dp.message(F.text == "✨ Уход")
async def cmd_care(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_care, spam_message = rate_limiter.check_spam(user_id, "care")
        if not can_care and spam_message:
            await message.answer(
                f"<b>✨ {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующей процедурой</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем максимум пушистости
        fluff_stat = dragon.stats.get("пушистость", 0)
        if fluff_stat >= 95:
            max_message = check_stat_max(fluff_stat, "пушистость", dragon.character.get("основная_черта", ""))
            if max_message:
                await message.answer(
                    f"<b>{max_message}</b>\n\n"
                    f"<i>💡 Может, сделаем что-то другое?</i>",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "care_time",
            dragon.name
        )
        
        inventory = db.get_inventory(user_id)
        
        care_text = (
            f"<b>✨ УХАЖИВАТЬ ЗА {escape_html(dragon.name)}</b>\n\n"
            f"{char_message}\n\n"
            f"✨ <i>Показатель пушистости:</i> <code>{fluff_stat}%</code>\n\n"
            f"<b>💡 Выбери процедуру:</b>\n"
            f"• ✨ <b>Расчесать лапки</b> - базовая процедура\n"
            f"• 🛁 <b>Протереть мордочку</b> - гигиена\n"
            f"• 💅 <b>Почистить когти</b> - уход за коготками\n"
            f"• 🦷 <b>Почистить зубы</b> - здоровье зубов\n"
        )
        
        # Добавляем дополнительные опции если есть предметы
        additional_options = ""
        if inventory.get("dragon_brush", 0) > 0:
            additional_options += "• 💆 <b>Расчесать шерстку</b> - с расчёской (лучший эффект)\n"
        if inventory.get("magic_shampoo", 0) > 0:
            additional_options += "• 🧴 <b>Искупать с шампунем</b> - полноценная ванна\n"
        if inventory.get("golden_scissors", 0) > 0:
            additional_options += "• ✂️ <b>Подстричь когти ножницами</b> - профессиональный уход\n"
        if inventory.get("plush_dragon", 0) > 0:
            additional_options += "• 🧸 <b>Играть с игрушкой</b> - развлечение и уход\n"
        
        if additional_options:
            care_text += additional_options
        
        care_text += (
            f"\n<b>📦 Доступные предметы:</b>\n"
            f"• 💆 Расчёска: {inventory.get('dragon_brush', 0)} шт.\n"
            f"• 🧴 Шампунь: {inventory.get('magic_shampoo', 0)} шт.\n"
            f"• ✂️ Ножницы: {inventory.get('golden_scissors', 0)} шт.\n"
            f"• 🧸 Игрушка: {inventory.get('plush_dragon', 0)} шт.\n\n"
            f"<i>💡 Чистюля особенно оценит качественный уход!</i>"
        )
        
        # Отправляем новое сообщение с выбором процедуры
        await message.answer(
            care_text,
            parse_mode="HTML",
            reply_markup=get_care_keyboard(inventory)
        )
        
        await state.set_state(GameStates.care_action)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_care: {e}")
        await message.answer("<b>❌ Произошла ошибка при уходе.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.care_action, F.data.startswith("care_"))
async def process_care_action(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("care_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        character_trait = dragon.character.get("основная_черта", "")
        
        # Применяем действие в зависимости от выбора
        if action == "brush_paws":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 10)
            bonus = 10
            scene = ActionDescriptions.get_care_scene(dragon.name, action)
            
        elif action == "wipe_face":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 8)
            bonus = 8
            scene = ActionDescriptions.get_care_scene(dragon.name, action)
            
        elif action == "clean_nails":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 12)
            bonus = 12
            scene = ActionDescriptions.get_care_scene(dragon.name, action)
            
        elif action == "clean_teeth":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 15)
            dragon.stats["аппетит"] = min(100, dragon.stats.get("аппетит", 0) + 5)
            bonus = 15
            scene = ActionDescriptions.get_care_scene(dragon.name, action)
            
        elif action == "brush_fur":
            inventory = db.get_inventory(user_id)
            has_brush = inventory.get("dragon_brush", 0) > 0
            if has_brush:
                # Используем расчёску
                db.update_inventory(user_id, "dragon_brush", -1)
                    
                result = dragon.apply_action("уход")
                dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 30)
                bonus = 30
                scene = ActionDescriptions.get_care_scene(dragon.name, action)
            else:
                await callback.answer("❌ Нет расчёски!")
                return
                
        elif action == "bath_shampoo":
            inventory = db.get_inventory(user_id)
            has_shampoo = inventory.get("magic_shampoo", 0) > 0
            if has_shampoo:
                # Используем шампунь
                db.update_inventory(user_id, "magic_shampoo", -1)
                    
                result = dragon.apply_action("уход")
                dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 40)
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
                bonus = 40
                scene = ActionDescriptions.get_care_scene(dragon.name, action)
            else:
                await callback.answer("❌ Нет шампуня!")
                return
                
        elif action == "trim_nails_scissors":
            inventory = db.get_inventory(user_id)
            has_scissors = inventory.get("golden_scissors", 0) > 0
            if has_scissors:
                # Используем ножницы
                db.update_inventory(user_id, "golden_scissors", -1)
                    
                result = dragon.apply_action("уход")
                dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 25)
                bonus = 25
                scene = ActionDescriptions.get_care_scene(dragon.name, action)
            else:
                await callback.answer("❌ Нет ножниц!")
                return
                
        elif action == "play_toy":
            inventory = db.get_inventory(user_id)
            has_toy = inventory.get("plush_dragon", 0) > 0
            if has_toy:
                # Используем игрушку
                db.update_inventory(user_id, "plush_dragon", -1)
                    
                result = dragon.apply_action("уход")
                dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 20)
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 25)
                dragon.stats["энергия"] = min(100, dragon.stats.get("энергия", 0) - 10)
                bonus = 20
                scene = ActionDescriptions.get_care_scene(dragon.name, action)
            else:
                await callback.answer("❌ Нет игрушки!")
                return
                
        else:
            await callback.answer("❌ Неизвестное действие")
            return
        
        # Бонус для чистюли
        character_bonus = ""
        if character_trait == "чистюля":
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 20)
            character_bonus = "<b>✨ Чистюля в восторге! +20 к настроению</b>\n"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Ухаживал за драконом ({action})")
        
        response = f"{scene}\n\n"
        response += f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
        response += f"• ✨ Пушистость: +{bonus}%\n"
        response += f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}%\n"
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Характерное сообщение
        if character_trait == "чистюля":
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "clean",
                dragon.name
            )
        else:
            char_message = CharacterPersonality.get_character_message(
                character_trait,
                "happy",
                dragon.name
            )
        
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Текущая пушистость:</i> <code>{dragon.stats.get('пушистость', 0)}%</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        # Отправляем новое сообщение с развёрнутой сценой
        await callback.message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await callback.answer("✅ Процедура завершена!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_care_action: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== ИГРЫ ====================
@dp.message(Command("games"))
@dp.message(F.text == "🎮 Игры")
async def cmd_games(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        # Проверяем спам
        can_game, spam_message = rate_limiter.check_spam(user_id, "game")
        if not can_game and spam_message:
            await message.answer(
                f"<b>🎮 {spam_message}</b>\n\n"
                f"<i>💡 Давай подождём немного перед следующей игрой</i>",
                parse_mode="HTML"
            )
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        energy_stat = dragon.stats.get("энергия", 0)
        if energy_stat < 20:
            await message.answer(
                "<b>⚡ Дракон слишком устал для игр!</b>\n\n"
                "<i>Ему нужен отдых или кофе. Попробуй:</i>\n"
                "• 😴 Уложить спать\n"
                "• ☕ Приготовить кофе\n"
                "• 🤗 Просто обнять\n\n"
                "<i>Игры требуют много энергии!</i>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "game_time",
            dragon.name
        )
        
        # Отправляем новое сообщение с выбором игры
        await message.answer(
            f"<b>🎮 ИГРАТЬ С {escape_html(dragon.name)}</b>\n\n"
            f"{char_message}\n\n"
            f"⚡ <i>Энергия дракона:</i> <code>{energy_stat}%</code>\n"
            f"🎭 <i>Характер:</b> <code>{character_trait}</code>\n\n"
            f"<b>💡 Доступные игры:</b>\n"
            f"• 🔢 <b>Угадай число</b> - дракон загадал число от 1 до 20\n\n"
            f"<i>💡 Игрик будет особенно рад поиграть!</i>",
            parse_mode="HTML",
            reply_markup=get_minigames_keyboard()
        )
        
        await state.set_state(GameStates.minigame_state)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_games: {e}")
        await message.answer("<b>❌ Произошла ошибка при запуске игр.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.minigame_state, F.data.startswith("game_"))
async def process_game_choice(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("game_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        if action == "guess":
            # Игра "Угадай число"
            game = minigame_manager.guess_number_game()
            
            await state.update_data(
                game_data=game,
                attempts=0,
                dragon_data=dragon.to_dict()
            )
            
            # Отправляем новое сообщение с началом игры
            await callback.message.answer(
                f"<b>🔢 ИГРА: УГАДАЙ ЧИСЛО</b>\n\n"
                f"{game['hints'][0]}\n\n"
                f"<b>🎯 У тебя {game['attempts']} попытки</b>\n"
                f"<b>💰 Награда за победу:</b>\n"
                f"• {game['reward']['gold']} золота\n"
                f"• +{game['reward']['mood']}% к настроению\n"
                f"• {game['reward']['energy']}% к энергии\n\n"
                f"<i>💡 Напиши число от 1 до 20:</i>",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.waiting_for_guess)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_game_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(GameStates.waiting_for_guess)
async def process_guess_number(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        guess_text = message.text.strip()
        
        data = await state.get_data()
        game_data = data.get("game_data")
        attempts = data.get("attempts", 0)
        dragon_data = data.get("dragon_data")
        
        if not game_data or not dragon_data:
            await message.answer("<b>❌ Ошибка в игре. Начни заново.</b>", parse_mode="HTML")
            await state.clear()
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем ввод
        if not guess_text.isdigit():
            await message.answer("<b>❌ Пожалуйста, введи число!</b>", parse_mode="HTML")
            return
        
        guess = int(guess_text)
        
        if guess < 1 or guess > 20:
            await message.answer("<b>❌ Число должно быть от 1 до 20!</b>", parse_mode="HTML")
            return
        
        attempts += 1
        secret = game_data["secret"]
        
        # Проверяем угадал ли
        if guess == secret:
            # Победа!
            reward = game_data["reward"]
            
            # Обновляем дракона из базы
            dragon_data = db.get_dragon(user_id)
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
            
            # Начисляем награду
            dragon.gold += reward["gold"]
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + reward["mood"])
            dragon.stats["энергия"] = max(0, dragon.stats.get("энергия", 0) + reward["energy"])
            
            # Бонус для игрика
            character_trait = dragon.character.get("основная_черта", "")
            if character_trait == "игрик":
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
                dragon.gold += 10
                character_bonus = "<b>🎮 Игрик обожает побеждать! +15 к настроению, +10 золота</b>\n"
            else:
                character_bonus = ""
            
            # Сохраняем изменения
            db.update_dragon(user_id, dragon.to_dict())
            db.record_action(user_id, "Выиграл в игре 'Угадай число'")
            
            # Проверяем повышение уровня
            level_up = dragon.check_level_up()
            
            response = (
                f"<b>🎉 ПОБЕДА! Ты угадал с {attempts} попытки!</b>\n\n"
                f"Дракон загадал число <code>{secret}</code>\n\n"
                f"<b>🏆 НАГРАДА:</b>\n"
                f"• +{reward['gold']} золота\n"
                f"• +{reward['mood']}% к настроению\n"
                f"• {reward['energy']}% к энергии\n"
            )
            
            if character_bonus:
                response += f"\n{character_bonus}"
            
            if level_up:
                response += f"\n\n<b>🎊 Уровень повышен! Теперь {dragon.name} {dragon.level}-го уровня!</b>"
            
            response += f"\n\n<i>💬 {CharacterPersonality.get_character_message(character_trait, 'win', dragon.name)}</i>"
            
            # Отправляем новое сообщение с результатом победы
            await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
            await state.clear()
            
        else:
            # Не угадал
            remaining_attempts = game_data["attempts"] - attempts
            
            if remaining_attempts <= 0:
                # Проиграл
                response = (
                    f"<b>😔 КОНЕЦ ИГРЫ</b>\n\n"
                    f"Ты использовал все попытки.\n"
                    f"Дракон загадал число <code>{secret}</code>\n\n"
                    f"<i>💬 {CharacterPersonality.get_character_message(dragon.character.get('основная_черта', ''), 'lose', dragon.name)}</i>"
                )
                
                # Отправляем новое сообщение с результатом проигрыша
                await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
                await state.clear()
                
            else:
                # Ещё есть попытки
                hint_index = min(attempts, len(game_data["hints"]) - 1)
                hint = game_data["hints"][hint_index]
                
                direction = "больше" if guess < secret else "меньше"
                
                response = (
                    f"<b>❌ Не угадал!</b>\n\n"
                    f"Число <code>{guess}</code> - {direction}, чем загаданное.\n\n"
                    f"<b>{hint}</b>\n\n"
                    f"<b>🎯 Осталось попыток:</b> <code>{remaining_attempts}</code>\n\n"
                    f"<i>💡 Попробуй ещё раз:</i>"
                )
                
                await state.update_data(attempts=attempts)
                # Отправляем новое сообщение с подсказкой
                await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка в process_guess_number: {e}")
        await message.answer("<b>❌ Произошла ошибка в игре.</b>", parse_mode="HTML")

# ==================== МАГАЗИН ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Отправляем новое сообщение с магазином
        await message.answer(
            f"<b>🛍️ МАГАЗИН КОФЕЙНОГО ДРАКОНА</b>\n\n"
            f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
            f"👇 <b>Выбери категорию товаров:</b>\n\n"
            f"• ☕ <b>Кофе и ингредиенты</b> - для приготовления напитков\n"
            f"• 🍪 <b>Сладости и угощения</b> - чтобы порадовать дракона\n"
            f"• ✨ <b>Предметы для ухода</b> - для красоты и здоровья\n\n"
            f"<i>💡 Каждый предмет имеет уникальные свойства!</i>",
            parse_mode="HTML",
            reply_markup=get_shop_main_keyboard()
        )
        
        await state.set_state(GameStates.shop_main)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_shop: {e}")
        await message.answer("<b>❌ Произошла ошибка при открытии магазина.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.shop_main, F.data.startswith("shop_"))
async def process_shop_main(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("shop_", "")
        
        if action == "close":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>🛍️ Магазин закрыт</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer("🛍️ Магазин закрыт")
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Обновляем данные дракона из базы
        dragon_data = db.get_dragon(user_id)
        if dragon_data:
            dragon = Dragon.from_dict(dragon_data)
        
        if action == "coffee":
            # Редактируем сообщение (для удобства навигации в магазине)
            await callback.message.edit_text(
                f"<b>☕ КОФЕ И ИНГРЕДИЕНТЫ</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
                f"<b>📋 Товары:</b>\n"
                f"• ☕ <b>Кофейные зёрна</b> (10💰) - основной ингредиент для кофе\n"
                f"• 🍫 <b>Шоколадные чипсы</b> (8💰) - добавка для мокко и латте\n"
                f"• 🍯 <b>Медовый сироп</b> (12💰) - натуральный подсластитель\n"
                f"• 🍦 <b>Ванильное мороженое</b> (15💰) - для рафа и холодных напитков\n"
                f"• 🍭 <b>Карамельный сироп</b> (10💰) - сладкая карамельная добавка\n"
                f"• 🌰 <b>Фундук молотый</b> (18💰) - для ароматных напитков\n\n"
                f"<i>💡 Кофеман особенно оценит качественные ингредиенты!</i>",
                parse_mode="HTML",
                reply_markup=get_coffee_shop_keyboard()
            )
            await state.set_state(GameStates.shop_coffee)
            
        elif action == "sweets":
            await callback.message.edit_text(
                f"<b>🍪 СЛАДОСТИ И УГОЩЕНИЯ</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
                f"<b>📋 Товары:</b>\n"
                f"• 🍪 <b>Печенье с изюмом</b> (5💰) - простое и вкусное\n"
                f"• 🍫 <b>Шоколадная плитка</b> (15💰) - любимое лакомство многих драконов\n"
                f"• ☁️ <b>Ванильный зефир</b> (7💰) - воздушный и нежный\n"
                f"• 🎄 <b>Имбирный пряник</b> (8💰) - с ароматными специями\n"
                f"• 🍬 <b>Фруктовый мармелад</b> (10💰) - яркий и вкусный\n"
                f"• 🎂 <b>Шоколадное пирожное</b> (20💰) - праздничное угощение\n"
                f"• 🍩 <b>Сладкий пончик</b> (12💰) - с сахарной пудрой\n\n"
                f"<i>💡 Гурман разбирается в качестве сладостей!</i>",
                parse_mode="HTML",
                reply_markup=get_sweets_shop_keyboard()
            )
            await state.set_state(GameStates.shop_sweets)
            
        elif action == "care":
            await callback.message.edit_text(
                f"<b>✨ ПРЕДМЕТЫ ДЛЯ УХОДА</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
                f"<b>📋 Товары:</b>\n"
                f"• 💆 <b>Драконья расчёска</b> (25💰) - для идеальной шёрстки\n"
                f"• 🧴 <b>Волшебный шампунь</b> (30💰) - делает шерсть блестящей\n"
                f"• ✂️ <b>Золотые ножницы</b> (35💰) - для аккуратных коготков\n"
                f"• 🧸 <b>Плюшевый дракончик</b> (40💰) - лучший друг для игр\n"
                f"• 🛁 <b>Ароматная соль</b> (20💰) - для расслабляющих ванн\n"
                f"• 💅 <b>Лак для когтей</b> (28💰) - для стильного вида\n\n"
                f"<i>💡 Чистюля обожает качественные средства для ухода!</i>",
                parse_mode="HTML",
                reply_markup=get_care_shop_keyboard()
            )
            await state.set_state(GameStates.shop_care)
        
        elif action == "back":
            await callback.message.edit_text(
                f"<b>🛍️ МАГАЗИН КОФЕЙНОГО ДРАКОНА</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
                f"👇 <b>Выбери категорию товаров:</b>",
                parse_mode="HTML",
                reply_markup=get_shop_main_keyboard()
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_shop_main: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy_item(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        item_id = callback.data.replace("buy_", "")
        
        prices = {
            "coffee_beans": 10,
            "chocolate_chips": 8,
            "honey_syrup": 12,
            "vanilla_icecream": 15,
            "caramel_syrup": 10,
            "hazelnut": 18,
            "cookie_raisin": 5,
            "chocolate_bar": 15,
            "vanilla_marshmallow": 7,
            "gingerbread": 8,
            "fruit_marmalade": 10,
            "chocolate_cake": 20,
            "donut": 12,
            "dragon_brush": 25,
            "magic_shampoo": 30,
            "golden_scissors": 35,
            "plush_dragon": 40,
            "aromatic_salt": 20,
            "nail_polish": 28
        }
        
        item_map = {
            "coffee_beans": "coffee_beans",
            "chocolate_chips": "chocolate_chips",
            "honey_syrup": "honey_syrup",
            "vanilla_icecream": "vanilla_icecream",
            "caramel_syrup": "caramel_syrup",
            "hazelnut": "hazelnut",
            "cookie_raisin": "cookie",
            "chocolate_bar": "chocolate",
            "vanilla_marshmallow": "marshmallow",
            "gingerbread": "gingerbread",
            "fruit_marmalade": "marmalade",
            "chocolate_cake": "cake",
            "donut": "donut",
            "dragon_brush": "dragon_brush",
            "magic_shampoo": "magic_shampoo",
            "golden_scissors": "golden_scissors",
            "plush_dragon": "plush_dragon",
            "aromatic_salt": "aromatic_salt",
            "nail_polish": "nail_polish"
        }
        
        price = prices.get(item_id)
        inventory_name = item_map.get(item_id)
        
        if not price or not inventory_name:
            await callback.answer("❌ Товар не найден")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("❌ У вас нет дракона")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        if dragon.gold < price:
            await callback.answer(f"❌ Недостаточно золота! Нужно {price}💰")
            return
        
        dragon.gold -= price
        
        db.update_inventory(user_id, inventory_name, 1)
        
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Купил {item_id} за {price} золота")
        
        await state.set_state(GameStates.shop_main)
        await state.update_data(dragon_data=dragon.to_dict())
        
        # Отправляем новое сообщение с подтверждением покупки
        await callback.message.answer(
            f"<b>✅ УСПЕШНАЯ ПОКУПКА!</b>\n\n"
            f"Вы купили <b>{item_id.replace('_', ' ').title()}</b> за <code>{price}</code>💰\n\n"
            f"💰 <b>Новый баланс:</b> <code>{dragon.gold}</code> золота\n\n"
            f"<i>💡 Теперь вы можете использовать этот предмет!</i>",
            parse_mode="HTML",
            reply_markup=get_shop_main_keyboard()
        )
        
        await callback.answer(f"✅ Куплено за {price}💰")
        
    except Exception as e:
        logger.error(f"Ошибка в process_buy_item: {e}")
        await callback.answer("❌ Произошла ошибка при покупке")

# ==================== ИНВЕНТАРЬ ====================
@dp.message(Command("inventory"))
@dp.message(F.text == "📦 Инвентарь")
async def cmd_inventory(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        total_items = sum(inventory.values())
        
        # Отправляем новое сообщение с инвентарём
        await message.answer(
            f"<b>📦 ИНВЕНТАРЬ {escape_html(dragon.name)}</b>\n\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n"
            f"📊 <b>Всего предметов:</b> <code>{total_items}</code>\n\n"
            f"👇 <b>Выбери категорию для просмотра:</b>\n\n"
            f"• 🍪 <b>Сладости</b> - угощения для дракона\n"
            f"• ✨ <b>Уход</b> - предметы для заботы\n"
            f"• ☕ <b>Ингредиенты</b> - для приготовления кофе\n"
            f"• 🧸 <b>Прочее</b> - разные полезные вещи\n\n"
            f"<i>💡 Предметы используются автоматически при соответствующих действиях!</i>",
            parse_mode="HTML",
            reply_markup=get_inventory_keyboard()
        )
        
        await state.set_state(GameStates.inventory_main)
        await state.update_data(dragon_data=dragon_data)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_inventory: {e}")
        await message.answer("<b>❌ Произошла ошибка при открытии инвентаря.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.inventory_main, F.data.startswith("inv_"))
async def process_inventory_category(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("inv_", "")
        
        if action == "back":
            await state.clear()
            # Отправляем новое сообщение вместо удаления
            await callback.message.answer(
                "<b>↩️ Возвращаемся в главное меню</b>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            await callback.answer("↩️ Возвращаемся...")
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        categories = {
            "snacks": {
                "cookie": "🍪 Печенье",
                "chocolate": "🍫 Шоколад",
                "marshmallow": "☁️ Зефир",
                "gingerbread": "🎄 Пряник",
                "marmalade": "🍬 Мармелад",
                "cake": "🎂 Пирожное",
                "donut": "🍩 Пончик"
            },
            "care": {
                "dragon_brush": "💆 Расчёска",
                "magic_shampoo": "🧴 Шампунь",
                "golden_scissors": "✂️ Ножницы",
                "plush_dragon": "🧸 Игрушка",
                "aromatic_salt": "🛁 Соль",
                "nail_polish": "💅 Лак"
            },
            "ingredients": {
                "coffee_beans": "☕ Кофейные зёрна",
                "chocolate_chips": "🍫 Шоколадные чипсы",
                "honey_syrup": "🍯 Медовый сироп",
                "vanilla_icecream": "🍦 Ванильное мороженое",
                "caramel_syrup": "🍭 Карамельный сироп",
                "hazelnut": "🌰 Фундук"
            },
            "other": {
                "toy": "🧸 Игрушка (старая)",
                "brush": "💆 Расчёска (старая)",
                "shampoo": "🧴 Шампунь (старый)",
                "scissors": "✂️ Ножницы (старые)"
            }
        }
        
        category_names = {
            "snacks": "🍪 СЛАДОСТИ",
            "care": "✨ ПРЕДМЕТЫ ДЛЯ УХОДА",
            "ingredients": "☕ ИНГРЕДИЕНТЫ",
            "other": "🧸 ПРОЧИЕ ПРЕДМЕТЫ"
        }
        
        category_desc = {
            "snacks": "Угощения для дракона. Используются при кормлении и как дополнение к кофе.",
            "care": "Средства для ухода за драконом. Улучшают пушистость и настроение.",
            "ingredients": "Ингредиенты для приготовления кофе. Качество влияет на удовольствие дракона.",
            "other": "Разные полезные предметы, которые могут пригодиться в уходе."
        }
        
        if action in categories:
            category_items = categories[action]
            
            items_text = ""
            total_count = 0
            
            for item_id, item_name in category_items.items():
                count = inventory.get(item_id, 0)
                if count > 0:
                    items_text += f"• {item_name}: <code>{int(count)}</code> шт.\n"
                    total_count += count
            
            if not items_text:
                items_text = "<i>😔 В этой категории пока нет предметов</i>\n"
            
            category_text = (
                f"<b>{category_names[action]}</b>\n\n"
                f"<i>{category_desc[action]}</i>\n\n"
                f"<b>📦 ПРЕДМЕТЫ:</b>\n"
                f"{items_text}\n"
                f"<b>📊 Всего в категории:</b> <code>{total_count}</code> предметов\n\n"
                f"<i>💡 Предметы расходуются автоматически при использовании</i>"
            )
            
            # Редактируем сообщение (для удобства навигации в инвентаре)
            await callback.message.edit_text(
                category_text,
                parse_mode="HTML",
                reply_markup=get_inventory_keyboard()
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_inventory_category: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== ОСНОВНОЙ ЦИКЛ ====================
async def periodic_tasks():
    """Периодические задачи"""
    retry_count = 0
    max_retries = 5
    
    while True:
        try:
            # Очищаем старые записи в rate limiter
            rate_limiter.clear_old_entries()
            
            # Простая проверка времени для утренних уведомлений
            now = datetime.now(timezone.utc)
            if 8 <= now.hour <= 9:
                try:
                    users = db.get_all_users()
                    for user_id in users:
                        try:
                            dragon_data = db.get_dragon(user_id)
                            if dragon_data:
                                dragon = Dragon.from_dict(dragon_data)
                                character_trait = dragon.character.get("основная_черта", "")
                                message = CharacterPersonality.get_character_message(
                                    character_trait,
                                    "morning",
                                    dragon.name
                                )
                                
                                notification = (
                                    f"<b>🌅 ДОБРОЕ УТРО!</b>\n\n"
                                    f"{message}\n\n"
                                    f"<i>💡 Не забудь покормить {dragon.name} и приготовить ему кофе! ☕</i>"
                                )
                                
                                await bot.send_message(user_id, notification, parse_mode="HTML")
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
                except Exception as e:
                    logger.error(f"Ошибка при получении пользователей: {e}")
            
            retry_count = 0
            await asyncio.sleep(300)
            
        except Exception as e:
            retry_count += 1
            logger.error(f"Ошибка в periodic_tasks (попытка {retry_count}): {e}")
            
            if retry_count >= max_retries:
                logger.error(f"Достигнуто максимальное количество попыток ({max_retries}). Перезапуск через 60 секунд.")
                retry_count = 0
                await asyncio.sleep(60)
            else:
                delay = min(60 * retry_count, 300)
                logger.info(f"Повторная попытка через {delay} секунд...")
                await asyncio.sleep(delay)

async def main():
    try:
        logger.info("Запуск бота Кофейный Дракон v7.0...")
        
        dp.error.register(error_handler)
        
        asyncio.create_task(periodic_tasks())
        
        await dp.start_polling(bot, 
                              allowed_updates=dp.resolve_used_update_types(),
                              skip_updates=True)
        
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}\n{traceback.format_exc()}")
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}\n{traceback.format_exc()}")