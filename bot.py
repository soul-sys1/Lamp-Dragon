"""
ГЛАВНЫЙ ФАЙЛ БОТА
Обрабатывает все команды и сообщения
"""
import asyncio
import logging
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage

# Наши модули
import config
from database import db
from dragon_model import Dragon
from books import get_random_book, get_all_genres

# Настройка логирования
logging.basicConfig(level=logging.INFO)
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

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐉 Статус"), KeyboardButton(text="☕ Кофе")],
            [KeyboardButton(text="🍪 Покормить"), KeyboardButton(text="🤗 Обнять")],
            [KeyboardButton(text="📚 Читать"), KeyboardButton(text="🎮 Играть")],
            [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="📦 Инвентарь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие..."
    )
    return keyboard

def get_shop_keyboard():
    """Клавиатура магазина"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☕ Зерна (10 золота)", callback_data="shop_coffee")],
            [InlineKeyboardButton(text="🍪 Печенье (5 золота)", callback_data="shop_cookie")],
            [InlineKeyboardButton(text="🍫 Шоколад (15 золота)", callback_data="shop_chocolate")],
            [InlineKeyboardButton(text="🎲 Игральная кость (20 золота)", callback_data="shop_dice")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="shop_close")]
        ]
    )
    return keyboard

def get_reading_keyboard():
    """Клавиатура для чтения"""
    genres = get_all_genres()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Добавляем кнопки по 2 в ряд
    row = []
    for genre in genres:
        row.append(InlineKeyboardButton(text=genre.capitalize(), callback_data=f"read_{genre}"))
        if len(row) == 2:
            keyboard.inline_keyboard.append(row)
            row = []
    
    if row:  # Если осталась неполная строка
        keyboard.inline_keyboard.append(row)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🎲 Случайная книга", callback_data="read_random"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="read_cancel")
    ])
    
    return keyboard

def get_coffee_keyboard():
    """Клавиатура для приготовления кофе"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Эспрессо", callback_data="coffee_espresso"),
                InlineKeyboardButton(text="Латте", callback_data="coffee_latte")
            ],
            [
                InlineKeyboardButton(text="Капучино", callback_data="coffee_cappuccino"),
                InlineKeyboardButton(text="Раф", callback_data="coffee_raf")
            ],
            [
                InlineKeyboardButton(text="Американо", callback_data="coffee_americano"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="coffee_cancel")
            ]
        ]
    )
    return keyboard

# ==================== КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - начало работы с ботом"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Создаем пользователя в базе
    db.create_user(user_id, username)
    
    welcome_text = (
        "🐉 **Приветствуем в мире Кофейных Драконов!**\n\n"
        "Ты стал хранителем последнего яйца кофейного дракона. "
        "Эти редкие существа питаются кофе, обожают книги и игры, "
        "и становятся верными друзьями на всю жизнь.\n\n"
        "📋 **Что делать:**\n"
        "1. Создай своего дракона командой /create\n"
        "2. Ухаживай за ним каждый день\n"
        "3. Развивай его навыки и характер\n"
        "4. Стань лучшим хранителем!\n\n"
        "Используй кнопки ниже или команды:\n"
        "/help - список всех команд\n"
        "/create - создать дракона"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help - помощь"""
    help_text = (
        "📖 **ДОСТУПНЫЕ КОМАНДЫ:**\n\n"
        "🐉 **Основные:**\n"
        "/start - начать работу\n"
        "/help - эта справка\n"
        "/create - создать дракона\n"
        "/status - статус дракона\n\n"
        
        "☕ **Уход:**\n"
        "/coffee - приготовить кофе\n"
        "/feed - покормить сладостями\n"
        "/hug - обнять дракона\n"
        "/clean - почистить/расчесать\n\n"
        
        "🎮 **Развлечения:**\n"
        "/read - почитать книгу\n"
        "/play - поиграть в игру\n"
        "/craft - заняться рукоделием\n\n"
        
        "🛍️ **Экономика:**\n"
        "/shop - магазин\n"
        "/inventory - инвентарь\n"
        "/gold - проверить золото\n\n"
        
        "⚙️ **Настройки:**\n"
        "/rename - переименовать дракона\n"
        "/stats - подробная статистика\n"
        "/achievements - достижения\n\n"
        
        "💡 **Совет:** Используй кнопки внизу экрана для быстрого доступа!"
    )
    
    await message.answer(help_text, reply_markup=get_main_keyboard())

@dp.message(Command("create"))
async def cmd_create(message: types.Message, state: FSMContext):
    """Команда /create - создать дракона"""
    user_id = message.from_user.id
    
    # Проверяем, есть ли уже дракон
    if db.dragon_exists(user_id):
        await message.answer(
            "У тебя уже есть дракон! 🐉\n"
            "Используй /status чтобы посмотреть на него.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Просим ввести имя
    await message.answer(
        "🎉 Отлично! Давай создадим твоего дракона!\n"
        "Как ты хочешь назвать своего кофейного дракончика?\n\n"
        "Просто отправь мне имя:"
    )
    
    await state.set_state(GameStates.waiting_for_name)

@dp.message(GameStates.waiting_for_name)
async def process_dragon_name(message: types.Message, state: FSMContext):
    """Обработка ввода имени дракона"""
    user_id = message.from_user.id
    dragon_name = message.text.strip()
    
    # Проверяем имя
    if len(dragon_name) < 2:
        await message.answer("Имя должно быть хотя бы 2 символа. Попробуй еще:")
        return
    
    if len(dragon_name) > 20:
        await message.answer("Имя слишком длинное. Максимум 20 символов. Попробуй еще:")
        return
    
    # Создаем дракона
    dragon = Dragon(name=dragon_name)
    dragon_data = dragon.to_dict()
    
    # Сохраняем в базу
    db.create_dragon(user_id, dragon_data)
    
    # Получаем характер для приветствия
    character = dragon.character["основная_черта"]
    character_descriptions = {
        "кофеман": "Обожает кофе больше всего на свете!",
        "соня": "Любит поспать и вздремнуть после кофе.",
        "игрик": "Обожает игры и соревнования.",
        "книгочей": "Проводит дни за чтением книг.",
        "неженка": "Требует много ласки и внимания.",
        "гурман": "Разбирается в кофе и сладостях.",
        "чистюля": "Следит за своей чистотой.",
        "лентяй": "Не любит лишнюю активность.",
        "энерджайзер": "Всегда полон энергии!",
        "философ": "Любит размышлять о жизни."
    }
    
    await message.answer(
        f"🎉 **Поздравляем!**\n\n"
        f"Ты создал дракона по имени **{dragon_name}**!\n"
        f"🎭 **Характер:** {character}\n"
        f"{character_descriptions.get(character, '')}\n\n"
        f"❤ **Любимое:**\n"
        f"• Кофе: {dragon.favorites['кофе']}\n"
        f"• Сладость: {dragon.favorites['сладость']}\n"
        f"• Книги: {dragon.favorites['жанр_книг']}\n\n"
        f"Теперь используй кнопки ниже, чтобы ухаживать за драконом!\n"
        f"Начни с того, что приготовь ему кофе ☕",
        reply_markup=get_main_keyboard()
    )
    
    await state.clear()

# ==================== ОСНОВНЫЕ ДЕЙСТВИЯ ====================
@dp.message(Command("status"))
@dp.message(F.text == "🐉 Статус")
async def cmd_status(message: types.Message):
    """Показать статус дракона"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer(
            "У тебя еще нет дракона! 🥺\n"
            "Создай его командой /create",
            reply_markup=get_main_keyboard()
        )
        return
    
    dragon = Dragon.from_dict(dragon_data)
    status_text = dragon.get_status_text()
    
    await message.answer(status_text, reply_markup=get_main_keyboard())

@dp.message(Command("coffee"))
@dp.message(F.text == "☕ Кофе")
async def cmd_coffee(message: types.Message):
    """Приготовить кофе"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Проверяем инвентарь
    inventory = db.get_inventory(user_id)
    if inventory.get("кофейные_зерна", 0) <= 0:
        await message.answer(
            "У тебя нет кофейных зерен! 😔\n"
            "Купи их в магазине /shop",
            reply_markup=get_main_keyboard()
        )
        return
    
    await message.answer(
        "☕ **Выбери тип кофе:**\n\n"
        "• **Эспрессо** - бодрящий, крепкий\n"
        "• **Латте** - нежный, с молоком\n"
        "• **Капучино** - с воздушной пенкой\n"
        "• **Раф** - сливочный, сладкий\n"
        "• **Американо** - классический",
        reply_markup=get_coffee_keyboard()
    )

@dp.callback_query(F.data.startswith("coffee_"))
async def process_coffee_choice(callback: types.CallbackQuery):
    """Обработка выбора кофе"""
    user_id = callback.from_user.id
    coffee_type = callback.data.replace("coffee_", "")
    
    if coffee_type == "cancel":
        await callback.message.edit_text("Приготовление кофе отменено ☕")
        await callback.answer()
        return
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await callback.answer("Дракон не найден!")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Используем зерна
    db.update_inventory(user_id, "кофейные_зерна", -1)
    
    # Применяем действие
    result = dragon.apply_action("кофе")
    
    # Особые эффекты в зависимости от типа кофе
    coffee_effects = {
        "espresso": {"энергия": +10, "сон": -5},
        "latte": {"настроение": +5, "аппетит": +5},
        "cappuccino": {"пушистость": +5, "настроение": +5},
        "raf": {"настроение": +10, "сон": +5},
        "americano": {"кофе": +5, "энергия": +5}
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
    if current_coffee == dragon.favorites["кофе"]:
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
        favorite_bonus = "\n🎉 Это его любимый кофе! +15 к настроению!"
    else:
        favorite_bonus = ""
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    # Готовим ответ
    coffee_descriptions = {
        "espresso": "Ты приготовил крепкий эспрессо! Дракон бодр и весел!",
        "latte": "Нежный латте с молочной пенкой готов! Дракон мурлычет от удовольствия!",
        "cappuccino": "Воздушный капучино с корицей! Аромат стоит на всю комнату!",
        "raf": "Сливочный раф с ванилью! Дракон в восторге!",
        "americano": "Классический американо! Просто и вкусно!"
    }
    
    response = (
        f"{coffee_descriptions.get(coffee_type, 'Кофе готов!')}\n\n"
        f"📊 **Изменения:**\n"
        f"• Кофе: +{result['stat_changes'].get('кофе', 0)}\n"
        f"• Энергия: +{result['stat_changes'].get('энергия', 0)}\n"
        f"• Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        f"• Сонливость: {result['stat_changes'].get('сон', 0)}\n"
        f"{favorite_bonus}"
    )
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await callback.message.edit_text(response)
    await callback.answer()

@dp.message(Command("feed"))
@dp.message(F.text == "🍪 Покормить")
async def cmd_feed(message: types.Message):
    """Покормить дракона"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    inventory = db.get_inventory(user_id)
    
    # Проверяем, что есть чем кормить
    available_snacks = []
    snack_items = {
        "печенье": "🍪 Печенье",
        "шоколад": "🍫 Шоколад", 
        "зефир": "☁️ Зефир",
        "пряник": "🎄 Пряник",
        "мармелад": "🍬 Мармелад"
    }
    
    for snack_key, snack_name in snack_items.items():
        if inventory.get(snack_key, 0) > 0:
            available_snacks.append(
                InlineKeyboardButton(
                    text=snack_name, 
                    callback_data=f"feed_{snack_key}"
                )
            )
    
    if not available_snacks:
        await message.answer(
            "Нет сладостей для кормления! 😔\n"
            "Купи их в магазине /shop",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Создаем клавиатуру со сладостями
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Распределяем кнопки по 2 в ряд
    for i in range(0, len(available_snacks), 2):
        row = available_snacks[i:i+2]
        keyboard.inline_keyboard.append(row)
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="feed_cancel")
    ])
    
    await message.answer(
        "🍪 **Чем угостим дракона?**\n\n"
        "Выбери сладость из инвентаря:",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("feed_"))
async def process_feed(callback: types.CallbackQuery):
    """Обработка кормления"""
    user_id = callback.from_user.id
    snack_type = callback.data.replace("feed_", "")
    
    if snack_type == "cancel":
        await callback.message.edit_text("Кормление отменено 🍪")
        await callback.answer()
        return
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await callback.answer("Дракон не найден!")
        return
    
    # Проверяем, есть ли такая сладость
    inventory = db.get_inventory(user_id)
    if inventory.get(snack_type, 0) <= 0:
        await callback.answer("Эта сладость закончилась!")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Используем сладость
    db.update_inventory(user_id, snack_type, -1)
    
    # Применяем действие
    result = dragon.apply_action("кормление")
    
    # Проверяем, любимая ли это сладость
    snack_names = {
        "печенье": "печенье",
        "шоколад": "шоколад",
        "зефир": "зефир", 
        "пряник": "пряник",
        "мармелад": "мармелад"
    }
    
    current_snack = snack_names.get(snack_type, "")
    if current_snack == dragon.favorites["сладость"]:
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
        favorite_bonus = "\n🎉 Это его любимая сладость! +20 к настроению!"
    else:
        favorite_bonus = ""
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    # Готовим ответ
    snack_descriptions = {
        "печенье": "🍪 Хрустящее печенье!",
        "шоколад": "🍫 Сладкий шоколад!",
        "зефир": "☁️ Воздушный зефир!",
        "пряник": "🎄 Ароматный пряник!",
        "мармелад": "🍬 Фруктовый мармелад!"
    }
    
    response = (
        f"{snack_descriptions.get(snack_type, 'Сладость')}\n"
        f"Дракон с удовольствием уплетает угощение!\n\n"
        f"📊 **Изменения:**\n"
        f"• Аппетит: {result['stat_changes'].get('аппетит', 0)}\n"
        f"• Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        f"{favorite_bonus}"
    )
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await callback.message.edit_text(response)
    await callback.answer()

@dp.message(Command("hug"))
@dp.message(F.text == "🤗 Обнять")
async def cmd_hug(message: types.Message):
    """Обнять дракона"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Применяем действие
    result = dragon.apply_action("обнимашки")
    
    # Бонус для неженки
    if dragon.character["основная_черта"] == "неженка":
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
        character_bonus = "\n🥰 Неженка обожает обнимашки! +15 к настроению!"
    else:
        character_bonus = ""
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    # Случайные реакции
    reactions = [
        "Дракон мурлычет от удовольствия! 🐾",
        "Дракон обнимает тебя в ответ! 🤗",
        "Дракон свернулся калачиком у тебя на коленях! 🥰",
        "Дракон трется мордочкой о тебя! 😊",
        "Дракон тихо урчит и закрывает глаза! 😴"
    ]
    
    response = (
        f"{random.choice(reactions)}\n\n"
        f"📊 **Изменения:**\n"
        f"• Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        f"• Сонливость: {result['stat_changes'].get('сон', 0)}\n"
        f"{character_bonus}"
    )
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await message.answer(response, reply_markup=get_main_keyboard())

@dp.message(Command("read"))
@dp.message(F.text == "📚 Читать")
async def cmd_read(message: types.Message):
    """Почитать книгу дракону"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Проверяем энергию
    if dragon.stats["энергия"] < 10:
        await message.answer(
            "Дракон слишком устал для чтения... 😴\n"
            "Дайте ему отдохнуть или приготовьте кофе!",
            reply_markup=get_main_keyboard()
        )
        return
    
    await message.answer(
        "📚 **Выбери жанр книги:**\n\n"
        "• **Фэнтези** - волшебные миры\n"
        "• **Сказки** - добрые истории\n"
        "• **Приключения** - захватывающие путешествия\n"
        "• **Детектив** - загадки и расследования\n"
        "• **Поэзия** - стихи и рифмы",
        reply_markup=get_reading_keyboard()
    )

@dp.callback_query(F.data.startswith("read_"))
async def process_read(callback: types.CallbackQuery):
    """Обработка чтения книги"""
    user_id = callback.from_user.id
    read_type = callback.data.replace("read_", "")
    
    if read_type == "cancel":
        await callback.message.edit_text("Чтение отменено 📚")
        await callback.answer()
        return
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await callback.answer("Дракон не найден!")
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
        await callback.answer("Книги не найдены!")
        return
    
    # Применяем действие
    result = dragon.apply_action("чтение")
    
    # Проверяем, любимый ли это жанр
    if book["жанр"] == dragon.favorites["жанр_книг"]:
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 15)
        dragon.skills["литературный_вкус"] = min(100, dragon.skills["литературный_вкус"] + 5)
        favorite_bonus = "\n🎉 Это его любимый жанр! +15 к настроению, +5 к литературному вкусу!"
    else:
        favorite_bonus = ""
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    # Формируем ответ
    response = (
        f"📖 **{book['название']}**\n"
        f"Автор: {book['автор']}\n\n"
        f"📝 **О чем книга:**\n{book['описание']}\n\n"
        f"🐉 **Мнение дракона:**\n{book['комментарий_дракона']}\n\n"
        f"📊 **После чтения:**\n"
        f"• Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        f"• Сонливость: +{result['stat_changes'].get('сон', 0)}\n"
        f"• Литературный вкус: +2{favorite_bonus}"
    )
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await callback.message.edit_text(response)
    await callback.answer()

@dp.message(Command("play"))
@dp.message(F.text == "🎮 Играть")
async def cmd_play(message: types.Message, state: FSMContext):
    """Поиграть с драконом"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Проверяем энергию
    if dragon.stats["энергия"] < 20:
        await message.answer(
            "Дракон слишком устал для игр... ⚡\n"
            "Дайте ему отдохнуть или приготовьте кофе!",
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
        "🎮 **Игра: Угадай число!**\n\n"
        "Я загадал число от 1 до 5.\n"
        "Попробуй угадать! Отправь цифру:"
    )

@dp.message(GameStates.waiting_for_guess)
async def process_game_guess(message: types.Message, state: FSMContext):
    """Обработка догадки в игре"""
    user_id = message.from_user.id
    
    try:
        guess = int(message.text.strip())
        if guess < 1 or guess > 5:
            await message.answer("Пожалуйста, введи число от 1 до 5:")
            return
    except ValueError:
        await message.answer("Пожалуйста, введи число от 1 до 5:")
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
            f"🎉 **Правильно!** Загаданное число: {secret_number}\n\n"
            f"Дракон радостно подпрыгивает! 🥳\n\n"
            f"📊 **Награда:**\n"
            f"• Настроение: +20\n"
            f"• Золото: +10\n"
            f"• Игровая эрудиция: +2"
        )
    else:
        # Поражение
        dragon.stats["настроение"] = max(0, dragon.stats["настроение"] - 5)
        
        response = (
            f"😔 **Не угадал!** Загаданное число: {secret_number}\n\n"
            f"Дракон немного расстроился... но это же игра!\n\n"
            f"📊 **Результат:**\n"
            f"• Настроение: -5\n"
            f"• Игровая эрудиция: +2"
        )
    
    # Бонус для игрика
    if dragon.character["основная_черта"] == "игрик":
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 10)
        response += "\n\n🎮 Игрик обожает игры! +10 к настроению!"
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await message.answer(response, reply_markup=get_main_keyboard())
    await state.clear()

@dp.message(Command("clean"))
async def cmd_clean(message: types.Message):
    """Почистить/расчесать дракона"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Применяем действие
    result = dragon.apply_action("расчесывание")
    
    # Бонус для чистюли
    if dragon.character["основная_черта"] == "чистюля":
        dragon.stats["настроение"] = min(100, dragon.stats["настроение"] + 20)
        character_bonus = "\n✨ Чистюля сияет от счастья! +20 к настроению!"
    else:
        character_bonus = ""
    
    # Сохраняем изменения
    db.update_dragon(user_id, dragon.to_dict())
    
    # Случайные реакции
    reactions = [
        "Дракон блаженно закрывает глаза, пока ты его расчесываешь! ✨",
        "Шерстка дракона теперь блестит и переливается! 🌟",
        "Дракон мурлычет, наслаждаясь процедурой ухода! 😌",
        "После расчесывания дракон выглядит просто великолепно! 💫"
    ]
    
    response = (
        f"{random.choice(reactions)}\n\n"
        f"📊 **Результат:**\n"
        f"• Пушистость: +{result['stat_changes'].get('пушистость', 0)}\n"
        f"• Настроение: +{result['stat_changes'].get('настроение', 0)}\n"
        f"{character_bonus}"
    )
    
    if result.get("level_up"):
        response += f"\n\n{result['message']}"
    
    await message.answer(response, reply_markup=get_main_keyboard())

# ==================== МАГАЗИН И ИНВЕНТАРЬ ====================
@dp.message(Command("shop"))
@dp.message(F.text == "🛍️ Магазин")
async def cmd_shop(message: types.Message):
    """Магазин"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    gold = db.get_gold(user_id)
    
    await message.answer(
        f"🛍️ **Магазин Кофейного Дракона**\n\n"
        f"💰 **Твой баланс:** {gold} золота\n\n"
        f"**Товары:**\n"
        f"• ☕ Кофейные зерна - 10 золота\n"
        f"• 🍪 Печенье - 5 золота\n"
        f"• 🍫 Шоколад - 15 золота\n"
        f"• 🎲 Игральная кость - 20 золота\n\n"
        f"Выбери товар для покупки:",
        reply_markup=get_shop_keyboard()
    )

@dp.callback_query(F.data.startswith("shop_"))
async def process_shop(callback: types.CallbackQuery):
    """Обработка покупок в магазине"""
    user_id = callback.from_user.id
    action = callback.data.replace("shop_", "")
    
    if action == "close":
        await callback.message.delete()
        await callback.answer("Магазин закрыт")
        return
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await callback.answer("Дракон не найден!")
        return
    
    gold = db.get_gold(user_id)
    
    # Цены товаров
    prices = {
        "coffee": 10,
        "cookie": 5,
        "chocolate": 15,
        "dice": 20
    }
    
    # Названия товаров
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
            
            await callback.message.edit_text(
                f"✅ **Покупка совершена!**\n\n"
                f"Ты купил: {description}\n"
                f"Цена: {price} золота\n"
                f"Остаток: {new_gold} золота\n\n"
                f"Что-нибудь еще?",
                reply_markup=get_shop_keyboard()
            )
            await callback.answer()
        else:
            await callback.answer(f"Недостаточно золота! Нужно {price}, а у тебя {gold}")
    else:
        await callback.answer("Неизвестный товар!")

@dp.message(Command("inventory"))
@dp.message(F.text == "📦 Инвентарь")
async def cmd_inventory(message: types.Message):
    """Показать инвентарь"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    inventory = db.get_inventory(user_id)
    gold = db.get_gold(user_id)
    
    if not inventory:
        await message.answer(
            "📦 **Инвентарь пуст!**\n\n"
            f"💰 Золото: {gold}\n\n"
            "Зайди в магазин /shop чтобы купить что-нибудь!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Формируем список предметов
    items_text = "📦 **Твой инвентарь:**\n\n"
    
    # Группируем по категориям
    categories = {
        "☕ Кофе и напитки": ["кофейные_зерна", "вода"],
        "🍪 Сладости": ["печенье", "шоколад", "зефир", "пряник", "мармелад"],
        "🎮 Игры и развлечения": ["игральная_кость"],
        "🧶 Рукоделие": [],
        "🏠 Украшения": []
    }
    
    for category, item_list in categories.items():
        category_items = []
        for item in item_list:
            if item in inventory and inventory[item] > 0:
                # Преобразуем название
                item_names = {
                    "кофейные_зерна": "Кофейные зерна",
                    "печенье": "Печенье",
                    "шоколад": "Шоколад",
                    "зефир": "Зефир",
                    "пряник": "Пряник",
                    "мармелад": "Мармелад",
                    "вода": "Вода",
                    "игральная_кость": "Игральная кость"
                }
                display_name = item_names.get(item, item)
                category_items.append(f"  • {display_name}: {inventory[item]}")
        
        if category_items:
            items_text += f"**{category}:**\n" + "\n".join(category_items) + "\n\n"
    
    items_text += f"💰 **Золото:** {gold}"
    
    await message.answer(items_text, reply_markup=get_main_keyboard())

@dp.message(Command("gold"))
async def cmd_gold(message: types.Message):
    """Показать количество золота"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    gold = db.get_gold(user_id)
    
    responses = [
        f"💰 **Твое золото:** {gold}\n\nЗолото можно заработать в играх или найти в книгах!",
        f"💰 **Сокровища:** {gold} золота\n\nПродолжай заботиться о драконе, и золото само придет!",
        f"💰 **Богатство:** {gold} золотых монет\n\nНа что потратишь? Загляни в магазин /shop!",
        f"💰 **Казна:** {gold} золота\n\nС каждым днем твое состояние растет!"
    ]
    
    await message.answer(random.choice(responses), reply_markup=get_main_keyboard())

# ==================== ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ ====================
@dp.message(Command("rename"))
async def cmd_rename(message: types.Message, state: FSMContext):
    """Переименовать дракона"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    await message.answer(
        "Как ты хочешь назвать своего дракона?\n"
        "Отправь новое имя:"
    )
    
    await state.set_state(GameStates.waiting_for_name)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Подробная статистика"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Навыки
    skills_text = "🎯 **Навыки дракона:**\n"
    for skill, value in dragon.skills.items():
        skill_name = skill.replace("_", " ").title()
        bar_length = 10
        filled = int(value / 100 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        skills_text += f"{skill_name:20} {bar} {value:3}%\n"
    
    # Характер
    character_text = (
        f"🎭 **Характер:**\n"
        f"• Основная черта: {dragon.character['основная_черта']}\n"
        f"• Дополнительные: {', '.join(dragon.character['второстепенные'])}\n"
    )
    
    # Любимое
    favorites_text = (
        f"❤ **Любимое:**\n"
        f"• Кофе: {dragon.favorites['кофе']}\n"
        f"• Сладость: {dragon.favorites['сладость']}\n"
        f"• Книги: {dragon.favorites['жанр_книг']}\n"
        f"• Цвет: {dragon.favorites['цвет']}\n"
    )
    
    # Прогресс
    progress_text = (
        f"📊 **Прогресс:**\n"
        f"• Уровень: {dragon.level}\n"
        f"• Опыт: {dragon.experience}/100\n"
        f"• Золото: {dragon.gold}\n"
        f"• Создан: {dragon.created_at[:10]}\n"
    )
    
    response = (
        f"🐉 **Подробная статистика {dragon.name}**\n\n"
        f"{progress_text}\n"
        f"{character_text}\n"
        f"{favorites_text}\n"
        f"{skills_text}"
    )
    
    await message.answer(response, reply_markup=get_main_keyboard())

@dp.message(Command("achievements"))
async def cmd_achievements(message: types.Message):
    """Достижения"""
    user_id = message.from_user.id
    
    dragon_data = db.get_dragon(user_id)
    if not dragon_data:
        await message.answer("Сначала создай дракона командой /create")
        return
    
    dragon = Dragon.from_dict(dragon_data)
    
    # Определяем достижения
    achievements = []
    
    # По уровню
    if dragon.level >= 5:
        achievements.append("🎓 **Ученик** - достиг 5 уровня")
    if dragon.level >= 10:
        achievements.append("🏆 **Мастер** - достиг 10 уровня")
    if dragon.level >= 20:
        achievements.append("👑 **Легенда** - достиг 20 уровня")
    
    # По навыкам
    if dragon.skills["кофейное_мастерство"] >= 50:
        achievements.append("☕ **Бариста** - кофейное мастерство 50+")
    if dragon.skills["литературный_вкус"] >= 50:
        achievements.append("📚 **Библиофил** - литературный вкус 50+")
    if dragon.skills["игровая_эрудиция"] >= 50:
        achievements.append("🎮 **Геймер** - игровая эрудиция 50+")
    
    # По золоту
    if dragon.gold >= 100:
        achievements.append("💰 **Богач** - накопил 100+ золота")
    if dragon.gold >= 500:
        achievements.append("💎 **Миллионер** - накопил 500+ золота")
    
    # По времени
    from datetime import datetime
    created_date = datetime.fromisoformat(dragon.created_at)
    days_with_dragon = (datetime.now() - created_date).days
    
    if days_with_dragon >= 7:
        achievements.append("📅 **Неделя вместе** - 7 дней с драконом")
    if days_with_dragon >= 30:
        achievements.append("📅 **Месяц вместе** - 30 дней с драконом")
    if days_with_dragon >= 100:
        achievements.append("📅 **Вековой союз** - 100 дней с драконом")
    
    if achievements:
        achievements_text = "\n".join(achievements)
        response = (
            f"🏆 **Достижения {dragon.name}**\n\n"
            f"{achievements_text}\n\n"
            f"Всего достижений: {len(achievements)}"
        )
    else:
        response = (
            f"🏆 **Достижения {dragon.name}**\n\n"
            f"Пока нет достижений... 😔\n"
            f"Продолжай заботиться о драконе, и достижения появятся!"
        )
    
    await message.answer(response, reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА ОШИБОК ====================
@dp.message()
async def handle_other_messages(message: types.Message):
    """Обработка всех остальных сообщений"""
    response = (
        "Я не понял команду... 🥺\n\n"
        "Используй кнопки внизу или команду /help для списка команд."
    )
    await message.answer(response, reply_markup=get_main_keyboard())

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Главная функция запуска бота"""
    logger.info("Запуск бота Кофейный Дракон...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())