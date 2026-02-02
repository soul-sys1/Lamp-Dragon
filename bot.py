"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 6.0
Улучшенная версия с:
- Глубоко проработанными характерами (10 типов)
- Менее агрессивным снижением показателей (5% в час)
- Упрощенной системой помощи
- Оптимизированным магазином (3 категории)
"""
import asyncio
import logging
import random
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
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
    coffee_additions = State()
    coffee_snack = State()
    sleep_choice = State()
    care_action = State()
    minigame_state = State()
    book_reading = State()
    help_section = State()

# ==================== КЛАССЫ И УТИЛИТЫ ====================
class RateLimiter:
    def __init__(self):
        self.user_actions: Dict[str, datetime] = {}
        self.user_notifications: Dict[int, Dict[str, datetime]] = {}
        self.user_feeding_schedule: Dict[int, List[datetime]] = {}
        self.user_last_interaction: Dict[int, datetime] = {}
    
    def can_perform_action(self, user_id: int, action: str, cooldown_seconds: int = 30) -> bool:
        now = datetime.now()
        key = f"{user_id}_{action}"
        
        if key in self.user_actions:
            last_time = self.user_actions[key]
            if now - last_time < timedelta(seconds=cooldown_seconds):
                return False
        
        self.user_actions[key] = now
        self.user_last_interaction[user_id] = now
        return True
    
    def record_feeding(self, user_id: int):
        now = datetime.now()
        if user_id not in self.user_feeding_schedule:
            self.user_feeding_schedule[user_id] = []
        
        self.user_feeding_schedule[user_id].append(now)
        if len(self.user_feeding_schedule[user_id]) > 30:
            self.user_feeding_schedule[user_id] = self.user_feeding_schedule[user_id][-30:]
    
    def should_send_morning_notification(self, user_id: int) -> bool:
        if user_id not in self.user_feeding_schedule:
            return True
        
        now = datetime.now()
        today = now.date()
        
        if not self.user_feeding_schedule[user_id]:
            return True
        
        for feeding_time in self.user_feeding_schedule[user_id]:
            if feeding_time.date() == today and 8 <= feeding_time.hour <= 9:
                return False
        
        if self.user_feeding_schedule[user_id]:
            last_feeding = max(self.user_feeding_schedule[user_id])
            if now - last_feeding > timedelta(hours=12):
                return True
        
        return True
    
    def clear_old_entries(self):
        now = datetime.now()
        month_ago = now - timedelta(days=30)
        
        keys_to_delete = [k for k, v in self.user_actions.items() if v < month_ago]
        for k in keys_to_delete:
            del self.user_actions[k]
        
        for user_id in list(self.user_feeding_schedule.keys()):
            self.user_feeding_schedule[user_id] = [
                t for t in self.user_feeding_schedule[user_id] 
                if t > month_ago
            ]
            if not self.user_feeding_schedule[user_id]:
                del self.user_feeding_schedule[user_id]

class MinigameManager:
    @staticmethod
    def guess_number_game() -> dict:
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

# ==================== МОДУЛЬ ХАРАКТЕРОВ ====================
class CharacterPersonality:
    """Глубоко проработанные характеры драконов"""
    
    @staticmethod
    def get_character_description(character_trait: str) -> Dict:
        """Возвращает полное описание характера"""
        descriptions = {
            "кофеман": {
                "name": "☕ Кофеман",
                "description": (
                    "Рождён среди кофейных плантаций волшебных гор, "
                    "этот дракон чувствует кофе на расстоянии мили! Его нос "
                    "может уловить аромат свежесваренного эспрессо за три дома."
                ),
                "features": [
                    "☕ Обожает экспериментировать с разными сортами",
                    "⚡ Быстро теряет энергию без кофейной подпитки",
                    "💬 Может часами рассказывать о методах заварки",
                    "🎯 Знает все виды кофе в радиусе 100 км"
                ],
                "advice": "Всегда держите запас кофейных зёрен!",
                "emoji": "☕"
            },
            "книгочей": {
                "name": "📚 Книгочей",
                "description": (
                    "Выращен в древней библиотеке драконьего знания, "
                    "этот дракон прочитал больше книг, чем звёзд на небе. "
                    "Каждая книга для него - новое приключение."
                ),
                "features": [
                    "📖 Обожает, когда ему читают перед сном",
                    "🧠 Быстро учится и запоминает прочитанное",
                    "💭 Часто цитирует любимые произведения",
                    "🎓 Знает историю всех драконьих родов"
                ],
                "advice": "Читайте ему каждый вечер - он это обожает!",
                "emoji": "📚"
            },
            "неженка": {
                "name": "💖 Неженка",
                "description": (
                    "Самый ласковый дракон во всём королевстве! "
                    "Рождённый из облака нежности и заботы, он верит, "
                    "что мир можно изменить объятиями."
                ),
                "features": [
                    "💕 Требует минимум 3 обнимашки в день",
                    "😢 Быстро грустит без внимания",
                    "✨ Расцветает от ласковых слов",
                    "🎀 Обожает, когда его гладят и чешут"
                ],
                "advice": "Не скупитесь на ласку и внимание!",
                "emoji": "💖"
            },
            "чистюля": {
                "name": "✨ Чистюля",
                "description": (
                    "Блестит и сверкает, как только что отполированный алмаз! "
                    "Этот дракон следит за чистотой так тщательно, "
                    "что даже пылинки боятся к нему приблизиться."
                ),
                "features": [
                    "✨ Быстро замечает малейшую пыль на себе",
                    "🛁 Обожает водные процедуры и уход",
                    "👃 Чувствителен к запахам",
                    "💅 Следит за состоянием коготков"
                ],
                "advice": "Регулярно ухаживайте за его шёрсткой!",
                "emoji": "✨"
            },
            "гурман": {
                "name": "🍰 Гурман",
                "description": (
                    "Настоящий ценитель изысканных вкусов! "
                    "Этот дракон родился на кухне волшебного замка "
                    "и с детства разбирается в кулинарных тонкостях."
                ),
                "features": [
                    "👨‍🍳 Критично оценивает каждое угощение",
                    "💎 Ценит качественные ингредиенты",
                    "🎭 Может отказаться от 'простых' сладостей",
                    "💰 Даёт больше золота за любимые лакомства"
                ],
                "advice": "Угощайте его только лучшими сладостями!",
                "emoji": "🍰"
            },
            "игрик": {
                "name": "🎮 Игрик",
                "description": (
                    "Энергия и азарт в одном драконьем теле! "
                    "Рождённый в игровой вселенной, он верит, "
                    "что жизнь - это самая интересная игра."
                ),
                "features": [
                    "🎯 Чаще инициирует мини-игры",
                    "⚡ Меньше устаёт от активностей",
                    "🏆 Обожает соревнования и победы",
                    "🤝 Ищет игровых партнёров"
                ],
                "advice": "Играйте с ним каждый день!",
                "emoji": "🎮"
            },
            "соня": {
                "name": "😴 Соня",
                "description": (
                    "Мастер сладких снов и пушистых облаков! "
                    "Этот дракон спит так крепко, что иногда "
                    "приснится самому себе во сне."
                ),
                "features": [
                    "💤 Чаще хочет спать и отдыхать",
                    "⚡ Быстрее восстанавливает энергию во сне",
                    "🌙 Может заснуть в самых неожиданных местах",
                    "🛏️ Обожает мягкие подушки и одеяла"
                ],
                "advice": "Не будите его без крайней необходимости!",
                "emoji": "😴"
            },
            "энерджайзер": {
                "name": "⚡ Энерджайзер",
                "description": (
                    "Живая электростанция драконьего мира! "
                    "Рождённый во время грозы, он накопил столько энергии, "
                    "что может осветить целый город."
                ),
                "features": [
                    "⚡ Медленнее теряет энергию",
                    "🏃 Чаще инициирует активные действия",
                    "🎢 Может 'перевозбудиться' от кофе",
                    "💥 Иногда получает дополнительное действие"
                ],
                "advice": "Давайте ему много активностей!",
                "emoji": "⚡"
            },
            "философ": {
                "name": "🤔 Философ",
                "description": (
                    "Мудрец драконьего племени! "
                    "Рождённый под древним дубом мудрости, "
                    "он видит смысл там, где другие видют лишь поверхность."
                ),
                "features": [
                    "💭 Задаёт глубокие вопросы",
                    "😌 Реже теряет настроение",
                    "📜 Любит размышлять о жизни",
                    "🎓 Даёт мудрые советы"
                ],
                "advice": "Обсуждайте с ним важные темы!",
                "emoji": "🤔"
            },
            "исследователь": {
                "name": "🔍 Исследователь",
                "description": (
                    "Неутомимый искатель тайн и загадок! "
                    "Рождённый с картой в лапках, он мечтает "
                    "исследовать каждый уголок волшебного мира."
                ),
                "features": [
                    "🔎 Задаёт любопытные вопросы",
                    "💎 Чаще находит случайные предметы",
                    "📈 Бонус к опыту от новых действий",
                    "🗺️ Обожает изучать новое"
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
                "morning": f"☕ {dragon_name} просыпается и сразу тянется к кофемашине: 'Утро начинается с ароматного кофе!'",
                "coffee_time": f"☕ {dragon_name} принюхивается: 'Чувствую нотки арабики с оттенком карамели...'",
                "no_coffee": f"😫 {dragon_name} грустно: 'Без кофе я как дракон без крыльев...'",
                "favorite_coffee": f"🎉 {dragon_name} в восторге: 'Это именно тот сорт, о котором я мечтал!'"
            },
            "книгочей": {
                "morning": f"📚 {dragon_name} зевает: 'Как жаль прерывать такой интересный сон... В нём я читал древний манускрипт!'",
                "reading_time": f"📖 {dragon_name} уютно устраивается: 'А помнишь, в прошлой книге герой...'",
                "bedtime": f"🌙 {dragon_name} просит: 'Можно ещё одну главу? Пожалуйста!'",
                "discovery": f"🤔 {dragon_name} задумчиво: 'Интересно, а что бы сделал герой той книги в этой ситуации?'"
            },
            "неженка": {
                "morning": f"💖 {dragon_name} потягивается: 'Доброе утро! Мне уже не хватает твоих объятий...'",
                "hug_time": f"🤗 {dragon_name} обнимает вас: 'Ты самый лучший хранитель на свете!'",
                "sad": f"😔 {dragon_name} грустит: 'Мне кажется, ты меня сегодня мало обнимал...'",
                "happy": f"✨ {dragon_name} сияет: 'Когда ты рядом, весь мир становится теплее!'"
            },
            "чистюля": {
                "morning": f"✨ {dragon_name} проверяет лапки: 'Ой, кажется, нужно почистить коготки...'",
                "dirty": f"😷 {dragon_name} морщится: 'Я чувствую пылинку на своём левом боку!'",
                "clean": f"🌟 {dragon_name} сверкает: 'Теперь я блещу чистотой!'",
                "care_time": f"🛁 {dragon_name} радостно: 'Время водных процедур! Я так это люблю!'"
            },
            "гурман": {
                "morning": f"🍰 {dragon_name} принюхивается: 'Чувствую запах свежей выпечки... Или это моё воображение?'",
                "treat_time": f"👨‍🍳 {dragon_name} оценивающе: 'Хм, интересное сочетание вкусов...'",
                "favorite_food": f"🎊 {dragon_name} в восторге: 'Это божественно! Где ты нашёл такое лакомство?'",
                "simple_food": f"😐 {dragon_name} вежливо: 'Спасибо, но... я не очень голоден.'"
            },
            "игрик": {
                "morning": f"🎮 {dragon_name} прыгает с кровати: 'Ура, новый день! Сколько игр нас сегодня ждёт?'",
                "game_time": f"🏆 {dragon_name} азартно: 'Давай сыграем! На этот раз я точно выиграю!'",
                "win": f"🎉 {dragon_name} ликует: 'Я чемпион! Давай ещё одну игру!'",
                "lose": f"😤 {dragon_name} решительно: 'В следующий раз я обязательно выиграю!'"
            },
            "соня": {
                "morning": f"😴 {dragon_name} неохотно открывает глаз: 'Уже утро? Кажется, я только что уснул...'",
                "nap_time": f"💤 {dragon_name} зевает: 'Может, вздремнём немного? Всего пять минуточек...'",
                "bedtime": f"🛏️ {dragon_name} уютно сворачивается: 'Наконец-то можно спать... Спокойной ночи!'",
                "well_rested": f"✨ {dragon_name} потягивается: 'Как же хорошо выспаться!'"
            },
            "энерджайзер": {
                "morning": f"⚡ {dragon_name} вскакивает: 'Доброе утро! У меня столько энергии, что можно горы свернуть!'",
                "active": f"🏃 {dragon_name} носится по комнате: 'Не могу усидеть на месте! Давай что-нибудь сделаем!'",
                "coffee_boost": f"💥 {dragon_name} после кофе: 'Вау! Теперь я могу летать без крыльев!'",
                "evening": f"🌙 {dragon_name} всё ещё активен: 'Уже вечер? А я только разогнался!'"
            },
            "философ": {
                "thinking": f"💭 {dragon_name} размышляет: 'Знаешь, я тут подумал о смысле драконьего бытия...'",
                "question": f"❓ {dragon_name} спрашивает: 'А что для тебя значит слово 'счастье'?'",
                "wisdom": f"🎓 {dragon_name} мудро: 'Иногда чтобы найти ответ, нужно просто перестать искать.'"
            },
            "исследователь": {
                "morning": f"🔍 {dragon_name} с интересом: 'Интересно, что нового сегодня откроется?'",
                "curious": f"🤨 {dragon_name} рассматривает предмет: 'А как это работает? Из чего сделано?'",
                "discovery": f"🎊 {dragon_name} радостно: 'Смотри, что я нашёл! Это же древний артефакт!'",
                "question": f"❓ {dragon_name} спрашивает: 'А ты знаешь, почему трава зелёная?'"
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

def check_stat_full(stat_value: int, stat_name: str, dragon_trait: str = "") -> Optional[str]:
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

def format_stat_line(stat_name: str, stat_value: int) -> str:
    """Форматирует строку статистики с одинаковыми отступами"""
    stat_names = {
        "кофе": "☕ Кофе",
        "сон": "💤 Сон", 
        "настроение": "😊 Настроение",
        "аппетит": "🍪 Аппетит",
        "энергия": "⚡ Энергия",
        "пушистость": "✨ Пушистость"
    }
    
    name = stat_names.get(stat_name, stat_name)
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
            [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="📦 Инвентарь")],
            [KeyboardButton(text="🔕 Уведомления"), KeyboardButton(text="📖 Помощь")]
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
    """Главное меню магазина (3 категории)"""
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
    """Магазин кофе и ингредиентов"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="☕ Кофейные зёрна", callback_data="buy_coffee_beans"),
                InlineKeyboardButton(text="10💰", callback_data="price_10")
            ],
            [
                InlineKeyboardButton(text="🍫 Шоколадные чипсы", callback_data="buy_chocolate_chips"),
                InlineKeyboardButton(text="8💰", callback_data="price_8")
            ],
            [
                InlineKeyboardButton(text="🍯 Медовый сироп", callback_data="buy_honey_syrup"),
                InlineKeyboardButton(text="12💰", callback_data="price_12")
            ],
            [
                InlineKeyboardButton(text="🍦 Ванильное мороженое", callback_data="buy_vanilla_icecream"),
                InlineKeyboardButton(text="15💰", callback_data="price_15")
            ],
            [
                InlineKeyboardButton(text="🍭 Карамельный сироп", callback_data="buy_caramel_syrup"),
                InlineKeyboardButton(text="10💰", callback_data="price_10")
            ],
            [
                InlineKeyboardButton(text="🌰 Фундук молотый", callback_data="buy_hazelnut"),
                InlineKeyboardButton(text="18💰", callback_data="price_18")
            ],
            [
                InlineKeyboardButton(text="« Назад в магазин", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

def get_sweets_shop_keyboard() -> InlineKeyboardMarkup:
    """Магазин сладостей и угощений"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍪 Печенье с изюмом", callback_data="buy_cookie_raisin"),
                InlineKeyboardButton(text="5💰", callback_data="price_5")
            ],
            [
                InlineKeyboardButton(text="🍫 Шоколадная плитка", callback_data="buy_chocolate_bar"),
                InlineKeyboardButton(text="15💰", callback_data="price_15")
            ],
            [
                InlineKeyboardButton(text="☁️ Ванильный зефир", callback_data="buy_vanilla_marshmallow"),
                InlineKeyboardButton(text="7💰", callback_data="price_7")
            ],
            [
                InlineKeyboardButton(text="🎄 Имбирный пряник", callback_data="buy_gingerbread"),
                InlineKeyboardButton(text="8💰", callback_data="price_8")
            ],
            [
                InlineKeyboardButton(text="🍬 Фруктовый мармелад", callback_data="buy_fruit_marmalade"),
                InlineKeyboardButton(text="10💰", callback_data="price_10")
            ],
            [
                InlineKeyboardButton(text="🎂 Шоколадное пирожное", callback_data="buy_chocolate_cake"),
                InlineKeyboardButton(text="20💰", callback_data="price_20")
            ],
            [
                InlineKeyboardButton(text="🍩 Сладкий пончик", callback_data="buy_donut"),
                InlineKeyboardButton(text="12💰", callback_data="price_12")
            ],
            [
                InlineKeyboardButton(text="« Назад в магазин", callback_data="shop_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")
            ]
        ]
    )
    return keyboard

def get_care_shop_keyboard() -> InlineKeyboardMarkup:
    """Магазин предметов для ухода"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💆 Драконья расчёска", callback_data="buy_dragon_brush"),
                InlineKeyboardButton(text="25💰", callback_data="price_25")
            ],
            [
                InlineKeyboardButton(text="🧴 Волшебный шампунь", callback_data="buy_magic_shampoo"),
                InlineKeyboardButton(text="30💰", callback_data="price_30")
            ],
            [
                InlineKeyboardButton(text="✂️ Золотые ножницы", callback_data="buy_golden_scissors"),
                InlineKeyboardButton(text="35💰", callback_data="price_35")
            ],
            [
                InlineKeyboardButton(text="🧸 Плюшевый дракончик", callback_data="buy_plush_dragon"),
                InlineKeyboardButton(text="40💰", callback_data="price_40")
            ],
            [
                InlineKeyboardButton(text="🛁 Ароматная соль", callback_data="buy_aromatic_salt"),
                InlineKeyboardButton(text="20💰", callback_data="price_20")
            ],
            [
                InlineKeyboardButton(text="💅 Лак для когтей", callback_data="buy_nail_polish"),
                InlineKeyboardButton(text="28💰", callback_data="price_28")
            ],
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
    
    # Создаем кнопки для сладостей, которые есть в инвентаре
    snack_items = {
        "печенье": "🍪 Печенье",
        "шоколад": "🍫 Шоколад", 
        "зефир": "☁️ Зефир",
        "пряник": "🎄 Пряник",
        "мармелад": "🍬 Мармелад",
        "пирожное": "🎂 Пирожное"
    }
    
    row = []
    for snack_key, snack_name in snack_items.items():
        count = inventory.get(snack_key, 0)
        if count > 0:
            row.append(InlineKeyboardButton(
                text=f"{snack_name} ×{count}", 
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

def get_minigames_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="game_back")
            ]
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
    
    # Базовые действия ухода
    row1 = []
    row1.append(InlineKeyboardButton(text="✨ Расчесать лапки", callback_data="care_brush_paws"))
    row1.append(InlineKeyboardButton(text="🛁 Протереть мордочку", callback_data="care_wipe_face"))
    keyboard.inline_keyboard.append(row1)
    
    row2 = []
    row2.append(InlineKeyboardButton(text="💅 Почистить когти", callback_data="care_clean_nails"))
    row2.append(InlineKeyboardButton(text="🦷 Почистить зубы", callback_data="care_clean_teeth"))
    keyboard.inline_keyboard.append(row2)
    
    # Действия с предметами из магазина
    row3 = []
    if inventory.get("расческа", 0) > 0:
        row3.append(InlineKeyboardButton(text="💆 Расчесать шерстку", callback_data="care_brush_fur"))
    if inventory.get("шампунь", 0) > 0:
        row3.append(InlineKeyboardButton(text="🧴 Искупать с шампунем", callback_data="care_bath_shampoo"))
    
    if row3:
        keyboard.inline_keyboard.append(row3)
    
    row4 = []
    if inventory.get("ножницы", 0) > 0:
        row4.append(InlineKeyboardButton(text="✂️ Подстричь когти ножницами", callback_data="care_trim_nails_scissors"))
    if inventory.get("игрушка", 0) > 0:
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

def get_feed_keyboard(inventory: dict) -> InlineKeyboardMarkup:
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
    """Клавиатура для меню помощи (2 раздела)"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Все команды", callback_data="help_commands")
            ],
            [
                InlineKeyboardButton(text="🎭 Все характеры", callback_data="help_characters")
            ],
            [
                InlineKeyboardButton(text="« Назад", callback_data="help_back")
            ]
        ]
    )
    return keyboard

def get_characters_list_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора характера в справке"""
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

# Инициализация менеджеров
rate_limiter = RateLimiter()
minigame_manager = MinigameManager()

# ==================== ДЕТАЛЬНЫЕ ОПИСАНИЯ ДЕЙСТВИЙ ====================
class ActionDescriptions:
    @staticmethod
    def get_hug_scenes(dragon_name: str, dragon_trait: str) -> List[str]:
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
        return [
            f"Вы берёте красивую расчёску и подзываете {dragon_name}. Он радостно подбегает и садится перед вами. "
            f"Вы начинаете аккуратно расчёсывать его шерстку, и дракон мурлычет от удовольствия. "
            f"С каждым движением расчёски его шёрстка становится всё более блестящей и пушистой! ✨💆",
            
            f"{dragon_name} лежит на специальном столике для ухода, счастливо развалившись. "
            f"Вы берёте расчёску и начинаете работать над его шерстку. Дракон закрывает глаза от наслаждения, "
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
    
    @staticmethod
    def get_coffee_preparation_scene(dragon_name: str, coffee_type: str, addition: str, snack: str) -> str:
        coffee_names = {
            "espresso": "эспрессо",
            "latte": "латте",
            "cappuccino": "капучино",
            "raf": "раф",
            "americano": "американо",
            "mocha": "мокко"
        }
        
        addition_names = {
            "chocolate": "шоколадом",
            "honey": "мёдом",
            "icecream": "мороженым",
            "syrup": "сиропом",
            "none": ""
        }
        
        snack_names = {
            "печенье": "печеньем",
            "шоколад": "шоколадом",
            "зефир": "зефиром",
            "пряник": "пряником",
            "мармелад": "мармеладом",
            "пирожное": "пирожным",
            "none": ""
        }
        
        coffee = coffee_names.get(coffee_type, "кофе")
        add_text = f" с {addition_names.get(addition, '')}" if addition != "none" else ""
        snack_text = f" с {snack_names.get(snack, '')}" if snack != "none" else ""
        
        scenes = [
            f"Вы начинаете готовить {coffee}{add_text} для {dragon_name}. Аромат свежего кофе заполняет комнату. "
            f"Дракон нетерпеливо переминается с лапки на лапку, ожидая своего напитка. "
            f"Наконец, вы подаёте чашку, и {dragon_name} с наслаждением делает первый глоток{snack_text}! ☕✨",
            
            f"Сегодня вы решили порадовать {dragon_name} особенным {coffee}{add_text}. "
            f"Дракон внимательно наблюдает за каждым вашим движением. Когда напиток готов, он аккуратно берёт чашку "
            f"в лапки и с удовольствием пьёт{snack_text}. 'Вкуснее всего, когда ты готовишь!' - говорит он. 🐉❤️",
            
            f"Вы создаёте идеальный {coffee}{add_text} для {dragon_name}. Пена идеальной консистенции, "
            f"температура как надо. Дракон пробует и мурлычет от удовольствия{snack_text}: "
            f"'Это именно то, что нужно для прекрасного дня!' 😊"
        ]
        
        return random.choice(scenes)

# ==================== НАЧАЛЬНЫЙ ЭКРАН И БАЗОВЫЕ КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - красивое приветствие"""
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
            
            f"<b>📋 ВОЗМОЖНОСТИ 6.0:</b>\n"
            f"• 🎭 <b>10 уникальных характеров</b> с глубокой проработкой\n"
            f"• ⏳ <b>Менее агрессивные показатели</b> (5%/час)\n"
            f"• 🛍️ <b>Упрощённый магазин</b> с 3 категориями\n"
            f"• 📚 <b>Расширенная помощь</b> по характерам\n"
            f"• ❤️ <b>Уникальные реакции</b> для каждого дракона\n\n"
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
    """Команда /help - красивая справка"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        try:
            await message.delete()
        except:
            pass
        
        has_dragon = db.dragon_exists(user_id)
        
        help_text = (
            "<b>📚 КОМАНДЫ И ХАРАКТЕРЫ (v6.0)</b>\n\n"
            
            "<b>🐉 ОСНОВНЫЕ КОМАНДЫ:</b>\n"
            "<code>/start</code> - начать игру\n"
            "<code>/help</code> - эта справка\n"
            "<code>/create</code> - создать дракона\n"
            "<code>/status</code> - статус дракона\n\n"
            
            "<b>😴 СОН И ОТДЫХ</b>\n"
            "<code>/sleep</code> - уложить дракона спать с разными сценами\n\n"
            
            "<b>❤ УХОД И ЗАБОТА</b>\n"
            "<code>/coffee</code> - приготовить кофе с добавками\n"
            "<code>/feed</code> - покормить сладостями\n"
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
        
        await message.answer(help_text, parse_mode="HTML", reply_markup=get_help_keyboard())
        await state.set_state(GameStates.help_section)
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_help: {e}")
        await message.answer("<b>❌ Произошла ошибка при показе помощи.</b>", parse_mode="HTML")

@dp.callback_query(GameStates.help_section, F.data.startswith("help_"))
async def process_help_section(callback: types.CallbackQuery, state: FSMContext):
    """Обработка разделов помощи"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("help_", "")
        
        if action == "back":
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
            return
        
        if action == "commands":
            commands_text = (
                "<b>📋 ВСЕ КОМАНДЫ БОТА</b>\n\n"
                
                "<b>🐉 ОСНОВНЫЕ:</b>\n"
                "<code>/start</code> - начать игру\n"
                "<code>/help</code> - помощь\n"
                "<code>/create</code> - создать дракона\n"
                "<code>/status</code> - статус дракона\n\n"
                
                "<b>☕ КОФЕ И ЕДА:</b>\n"
                "<code>/coffee</code> - приготовить кофе\n"
                "<code>/feed</code> - покормить дракона\n\n"
                
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
    """Обработка детального просмотра характера"""
    try:
        action = callback.data.replace("char_", "")
        
        if action == "back":
            characters_intro = (
                "<b>🎭 ВСЕ ХАРАКТЕРЫ ДРАКОНОВ</b>\n\n"
                "<i>👇 Выбери характер, чтобы узнать о нём подробнее:</i>"
            )
            
            await callback.message.edit_text(
                characters_intro,
                parse_mode="HTML",
                reply_markup=get_characters_list_keyboard()
            )
            await callback.answer()
            return
        
        # Сопоставление callback с названиями характеров
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
            "его реакции в уведомлениях и предпочтения в еде и уходе!</i>"
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
        
        dragon = Dragon(name=dragon_name)
        dragon_data = dragon.to_dict()
        
        success = db.create_dragon(user_id, dragon_data)
        
        if not success:
            await message.answer("<b>❌ Не удалось создать дракона. Попробуй еще раз.</b>", parse_mode="HTML")
            await state.clear()
            return
        
        initial_inventory = {
            "кофейные_зерна": 10,
            "печенье": 5,
            "шоколад": 2,
            "зефир": 1,
            "пряник": 1
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
    """Показать статус дракона"""
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
        
        # Используем серверное время
        now = datetime.now()
        
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
        
        status_text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 <i>Текущее время:</i> <code>{now.strftime('%H:%M:%S')}</code>\n"
            f"📅 <i>Дата:</i> <code>{now.strftime('%d.%m.%Y')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

# ==================== КОФЕ ====================
@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message):
    """Приготовить кофе"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было
        try:
            await message.delete()
        except:
            pass
        
        if not rate_limiter.can_perform_action(user_id, "coffee", 15):
            await message.answer("<b>⏳ Дракон ещё не готов к новому кофе. Подожди немного ☕</b>", parse_mode="HTML")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        coffee_stat = dragon.stats.get("кофе", 0)
        full_message = check_stat_full(coffee_stat, "кофе", dragon.character.get("основная_черта", ""))
        if full_message:
            await message.answer(full_message, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        inventory = db.get_inventory(user_id)
        
        if inventory.get("кофейные_зерна", 0) <= 0:
            await message.answer(
                "<b>❌ Нет кофейных зёрен!</b>\n\n"
                "<b>🛍️ Купи в магазине:</b>\n"
                "• Нажми «🛍️ Магазин»\n"
                "• Или <code>/shop</code>",
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
            
            f"<b>📦 Кофейные зёрна:</b> <code>{inventory.get('кофейные_зерна', 0)}</code>\n"
            f"<b>🎭 Характер:</b> <code>{character_trait}</code>\n\n"
            
            f"<i>Любимый кофе дракона: {dragon.favorites.get('кофе', 'латте')}</i>",
            parse_mode="HTML",
            reply_markup=get_coffee_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_coffee: {e}")
        await message.answer("<b>❌ Произошла ошибка при приготовлении кофе.</b>", parse_mode="HTML")

# ==================== МАГАЗИН ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message):
    """Открыть магазин"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        try:
            await message.delete()
        except:
            pass
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        await message.answer(
            f"<b>🏪 МАГАЗИН ДЛЯ {escape_html(dragon.name)}</b>\n\n"
            
            f"<b>💰 Твоё золото:</b> <code>{dragon.gold}</code>\n\n"
            
            f"<b>🛒 ВЫБЕРИ КАТЕГОРИЮ:</b>\n"
            f"• ☕ <b>Кофе и ингредиенты</b> - всё для идеального напитка\n"
            f"• 🍪 <b>Сладости и угощения</b> - вкусные лакомства для дракона\n"
            f"• ✨ <b>Предметы для ухода</b> - средства для красоты и чистоты\n\n"
            
            f"<i>💡 Каждая категория содержит уникальные товары!</i>",
            parse_mode="HTML",
            reply_markup=get_shop_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_shop: {e}")
        await message.answer("<b>❌ Произошла ошибка при открытии магазина.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_"))
async def process_shop_category(callback: types.CallbackQuery):
    """Обработка выбора категории в магазине"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("shop_", "")
        
        if action == "back":
            # Возврат к главному меню магазина
            dragon_data = db.get_dragon(user_id)
            if not dragon_data:
                await callback.answer("🐣 Дракон не найден")
                return
            
            dragon = Dragon.from_dict(dragon_data)
            
            await callback.message.edit_text(
                f"<b>🏪 МАГАЗИН ДЛЯ {escape_html(dragon.name)}</b>\n\n"
                f"<b>💰 Твоё золото:</b> <code>{dragon.gold}</code>\n\n"
                f"<b>🛒 ВЫБЕРИ КАТЕГОРИЮ:</b>\n"
                f"• ☕ <b>Кофе и ингредиенты</b>\n"
                f"• 🍪 <b>Сладости и угощения</b>\n"
                f"• ✨ <b>Предметы для ухода</b>\n\n"
                f"<i>💡 Каждая категория содержит уникальные товары!</i>",
                parse_mode="HTML",
                reply_markup=get_shop_main_keyboard()
            )
            await callback.answer()
            return
        
        if action == "close":
            await callback.message.delete()
            await callback.answer("❌ Магазин закрыт")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("🐣 Дракон не найден")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        if action == "coffee":
            category_text = (
                f"<b>☕ КОФЕ И ИНГРЕДИЕНТЫ</b>\n\n"
                f"<b>💰 Твоё золото:</b> <code>{dragon.gold}</code>\n\n"
                f"<i>✨ Всё для создания идеального кофейного напитка!</i>\n\n"
                f"<b>🛒 ТОВАРЫ:</b>\n"
                f"• ☕ Кофейные зёрна - 10💰 (основа любого напитка)\n"
                f"• 🍫 Шоколадные чипсы - 8💰 (для мокко и рафа)\n"
                f"• 🍯 Медовый сироп - 12💰 (натуральная сладость)\n"
                f"• 🍦 Ванильное мороженое - 15💰 (для гляссе)\n"
                f"• 🍭 Карамельный сироп - 10💰 (сладкая добавка)\n"
                f"• 🌰 Фундук молотый - 18💰 (ореховый аромат)\n\n"
                f"<i>💡 Добавки делают кофе особенным!</i>"
            )
            keyboard = get_coffee_shop_keyboard()
            
        elif action == "sweets":
            category_text = (
                f"<b>🍪 СЛАДОСТИ И УГОЩЕНИЯ</b>\n\n"
                f"<b>💰 Твоё золото:</b> <code>{dragon.gold}</code>\n\n"
                f"<i>✨ Вкусные лакомства для твоего дракона!</i>\n\n"
                f"<b>🛒 ТОВАРЫ:</b>\n"
                f"• 🍪 Печенье с изюмом - 5💰 (классическое угощение)\n"
                f"• 🍫 Шоколадная плитка - 15💰 (особое лакомство)\n"
                f"• ☁️ Ванильный зефир - 7💰 (воздушное наслаждение)\n"
                f"• 🎄 Имбирный пряник - 8💰 (праздничное угощение)\n"
                f"• 🍬 Фруктовый мармелад - 10💰 (витаминная радость)\n"
                f"• 🎂 Шоколадное пирожное - 20💰 (праздник каждый день)\n"
                f"• 🍩 Сладкий пончик - 12💰 (круглое удовольствие)\n\n"
                f"<i>💡 Каждая сладость поднимает настроение!</i>"
            )
            keyboard = get_sweets_shop_keyboard()
            
        elif action == "care":
            category_text = (
                f"<b>✨ ПРЕДМЕТЫ ДЛЯ УХОДА</b>\n\n"
                f"<b>💰 Твоё золото:</b> <code>{dragon.gold}</code>\n\n"
                f"<i>✨ Всё для красоты и чистоты твоего дракона!</i>\n\n"
                f"<b>🛒 ТОВАРЫ:</b>\n"
                f"• 💆 Драконья расчёска - 25💰 (для идеальной шёрстки)\n"
                f"• 🧴 Волшебный шампунь - 30💰 (блеск и аромат)\n"
                f"• ✂️ Золотые ножницы - 35💰 (аккуратные коготки)\n"
                f"• 🧸 Плюшевый дракончик - 40💰 (лучший друг для игр)\n"
                f"• 🛁 Ароматная соль - 20💰 (расслабляющая ванна)\n"
                f"• 💅 Лак для когтей - 28💰 (стильный маникюр)\n\n"
                f"<i>💡 Ухоженный дракон - счастливый дракон!</i>"
            )
            keyboard = get_care_shop_keyboard()
        
        else:
            await callback.answer("❌ Неизвестная категория")
            return
        
        await callback.message.edit_text(category_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_shop_category: {e}")
        await callback.answer("❌ Произошла ошибка при выборе категории")

# ==================== УВЕДОМЛЕНИЯ ====================
@dp.message(Command("notifications"))
@dp.message(F.text == "🔕 Уведомления")
async def cmd_notifications(message: types.Message):
    """Управление уведомлениями"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        try:
            await message.delete()
        except:
            pass
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        user_settings = db.get_user_settings(user_id)
        notifications_enabled = user_settings.get("notifications_enabled", True)
        
        # Используем серверное время
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        
        status_text = "🔔 <b>ВКЛЮЧЕНЫ</b>" if notifications_enabled else "🔕 <b>ВЫКЛЮЧЕНЫ</b>"
        
        await message.answer(
            f"<b>🔔 УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ</b>\n\n"
            
            f"<i>✨ Дракон будет присылать уведомления по серверному времени:</i>\n\n"
            f"• 🌅 <b>Утренние напоминания</b> (8-9 утра)\n"
            f"• 🌙 <b>Вечерние напоминания</b> (20-21 час)\n"
            f"• ❤️ <b>Случайные сообщения</b> о том, что он скучает\n"
            f"• 🍪 <b>Напоминания</b> если вы давно не кормили\n\n"
            
            f"<b>Текущий статус:</b> {status_text}\n"
            f"<b>Серверное время:</b> <code>{time_str}</code>\n\n"
            
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>💡 Включи уведомления чтобы не пропустить важные моменты!</i>",
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
        else:
            await callback.answer("❌ Неизвестное действие")
            return
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer("✅ Настройки сохранены")
        
    except Exception as e:
        logger.error(f"Ошибка в process_notifications: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== УВЕДОМЛЕНИЯ ====================
async def send_notifications():
    """Отправка умных уведомлений"""
    try:
        all_users = db.get_all_users_with_dragons()
        
        for user_id in all_users:
            try:
                user_settings = db.get_user_settings(user_id)
                if not user_settings.get("notifications_enabled", True):
                    continue
                
                dragon_data = db.get_dragon(user_id)
                if not dragon_data:
                    continue
                
                dragon = Dragon.from_dict(dragon_data)
                dragon_name = dragon.name
                character_trait = dragon.character.get("основная_черта", "")
                
                # Используем серверное время
                now = datetime.now()
                current_hour = now.hour
                
                # Утренние уведомления (8-9 утра серверного времени)
                if 8 <= current_hour <= 9:
                    if rate_limiter.should_send_morning_notification(user_id):
                        morning_message = CharacterPersonality.get_character_message(
                            character_trait,
                            "morning",
                            dragon_name
                        )
                        
                        await bot.send_message(user_id, morning_message)
                        continue
                
                # Вечерние уведомления (20-21 час серверного времени)
                elif 20 <= current_hour <= 21:
                    if random.random() < 0.3:
                        evening_situations = ["bedtime", "reading_time", "thinking"]
                        situation = random.choice(evening_situations)
                        evening_message = CharacterPersonality.get_character_message(
                            character_trait,
                            situation,
                            dragon_name
                        )
                        
                        await bot.send_message(user_id, evening_message)
                        continue
                
                # Случайные сообщения (1% шанс)
                if random.random() < 0.01:
                    random_situations = ["happy", "curious", "question", "discovery"]
                    situation = random.choice(random_situations)
                    random_message = CharacterPersonality.get_character_message(
                        character_trait,
                        situation,
                        dragon_name
                    )
                    
                    await bot.send_message(user_id, random_message)
                    continue
                
                # Напоминания если давно не было взаимодействия
                last_action_time = rate_limiter.user_last_interaction.get(user_id)
                if last_action_time:
                    hours_since_last = (datetime.now() - last_action_time).total_seconds() / 3600
                    if hours_since_last > 3 and random.random() < 0.1:
                        if character_trait == "неженка":
                            message = f"😔 {dragon_name} грустно смотрит на дверь: 'Мне кажется, ты меня забыл...'"
                        elif character_trait == "игрик":
                            message = f"🎮 {dragon_name} скучает: 'Так давно не играли... Может, сыграем?'"
                        elif character_trait == "книгочей":
                            message = f"📚 {dragon_name} листает книгу: 'Интересно, что бы ты сказал об этом сюжете?'"
                        else:
                            message = f"💭 {dragon_name} думает о тебе: 'Скучаю по нашим приключениям...'"
                        
                        await bot.send_message(user_id, message)
                        
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Ошибка в send_notifications: {e}")

# ==================== ОБНОВЛЁННЫЕ ОБРАБОТЧИКИ ДЕЙСТВИЙ ====================
@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        try:
            await message.delete()
        except:
            pass
        
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
        
        result = dragon.apply_action("обнимашки")
        
        character_trait = dragon.character.get("основная_черта", "")
        
        # Характерный бонус
        if character_trait == "неженка":
            dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 25)
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 10)
            character_bonus = "<b>💖 Неженка обожает обнимашки! +25 к настроению, +10 к сну</b>\n"
        else:
            character_bonus = ""
        
        scenes = ActionDescriptions.get_hug_scenes(dragon.name, character_trait)
        scene = random.choice(scenes)
        
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
        
        await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_hug: {e}")
        await message.answer("<b>❌ Произошла ошибка при обнимашках.</b>", parse_mode="HTML")

# ==================== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ====================
@dp.error()
async def error_handler(event: Exception, *args, **kwargs):
    """Глобальный обработчик ошибок"""
    logger.error(f"Необработанная ошибка: {event}")

# ==================== ЗАПУСК БОТА ====================
async def scheduled_notifications():
    """Планировщик уведомлений"""
    while True:
        try:
            await send_notifications()
            rate_limiter.clear_old_entries()
        except Exception as e:
            logger.error(f"Ошибка в scheduled_notifications: {e}")
        except KeyboardInterrupt:
            break
        
        await asyncio.sleep(1800)  # Проверка каждые 30 минут

async def main():
    """Главная функция запуска бота"""
    logger.info("✨ Запуск бота Кофейный Дракон v6.0...")
    
    try:
        asyncio.create_task(scheduled_notifications())
        rate_limiter.clear_old_entries()
        
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())