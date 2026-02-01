"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 5.1
Улучшенная версия с:
- Детальными описаниями действий
- Реалистичными играми
- Улучшенными уведомлениями
- Балансировкой механик
"""
import asyncio
import logging
import random
import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Optional, List, Tuple, Union
from enum import Enum

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

import config
from database import db
from dragon_model import Dragon
from books import get_random_book, get_all_genres  # Теперь используется!

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
    book_reading = State()  # Новое состояние для чтения книг

# ==================== КЛАССЫ И УТИЛИТЫ ====================
class TimeOfDay(Enum):
    """Время суток для уведомлений"""
    MORNING = (8, 9)  # 8-9 утра
    AFTERNOON = (12, 14)  # 12-14 дня
    EVENING = (19, 21)  # 7-9 вечера
    NIGHT = (22, 23)  # 10-11 вечера

class RateLimiter:
    """Ограничитель частоты действий с умными уведомлениями"""
    def __init__(self):
        self.user_actions: Dict[str, datetime] = {}
        self.user_notifications: Dict[int, Dict[str, datetime]] = {}
        self.user_feeding_schedule: Dict[int, List[datetime]] = {}
        self.user_last_interaction: Dict[int, datetime] = {}
    
    def can_perform_action(self, user_id: int, action: str, cooldown_seconds: int = 30) -> bool:
        """Проверяет, можно ли выполнить действие"""
        now = datetime.now()
        key = f"{user_id}_{action}"
        
        if key in self.user_actions:
            last_time = self.user_actions[key]
            if now - last_time < timedelta(seconds=cooldown_seconds):
                return False
        
        # Записываем только если действие разрешено
        self.user_actions[key] = now
        self.user_last_interaction[user_id] = now
        return True
    
    def record_feeding(self, user_id: int):
        """Записывает время кормления для анализа расписания"""
        now = datetime.now()
        if user_id not in self.user_feeding_schedule:
            self.user_feeding_schedule[user_id] = []
        
        # Храним только последние 30 кормлений
        self.user_feeding_schedule[user_id].append(now)
        if len(self.user_feeding_schedule[user_id]) > 30:
            self.user_feeding_schedule[user_id] = self.user_feeding_schedule[user_id][-30:]
    
    def should_send_morning_notification(self, user_id: int) -> bool:
        """Определяет, нужно ли отправлять утреннее уведомление"""
        if user_id not in self.user_feeding_schedule:
            return True  # Новый пользователь
        
        now = datetime.now()
        today = now.date()
        
        # Проверяем, есть ли записи
        if not self.user_feeding_schedule[user_id]:
            return True
        
        # Проверяем, кормили ли сегодня в утренние часы
        for feeding_time in self.user_feeding_schedule[user_id]:
            if feeding_time.date() == today and 8 <= feeding_time.hour <= 9:
                return False  # Уже покормили сегодня утром
        
        # Проверяем время последнего кормления
        if self.user_feeding_schedule[user_id]:
            last_feeding = max(self.user_feeding_schedule[user_id])
            if now - last_feeding > timedelta(hours=12):
                return True  # Долго не кормили
        
        return True  # По умолчанию отправляем
    
    def clear_old_entries(self):
        """Очищает старые записи"""
        now = datetime.now()
        month_ago = now - timedelta(days=30)
        
        # Очистка действий
        keys_to_delete = [k for k, v in self.user_actions.items() if v < month_ago]
        for k in keys_to_delete:
            del self.user_actions[k]
        
        # Очистка расписания кормления
        for user_id in list(self.user_feeding_schedule.keys()):
            self.user_feeding_schedule[user_id] = [
                t for t in self.user_feeding_schedule[user_id] 
                if t > month_ago
            ]
            if not self.user_feeding_schedule[user_id]:
                del self.user_feeding_schedule[user_id]

class MinigameManager:
    """Менеджер улучшенных мини-игр"""
    
    @staticmethod
    def guess_number_game() -> dict:
        """Классическая игра 'Угадай число' с подсказками"""
        secret = random.randint(1, 20)
        hints = [
            f"🐉 Дракон задумал число от 1 до 20 и хитренько улыбается...",
            f"📝 Подсказка: это число {'чётное' if secret % 2 == 0 else 'нечётное'}",
            f"🎯 Число находится в диапазоне {max(1, secret-3)}-{min(20, secret+3)}"
        ]
        return {
            "type": "guess",
            "secret": secret,
            "hints": hints,
            "attempts": 3,
            "reward": {"gold": 20, "mood": 30, "energy": -10}
        }
    
    @staticmethod
    def coffee_art_game() -> dict:
        """Игра 'Кофейный арт' с разными уровнями сложности"""
        patterns = ["❤️", "⭐", "🐉", "☕", "✨", "🌈", "🌙", "🌟", "⚡", "🎨"]
        difficulty = random.choice(["легкий", "средний", "сложный"])
        
        if difficulty == "легкий":
            pattern_length = 3
        elif difficulty == "средний":
            pattern_length = 4
        else:
            pattern_length = 5
        
        target_pattern = random.sample(patterns, pattern_length)
        
        return {
            "type": "coffee_art",
            "target": target_pattern,
            "patterns": patterns,
            "difficulty": difficulty,
            "description": f"🎨 Создай кофейный арт {difficulty} уровня! Повтори последовательность:",
            "reward": {"gold": 15 + pattern_length * 5, "mood": 20 + pattern_length * 3, "coffee_skill": 5, "energy": -15}
        }
    
    @staticmethod
    def coffee_quiz_game() -> dict:
        """Викторина о кофе"""
        questions = [
            {
                "question": "Как называется самый дорогой сорт кофе?",
                "options": ["Копи Лувак", "Арабика", "Робуста", "Эспрессо"],
                "answer": "Копи Лувак"
            },
            {
                "question": "В какой стране впервые начали пить кофе?",
                "options": ["Эфиопия", "Италия", "Бразилия", "Колумбия"],
                "answer": "Эфиопия"
            },
            {
                "question": "Какой кофе самый крепкий?",
                "options": ["Эспрессо", "Американо", "Ристретто", "Лунго"],
                "answer": "Ристретто"
            },
            {
                "question": "Что такое 'латте арт'?",
                "options": ["Рисунок на кофе", "Особый сорт кофе", "Кофейный напиток", "Кофейная машина"],
                "answer": "Рисунок на кофе"
            },
            {
                "question": "Какой ингредиент добавляют в капучино?",
                "options": ["Молоко", "Сливки", "Шоколад", "Корицу"],
                "answer": "Молоко"
            }
        ]
        
        question = random.choice(questions)
        
        return {
            "type": "quiz",
            "question": question["question"],
            "options": question["options"],
            "answer": question["answer"],
            "description": "🧠 Викторина о кофе! Дракон задаёт вопрос:",
            "reward": {"gold": 30, "mood": 25, "coffee_skill": 10, "energy": -15}
        }
    
    @staticmethod
    def coffee_tasting_game() -> dict:
        """Игра на определение вкуса кофе"""
        coffee_types = {
            "Арабика": ["Фруктовый", "Сладкий", "Нежный", "Кислинка"],
            "Робуста": ["Горький", "Землистый", "Крепкий", "Ореховый"],
            "Либерика": ["Дымный", "Пряный", "Древесный", "Цветочный"],
            "Эксцельса": ["Экзотический", "Тропический", "Ягодный", "Пряный"]
        }
        
        coffee = random.choice(list(coffee_types.keys()))
        real_flavors = coffee_types[coffee]
        fake_flavors = ["Соленый", "Металлический", "Мятный", "Сливочный", "Ванильный", "Карамельный"]
        
        # Смешиваем настоящие и ложные вкусы
        all_flavors = real_flavors + random.sample(fake_flavors, 2)
        random.shuffle(all_flavors)
        
        return {
            "type": "tasting",
            "coffee": coffee,
            "real_flavors": real_flavors,
            "all_flavors": all_flavors,
            "description": f"👅 Угадай вкусы кофе {coffee}! Выбери 4 правильных вкуса из списка:",
            "reward": {"gold": 40, "mood": 30, "coffee_skill": 15, "energy": -20}
        }

def validate_dragon_name(name: str) -> Tuple[bool, Optional[str]]:
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
                f"☕ Дракон отворачивается от чашки: 'Мой кофейный датчик показывает 100%!'",
                f"☕ {dragon_trait} покачивает головой: 'Ещё одна капля - и я взлечу к облакам!'",
                f"☕ Дракон похлопывает по своему круглому брюшку: 'До краёв наполнен ароматным кофе!'"
            ],
            "сон": [
                f"💤 Дракон уже сладко похрапывает, укрывшись облачным одеялом...",
                f"💤 {dragon_trait} спит так крепко, что даже звёзды боятся его потревожить",
                f"💤 Дракон путешествует по царству снов, не стоит его беспокоить"
            ],
            "настроение": [
                f"😊 Дракон сияет ярче тысячи солнц! Он не может быть счастливее!",
                f"😊 {dragon_trait} танцует от радости: 'Я самый счастливый дракон во вселенной!'",
                f"😊 Улыбка дракона освещает всю комнату волшебным светом!"
            ],
            "аппетит": [
                f"🍪 Дракон вежливо отодвигает угощение: 'Благодарю, но я совершенно сыт!'",
                f"🍪 {dragon_trait} показывает на свой довольный животик",
                f"🍪 'Нет-нет, спасибо!' - говорит дракон, бережно накрывая еду салфеткой"
            ],
            "энергия": [
                f"⚡ Дракон носится по комнате, оставляя за собой светящийся след!",
                f"⚡ {dragon_trait} излучает столько энергии, что лампочки мигают!",
                f"⚡ Дракон слишком энергичен, чтобы усидеть на месте - он буквально парит в воздухе!"
            ],
            "пушистость": [
                f"✨ Шёрстка дракона сияет и переливается всеми цветами радуги!",
                f"✨ {dragon_trait} уже идеально ухожен - ни одной спутанной шерстинки!",
                f"✨ Дракон блестит чистотой, как будто только что с картинки!"
            ]
        }
        
        if stat_name in messages:
            return random.choice(messages[stat_name])
    
    return None

def format_stat_line(stat_name: str, stat_value: int, length: int = 12) -> str:
    """Форматирует строку статистики с выравниванием"""
    stat_names = {
        "кофе": "☕ Кофе",
        "сон": "💤 Сон", 
        "настроение": "😊 Настроение",
        "аппетит": "🍪 Аппетит",
        "энергия": "⚡ Энергия",
        "пушистость": "✨ Пушистость"
    }
    
    name = stat_names.get(stat_name, stat_name)
    # Добавляем пробелы для выравнивания
    padded_name = name.ljust(length)
    bar = create_progress_bar(stat_value)
    
    return f"{padded_name}: <code>{bar}</code> <code>{stat_value}%</code>"

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Статус"), KeyboardButton(text="☕ Кофе")],
            [KeyboardButton(text="😴 Сон"), KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🤗 Обнять"), KeyboardButton(text="✨ Уход")],
            [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="📦 Инвентарь")],
            [KeyboardButton(text="🔕 Уведомления"), KeyboardButton(text="📖 Помощь")]
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

def get_minigames_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура мини-игр"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess"),
                InlineKeyboardButton(text="🎨 Кофейный арт", callback_data="game_coffee_art")
            ],
            [
                InlineKeyboardButton(text="🧠 Кофейная викторина", callback_data="game_quiz"),
                InlineKeyboardButton(text="👅 Дегустация кофе", callback_data="game_tasting")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="game_back")
            ]
        ]
    )
    return keyboard

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
    
    # Основной уход
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

def get_notifications_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек уведомлений"""
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

# ==================== ДЕТАЛЬНЫЕ ОПИСАНИЯ ДЕЙСТВИЙ ====================
class ActionDescriptions:
    """Класс с детальными описаниями действий"""
    
    @staticmethod
    def get_hug_scenes(dragon_name: str, dragon_trait: str) -> List[str]:
        """Сцены для обнимашек"""
        return [
            f"Вы застали {dragon_name} сидящим на высоком стуле и пытающимся дотянуться до чашки с кофе на верхней полке. "
            f"Он машет маленькими лапками, но всё тщетно. Вы подходите, мягко обнимаете его и поднимаете на ручки. "
            f"{dragon_name} радостно хватает чашку и мурлычет от счастья, прижимаясь к вам! 🐾☕",
            
            f"{dragon_name} уютно устроился на диване и смотрит телевизор, где показывают документальный фильм о драконах. "
            f"Вы садитесь рядом и нежно обнимаете его. Дракон поворачивает голову, его глазки светятся от радости, "
            f"и он забирается к вам на колени, продолжая смотреть фильм вместе с вами. 📺🐉",
            
            f"Вы находите {dragon_name} в углу комнаты, где он играет с мячиком. Он так увлечён, что не замечает вас. "
            f"Вы тихо подходите сзади и обнимаете его. Дракон вздрагивает от неожиданности, но, поняв, что это вы, "
            f"радостно виляет хвостом и обнимает вас в ответ своими мягкими лапками. 🎾✨",
            
            f"{dragon_name} сидит у окна и грустно смотрит на дождь за стеклом. Вы подходите и обнимаете его сзади, "
            f"прижимая к себе. Дракон оборачивается, и в его глазах появляется искорка счастья. "
            f"Он прижимается к вам, и вместе вы смотрите на падающие капли. 🌧️🤗",
            
            f"Вы застали {dragon_name} за попыткой сделать утреннюю зарядку. Он неуклюже пытается приседать, "
            f"но постоянно теряет равновесие. Вы смеётесь и обнимаете его. "
            f"Дракон смущённо хрюкает, но затем начинает смеяться вместе с вами! 💪😄"
        ]
    
    @staticmethod
    def get_sleep_kiss_scenes(dragon_name: str, dragon_trait: str) -> List[str]:
        """Сцены для поцелуя в лобик перед сном"""
        return [
            f"Вы подходите к кроватке, где {dragon_name} уже уютно устроился, укрывшись мягким облачным одеялом. "
            f"Его глазки медленно закрываются, но, услышав ваши шаги, он приоткрывает один глаз. "
            f"Вы наклоняетесь и нежно целуете его в лобик. Дракон тихо мурлычет и засыпает с улыбкой. 🌙😘",
            
            f"{dragon_name} лежит на боку, обняв свою любимую игрушку. Он уже почти спит, но, почувствовав ваше присутствие, "
            f"приоткрывает глаза. Вы садитесь на край кровати, гладите его по голове и целуете в лобик. "
            f"Дракон счастливо вздыхает и крепче прижимает игрушку. 🧸💤",
            
            f"Вы находите {dragon_name} сидящим на кровати и смотрящим на звёзды в окне. 'Не могу уснуть,' - шепчет он вам. "
            f"Вы садитесь рядом, обнимаете его и целуете в лобик. 'Спокойной ночи, малыш,' - говорите вы. "
            f"Дракон улыбается, закрывает глаза и почти мгновенно засыпает. ⭐😴",
            
            f"{dragon_name} уже спит, но его сон беспокойный - он ворочается и тихо постанывает. "
            f"Вы осторожно подходите, поправляете одеяло и нежно целуете его в лобик. "
            f"Дракон успокаивается, его дыхание становится ровным, и он погружается в сладкий сон. 😊💫",
            
            f"Вы застаёте {dragon_name} за чтением книги при свете ночника. 'Ещё одну страничку,' - просит он. "
            f"Вы забираете книгу, целуете его в лобик и говорите: 'Завтра дочитаем.' "
            f"Дракон смиряется, укладывается и засыпает, мечтая о продолжении истории. 📚🌙"
        ]
    
    @staticmethod
    def get_care_brush_fur_scenes(dragon_name: str, dragon_trait: str) -> List[str]:
        """Сцены для расчёсывания шерстки"""
        return [
            f"Вы берёте красивую расчёску и подзываете {dragon_name}. Он радостно подбегает и садится перед вами. "
            f"Вы начинаете аккуратно расчёсывать его шерстку, и дракон мурлычет от удовольствия. "
            f"С каждым движением расчёски его шёрстка становится всё более блестящей и пушистой! ✨💆",
            
            f"{dragon_name} лежит на специальном столике для ухода, счастливо развалившись. "
            f"Вы берёте расчёску и начинаете работать над его шерсткой. Дракон закрывает глаза от наслаждения, "
            f"а иногда даже подставляет особенно любимые места для расчёсывания. После процедуры он сияет как новенький! 🛁🐉",
            
            f"Сегодня {dragon_name} особенно пушистый - видимо, он хорошенько выспался. "
            f"Вы усаживаете его перед собой и начинаете расчёсывать. Шерсть летит во все стороны, создавая вокруг вас облачко пушистости. "
            f"В конце вы даже делаете дракону небольшую стильную причёску! 💇✨",
            
            f"{dragon_name} сначала недоверчиво смотрит на расчёску, но вы показываете ему, как это приятно, "
            f"расчёсывая маленький участок. Дракон понимает и радостно подставляет спинку. "
            f"Вскоре он уже мурлычет и подставляет то один бок, то другой! 😊🦔"
        ]
    
    @staticmethod
    def get_book_reading_scene(dragon_name: str, dragon_trait: str, book_title: str, book_content: str) -> str:
        """Сцена чтения книги"""
        scenes = [
            f"Вы усаживаетесь в удобное кресло, а {dragon_name} укладывается у вас на коленях, уютно устроившись. "
            f"Вы открываете книгу '{book_title}' и начинаете читать:\n\n"
            f"<i>{book_content[:300]}...</i>\n\n"
            f"{dragon_name} внимательно слушает, его глазки медленно закрываются. К концу первой страницы он уже тихо посапывает. 📖😴",
            
            f"{dragon_name} приносит вам книгу '{book_title}' и с надеждой смотрит на вас. "
            f"Вы садитесь на диван, дракон укладывается рядом, положив голову вам на колени. "
            f"Вы начинаете читать:\n\n"
            f"<i>{book_content[:300]}...</i>\n\n"
            f"Голос ваш тихий и убаюкивающий. Через несколько минут {dragon_name} уже сладко спит. 🛋️💤",
            
            f"Вы готовитесь ко сну и замечаете, что {dragon_name} уже ждёт вас в кровати с книгой '{book_title}' в лапках. "
            f"Вы ложитесь рядом и начинаете читать:\n\n"
            f"<i>{book_content[:300]}...</i>\n\n"
            f"Дракон прижимается к вам, его дыхание становится ровным, и вскоре он засыпает под звук вашего голоса. 🛏️🌟"
        ]
        return random.choice(scenes)

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
            
            f"<b>📋 ВОЗМОЖНОСТИ 5.1:</b>\n"
            f"• 🎮 <b>4 разнообразные мини-игры</b> с уникальными механиками\n"
            f"• 📖 <b>Чтение настоящих книг</b> перед сном\n"
            f"• 😴 <b>Детальные сцены сна</b> с разными вариантами\n"
            f"• 🤗 <b>Живые обнимашки</b> в разных ситуациях\n"
            f"• 🔔 <b>Умные уведомления</b> с заботой о вас\n"
            f"• ⚡ <b>Динамические показатели</b>, меняющиеся со временем\n\n"
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
        "<b>📚 КОМАНДЫ И ВОЗМОЖНОСТИ (v5.1)</b>\n\n"
        
        "<b>🐉 ОСНОВНОЕ</b>\n"
        "<code>/start</code> - начать игру\n"
        "<code>/help</code> - эта справка\n"
        "<code>/create</code> - создать дракона\n"
        "<code>/status</code> - статус дракона\n\n"
        
        "<b>😴 СОН И ОТДЫХ</b>\n"
        "<code>/sleep</code> - уложить дракона спать с разными сценами\n"
        "<code>/dream</code> - присниться дракону\n\n"
        
        "<b>❤ УХОД И ЗАБОТА</b>\n"
        "<code>/coffee</code> - приготовить кофе с артом\n"
        "<code>/feed</code> - покормить сладостями\n"
        "<code>/hug</code> - обнять дракона в разных ситуациях\n"
        "<code>/care</code> - ухаживать за драконом\n\n"
        
        "<b>🎮 РАЗВЛЕЧЕНИЯ</b>\n"
        "<code>/games</code> - поиграть в 4 разные игры\n"
        "<code>/play</code> - быстрая игра\n\n"
        
        "<b>💰 ЭКОНОМИКА</b>\n"
        "<code>/shop</code> - магазин товаров\n"
        "<code>/inventory</code> - инвентарь\n"
        "<code>/gold</code> - проверить золото\n\n"
        
        "<b>🔕 НАСТРОЙКИ</b>\n"
        "<code>/notifications</code> - управление уведомлениями\n\n"
        
        "━━━━━━━━━━━━━━━━━━━\n"
        "<i>💡 Используй кнопки внизу для быстрого доступа</i>"
    )
    
    keyboard = get_main_keyboard() if db.dragon_exists(message.from_user.id) else get_short_main_keyboard()
    await message.answer(help_text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(Command("create"))
@dp.message(F.text == "🐉 Создать дракона")
async def cmd_create(message: types.Message, state: FSMContext):
    """Создание дракона"""
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
    """Обработка ввода имени дракона"""
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
        
        # Создаем дракона
        dragon = Dragon(name=dragon_name)
        dragon_data = dragon.to_dict()
        
        success = db.create_dragon(user_id, dragon_data)
        
        if not success:
            await message.answer("<b>❌ Не удалось создать дракона. Попробуй еще раз.</b>", parse_mode="HTML")
            await state.clear()
            return
        
        # Начальный инвентарь
        initial_inventory = {
            "кофейные_зерна": 10,
            "печенье": 5,
            "шоколад": 2,
            "вода": 3,
            "зефир": 1,
            "пряник": 1
        }
        
        for item, count in initial_inventory.items():
            db.update_inventory(user_id, item, count)
        
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
        
        await message.answer(
            f"<b>🎊 ВОЛШЕБСТВО СВЕРШИЛОСЬ! 🎊</b>\n\n"
            f"✨ Из яйца появился <b>{escape_html(dragon_name)}</b> - твой кофейный дракон!\n\n"
            f"<b>🎭 Характер:</b> {character}\n"
            f"{character_descriptions.get(character, '')}\n\n"
            
            f"<b>❤ ЛЮБИМОЕ:</b>\n"
            f"• ☕ Кофе: <code>{dragon.favorites['кофе']}</code>\n"
            f"• 🍬 Сладость: <code>{dragon.favorites['сладость']}</code>\n"
            f"• 📚 Книги: <code>{dragon.favorites['жанр_книг']}</code>\n\n"
            
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
        await state.clear()
        await message.answer("<b>❌ Произошла ошибка при создании дракона.</b>", parse_mode="HTML")

# ==================== СТАТУС ДРАКОНА (УЛУЧШЕННЫЙ) ====================
@dp.message(Command("status"))
@dp.message(F.text == "🐉 Статус")
async def cmd_status(message: types.Message):
    """Показать статус дракона с выровненными полосками"""
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
        dragon.update_over_time()  # Теперь показатели снижаются со временем!
        db.update_dragon(user_id, dragon.to_dict())
        
        status_text = (
            f"<b>🐉 {escape_html(dragon.name)} [Уровень {dragon.level}]</b>\n"
            f"⭐ <b>Опыт:</b> <code>{dragon.experience}/100</code>\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n\n"
            
            f"🎭 <b>Характер:</b> <code>{dragon.character.get('основная_черта', 'неженка')}</code>\n\n"
            
            f"<b>📊 ПОКАЗАТЕЛИ:</b>\n"
        )
        
        # Добавляем выровненные строки статистики
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
        
        # Проверяем критические состояния
        warnings = []
        if dragon.stats.get("кофе", 70) < 30:
            warnings.append("☕ Нужно срочно попить кофе!")
        if dragon.stats.get("сон", 30) < 30:
            warnings.append("💤 Дракон с трудом держит глазки открытыми...")
        if dragon.stats.get("аппетит", 60) > 80:
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
        
        # Время по часовому поясу пользователя
        user_time = datetime.now()
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 <i>Обновлено:</i> <code>{user_time.strftime('%H:%M:%S')}</code>\n"
            f"📅 <i>Дата:</i> <code>{user_time.strftime('%d.%m.%Y')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

# ==================== УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ ====================
@dp.message(Command("notifications"))
@dp.message(F.text == "🔕 Уведомления")
async def cmd_notifications(message: types.Message):
    """Управление уведомлениями"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        # Получаем текущие настройки
        user_settings = db.get_user_settings(user_id)
        notifications_enabled = user_settings.get("notifications_enabled", True)
        
        status_text = "🔔 <b>ВКЛЮЧЕНЫ</b>" if notifications_enabled else "🔕 <b>ВЫКЛЮЧЕНЫ</b>"
        
        await message.answer(
            f"<b>🔔 УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ</b>\n\n"
            f"<i>Дракон может присылать вам:</i>\n"
            f"• 🌅 Утренние напоминания о кормлении (8-9 утра)\n"
            f"• 🌙 Вечерние напоминания о сне\n"
            f"• ❤️ Случайные сообщения о том, что он скучает\n"
            f"• 🍪 Напоминания, если вы давно не кормили\n\n"
            
            f"<b>Текущий статус:</b> {status_text}\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Выбери действие:</i>",
            parse_mode="HTML",
            reply_markup=get_notifications_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_notifications: {e}")
        await message.answer("<b>❌ Произошла ошибка.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("notif_"))
async def process_notifications(callback: types.CallbackQuery):
    """Обработка настроек уведомлений"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("notif_", "")
        
        if action == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        if action == "on":
            db.update_user_setting(user_id, "notifications_enabled", True)
            response = (
                f"<b>🔔 УВЕДОМЛЕНИЯ ВКЛЮЧЕНЫ</b>\n\n"
                f"✨ {dragon.name} радостно машет хвостиком!\n"
                f"Теперь он сможет напоминать тебе о себе в нужное время.\n\n"
                f"<i>Ожидай утренних приветствий и вечерних напоминаний! 🐾</i>"
            )
            
        elif action == "off":
            db.update_user_setting(user_id, "notifications_enabled", False)
            response = (
                f"<b>🔕 УВЕДОМЛЕНИЯ ВЫКЛЮЧЕНЫ</b>\n\n"
                f"😔 {dragon.name} немного грустно опускает голову...\n"
                f"Но он понимает, что иногда нужно побыть в тишине.\n\n"
                f"<i>Ты всегда можешь включить их снова, если заскучаешь! 💕</i>"
            )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer("✅ Настройки сохранены")
        
    except Exception as e:
        logger.error(f"Ошибка в process_notifications: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== СОН С ЧТЕНИЕМ КНИГ ====================
@dp.message(Command("sleep"))
@dp.message(F.text == "😴 Сон")
async def cmd_sleep(message: types.Message):
    """Уложить дракона спать с детальными сценами"""
    try:
        user_id = message.from_user.id
        
        if not rate_limiter.can_perform_action(user_id, "sleep", 30):
            await message.answer("<b>⏳ Дракон только что спал. Подожди немного 😴</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        sleep_stat = dragon.stats.get("сон", 0)
        full_message = check_stat_full(sleep_stat, "сон", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        # Для книгочея - особая логика
        character_trait = dragon.character.get("основная_черта", "")
        if character_trait == "книгочей":
            if random.random() < 0.4:  # 40% шанс для книгочея
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
            f"💤 <i>Текущая сонливость:</i> <code>{sleep_stat}%</code>\n\n"
            
            f"<b>💡 Как уложить дракона?</b>\n"
            f"• 📖 <b>Почитать сказку</b> - настоящую книгу из библиотеки\n"
            f"• 💤 <b>Лечь рядом</b> - разделить тепло и уют\n"
            f"• 😘 <b>Поцеловать в лобик</b> - нежный поцелуй на ночь\n"
            f"• 🎵 <b>Спеть колыбельную</b> - тихая песенка\n"
            f"• 🧸 <b>Дать игрушку</b> - для крепкого сна\n"
            f"• 🌙 <b>Просто уложить</b> - стандартный вариант\n\n"
            
            f"<i>Каждый способ даёт разное восстановление сна (60-90%)</i>",
            parse_mode="HTML",
            reply_markup=get_sleep_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_sleep: {e}")
        await message.answer("<b>❌ Произошла ошибка при укладывании спать.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("sleep_"))
async def process_sleep(callback: types.CallbackQuery, state: FSMContext):
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
        
        if sleep_action == "read":
            # Чтение книги - получаем случайную книгу
            book = get_random_book()
            if not book:
                await callback.answer("❌ Книги временно недоступны")
                return
            
            await state.update_data(
                sleep_action=sleep_action,
                book_title=book["title"],
                book_content=book["content"]
            )
            await state.set_state(GameStates.book_reading)
            
            await callback.message.edit_text(
                f"<b>📖 ВЫБРАНА КНИГА: {book['title']}</b>\n\n"
                f"✨ <i>Жанр:</i> {book.get('genre', 'Сказка')}\n"
                f"📚 <i>Автор:</i> {book.get('author', 'Неизвестен')}\n\n"
                f"<i>Отправь любое сообщение, чтобы начать чтение...</i>",
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Для других действий - сразу обработка
        await _process_sleep_action(callback, dragon, sleep_action)
        
    except Exception as e:
        logger.error(f"Ошибка в process_sleep: {e}")
        await callback.answer("❌ Произошла ошибка")

async def _process_sleep_action(callback: types.CallbackQuery, dragon: Dragon, sleep_action: str):
    """Обработка действий сна"""
    try:
        user_id = callback.from_user.id
        dragon_name = dragon.name
        dragon_trait = dragon.character.get("основная_черта", "")
        
        # Применяем действие с новыми модификаторами (60-90%)
        result = dragon.apply_action("сон")
        
        # Новые модификаторы сна (60-90% восстановления)
        sleep_modifiers = {
            "read": {"сон": random.randint(70, 90), "настроение": 20, "литературный_вкус": 10},
            "lay": {"сон": random.randint(75, 90), "настроение": 25},
            "kiss": {"сон": random.randint(65, 85), "настроение": 30},
            "sing": {"сон": random.randint(60, 80), "настроение": 15},
            "toy": {"сон": random.randint(70, 85), "настроение": 20},
            "simple": {"сон": random.randint(60, 75), "настроение": 10}
        }
        
        modifier = sleep_modifiers.get(sleep_action, sleep_modifiers["simple"])
        
        # Применяем модификаторы
        dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + modifier["сон"])
        dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + modifier.get("настроение", 0))
        
        if sleep_action == "read" and "литературный_вкус" in modifier:
            dragon.skills["литературный_вкус"] = min(100, dragon.skills.get("литературный_вкус", 0) + modifier["литературный_вкус"])
        
        # Бонус для сонь
        if dragon_trait == "соня":
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 15)
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            character_bonus = "\n<b>😴 Соня обожает спать! +15 к сну, +20 к настроению</b>"
        else:
            character_bonus = ""
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уложил спать ({sleep_action})")
        
        # Получаем детальное описание действия
        if sleep_action == "kiss":
            scenes = ActionDescriptions.get_sleep_kiss_scenes(dragon_name, dragon_trait)
            description = random.choice(scenes)
        elif sleep_action == "lay":
            scenes = [
                f"Вы ложитесь рядом с {dragon_name} на большую мягкую кровать. Дракон сразу прижимается к вам, "
                f"ища тепла и защиты. Вы обнимаете его, и вместе вы медленно погружаетесь в сон... 🛏️💤",
                
                f"{dragon_name} уже лежит в кровати, но место рядом свободно. Вы ложитесь, и дракон сразу "
                f"переворачивается на бок, прижимаясь спиной к вам. Вы кладёте руку на его бочок и засыпаете. 😴🐉",
                
                f"Вы забираетесь под одеяло рядом с {dragon_name}. Он сонно открывает один глаз, видит вас и "
                f"довольно мурлычет, забираясь к вам на грудь. Вскоре вы оба засыпаете под тиканье часов. ⏰❤️"
            ]
            description = random.choice(scenes)
        elif sleep_action == "sing":
            scenes = [
                f"Вы садитесь на край кровати рядом с {dragon_name} и начинаете тихо напевать старую колыбельную. "
                f"Дракон закрывает глазки, его дыхание становится ровным. К концу песни он уже крепко спит. 🎵💫",
                
                f"{dragon_name} смотрит на вас большими глазами. Вы берёте его на руки, качаете и напеваете "
                f"нежную мелодию. Постепенно его глазки закрываются, и он засыпает у вас на руках. 👶🐲",
                
                f"Вы включаете тихую музыку и садитесь рядом с {dragon_name}. Напевая вместе с мелодией, "
                f"вы гладите дракона по спинке. Он зевает, потягивается и засыпает под ваше пение. 🎶✨"
            ]
            description = random.choice(scenes)
        elif sleep_action == "toy":
            scenes = [
                f"Вы даёте {dragon_name} его любимую плюшевую игрушку - маленького дракончика. "
                f"Он радостно обнимает её, устраивается поудобнее и почти мгновенно засыпает. 🧸😴",
                
                f"{dragon_name} с надеждой смотрит на полку с игрушками. Вы достаёте его любимую погремушку. "
                f"Дракон берёт её в лапки, тихонько трясёт и засыпает с улыбкой. 🎪💤",
                
                f"Вы находите под кроватью старую, но любимую игрушку {dragon_name}. Он счастливо хватает её, "
                f"прижимает к себе и засыпает, как будто встретил старого друга. 🐻❤️"
            ]
            description = random.choice(scenes)
        elif sleep_action == "simple":
            scenes = [
                f"Вы аккуратно укладываете {dragon_name} в его уютную лежанку и накрываете лёгким одеялом. "
                f"'Спокойной ночи,' - шепчете вы. Дракон зевает и закрывает глаза. 🌙✨",
                
                f"Вы поправляете подушку под головой {dragon_name} и накрываете его тёплым пледом. "
                f"'Сладких снов,' - говорите вы, выключая свет. Дракон мурлычет в ответ. 🛌💫",
                
                f"Вы проверяете, удобно ли лежит {dragon_name}, поправляете одеяло и целуете его в макушку. "
                f"'До утра,' - говорите вы, выходя из комнаты. 🚪😴"
            ]
            description = random.choice(scenes)
        else:
            description = f"Вы укладываете {dragon_name} спать."
        
        response = (
            f"{description}\n\n"
            
            f"<b>📊 ПОСЛЕ СНА:</b>\n"
            f"• 😴 Сон: +{modifier['сон']}% (теперь {dragon.stats.get('сон', 0)}%)\n"
            f"• 😊 Настроение: +{modifier.get('настроение', 0)}\n"
        )
        
        if sleep_action == "read":
            response += f"• 📚 Литературный вкус: +10\n"
        
        response += character_bonus
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в _process_sleep_action: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(GameStates.book_reading)
async def process_book_reading(message: types.Message, state: FSMContext):
    """Обработка чтения книги"""
    try:
        user_id = message.from_user.id
        
        data = await state.get_data()
        sleep_action = data.get("sleep_action")
        book_title = data.get("book_title")
        book_content = data.get("book_content")
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("❌ Дракон не найден")
            await state.clear()
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Создаем сцену чтения книги
        reading_scene = ActionDescriptions.get_book_reading_scene(
            dragon.name,
            dragon.character.get("основная_черта", ""),
            book_title,
            book_content
        )
        
        # Применяем эффекты сна (чтение дает 70-90% восстановления)
        sleep_restore = random.randint(70, 90)
        dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + sleep_restore)
        dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 20)
        dragon.skills["литературный_вкус"] = min(100, dragon.skills.get("литературный_вкус", 0) + 10)
        
        # Бонус для книгочея
        if dragon.character.get("основная_черта") == "книгочей":
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 10)
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            reading_scene += "\n\n<b>📚 Книгочей в восторге! +10 к сну, +15 к настроению</b>"
        
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Прочитал книгу: {book_title}")
        
        response = (
            f"{reading_scene}\n\n"
            
            f"<b>📊 ПОСЛЕ ЧТЕНИЯ:</b>\n"
            f"• 😴 Сон: +{sleep_restore}% (теперь {dragon.stats.get('сон', 0)}%)\n"
            f"• 😊 Настроение: +20\n"
            f"• 📚 Литературный вкус: +10\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Дракон сладко спит, улыбаясь во сне... 💤✨</i>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_mup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_book_reading: {e}")
        await state.clear()
        await message.answer("<b>❌ Произошла ошибка при чтении книги.</b>", parse_mode="HTML")

# ==================== ОБНИМАШКИ С ДЕТАЛЬНЫМИ СЦЕНАМИ ====================
@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона с детальными сценами"""
    try:
        user_id = message.from_user.id
        
        if not rate_limiter.can_perform_action(user_id, "hug", 5):
            await message.answer("<b>⏳ Не переусердствуй с объятиями! Подожди немного 🤗</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
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
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 25)
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 10)
            character_bonus = "<b>🥰 Неженка обожает обнимашки! +25 к настроению, +10 к сну</b>\n"
        else:
            character_bonus = ""
        
        # Получаем случайную сцену обнимашек
        scenes = ActionDescriptions.get_hug_scenes(dragon.name, character_trait)
        scene = random.choice(scenes)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, "Обнял дракона")
        
        response = (
            f"{scene}\n\n"
            
            f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
            f"• 😊 Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
            f"• 💤 Сон: +{result['stat_changes'].get('сон', 0)}\n"
        )
        
        if character_bonus:
            response += f"\n{character_bonus}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"❤ <i>Текущее настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_hug: {e}")
        await message.answer("<b>❌ Произошла ошибка при обнимашках.</b>", parse_mode="HTML")

# ==================== МИНИ-ИГРЫ (УЛУЧШЕННЫЕ) ====================
@dp.message(Command("games"))
@dp.message(F.text == "🎮 Игры")
async def cmd_games(message: types.Message):
    """Выбор улучшенных мини-игр"""
    try:
        user_id = message.from_user.id
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
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
            
            "<b>✨ Улучшенные игры:</b>\n"
            "• 🔢 <b>Угадай число</b> - классика с подсказками (1-20)\n"
            "• 🎨 <b>Кофейный арт</b> - запомни последовательность\n"
            "• 🧠 <b>Кофейная викторина</b> - проверь знания о кофе\n"
            "• 👅 <b>Дегустация кофе</b> - угадай вкусы разных сортов\n\n"
            
            f"⚡ <i>Энергия дракона:</i> <code>{dragon.stats.get('энергия', 0)}%</code>\n"
            f"🎭 <i>Характер:</i> <code>{dragon.character.get('основная_черта', '')}</code>\n\n"
            
            f"<i>Каждая игра тратит 15-25 энергии и даёт уникальные награды!</i>",
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
        
        if game_type == "back":
            await callback.message.edit_text(
                "<b>🎮 Возвращаемся...</b>",
                parse_mode="HTML"
            )
            await callback.answer("↩️ Возвращаемся")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        if not rate_limiter.can_perform_action(user_id, f"game_{game_type}", 60):
            await callback.answer("⏳ Слишком часто играешь в эту игру!")
            return
        
        # Тратим энергию
        energy_cost = random.randint(15, 25)
        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] - energy_cost)
        db.update_dragon(user_id, dragon.to_dict())
        
        # Запускаем выбранную игру
        if game_type == "guess":
            game = minigame_manager.guess_number_game()
            await state.update_data(current_game=game)
            await state.set_state(GameStates.minigame_state)
            
            await callback.message.edit_text(
                f"<b>🔢 ИГРА: УГАДАЙ ЧИСЛО</b>\n\n"
                f"🐉 Дракон загадал число от 1 до 20!\n"
                f"У тебя есть {game['attempts']} попытки.\n\n"
                f"{game['hints'][0]}\n\n"
                f"<b>Введи свой вариант:</b>",
                parse_mode="HTML"
            )
            
        elif game_type == "coffee_art":
            game = minigame_manager.coffee_art_game()
            await state.update_data(current_game=game)
            
            pattern_display = "   ".join(game["target"])
            await callback.message.edit_text(
                f"<b>🎨 ИГРА: КОФЕЙНЫЙ АРТ</b>\n\n"
                f"<i>{game['description']}</i>\n\n"
                f"<b>Уровень сложности:</b> {game['difficulty']}\n"
                f"<b>Запомни:</b> <code>{pattern_display}</code>\n\n"
                f"У тебя 7 секунд...",
                parse_mode="HTML"
            )
            
            await asyncio.sleep(7)
            
            await callback.message.edit_text(
                f"<b>🎨 ПОВТОРИ ПОСЛЕДОВАТЕЛЬНОСТЬ</b>\n\n"
                f"<i>Отправь {len(game['target'])} символа через пробел:</i>\n"
                f"<code>❤️ ⭐ 🐉</code>\n\n"
                f"<b>Доступные символы:</b>\n"
                f"{'   '.join(game['patterns'])}",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.minigame_state)
            
        elif game_type == "quiz":
            game = minigame_manager.coffee_quiz_game()
            await state.update_data(current_game=game)
            
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(game["options"])])
            
            await callback.message.edit_text(
                f"<b>🧠 ИГРА: КОФЕЙНАЯ ВИКТОРИНА</b>\n\n"
                f"{game['description']}\n\n"
                f"<b>❓ Вопрос:</b> {game['question']}\n\n"
                f"<b>📋 Варианты:</b>\n"
                f"{options_text}\n\n"
                f"<b>Введи номер правильного ответа:</b>",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.minigame_state)
            
        elif game_type == "tasting":
            game = minigame_manager.coffee_tasting_game()
            await state.update_data(current_game=game)
            
            flavors_text = "\n".join([f"{i+1}. {flavor}" for i, flavor in enumerate(game["all_flavors"])])
            
            await callback.message.edit_text(
                f"<b>👅 ИГРА: ДЕГУСТАЦИЯ КОФЕ</b>\n\n"
                f"{game['description']}\n\n"
                f"<b>☕ Сорт кофе:</b> {game['coffee']}\n\n"
                f"<b>📋 Возможные вкусы:</b>\n"
                f"{flavors_text}\n\n"
                f"<b>Введи номера 4 правильных вкусов через пробел (например: 1 2 3 4):</b>",
                parse_mode="HTML"
            )
            
            await state.set_state(GameStates.minigame_state)
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_game_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(GameStates.minigame_state)
async def process_minigame_answer(message: types.Message, state: FSMContext):
    """Обработка ответов в мини-играх"""
    try:
        user_id = message.from_user.id
        user_answer = message.text.strip().lower()
        
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
        response = ""
        
        # Обработка разных игр
        if game["type"] == "guess":
            try:
                guess = int(user_answer)
                if 1 <= guess <= 20:
                    if guess == game["secret"]:
                        # Победа
                        dragon.gold += game["reward"]["gold"]
                        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                        dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 3)
                        
                        response = (
                            f"<b>🎉 ПРАВИЛЬНО! Загаданное число: {game['secret']}</b>\n\n"
                            f"✨ Дракон радостно подпрыгивает и хлопает в ладоши!\n\n"
                            f"<b>🏆 НАГРАДА:</b>\n"
                            f"• 💰 Золото: +{game['reward']['gold']}\n"
                            f"• 😊 Настроение: +{game['reward']['mood']}\n"
                            f"• 🎮 Игровая эрудиция: +3\n"
                        )
                    else:
                        # Не угадал
                        dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
                        dragon.skills["игровая_эрудиция"] = min(100, dragon.skills.get("игровая_эрудиция", 0) + 1)
                        
                        response = (
                            f"<b>😔 НЕ УГАДАЛ!</b> Загаданное число: {game['secret']}\n\n"
                            f"✨ Дракон подбадривающе похлопывает тебя по плечу.\n\n"
                            f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                            f"• 😊 Настроение: -5\n"
                            f"• 🎮 Игровая эрудиция: +1\n"
                        )
                else:
                    response = "<b>❌ Число должно быть от 1 до 20!</b>"
            except ValueError:
                response = "<b>❌ Введи число!</b>"
        
        elif game["type"] == "coffee_art":
            user_pattern = user_answer.split()
            if user_pattern == game["target"]:
                dragon.gold += game["reward"]["gold"]
                dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                dragon.skills["кофейное_мастерство"] = min(100, 
                    dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"])
                dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                
                response = (
                    f"<b>🎉 ИДЕАЛЬНО! Прекрасный кофейный арт! 🎉</b>\n\n"
                    f"Дракон восхищённо смотрит на твоё творение!\n\n"
                    f"<b>🏆 НАГРАДА:</b>\n"
                    f"• 💰 Золото: +{game['reward']['gold']}\n"
                    f"• 😊 Настроение: +{game['reward']['mood']}\n"
                    f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill']}\n"
                )
            else:
                dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 10)
                dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + 1)
                
                correct_pattern = "   ".join(game["target"])
                response = (
                    f"<b>😔 УВЫ, НЕПРАВИЛЬНО</b>\n\n"
                    f"Правильная последовательность: <code>{correct_pattern}</code>\n\n"
                    f"Дракон смотрит на бесформенную пенку и вздыхает...\n\n"
                    f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                    f"• 😊 Настроение: -10\n"
                    f"• 🎨 Кофейное мастерство: +1\n"
                )
        
        elif game["type"] == "quiz":
            try:
                answer_num = int(user_answer)
                if 1 <= answer_num <= 4:
                    user_choice = game["options"][answer_num - 1]
                    if user_choice == game["answer"]:
                        dragon.gold += game["reward"]["gold"]
                        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                        dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"])
                        dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                        
                        response = (
                            f"<b>🎉 ВЕРНО! Правильный ответ: {game['answer']}</b>\n\n"
                            f"Дракон впечатлён твоими знаниями о кофе!\n\n"
                            f"<b>🏆 НАГРАДА:</b>\n"
                            f"• 💰 Золото: +{game['reward']['gold']}\n"
                            f"• 😊 Настроение: +{game['reward']['mood']}\n"
                            f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill']}\n"
                        )
                    else:
                        dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
                        dragon.skills["кофейное_мастерство"] = min(100, dragon.skills.get("кофейное_мастерство", 0) + 2)
                        
                        response = (
                            f"<b>😔 НЕВЕРНО!</b> Правильный ответ: {game['answer']}\n\n"
                            f"Дракон терпеливо объясняет тебе правильный ответ.\n\n"
                            f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                            f"• 😊 Настроение: -5\n"
                            f"• 🎨 Кофейное мастерство: +2 (новое знание!)\n"
                        )
                else:
                    response = "<b>❌ Введи число от 1 до 4!</b>"
            except ValueError:
                response = "<b>❌ Введи число!</b>"
        
        elif game["type"] == "tasting":
            try:
                selected_nums = [int(x) for x in user_answer.split()]
                if len(selected_nums) != 4:
                    response = "<b>❌ Нужно выбрать ровно 4 вкуса!</b>"
                else:
                    # Проверяем, что все номера в диапазоне
                    if any(num < 1 or num > len(game["all_flavors"]) for num in selected_nums):
                        response = f"<b>❌ Номера должны быть от 1 до {len(game['all_flavors'])}!</b>"
                    else:
                        selected_flavors = [game["all_flavors"][num-1] for num in selected_nums]
                        correct_count = sum(1 for flavor in selected_flavors if flavor in game["real_flavors"])
                        
                        if correct_count == 4:
                            dragon.gold += game["reward"]["gold"]
                            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"])
                            dragon.skills["кофейное_мастерство"] = min(100, 
                                dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"])
                            dragon.stats["энергия"] = max(0, dragon.stats["энергия"] + game["reward"]["energy"])
                            
                            response = (
                                f"<b>🎉 БРАВО! Все 4 вкуса угаданы правильно! 🎉</b>\n\n"
                                f"Дракон поражён твоим дегустаторским талантом!\n\n"
                                f"<b>🏆 НАГРАДА:</b>\n"
                                f"• 💰 Золото: +{game['reward']['gold']}\n"
                                f"• 😊 Настроение: +{game['reward']['mood']}\n"
                                f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill']}\n"
                            )
                        else:
                            dragon.gold += game["reward"]["gold"] // 2
                            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + game["reward"]["mood"] // 2)
                            dragon.skills["кофейное_мастерство"] = min(100, 
                                dragon.skills.get("кофейное_мастерство", 0) + game["reward"]["coffee_skill"] // 2)
                            
                            real_flavors_text = ", ".join(game["real_flavors"])
                            response = (
                                f"<b>📊 УГАДАНО {correct_count} из 4 вкусов</b>\n\n"
                                f"Правильные вкусы: {real_flavors_text}\n\n"
                                f"<b>📊 РЕЗУЛЬТАТ:</b>\n"
                                f"• 💰 Золото: +{game['reward']['gold'] // 2}\n"
                                f"• 😊 Настроение: +{game['reward']['mood'] // 2}\n"
                                f"• 🎨 Кофейное мастерство: +{game['reward']['coffee_skill'] // 2}\n"
                            )
            except ValueError:
                response = "<b>❌ Введи номера через пробел!</b>"
        
        # Бонус для игрика
        if dragon.character.get("основная_черта") == "игрик":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
            response += "\n\n<b>🎮 Игрик обожает игры! +15 к настроению</b>"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Мини-игра: {game['type']}")
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <i>Золото:</i> <code>{dragon.gold}</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>\n"
            f"⚡ <i>Энергия:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_minigame_answer: {e}")
        await state.clear()
        await message.answer("<b>❌ Произошла ошибка в игре.</b>", parse_mode="HTML")

# ==================== УХОД С ДЕТАЛЬНЫМИ ОПИСАНИЯМИ ====================
@dp.message(Command("care"))
@dp.message(F.text == "✨ Уход")
async def cmd_care(message: types.Message):
    """Уход за драконом с детальными описаниями"""
    try:
        user_id = message.from_user.id
        
        if not rate_limiter.can_perform_action(user_id, "care", 300):
            await message.answer("<b>✨ Дракон уже ухожен. Подожди немного</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
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
    """Обработка ухода за драконом с детальными описаниями"""
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
        dragon_name = dragon.name
        dragon_trait = dragon.character.get("основная_черта", "")
        
        # Проверяем наличие предметов
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
        if dragon_trait == "чистюля":
            dragon.stats["пушистость"] = min(100, dragon.stats["пушистость"] + 15)
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
            character_bonus = "\n<b>✨ Чистюля сияет от счастья! +15 к пушистости, +20 к настроению</b>"
        else:
            character_bonus = ""
        
        # Получаем описание действия
        description = ""
        if care_action == "brush_fur":
            scenes = ActionDescriptions.get_care_brush_fur_scenes(dragon_name, dragon_trait)
            description = random.choice(scenes)
        elif care_action == "brush_paws":
            scenes = [
                f"Вы усаживаете {dragon_name} перед собой и начинаете аккуратно расчёсывать его лапки. "
                f"Дракон поднимает каждую лапку по очереди, наслаждаясь процессом. "
                f"После расчёсывания его лапки становятся мягкими и пушистыми! 🐾✨",
                
                f"{dragon_name} с интересом наблюдает, как вы берёте специальную щёточку для лапок. "
                f"Вы начинаете расчёсывать, и дракон мурлычет от удовольствия. "
                f"Особенно он любит, когда вы расчёсываете между пальчиками! 💕👣"
            ]
            description = random.choice(scenes)
        elif care_action == "wipe_face":
            scenes = [
                f"Вы берёте мягкую влажную салфетку и аккуратно протираете мордочку {dragon_name}. "
                f"Он закрывает глазки и позволяет вам убрать все следы от кофе и сладостей. "
                f"После этого его мордочка сияет чистотой! 🧼😊",
                
                f"{dragon_name} трётся мордочкой о вашу руку, показывая, что хочет, чтобы ему протёрли лицо. "
                f"Вы берёте тёплую салфетку и нежно очищаете его щёчки, нос и подбородок. "
                f"Дракон благодарно мурлычет! 🐱💖"
            ]
            description = random.choice(scenes)
        elif care_action == "bath":
            scenes = [
                f"Вы наполняете ванну тёплой водой с ароматной пеной. {dragon_name} осторожно залезает в воду. "
                f"Вы намыливаете его специальным шампунем для драконов, и он с удовольствием пускает пузыри! "
                f"После купания он пахнет цветами и свежестью. 🛁🌺",
                
                f"Сегодня день купания! {dragon_name} сначала неохотно, но потом с радостью плещется в ванной. "
                f"Вы моете ему спинку, животик и даже хвостик. После ванны вы заворачиваете его в мягкое полотенце. "
                f"Дракон сияет чистотой! 🧖✨"
            ]
            description = random.choice(scenes)
        else:
            description = f"Вы ухаживаете за {dragon_name}."
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уход: {care_action}")
        
        response = (
            f"{description}\n\n"
            
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
            remaining = inventory.get(item_name, 0) - 1
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
                # Проверяем настройки уведомлений
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get("notifications_enabled", True):
                    continue
                
                dragon_data = db.get_dragon(user_id)
                if not dragon_data:
                    continue
                
                dragon = Dragon.from_dict(dragon_data)
                dragon_name = dragon.name
                dragon_trait = dragon.character.get("основная_черта", "")
                
                # Утренние уведомления (8-9 утра)
                if 8 <= current_hour <= 9:
                    # Проверяем, нужно ли отправлять уведомление
                    if rate_limiter.should_send_morning_notification(user_id):
                        # Случайное утреннее сообщение
                        messages = [
                            f"☀️ Доброе утро! {dragon_name} просыпается и потягивается. "
                            f"Он смотрит на тебя голодными глазками: 'Может, кофе? И печенье?' ☕🍪",
                            
                            f"🌅 {dragon_name} зевает и трёт глазки. 'Утро... Кофе...' - бормочет он, "
                            f"с надеждой глядя на кофемашину. Не забудь покормить дракона! ✨",
                            
                            f"🕗 Восемь утра! {dragon_name} уже на ногах и принюхивается к запахам с кухни. "
                            f"'Пахнет... кофе? Или это моё воображение?' 🐉👃"
                        ]
                        
                        # Особые сообщения для разных характеров
                        if dragon_trait == "кофеман":
                            messages.append(
                                f"☕ КОФЕМАН ТРЕБУЕТ КОФЕ! {dragon_name} буквально трясётся от нетерпения. "
                                f"'Пожалуйста, скорее! Мне нужна моя утренняя доза!' ⚡"
                            )
                        elif dragon_trait == "гурман":
                            messages.append(
                                f"🍽️ {dragon_name} смотрит на тебя с надеждой: "
                                f"'Я слышал, сегодня у нас на завтрак что-то особенное?' 👨‍🍳✨"
                            )
                        
                        await bot.send_message(user_id, random.choice(messages))
                        logger.info(f"Отправлено утреннее уведомление пользователю {user_id}")
                        continue
                
                # Вечерние уведомления (20-21 вечера)
                elif 20 <= current_hour <= 21:
                    if random.random() < 0.3:  # 30% шанс
                        messages = [
                            f"🌙 {dragon_name} зевает и сворачивается калачиком на диване. "
                            f"'Уже поздно... скоро спать,' - говорит он, медленно закрывая глаза. 😴",
                            
                            f"✨ Вечер. {dragon_name} смотрит на звёзды в окне. "
                            f"'Сегодня был хороший день. Спасибо тебе,' - шепчет он тихо. 💫",
                            
                            f"🛏️ {dragon_name} уже в пижамке и готовится ко сну. "
                            f"'Не забудь почитать мне сказку перед сном?' 📖"
                        ]
                        await bot.send_message(user_id, random.choice(messages))
                        continue
                
                # Случайные заботливые сообщения (1% шанс в любое время)
                if random.random() < 0.01:
                    messages = [
                        f"❤️ {dragon_name} вдруг обнимает тебя: 'Я так рад, что ты у меня есть!' 🐾",
                        f"💕 {dragon_name} смотрит на тебя с любовью: 'Ты - лучший хозяин в мире!' ✨",
                        f"🌟 {dragon_name} думает о тебе и улыбается. 'Как же я тебя люблю!' 💖"
                    ]
                    await bot.send_message(user_id, random.choice(messages))
                    continue
                
                # Сообщения о том, что дракон скучает (если не было активности 3+ часа)
                last_action_time = rate_limiter.user_last_interaction.get(user_id)
                if last_action_time:
                    hours_since_last = (now - last_action_time).total_seconds() / 3600
                    if hours_since_last > 3 and random.random() < 0.1:  # 10% шанс
                        messages = [
                            f"😔 {dragon_name} грустно смотрит на дверь. 'Когда же он вернётся?' 💭",
                            f"⏳ {dragon_name} перебирает свои игрушки. 'Скучно без него...' 🧸",
                            f"📱 {dragon_name} смотрит на телефон. 'Написать ему? Или подождать?' ✍️"
                        ]
                        await bot.send_message(user_id, random.choice(messages))
                        
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Ошибка в send_notifications: {e}")

# ==================== КОРМЛЕНИЕ (ДЛЯ ЗАПИСИ В РАСПИСАНИЕ) ====================
@dp.message(Command("feed"))
async def cmd_feed(message: types.Message):
    """Покормить дракона - записываем в расписание"""
    try:
        user_id = message.from_user.id
        
        if not rate_limiter.can_perform_action(user_id, "feed", 15):
            await message.answer("<b>⏳ Дракон еще не проголодался. Подожди немного 🍪</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        appetite_stat = dragon.stats.get("аппетит", 0)
        full_message = check_stat_full(appetite_stat, "аппетит", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        # Записываем время кормления для умных уведомлений
        rate_limiter.record_feeding(user_id)
        
        inventory = db.get_inventory(user_id)
        
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

# ==================== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ====================
@dp.error()
async def error_handler(event: Exception, *args, **kwargs):
    """Глобальный обработчик ошибок"""
    logger.error(f"Необработанная ошибка: {event}")

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
        except KeyboardInterrupt:
            break
        
        # Проверяем каждые 30 минут
        await asyncio.sleep(1800)

async def main():
    """Главная функция запуска бота"""
    logger.info("✨ Запуск бота Кофейный Дракон v5.1...")
    
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