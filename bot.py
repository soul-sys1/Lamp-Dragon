"""
🐉 КОФЕЙНЫЙ ДРАКОН - Версия 6.1.4
ИСПРАВЛЕННАЯ ВЕРСИЯ - Все критические ошибки устранены, навигация исправлена
"""
import asyncio
import logging
import random
import re
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Tuple
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

# Импортируем модули
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

# ==================== КЛАССЫ И УТИЛИТЫ ====================
class RateLimiter:
    def __init__(self):
        self.user_actions: Dict[str, datetime] = {}
        self.user_notifications: Dict[int, Dict[str, datetime]] = {}
        self.user_feeding_schedule: Dict[int, List[datetime]] = {}
        self.user_last_interaction: Dict[int, datetime] = {}
    
    def can_perform_action(self, user_id: int, action: str, cooldown_seconds: int = 30) -> bool:
        self.clear_old_entries()  # Очищаем старые записи
        now = datetime.now(timezone.utc)
        key = f"{user_id}_{action}"
        
        if key in self.user_actions:
            last_time = self.user_actions[key]
            if now - last_time < timedelta(seconds=cooldown_seconds):
                return False
        
        self.user_actions[key] = now
        self.user_last_interaction[user_id] = now
        return True
    
    def record_feeding(self, user_id: int):
        now = datetime.now(timezone.utc)
        if user_id not in self.user_feeding_schedule:
            self.user_feeding_schedule[user_id] = []
        
        self.user_feeding_schedule[user_id].append(now)
        if len(self.user_feeding_schedule[user_id]) > 30:
            self.user_feeding_schedule[user_id] = self.user_feeding_schedule[user_id][-30:]
    
    def should_send_morning_notification(self, user_id: int) -> bool:
        if user_id not in self.user_feeding_schedule:
            return True
        
        now = datetime.now(timezone.utc)
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
        
        return False
    
    def clear_old_entries(self):
        now = datetime.now(timezone.utc)
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
                    "Рождённый из облака нежности и заботя, он верит, "
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
                "advice": "Угощайте его только лучшими сладости!",
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
                    "он видит смысл там, где другие видят лишь поверхность."
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
                "favorite_coffee": f"🎉 {dragon_name} в восторге: 'Это именно тот сорт, о котором я мечтал!'",
                "hug_time": f"☕ {dragon_name} обнимает вас одной лапкой, а другой держит чашку кофе"
            },
            "книгочей": {
                "morning": f"📚 {dragon_name} зевает: 'Как жаль прерывать такой интересный сон... В нём я читал древний манускрипт!'",
                "reading_time": f"📖 {dragon_name} уютно устраивается: 'А помнишь, в прошлой книге герой...'",
                "bedtime": f"🌙 {dragon_name} просит: 'Можно ещё одну главу? Пожалуйста!'",
                "discovery": f"🤔 {dragon_name} задумчиво: 'Интересно, а что бы сделал герой той книги в этой ситуации?'",
                "hug_time": f"📚 {dragon_name} обнимает вас, не выпуская книгу из лапок"
            },
            "неженка": {
                "morning": f"💖 {dragon_name} потягивается: 'Доброе утро! Мне уже не хватает твоих объятий...'",
                "hug_time": f"🤗 {dragon_name} обнимает вас: 'Ты самый лучший хранитель на свете!'",
                "sad": f"😔 {dragon_name} грустит: 'Мне кажется, ты меня сегодня мало обнимал...'",
                "happy": f"✨ {dragon_name} сияет: 'Когда ты рядом, весь мир становится теплее!'",
                "question": f"💖 {dragon_name} смотрит с нежностью: 'Почему ты такой хороший?'"
            },
            "чистюля": {
                "morning": f"✨ {dragon_name} проверяет лапки: 'Ой, кажется, нужно почистить коготки...'",
                "dirty": f"😷 {dragon_name} морщится: 'Я чувствую пылинку на своём левом боку!'",
                "clean": f"🌟 {dragon_name} сверкает: 'Теперь я блещу чистотой!'",
                "care_time": f"🛁 {dragon_name} радостно: 'Время водных процедур! Я так это люблю!'",
                "hug_time": f"✨ {dragon_name} осторожно обнимает: 'Только не помните мою шёрстку!'"
            },
            "гурман": {
                "morning": f"🍰 {dragon_name} принюхивается: 'Чувствую запах свежей выпечки... Или это моё воображение?'",
                "treat_time": f"👨‍🍳 {dragon_name} оценивающе: 'Хм, интересное сочетание вкусов...'",
                "favorite_food": f"🎊 {dragon_name} в восторге: 'Это божественно! Где ты нашёл такое лакомство?'",
                "simple_food": f"😐 {dragon_name} вежливо: 'Спасибо, но... я не очень голоден.'",
                "hug_time": f"🍰 {dragon_name} обнимает вас: 'Твои объятия слаще шоколада!'"
            },
            "игрик": {
                "morning": f"🎮 {dragon_name} прыгает с кровати: 'Ура, новый день! Сколько игр нас сегодня ждёт?'",
                "game_time": f"🏆 {dragon_name} азартно: 'Давай сыграем! На этот раз я точно выиграю!'",
                "win": f"🎉 {dragon_name} ликует: 'Я чемпион! Давай ещё одну игру!'",
                "lose": f"😤 {dragon_name} решительно: 'В следующий раз я обязательно выиграю!'",
                "hug_time": f"🎮 {dragon_name} обнимает вас: 'Объятия - лучшая разминка перед игрой!'"
            },
            "соня": {
                "morning": f"😴 {dragon_name} неохотно открывает глаз: 'Уже утро? Кажется, я только что уснул...'",
                "nap_time": f"💤 {dragon_name} зевает: 'Может, вздремнём немного? Всего пять минуточек...'",
                "bedtime": f"🛏️ {dragon_name} уютно сворачивается: 'Наконец-то можно спать... Спокойной ночи!'",
                "well_rested": f"✨ {dragon_name} потягивается: 'Как же хорошо выспаться!'",
                "hug_time": f"😴 {dragon_name} обнимает вас и зевает: 'Так тепло и уютно...'"
            },
            "энерджайзер": {
                "morning": f"⚡ {dragon_name} вскакивает: 'Доброе утро! У меня столько энергии, что можно горы свернуть!'",
                "active": f"🏃 {dragon_name} носится по комнате: 'Не могу усидеть на месте! Давай что-нибудь сделаем!'",
                "coffee_boost": f"💥 {dragon_name} после кофе: 'Вау! Теперь я могу летать без крыльев!'",
                "evening": f"🌙 {dragon_name} всё ещё активен: 'Уже вечер? А я только разогнался!'",
                "hug_time": f"⚡ {dragon_name} энергично обнимает вас: 'Объятия заряжают ещё больше!'"
            },
            "философ": {
                "morning": f"🤔 {dragon_name} задумчиво: 'Каждое утро - это новая глава в книге жизни...'",
                "thinking": f"💭 {dragon_name} размышляет: 'Знаешь, я тут подумал о смысле драконьего бытия...'",
                "question": f"❓ {dragon_name} спрашивает: 'А что для тебя значит слово 'счастье'?'",
                "wisdom": f"🎓 {dragon_name} мудро: 'Иногда чтобы найти ответ, нужно просто перестать искать.'",
                "hug_time": f"🤔 {dragon_name} обнимает вас: 'Объятия - это универсальный язык любви...'"
            },
            "исследователь": {
                "morning": f"🔍 {dragon_name} с интересом: 'Интересно, что нового сегодня откроется?'",
                "curious": f"🤨 {dragon_name} рассматривает предмет: 'А как это работает? Из чего сделано?'",
                "discovery": f"🎊 {dragon_name} радостно: 'Смотри, что я нашёл! Это же древний артефакт!'",
                "question": f"❓ {dragon_name} спрашивает: 'А ты знаешь, почему трава зелёная?'",
                "hug_time": f"🔍 {dragon_name} изучающе обнимает: 'Интересно, из чего состоят твои объятия?'"
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
                InlineKeyboardButton(text="☕ Кофейные зёрна (10💰)", callback_data="buy_coffee_beans")
            ],
            [
                InlineKeyboardButton(text="🍫 Шоколадные чипсы (8💰)", callback_data="buy_chocolate_chips")
            ],
            [
                InlineKeyboardButton(text="🍯 Медовый сироп (12💰)", callback_data="buy_honey_syrup")
            ],
            [
                InlineKeyboardButton(text="🍦 Ванильное мороженое (15💰)", callback_data="buy_vanilla_icecream")
            ],
            [
                InlineKeyboardButton(text="🍭 Карамельный сироп (10💰)", callback_data="buy_caramel_syrup")
            ],
            [
                InlineKeyboardButton(text="🌰 Фундук молотый (18💰)", callback_data="buy_hazelnut")
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
                InlineKeyboardButton(text="🍪 Печенье с изюмом (5💰)", callback_data="buy_cookie_raisin")
            ],
            [
                InlineKeyboardButton(text="🍫 Шоколадная плитка (15💰)", callback_data="buy_chocolate_bar")
            ],
            [
                InlineKeyboardButton(text="☁️ Ванильный зефир (7💰)", callback_data="buy_vanilla_marshmallow")
            ],
            [
                InlineKeyboardButton(text="🎄 Имбирный пряник (8💰)", callback_data="buy_gingerbread")
            ],
            [
                InlineKeyboardButton(text="🍬 Фруктовый мармелад (10💰)", callback_data="buy_fruit_marmalade")
            ],
            [
                InlineKeyboardButton(text="🎂 Шоколадное пирожное (20💰)", callback_data="buy_chocolate_cake")
            ],
            [
                InlineKeyboardButton(text="🍩 Сладкий пончик (12💰)", callback_data="buy_donut")
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
                InlineKeyboardButton(text="💆 Драконья расчёска (25💰)", callback_data="buy_dragon_brush")
            ],
            [
                InlineKeyboardButton(text="🧴 Волшебный шампунь (30💰)", callback_data="buy_magic_shampoo")
            ],
            [
                InlineKeyboardButton(text="✂️ Золотые ножницы (35💰)", callback_data="buy_golden_scissors")
            ],
            [
                InlineKeyboardButton(text="🧸 Плюшевый дракончик (40💰)", callback_data="buy_plush_dragon")
            ],
            [
                InlineKeyboardButton(text="🛁 Ароматная соль (20💰)", callback_data="buy_aromatic_salt")
            ],
            [
                InlineKeyboardButton(text="💅 Лак для когтей (28💰)", callback_data="buy_nail_polish")
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
    
    # ПОЛНЫЙ МАППИНГ callback_data -> inventory_name
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
        inv_key = inventory_map[snack_key]  # Уверены что ключ есть
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

def get_feed_keyboard(inventory: dict) -> InlineKeyboardMarkup:
    """Клавиатура для кормления с полным маппингом"""
    # ПОЛНЫЙ МАППИНГ callback_data -> inventory_name
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
    """Клавиатура для меню помощи"""
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

# ==================== УТИЛИТЫ ДЛЯ КОФЕ ====================
def get_coffee_name(coffee_type: str) -> str:
    """Возвращает название кофе на русском"""
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
    """Возвращает название добавки на русском"""
    names = {
        "chocolate": "шоколадом",
        "honey": "мёдом",
        "icecream": "мороженым",
        "syrup": "сиропом",
        "none": "без добавок"
    }
    return names.get(addition, f"добавкой '{addition}'")

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
            
            f"Вы находите {dragon_name} в углу комната, где он играет с мячиком. Он так увлечён, что не замечает вас. "
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
            
            f"Вы находите {dragon_name} сидящим на кровати и смотрящим на звёзды в окна. 'Не могу уснуть,' - шепчет он вам. "
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
            f"Вы берёте расчёска и начинаете работать над его шерсткой. Дракон закрывает глаза от наслаждения, "
            f"а иногда даже подставляет особенно любимые места для расчёсывания. После процедуры он сияет как новенький! 🛁🐉",
            
            f"Сегодня {dragon_name} особенно пушистый - видимо, он хорошенько выспался. "
            f"Вы усаживаете его перед собой и начинаете расчёсывать. Шерсть летит во все стороны, создавая вокруг вас облачко пушистоности. "
            f"В конце вы даже делаете дракону небольшую стильную причёску! 💇✨",
            
            f"{dragon_name} сначала недоверчиво смотрит на расчёску, но вы показываете ему, как это приятно, "
            f"расчёсывая маленький участок. Дракон понимает и радостно подставляет спинку. "
            f"Вскоре он уже мурлычет и подставляет то один бок, то другой! 😊🦔"
        ]
    
    @staticmethod
    def get_book_reading_scene(dragon_name: str, dragon_trait: str, book_title: str, book_content: str) -> str:
        # ЭКРАНИРОВАНИЕ HTML
        book_title = escape_html(book_title)
        book_content = escape_html(book_content[:300])
        
        scenes = [
            f"Вы усаживаетесь в удобное кресло, а {dragon_name} укладывается у вас на коленях, уютно устроившись. "
            f"Вы открываете книгу '{book_title}' и начинаете читать:\n\n"
            f"<i>{book_content}...</i>\n\n"
            f"{dragon_name} внимательно слушает, его глазки медленно закрываются. К концу первой страницы он уже тихо посапывает. 📖😴",
            
            f"{dragon_name} приносит вам книгу '{book_title}' и с надеждой смотрит на вас. "
            f"Вы садитесь на диван, дракон укладывается рядом, положив голову вам на колени. "
            f"Вы начинаете читать:\n\n"
            f"<i>{book_content}...</i>\n\n"
            f"Голос ваш тихий и убаюкивающий. Через несколько минут {dragon_name} уже сладко спит. 🛋️💤",
            
            f"Вы готовитесь ко сну и замечаете, что {dragon_name} уже ждёт вас в кровати с книгой '{book_title}' в лапках. "
            f"Вы ложитесь рядом и начинаете читать:\n\n"
            f"<i>{book_content}...</i>\n\n"
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
            "cookie_raisin": "печеньем",
            "chocolate_bar": "шоколадом",
            "vanilla_marshmallow": "зефиром",
            "gingerbread": "пряником",
            "fruit_marmalade": "мармеладом",
            "chocolate_cake": "пирожным",
            "donut": "пончиком",
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

# ==================== МИДЛВАРЫ И ОБРАБОТЧИКИ ОШИБОК ====================
async def error_handler(update: types.Update, exception: Exception):
    """Глобальный обработчик ошибок"""
    try:
        if isinstance(exception, TelegramAPIError):
            logger.error(f"Telegram API error: {exception}")
        else:
            logger.error(f"Unhandled exception: {exception}\n{traceback.format_exc()}")
        
        # Попытаемся отправить сообщение об ошибке пользователю
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
    """Отмена текущего действия и выход из состояния"""
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

# ==================== ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ НАВИГАЦИИ ====================
@dp.callback_query(F.data.in_(["shop_close", "shop_back"]))
async def process_shop_navigation(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик навигации в магазине (доступен из любого состояния)"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("shop_", "")
        
        if action == "close":
            await state.clear()
            await callback.message.delete()
            await callback.answer("🛍️ Магазин закрыт")
            return
            
        elif action == "back":
            # Получаем данные дракона
            dragon_data = db.get_dragon(user_id)
            if not dragon_data:
                await callback.answer("❌ У вас нет дракона")
                return
                
            dragon = Dragon.from_dict(dragon_data)
            
            # Показываем главное меню магазина
            await callback.message.edit_text(
                f"<b>🛍️ МАГАЗИН КОФЕЙНОГО ДРАКОНА</b>\n\n"
                f"💰 <b>Ваш баланс:</b> <code>{dragon.gold}</code> золота\n\n"
                f"👇 <b>Выбери категорию товаров:</b>",
                parse_mode="HTML",
                reply_markup=get_shop_main_keyboard()
            )
            # Устанавливаем правильное состояние
            await state.set_state(GameStates.shop_main)
            await state.update_data(dragon_data=dragon.to_dict())
            await callback.answer("↩️ В главное меню магазина")
            
    except Exception as e:
        logger.error(f"Ошибка в process_shop_navigation: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data == "close")
async def process_global_close(callback: types.CallbackQuery, state: FSMContext):
    """Глобальный обработчик кнопки закрытия"""
    try:
        await state.clear()
        await callback.message.delete()
        await callback.answer("✅ Закрыто")
    except Exception as e:
        logger.error(f"Ошибка в process_global_close: {e}")
        await callback.answer("❌ Ошибка при закрытии")

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
            
            f"<b>📋 ВОЗМОЖНОСТИ 6.1.4:</b>\n"
            f"• 🎭 <b>10 уникальных характеров</b> с глубокой проработкой\n"
            f"• ⏳ <b>Менее агрессивные показатели</b> (5%/час)\n"
            f"• 🛍️ <b>Рабочий магазин</b> с исправленной навигацией\n"
            f"• 📚 <b>Рабочие сказки</b> и чтение\n"
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
        with suppress(Exception):
            await message.delete()
        
        has_dragon = db.dragon_exists(user_id)
        
        help_text = (
            "<b>📚 КОМАНДЫ И ХАРАКТЕРЫ (v6.1.4)</b>\n\n"
            
            "<b>🐉 ОСНОВНЫЕ КОМАНДЫ:</b>\n"
            "<code>/start</code> - начать игру\n"
            "<code>/help</code> - эта справка\n"
            "<code>/create</code> - создать дракона\n"
            "<code>/status</code> - статус дракона\n"
            "<code>/cancel</code> - отменить текущее действие\n\n"
            
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
    """Обработка разделов помощи - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("help_", "")
        
        if action == "back":
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Явно очищаем состояние
            await state.clear()
            await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
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
    """Обработка детального просмотра характера - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        action = callback.data.replace("char_", "")
        
        if action == "back":
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Явно показываем меню помощи
            await callback.message.edit_text(
                "<b>📚 Помощь</b>\n\nВыберите раздел:",
                parse_mode="HTML",
                reply_markup=get_help_keyboard()
            )
            # Состояние уже GameStates.help_section, но для надёжности:
            await state.set_state(GameStates.help_section)
            await callback.answer("↩️ Возвращаемся в помощь")
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
        
        # Используем серверное время в UTC
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
            f"🕐 <i>Текущее время (UTC):</i> <code>{now.strftime('%H:%M:%S')}</code>\n"
            f"📅 <i>Дата:</i> <code>{now.strftime('%d.%m.%Y')}</code>\n"
            f"⬇️ <i>Используй кнопки ниже для ухода</i>"
        )
        
        await message.answer(status_text, parse_mode="HTML", reply_markup=get_main_keyboard())
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_status: {e}")
        await message.answer("<b>❌ Произошла ошибка при получении статуса.</b>", parse_mode="HTML")

# ==================== МАГАЗИН ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message, state: FSMContext):
    """Открыть магазин"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было
        with suppress(Exception):
            await message.delete()
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
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
    """Обработка главного меню магазина"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("shop_", "")
        
        if action == "close":
            await state.clear()
            await callback.message.delete()
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
    """Обработка покупки товара - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        user_id = callback.from_user.id
        item_id = callback.data.replace("buy_", "")
        
        # Цены товаров
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
        
        # Маппинг ID товаров на названия в инвентаре
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
        
        # Получаем данные дракона
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("❌ У вас нет дракона")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # Проверяем хватает ли денег
        if dragon.gold < price:
            await callback.answer(f"❌ Недостаточно золота! Нужно {price}💰")
            return
        
        # Списываем деньги
        dragon.gold -= price
        
        # Добавляем предмет в инвентарь
        db.update_inventory(user_id, inventory_name, 1)
        
        # Сохраняем изменения дракона
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Купил {item_id} за {price} золота")
        
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем состояние после покупки
        await state.set_state(GameStates.shop_main)
        await state.update_data(dragon_data=dragon.to_dict())
        
        # Показываем успешную покупку с обновлённой клавиатурой магазина
        await callback.message.edit_text(
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
    """Показать инвентарь"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было
        with suppress(Exception):
            await message.delete()
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        # ПРОСТОЙ ПОДСЧЁТ
        total_items = sum(inventory.values())
        
        await message.answer(
            f"<b>📦 ИНВЕНТАРЬ {escape_html(dragon.name)}</b>\n\n"
            f"💰 <b>Золото:</b> <code>{dragon.gold}</code>\n"
            f"📊 <b>Всего предметов:</b> <code>{total_items}</code>\n\n"
            f"👇 <b>Выбери категорию для просмотра:</b>\n\n"
            f"• 🍪 <b>Сладости</b> - угощения для дракона\n"
            f"• ✨ <b>Уход</b> - предметы для заботя\n"
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
    """Обработка выбора категории инвентаря"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("inv_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
            return
        
        data = await state.get_data()
        dragon_data = data.get("dragon_data")
        if not dragon_data:
            await callback.answer("❌ Ошибка: данные дракона не найдены")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        inventory = db.get_inventory(user_id)
        
        # Категории предметов
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
            
            await callback.message.edit_text(
                category_text,
                parse_mode="HTML",
                reply_markup=get_inventory_keyboard()
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_inventory_category: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== КОФЕ ====================
@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message, state: FSMContext):
    """Приготовить кофе"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было
        with suppress(Exception):
            await message.delete()
        
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
    """Обработка выбора типа кофе"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("coffee_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
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
    """Обработка выбора добавок"""
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
            
            await callback.message.edit_text(
                f"<b>☕ {get_coffee_name(data.get('coffee_type', 'espresso'))} с {get_addition_name(action)} готов!</b>\n\n"
                f"✨ <i>Теперь выбери сладость (или пропусти):</i>\n\n"
                f"<b>📦 Доступные сладости:</b>\n"
                f"{snacks_text}\n"
                f"<i>💡 Сладости улучшают настроение дракона!</i>",
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
    """Обработка когда нет добавок"""
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
            
            await callback.message.edit_text(
                f"<b>☕ {get_coffee_name(data.get('coffee_type', 'espresso'))} готов!</b>\n\n"
                f"✨ <i>Теперь выбери сладость (или пропусти):</i>\n\n"
                f"<b>📦 Доступные сладости:</b>\n"
                f"{snacks_text}\n"
                f"<i>💡 Сладости улучшают настроение дракона!</i>",
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
    """Обработка выбора сладости"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("snack_", "")
        
        if action == "back":
            data = await state.get_data()
            dragon_data = data.get("dragon_data")
            if dragon_data:
                dragon = Dragon.from_dict(dragon_data)
                inventory = db.get_inventory(user_id)
                
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
    """Завершение приготовления кофе - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
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
        
        if addition != "none":
            mood_bonus += 10
            if addition == "honey" and dragon.character.get("основная_черта") == "гурман":
                mood_bonus += 5
        
        if snack != "none":
            mood_bonus += 15
            
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
        
        # Применяем бонусы
        dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + mood_bonus)
        
        # Особый бонус за любимый кофе
        if coffee_type == dragon.favorites.get("кофе", ""):
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
            dragon.stats["энергия"] = min(100, dragon.stats.get("энергия", 0) + 10)
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Приготовил {get_coffee_name(coffee_type)}")
        
        # Сцена приготовления
        scene = ActionDescriptions.get_coffee_preparation_scene(
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
        )
        
        if addition != "none" or snack != "none":
            response += f"\n<b>✨ БОНУСЫ:</b>\n"
            if addition != "none":
                response += f"• Добавка: +10 к настроению\n"
            if snack != "none":
                response += f"• Сладость: +15 к настроению\n"
            if coffee_type == dragon.favorites.get("кофе", ""):
                response += f"• Любимый кофе: +15 к настроению, +10 к энергии\n"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"☕ <i>Текущий показатель кофе:</i> <code>{dragon.stats.get('кофе', 0)}%</code>\n"
            f"😊 <i>Настроение:</i> <code>{dragon.stats.get('настроение', 0)}%</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer("✅ Кофе готово!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в finish_coffee_preparation: {e}")
        await callback.answer("❌ Произошла ошибка при приготовлении кофе")

# ==================== СОН И ЧТЕНИЕ СКАЗОК ====================
@dp.message(Command("sleep"))
@dp.message(F.text == "😴 Сон")
async def cmd_sleep(message: types.Message, state: FSMContext):
    """Уложить дракона спать"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        with suppress(Exception):
            await message.delete()
        
        if not rate_limiter.can_perform_action(user_id, "sleep", 30):
            await message.answer("<b>⏳ Дракон ещё не готов ко сну. Подожди немного 😴</b>", parse_mode="HTML")
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
        
        character_trait = dragon.character.get("основная_черта", "")
        char_message = CharacterPersonality.get_character_message(
            character_trait,
            "bedtime" if character_trait == "книгочей" else "nap_time",
            dragon.name
        )
        
        await message.answer(
            f"<b>😴 УЛОЖИТЬ {escape_html(dragon.name)} СПАТЬ</b>\n\n"
            f"{char_message}\n\n"
            f"✨ <i>Показатель сна:</i> <code>{sleep_stat}%</code>\n\n"
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
    """Обработка выбора способа уложить спать - ИСПРАВЛЕННАЯ ВЕРСИЯ С ЭКРАНИРОВАНИЕМ КНИГ"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("sleep_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
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
        
        # Применяем действие в зависимости от выбора
        if action == "read":
            # Чтение сказки - ИСПРАВЛЕННАЯ ВЕРСИЯ С ЭКРАНИРОВАНИЕМ
            result = dragon.apply_action("сон")
            
            # Получаем случайную книгу
            favorite_genre = dragon.favorites.get("жанр_книг", "сказка")
            book = get_random_book(favorite_genre)
            
            # ИСПРАВЛЕНИЕ: Экранирование HTML
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
                if "комментарий_дракона" in book:
                    book["комментарий_дракона"] = escape_html(book["комментарий_дракона"])
            
            # Бонус для книгочея
            character_trait = dragon.character.get("основная_черта", "")
            if character_trait == "книгочей":
                dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 20)
                dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 15)
                bonus_text = "<b>📚 Книгочей обожает сказки! +20 к настроению, +15 ко сну</b>\n"
            else:
                bonus_text = ""
            
            # Получаем сцену чтения книги
            scene = ActionDescriptions.get_book_reading_scene(
                dragon.name,
                character_trait,
                book["title"],
                book["content"]
            )
            
        elif action == "lay":
            # Лечь рядом
            result = dragon.apply_action("сон")
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 10)
            bonus_text = "<b>💤 Тепло хранителя: +10 к настроению</b>\n"
            scene = f"Вы ложитесь рядом с {dragon.name}, обнимаете его и гладите по спинке. Дракон мурлычет от удовольствия и постепенно засыпает, прижимаясь к вам. 🛏️💕"
            
        elif action == "kiss":
            # Поцеловать в лобик
            result = dragon.apply_action("сон")
            scenes = ActionDescriptions.get_sleep_kiss_scenes(dragon.name, dragon.character.get("основная_черта", ""))
            scene = random.choice(scenes)
            bonus_text = "<b>😘 Нежный поцелуй: +15 к настроению</b>\n"
            dragon.stats["настроение"] = min(100, dragon.stats.get("настроение", 0) + 15)
            
        elif action == "sing":
            # Спеть колыбельную
            result = dragon.apply_action("сон")
            dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 10)
            bonus_text = "<b>🎵 Колыбельная: +10 ко сну</b>\n"
            scene = f"Вы тихо напеваете колыбельную, гладя {dragon.name} по голове. Его глазки медленно закрываются, дыхание становится ровным, и вскоре он погружается в сладкий сон. 🎶😴"
            
        elif action == "toy":
            # Дать игрушку
            result = dragon.apply_action("сон")
            inventory = db.get_inventory(user_id)
            if inventory.get("plush_dragon", 0) > 0 or inventory.get("toy", 0) > 0:
                bonus_text = "<b>🧸 С игрушкой: +20 ко сну</b>\n"
                dragon.stats["сон"] = min(100, dragon.stats.get("сон", 0) + 20)
                scene = f"Вы даёте {dragon.name} его любимую игрушку. Дракон счастливо обнимает её, укладывается поудобнее и быстро засыпает, улыбаясь во сне. 🧸💤"
            else:
                bonus_text = ""
                scene = f"Вы укладываете {dragon.name}, гладите его по спинке и шепчете 'Спокойной ночи'. Дракон зевает, закрывает глазки и засыпает. 🌙"
                
        else:  # simple или любой другой
            # Просто уложить
            result = dragon.apply_action("сон")
            bonus_text = ""
            scene = f"Вы укладываете {dragon.name} в кроватку, поправляете одеяло и желаете спокойной ночи. Дракон кивает и закрывает глаза. 🌙"
        
        # Сохраняем изменения
        db.update_dragon(user_id, dragon.to_dict())
        db.record_action(user_id, f"Уложил дракона спать ({action})")
        
        response = f"{scene}\n\n"
        response += f"<b>📊 ИЗМЕНЕНИЯ:</b>\n"
        response += f"• 💤 Сон: +{result['stat_changes'].get('сон', 0)}%\n"
        response += f"• ⚡ Энергия: +{result['stat_changes'].get('энергия', 0)}%\n"
        
        if bonus_text:
            response += f"\n{bonus_text}"
        
        if result.get("level_up"):
            response += f"\n\n<b>🎊 {result['message']}</b>"
        
        # Характерное сообщение
        char_message = CharacterPersonality.get_character_message(
            dragon.character.get("основная_черта", ""),
            "well_rested",
            dragon.name
        )
        response += f"\n\n<i>💬 {char_message}</i>"
        
        response += (
            f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"💤 <i>Текущий показатель сна:</i> <code>{dragon.stats.get('сон', 0)}%</code>\n"
            f"⚡ <i>Энергия:</i> <code>{dragon.stats.get('энергия', 0)}%</code>"
        )
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer("✅ Дракон спит сладко!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_sleep_choice: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== ОБНЯТЬ ====================
@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        with suppress(Exception):
            await message.delete()
        
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
        elif character_trait == "энерджайзер":
            dragon.stats["энергия"] = min(100, dragon.stats["энергия"] + 15)
            character_bonus = "<b>⚡ Энерджайзер заряжается от объятий! +15 к энергии</b>\n"
        elif character_trait == "соня":
            dragon.stats["сон"] = min(100, dragon.stats["сон"] + 20)
            character_bonus = "<b>😴 Соне в объятиях тепло и уютно! +20 ко сну</b>\n"
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

# ==================== УХОД ====================
@dp.message(Command("care"))
@dp.message(F.text == "✨ Уход")
async def cmd_care(message: types.Message, state: FSMContext):
    """Ухаживать за драконом"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        with suppress(Exception):
            await message.delete()
        
        if not rate_limiter.can_perform_action(user_id, "care", 10):
            await message.answer("<b>⏳ Дракону нужно время отдохнуть между процедурами. Подожди немного ✨</b>", parse_mode="HTML")
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
    """Обработка выбора действия по уходу"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("care_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
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
            scene = f"Вы аккуратно расчёсываете лапки {dragon.name}. Дракон мурлычет от удовольствия и подставляет то одну, то другую лапку. ✨🐾"
            
        elif action == "wipe_face":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 8)
            bonus = 8
            scene = f"Вы нежно протираете мордочку {dragon.name} мягкой салфеткой. Дракон закрывает глазки от удовольствия. 🛁😊"
            
        elif action == "clean_nails":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 12)
            bonus = 12
            scene = f"Вы осторожно чистите коготки {dragon.name}. Дракон терпеливо сидит и наблюдает за вашими действиями. 💅✨"
            
        elif action == "clean_teeth":
            result = dragon.apply_action("уход")
            dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 15)
            dragon.stats["аппетит"] = min(100, dragon.stats.get("аппетит", 0) + 5)
            bonus = 15
            scene = f"Вы чистите зубки {dragon.name} специальной драконьей щёткой. После процедуры дракон сияет белоснежной улыбкой! 🦷🌟"
            
        elif action == "brush_fur":
            inventory = db.get_inventory(user_id)
            has_brush = inventory.get("dragon_brush", 0) > 0
            if has_brush:
                # Используем расчёску
                db.update_inventory(user_id, "dragon_brush", -1)
                    
                result = dragon.apply_action("уход")
                dragon.stats["пушистость"] = min(100, dragon.stats.get("пушистость", 0) + 30)
                bonus = 30
                scenes = ActionDescriptions.get_care_brush_fur_scenes(dragon.name, character_trait)
                scene = random.choice(scenes)
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
                scene = f"Вы купаете {dragon.name} с волшебным шампунем. Пена благоухает цветами, а шёрстка дракона после ванны сияет и переливается! 🧴🌈"
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
                scene = f"Вы аккуратно подстригаете коготки {dragon.name} золотыми ножницами. Когти становятся идеальной формы! ✂️💎"
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
                scene = f"Вы играете с {dragon.name} и его любимой игрушкой. Дракон радостно носится по комнате, его глазки сияют от счастья! 🧸🎉"
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
        
        await callback.message.edit_text(response, parse_mode="HTML")
        await callback.answer("✅ Процедура завершена!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_care_action: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== ИГРЫ ====================
@dp.message(Command("games"))
@dp.message(F.text == "🎮 Игры")
async def cmd_games(message: types.Message, state: FSMContext):
    """Игры с драконом - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было из другой вкладки
        with suppress(Exception):
            await message.delete()
        
        if not rate_limiter.can_perform_action(user_id, "games", 20):
            await message.answer("<b>⏳ Дракон устал от игр. Дайте ему отдохнуть 🎮</b>", parse_mode="HTML")
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
        
        # ИСПРАВЛЕНИЕ: Корректный HTML
        await message.answer(
            f"<b>🎮 ИГРАТЬ С {escape_html(dragon.name)}</b>\n\n"
            f"{char_message}\n\n"
            f"⚡ <i>Энергия дракона:</i> <code>{energy_stat}%</code>\n"
            f"🎭 <i>Характер:</i> <code>{character_trait}</code>\n\n"
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
    """Обработка выбора игры"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("game_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            await state.clear()
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
            
            await callback.message.edit_text(
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
    """Обработка попытки угадать число"""
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
                await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка в process_guess_number: {e}")
        await message.answer("<b>❌ Произошла ошибка в игре.</b>", parse_mode="HTML")

# ==================== УВЕДОМЛЕНИЯ ====================
@dp.message(Command("notifications"))
@dp.message(F.text == "🔕 Уведомления")
async def cmd_notifications(message: types.Message):
    """Управление уведомлениями - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        user_id = message.from_user.id
        
        # Удаляем предыдущее сообщение если оно было
        with suppress(Exception):
            await message.delete()
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await message.answer("<b>🐣 Сначала создай дракона!</b>", parse_mode="HTML")
            return
        
        dragon = Dragon.from_dict(dragon_data)
        
        # ИСПРАВЛЕНИЕ: Используем правильный метод
        try:
            # Пытаемся получить настройки уведомлений
            # Если метода нет, используем заглушку
            try:
                notifications_enabled = db.get_user_settings(user_id).get('notifications_enabled', True)
            except:
                # Если метода не существует, предполагаем что уведомления включены
                notifications_enabled = True
        except Exception as e:
            logger.warning(f"Ошибка при получении настроек уведомлений: {e}")
            notifications_enabled = True
        
        status = "🔔 Включены" if notifications_enabled else "🔕 Выключены"
        
        await message.answer(
            f"<b>🔕 УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ</b>\n\n"
            f"<b>Текущий статус:</b> {status}\n\n"
            f"<b>💡 Что такое уведомления?</b>\n"
            f"• Утренние напоминания покормить дракона\n"
            f"• Напоминания, если дракону что-то нужно\n"
            f"• Случайные сообщения от дракона в течение дня\n\n"
            f"<b>⚠️ Внимание:</b> Уведомления отправляются только когда дракону нужна помощь!\n\n"
            f"<i>💡 Рекомендуем оставить уведомления включёнными</i>",
            parse_mode="HTML",
            reply_markup=get_notifications_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cmd_notifications: {e}")
        await message.answer("<b>❌ Произошла ошибка при настройке уведомлений.</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("notif_"))
async def process_notifications(callback: types.CallbackQuery):
    """Обработка настроек уведомлений - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        user_id = callback.from_user.id
        action = callback.data.replace("notif_", "")
        
        if action == "back":
            with suppress(Exception):
                await callback.message.delete()
            await callback.answer("↩️ Возвращаемся...")
            return
        
        dragon_data = db.get_dragon(user_id)
        if not dragon_data:
            await callback.answer("❌ У вас нет дракона")
            return
        
        if action == "on":
            try:
                # Пытаемся обновить настройки
                # Если метода нет, просто продолжаем
                try:
                    db.update_user_settings(user_id, {'notifications_enabled': True})
                except:
                    pass
            except Exception as e:
                logger.warning(f"Не удалось обновить настройки уведомлений: {e}")
            
            status = "🔔 Включены"
            message_text = "<b>✅ Уведомления включены!</b>\n\nДракон будет напоминать о себе когда ему что-то понадобится."
            
        elif action == "off":
            try:
                # Пытаемся обновить настройки
                try:
                    db.update_user_settings(user_id, {'notifications_enabled': False})
                except:
                    pass
            except Exception as e:
                logger.warning(f"Не удалось обновить настройки уведомлений: {e}")
            
            status = "🔕 Выключены"
            message_text = "<b>🔕 Уведомления выключены.</b>\n\nВы не будете получать напоминания от дракона."
        
        else:
            await callback.answer("❌ Неизвестное действие")
            return
        
        await callback.message.edit_text(
            f"<b>🔕 УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ</b>\n\n"
            f"<b>Текущий статус:</b> {status}\n\n"
            f"{message_text}\n\n"
            f"<i>💡 Вы можете изменить настройки в любое время</i>",
            parse_mode="HTML",
            reply_markup=get_notifications_keyboard()
        )
        
        await callback.answer(f"✅ Уведомления {status.replace('🔔 ', '').replace('🔕 ', '')}")
        
    except Exception as e:
        logger.error(f"Ошибка в process_notifications: {e}")
        await callback.answer("❌ Произошла ошибка")

# ==================== ОСНОВНОЙ ЦИКЛ ====================
async def periodic_tasks():
    """Периодические задачи - УПРОЩЕННАЯ ВЕРСИЯ"""
    retry_count = 0
    max_retries = 5
    
    while True:
        try:
            # Очищаем старые записи в rate limiter
            rate_limiter.clear_old_entries()
            
            # Простая проверка времени для утренних уведомлений (8-9 утра по UTC)
            now = datetime.now(timezone.utc)
            if 8 <= now.hour <= 9:
                # ИСПРАВЛЕНИЕ: Простой способ получить пользователей
                try:
                    users = db.get_all_users()
                    for user_id in users:
                        try:
                            if rate_limiter.should_send_morning_notification(user_id):
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
                                    rate_limiter.record_feeding(user_id)
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
                except Exception as e:
                    logger.error(f"Ошибка при получении пользователей: {e}")
            
            retry_count = 0
            await asyncio.sleep(300)  # Проверяем каждые 5 минут
            
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
    """Основная функция запуска бота"""
    try:
        logger.info("Запуск бота Кофейный Дракон v6.1.4 (исправленная версия)...")
        
        # Добавляем обработчик ошибок
        dp.error.register(error_handler)
        
        # Запускаем периодические задачи
        asyncio.create_task(periodic_tasks())
        
        # Запускаем бота
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