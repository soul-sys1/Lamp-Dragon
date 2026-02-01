"""
МОДЕЛЬ ДРАКОНА
Содержит все данные и логику дракона
Версия с исправлениями ошибок
"""
import random
from datetime import datetime
import json

class Dragon:
    def __init__(self, name="Дракоша"):
        self.name = name
        self.created_at = datetime.now().isoformat()
        
        # Основные показатели (0-100)
        self.stats = {
            "кофе": 70,        # Хочет кофе
            "сон": 30,         # Хочет спать
            "настроение": 80,  # Настроение
            "аппетит": 60,     # Хочет есть
            "энергия": 75,     # Энергия для игр
            "пушистость": 90   # Чистота/ухоженность
        }
        
        # Генерируем характер
        self.character = self._generate_character()
        
        # Навыки (0-100)
        self.skills = {
            "кофейное_мастерство": 10,
            "литературный_вкус": 5,
            "игровая_эрудиция": 5,
            "вязальная_сноровка": 0
        }
        
        # Прогресс
        self.level = 1
        self.experience = 0
        self.gold = 50
        
        # Инвентарь (будет синхронизирован с базой)
        self.inventory = {}
        
        # Привычки
        self.habits = []
        
        # Любимые вещи (определяются характером)
        self.favorites = self._generate_favorites()
        
        # Время последнего обновления
        self.last_update = datetime.now().isoformat()
    
    def _generate_character(self):
        """Генерирует случайный характер"""
        traits = [
            "кофеман",      # Любит кофе больше всего
            "соня",         # Быстро устает, любит спать
            "игрик",        # Обожает игры
            "книгочей",     # Любит читать
            "неженка",      # Требует много ласки
            "гурман",       # Разбирается в еде
            "чистюля",      # Следит за чистотой
            "лентяй",       # Не любит активность
            "энерджайзер",  # Всегда полон энергии
            "философ"       # Любит размышлять
        ]
        
        main_trait = random.choice(traits)
        other_traits = [t for t in traits if t != main_trait]
        secondary = random.sample(other_traits, min(2, len(other_traits)))
        
        return {
            "основная_черта": main_trait,
            "второстепенные": secondary
        }
    
    def _generate_favorites(self):
        """Генерирует любимые вещи в зависимости от характера"""
        # Используем get() с значением по умолчанию для безопасности
        main_trait = self.character.get("основная_черта", "неженка")
        
        favorites = {
            "кофе": random.choice(["эспрессо", "латте", "капучино", "раф", "американо"]),
            "сладость": random.choice(["печенье", "шоколад", "зефир", "пряник", "мармелад"]),
            "жанр_книг": random.choice(["фэнтези", "приключения", "сказки", "детектив", "поэзия"]),
            "цвет": random.choice(["синий", "зеленый", "красный", "фиолетовый", "золотой"])
        }
        
        # Особые предпочтения по характеру
        if main_trait == "кофеман":
            favorites["кофе"] = "эспрессо"  # Самый крепкий
        elif main_trait == "сладкоежка":
            favorites["сладость"] = "шоколад"
        elif main_trait == "книгочей":
            favorites["жанр_книг"] = "фэнтези"
        elif main_trait == "чистюля":
            favorites["цвет"] = "белый"
        
        return favorites
    
    def update_over_time(self):
        """Обновляет показатели со временем"""
        try:
            now = datetime.now()
            last_update = datetime.fromisoformat(self.last_update)
            hours_passed = (now - last_update).total_seconds() / 3600
            
            if hours_passed < 0.5:  # Меньше 30 минут
                return
            
            # Кофе уменьшается
            self.stats["кофе"] = max(0, self.stats["кофе"] - int(5 * hours_passed))
            
            # Сонливость растет
            self.stats["сон"] = min(100, self.stats["сон"] + int(3 * hours_passed))
            
            # Аппетит растет
            self.stats["аппетит"] = min(100, self.stats["аппетит"] + int(2 * hours_passed))
            
            # Энергия падает
            self.stats["энергия"] = max(0, self.stats["энергия"] - int(2 * hours_passed))
            
            # Пушистость уменьшается
            self.stats["пушистость"] = max(0, self.stats["пушистость"] - int(1 * hours_passed))
            
            # Настроение зависит от других показателей
            mood_change = 0
            
            if self.stats["кофе"] < 20:
                mood_change -= 10
            if self.stats["сон"] > 80:
                mood_change -= 5
            if self.stats["аппетит"] > 80:
                mood_change -= 5
            if self.stats["энергия"] < 20:
                mood_change -= 5
            if self.stats["пушистость"] < 30:
                mood_change -= 5
            
            self.stats["настроение"] = max(0, min(100, self.stats["настроение"] + mood_change))
            
            self.last_update = now.isoformat()
        except Exception as e:
            # В случае ошибки сбросим время обновления
            self.last_update = datetime.now().isoformat()
            print(f"Ошибка в update_over_time: {e}")
    
    def add_experience(self, amount):
        """Добавляет опыт и проверяет повышение уровня"""
        try:
            self.experience += amount
            levels_gained = 0
            
            while self.experience >= 100:
                self.experience -= 100
                self.level += 1
                levels_gained += 1
                
                # При повышении уровня улучшаем случайный навык
                if self.skills:
                    skill = random.choice(list(self.skills.keys()))
                    self.skills[skill] = min(100, self.skills[skill] + 10)
            
            return levels_gained
        except Exception as e:
            print(f"Ошибка в add_experience: {e}")
            return 0
    
    def apply_action(self, action_type, action_data=None):
        """Применяет действие к дракону и возвращает результат"""
        result = {
            "success": True,
            "message": "",
            "stat_changes": {},
            "level_up": False
        }
        
        try:
            # Эффекты в зависимости от действия
            effects = {
                "кофе": {
                    "кофе": +40,
                    "сон": -20,
                    "энергия": +30,
                    "настроение": +10
                },
                "кормление": {
                    "аппетит": -40,
                    "настроение": +15,
                    "энергия": +5
                },
                "обнимашки": {
                    "настроение": +25,
                    "сон": -10
                },
                "расчесывание": {
                    "пушистость": +50,
                    "настроение": +10
                },
                "чтение": {
                    "сон": +20,
                    "настроение": +20,
                    "литературный_вкус": +2
                },
                "игра": {
                    "энергия": -20,
                    "настроение": +15,
                    "игровая_эрудиция": +2
                }
            }
            
            if action_type in effects:
                for stat, change in effects[action_type].items():
                    if stat in self.stats:
                        old_value = self.stats[stat]
                        self.stats[stat] = max(0, min(100, old_value + change))
                        result["stat_changes"][stat] = self.stats[stat] - old_value
                    elif stat in self.skills:
                        self.skills[stat] = min(100, self.skills.get(stat, 0) + change)
                
                # Даем опыт
                exp_gained = random.randint(5, 15)
                levels = self.add_experience(exp_gained)
                if levels > 0:
                    result["level_up"] = True
                    result["message"] = f"🎉 Дракон достиг {self.level} уровня!"
                
                # Проверяем характер для особых бонусов
                # Используем get() с значением по умолчанию
                main_trait = self.character.get("основная_черта", "неженка")
                
                if action_type == "кофе" and main_trait == "кофеман":
                    mood_change = result["stat_changes"].get("настроение", 0) + 10
                    result["stat_changes"]["настроение"] = mood_change
                    if result["message"]:
                        result["message"] += "\n☕ Кофеман в восторге от кофе!"
                    else:
                        result["message"] = "☕ Кофеман в восторге от кофе!"
                
                elif action_type == "обнимашки" and main_trait == "неженка":
                    mood_change = result["stat_changes"].get("настроение", 0) + 15
                    result["stat_changes"]["настроение"] = mood_change
                    if result["message"]:
                        result["message"] += "\n🥰 Неженка обожает обнимашки!"
                    else:
                        result["message"] = "🥰 Неженка обожает обнимашки!"
            else:
                result["success"] = False
                result["message"] = f"Неизвестное действие: {action_type}"
                
        except Exception as e:
            result["success"] = False
            result["message"] = f"Ошибка при выполнении действия: {str(e)}"
            print(f"Ошибка в apply_action: {e}")
        
        return result
    
    def get_status_text(self):
        """Возвращает текстовый статус дракона"""
        try:
            # Обновляем показатели
            self.update_over_time()
            
            # Проверяем критические состояния
            warnings = []
            if self.stats.get("кофе", 70) < 10:
                warnings.append("☕ Нужно срочно кофе!")
            if self.stats.get("сон", 30) > 90:
                warnings.append("💤 Дракон засыпает на ходу...")
            if self.stats.get("аппетит", 60) > 90:
                warnings.append("🍪 Очень голоден!")
            if self.stats.get("настроение", 80) < 20:
                warnings.append("😔 Дракон в депрессии...")
            if self.stats.get("энергия", 75) < 10:
                warnings.append("⚡ Нет сил даже двигаться")
            if self.stats.get("пушистость", 90) < 20:
                warnings.append("🛁 Пора принять ванну!")
            
            # Формируем текст
            text = f"🐉 **{self.name}** [Уровень {self.level}]\n"
            
            # Используем get() для character
            main_trait = self.character.get("основная_черта", "неженка")
            text += f"🎭 Характер: {main_trait}\n"
            
            text += f"💰 Золото: {self.gold} | ⭐ Опыт: {self.experience}/100\n\n"
            
            text += "**ПОКАЗАТЕЛИ:**\n"
            
            # Безопасный перебор stats
            stats_to_display = {
                "кофе": "Кофе",
                "сон": "Сон",
                "настроение": "Настроение",
                "аппетит": "Аппетит",
                "энергия": "Энергия",
                "пушистость": "Пушистость"
            }
            
            for stat_key, stat_name in stats_to_display.items():
                value = self.stats.get(stat_key, 0)
                bar_length = 10
                filled = int(value / 100 * bar_length) if value >= 0 else 0
                bar = "█" * filled + "░" * (bar_length - filled)
                text += f"{stat_name:12} {bar} {value:3}%\n"
            
            if warnings:
                text += "\n**⚠ ВНИМАНИЕ:**\n"
                for warning in warnings:
                    text += f"• {warning}\n"
            
            # Любимые вещи с проверкой
            text += f"\n**❤ ЛЮБИМОЕ:**\n"
            
            favorites_display = {
                "кофе": "Кофе",
                "сладость": "Сладость",
                "жанр_книг": "Книги",
                "цвет": "Цвет"
            }
            
            for fav_key, fav_name in favorites_display.items():
                fav_value = self.favorites.get(fav_key, "неизвестно")
                text += f"{fav_name}: {fav_value}\n"
            
            return text
            
        except Exception as e:
            print(f"Ошибка в get_status_text: {e}")
            return f"🐉 **{self.name}**\n\nПроизошла ошибка при получении статуса. Попробуйте позже."
    
    def to_dict(self):
        """Преобразует объект в словарь для сохранения"""
        return {
            "name": self.name,
            "created_at": self.created_at,
            "stats": self.stats,
            "character": self.character,
            "skills": self.skills,
            "level": self.level,
            "experience": self.experience,
            "gold": self.gold,
            "inventory": self.inventory,
            "habits": self.habits,
            "favorites": self.favorites,
            "last_update": self.last_update
        }
    
    @classmethod
    def from_dict(cls, data):
        """Создает объект из словаря"""
        try:
            dragon = cls(data.get("name", "Дракоша"))
            dragon.created_at = data.get("created_at", datetime.now().isoformat())
            
            # Статистика с проверкой
            dragon.stats = data.get("stats", dragon.stats.copy())
            
            # Характер с проверкой
            character = data.get("character", {})
            if not isinstance(character, dict):
                character = {}
            if "основная_черта" not in character:
                character["основная_черта"] = "неженка"
            if "второстепенные" not in character:
                character["второстепенные"] = []
            dragon.character = character
            
            # Навыки с проверкой
            dragon.skills = data.get("skills", dragon.skills.copy())
            
            # Прогресс
            dragon.level = data.get("level", 1)
            dragon.experience = data.get("experience", 0)
            dragon.gold = data.get("gold", 50)
            
            # Инвентарь и привычки
            dragon.inventory = data.get("inventory", {})
            dragon.habits = data.get("habits", [])
            
            # Любимые вещи с проверкой
            favorites = data.get("favorites", {})
            if not isinstance(favorites, dict):
                favorites = {}
            
            # Убедимся, что есть все нужные ключи
            default_favorites = dragon._generate_favorites()
            for key in default_favorites:
                if key not in favorites:
                    favorites[key] = default_favorites[key]
            dragon.favorites = favorites
            
            # Время обновления
            dragon.last_update = data.get("last_update", datetime.now().isoformat())
            
            return dragon
            
        except Exception as e:
            print(f"Ошибка при создании дракона из словаря: {e}")
            # Возвращаем нового дракона с дефолтными значениями
            return cls(data.get("name", "Дракоша") if isinstance(data, dict) else "Дракоша")