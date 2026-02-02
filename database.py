"""
БАЗА ДАННЫХ ДЛЯ ДРАКОНОВ v6.0 - ИСПРАВЛЕННАЯ ВЕРСИЯ
Хранит всех драконов в SQLite базе с обновленными функциями
Версия с английскими названиями предметов и упрощенным инвентарем
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pytz

class DragonDatabase:
    def __init__(self, db_name="dragons.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Для доступа по имени колонок
        self.cursor = self.conn.cursor()
        self.create_tables()  # Создаем таблицы сразу при инициализации
    
    def create_tables(self):
        """Создаем таблицы, если их нет"""
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_play_time INTEGER DEFAULT 0,
                first_visit_date DATE DEFAULT CURRENT_DATE
            )
        ''')
        
        # Таблица драконов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS dragons (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                character_trait TEXT,
                level INTEGER DEFAULT 1,
                experience INTEGER DEFAULT 0,
                gold INTEGER DEFAULT 50,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                dragon_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_xp_earned INTEGER DEFAULT 0,
                total_gold_earned INTEGER DEFAULT 0,
                days_with_dragon INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица инвентаря (упрощенная структура)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                category TEXT,
                rarity TEXT DEFAULT 'common',
                last_used TIMESTAMP,
                purchase_price INTEGER DEFAULT 0,
                UNIQUE(user_id, item_name)
            )
        ''')
        
        # Таблица привычек
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                habit_type TEXT NOT NULL,
                habit_time TEXT,
                streak INTEGER DEFAULT 1,
                last_performed TIMESTAMP,
                total_performed INTEGER DEFAULT 1,
                best_streak INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица действий пользователя (для уведомлений и статистики)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action_type TEXT NOT NULL,
                action_details TEXT,
                dragon_response TEXT,
                character_trait TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hour_of_day INTEGER,
                day_of_week INTEGER
            )
        ''')
        
        # Таблица настроек пользователя (добавлен часовой пояс)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                morning_notifications INTEGER DEFAULT 1,
                evening_notifications INTEGER DEFAULT 1,
                feeding_reminders INTEGER DEFAULT 1,
                night_mode INTEGER DEFAULT 0,
                quiet_mode INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'standard',
                font_size TEXT DEFAULT 'medium',
                sound_effects INTEGER DEFAULT 1,
                background_music INTEGER DEFAULT 0,
                timezone TEXT DEFAULT 'Europe/Moscow',
                notifications_enabled INTEGER DEFAULT 1,
                auto_save INTEGER DEFAULT 1,
                daily_reminder_time TIME DEFAULT '20:00',
                weekly_report INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица статистики (расширенная)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                total_coffees INTEGER DEFAULT 0,
                total_feeds INTEGER DEFAULT 0,
                total_hugs INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                total_care INTEGER DEFAULT 0,
                total_sleep INTEGER DEFAULT 0,
                total_minigames_won INTEGER DEFAULT 0,
                total_minigames_lost INTEGER DEFAULT 0,
                total_items_bought INTEGER DEFAULT 0,
                total_gold_spent INTEGER DEFAULT 0,
                total_character_messages INTEGER DEFAULT 0,
                favorite_action TEXT,
                favorite_time TEXT,
                achievements TEXT DEFAULT '[]',
                daily_streak INTEGER DEFAULT 0,
                last_daily_date DATE,
                longest_daily_streak INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица игровых событий (для аналитики)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_type TEXT NOT NULL,
                event_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица истории покупок
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 1,
                price INTEGER DEFAULT 0,
                category TEXT,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Индексы для ускорения запросов
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_dragons_user_id ON dragons(user_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_inventory_user_item ON inventory(user_id, item_name)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_user_time ON user_actions(user_id, created_at)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_actions_type ON user_actions(action_type)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_user ON game_events(user_id, event_type)')
        
        self.conn.commit()
        print("✅ Таблицы базы данных созданы/проверены")
    
    def user_exists(self, user_id: int) -> bool:
        """Проверяет, есть ли пользователь в базе"""
        self.cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None
    
    def dragon_exists(self, user_id: int) -> bool:
        """Проверяет, есть ли дракон у пользователя"""
        self.cursor.execute("SELECT 1 FROM dragons WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None
    
    def create_user(self, user_id: int, username: str) -> bool:
        """Создает нового пользователя"""
        try:
            if not self.user_exists(user_id):
                self.cursor.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    (user_id, username)
                )
                
                # Создаем настройки по умолчанию
                self.cursor.execute('''
                    INSERT INTO user_settings (user_id, timezone) 
                    VALUES (?, ?)
                ''', (user_id, 'Europe/Moscow'))
                
                # Создаем статистику
                self.cursor.execute(
                    "INSERT INTO user_stats (user_id) VALUES (?)",
                    (user_id,)
                )
                
                self.conn.commit()
                print(f"✅ Создан пользователь: {username} (ID: {user_id})")
                return True
            return True  # Пользователь уже существует
        except Exception as e:
            print(f"❌ Ошибка при создании пользователя: {e}")
            self.conn.rollback()
            return False
    
    def create_dragon(self, user_id: int, dragon_data: Dict) -> bool:
        """Создает нового дракона - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        try:
            if not self.dragon_exists(user_id):
                # Сначала убедимся, что пользователь существует
                if not self.user_exists(user_id):
                    self.create_user(user_id, "Unknown")
                
                character_trait = dragon_data.get('character', {}).get('основная_черта', 'неженка')
                
                self.cursor.execute('''
                    INSERT INTO dragons 
                    (user_id, name, character_trait, level, experience, gold, dragon_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    dragon_data.get('name', 'Дракоша'),
                    character_trait,
                    dragon_data.get('level', 1),
                    dragon_data.get('experience', 0),
                    dragon_data.get('gold', 50),
                    json.dumps(dragon_data, ensure_ascii=False)
                ))
                
                # СОЗДАЕМ НАЧАЛЬНЫЙ ИНВЕНТАРЬ С АНГЛИЙСКИМИ НАЗВАНИЯМИ
                initial_items = [
                    # Кофе и ингредиенты
                    (user_id, 'coffee_beans', 10, 'coffee', 'common', 0),
                    
                    # Сладости
                    (user_id, 'cookie', 5, 'sweets', 'common', 0),
                    (user_id, 'chocolate', 2, 'sweets', 'uncommon', 0),
                    (user_id, 'marshmallow', 1, 'sweets', 'rare', 0),
                    (user_id, 'gingerbread', 1, 'sweets', 'common', 0),
                    
                    # Предметы для ухода (по умолчанию нет)
                    # Ингредиенты для кофе (по умолчанию нет)
                    # Прочие предметы (по умолчанию нет)
                ]
                
                for item in initial_items:
                    try:
                        self.cursor.execute('''
                            INSERT INTO inventory 
                            (user_id, item_name, quantity, category, rarity, purchase_price)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, item_name) 
                            DO UPDATE SET quantity = quantity + excluded.quantity
                        ''', item)
                    except Exception as e:
                        print(f"❌ Ошибка добавления предмета {item[1]}: {e}")
                
                # Записываем событие создания дракона
                self.log_game_event(user_id, 'dragon_created', {
                    'dragon_name': dragon_data.get('name', 'Дракоша'),
                    'character_trait': character_trait,
                    'initial_gold': dragon_data.get('gold', 50)
                })
                
                self.conn.commit()
                print(f"✅ Создан дракон: {dragon_data.get('name', 'Дракоша')} ({character_trait}) для пользователя {user_id}")
                return True
            return False  # Дракон уже существует
        except Exception as e:
            print(f"❌ Ошибка при создании дракона: {e}")
            self.conn.rollback()
            return False
    
    def get_dragon(self, user_id: int) -> Optional[Dict]:
        """Получает данные дракона"""
        self.cursor.execute(
            "SELECT dragon_data FROM dragons WHERE user_id = ?", 
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result:
            try:
                return json.loads(result[0])
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка декодирования JSON для пользователя {user_id}: {e}")
                return None
        return None
    
    def update_dragon(self, user_id: int, dragon_data: Dict) -> bool:
        """Обновляет данные дракона"""
        try:
            character_trait = dragon_data.get('character', {}).get('основная_черта', 'неженка')
            
            self.cursor.execute('''
                UPDATE dragons 
                SET dragon_data = ?, 
                    name = ?,
                    character_trait = ?,
                    level = ?,
                    experience = ?,
                    gold = ?,
                    last_interaction = CURRENT_TIMESTAMP,
                    total_xp_earned = total_xp_earned + (? - experience),
                    total_gold_earned = total_gold_earned + (? - gold)
                WHERE user_id = ?
            ''', (
                json.dumps(dragon_data, ensure_ascii=False),
                dragon_data.get('name', 'Дракоша'),
                character_trait,
                dragon_data.get('level', 1),
                dragon_data.get('experience', 0),
                dragon_data.get('gold', 50),
                dragon_data.get('experience', 0),
                dragon_data.get('gold', 50),
                user_id
            ))
            
            # Обновляем дни с драконом если прошло больше суток
            self.cursor.execute('''
                UPDATE dragons 
                SET days_with_dragon = days_with_dragon + 1
                WHERE user_id = ? 
                AND DATE(last_interaction) < DATE('now')
                AND DATE('now') > DATE(created_at)
            ''', (user_id,))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления дракона: {e}")
            self.conn.rollback()
            return False
    
    def get_inventory(self, user_id: int) -> Dict[str, int]:
        """Получает инвентарь пользователя - ВСЕГДА возвращает {item_name: quantity}"""
        try:
            self.cursor.execute('''
                SELECT item_name, quantity 
                FROM inventory 
                WHERE user_id = ? AND quantity > 0
                ORDER BY item_name
            ''', (user_id,))
            
            result = self.cursor.fetchall()
            return {row[0]: row[1] for row in result} if result else {}
                
        except Exception as e:
            print(f"❌ Ошибка получения инвентаря: {e}")
            return {}
    
    def get_inventory_with_details(self, user_id: int) -> Dict[str, Dict]:
        """Получает инвентарь с деталями (категория, редкость)"""
        try:
            self.cursor.execute('''
                SELECT item_name, quantity, category, rarity
                FROM inventory 
                WHERE user_id = ? AND quantity > 0
                ORDER BY category, item_name
            ''', (user_id,))
            
            result = self.cursor.fetchall()
            inventory = {}
            
            for row in result:
                item_name, quantity, category, rarity = row
                inventory[item_name] = {
                    'quantity': quantity,
                    'category': category,
                    'rarity': rarity
                }
            
            return inventory
        except Exception as e:
            print(f"❌ Ошибка получения инвентаря с деталями: {e}")
            return {}
    
    def get_inventory_by_category(self, user_id: int) -> Dict[str, Dict[str, int]]:
        """Получает инвентарь сгруппированный по категориям"""
        try:
            self.cursor.execute('''
                SELECT category, item_name, quantity
                FROM inventory 
                WHERE user_id = ? AND quantity > 0
                ORDER BY category, item_name
            ''', (user_id,))
            
            result = self.cursor.fetchall()
            inventory_by_category = {}
            
            for row in result:
                category, item_name, quantity = row
                if category not in inventory_by_category:
                    inventory_by_category[category] = {}
                inventory_by_category[category][item_name] = quantity
            
            return inventory_by_category
        except Exception as e:
            print(f"❌ Ошибка получения инвентаря по категориям: {e}")
            return {}
    
    def update_inventory(self, user_id: int, item_name: str, quantity_change: int, 
                        category: str = None, rarity: str = 'common', price: int = 0) -> bool:
        """Обновляет количество предмета в инвентаре"""
        try:
            # Проверяем, есть ли предмет
            self.cursor.execute(
                "SELECT quantity, category FROM inventory WHERE user_id = ? AND item_name = ?",
                (user_id, item_name)
            )
            result = self.cursor.fetchone()
            
            if result:
                current_quantity, current_category = result
                new_quantity = current_quantity + quantity_change
                
                if new_quantity <= 0:
                    # Удаляем предмет, если количество 0 или меньше
                    self.cursor.execute(
                        "DELETE FROM inventory WHERE user_id = ? AND item_name = ?",
                        (user_id, item_name)
                    )
                else:
                    # Обновляем количество
                    update_category = category if category else current_category
                    self.cursor.execute('''
                        UPDATE inventory 
                        SET quantity = ?, category = COALESCE(?, category),
                            last_used = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND item_name = ?
                    ''', (new_quantity, update_category, user_id, item_name))
            else:
                # Добавляем новый предмет только если количество положительное
                if quantity_change > 0 and category:
                    self.cursor.execute('''
                        INSERT INTO inventory (user_id, item_name, quantity, category, rarity, purchase_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (user_id, item_name, quantity_change, category, rarity, price))
            
            # Записываем в историю покупок если это покупка
            if quantity_change > 0 and price > 0:
                self.cursor.execute('''
                    INSERT INTO purchase_history (user_id, item_name, quantity, price, category)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, item_name, quantity_change, price, category))
                
                # Обновляем статистику покупок
                self.cursor.execute('''
                    UPDATE user_stats 
                    SET total_items_bought = total_items_bought + ?,
                        total_gold_spent = total_gold_spent + ?
                    WHERE user_id = ?
                ''', (quantity_change, price * quantity_change, user_id))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления инвентаря: {e}")
            self.conn.rollback()
            return False
    
    def use_item(self, user_id: int, item_name: str, quantity: int = 1) -> bool:
        """Использует предмет из инвентаря"""
        try:
            self.cursor.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?",
                (user_id, item_name)
            )
            result = self.cursor.fetchone()
            
            if not result or result[0] < quantity:
                return False
            
            new_quantity = result[0] - quantity
            
            if new_quantity <= 0:
                self.cursor.execute(
                    "DELETE FROM inventory WHERE user_id = ? AND item_name = ?",
                    (user_id, item_name)
                )
            else:
                self.cursor.execute('''
                    UPDATE inventory 
                    SET quantity = ?, last_used = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND item_name = ?
                ''', (new_quantity, user_id, item_name))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка использования предмета: {e}")
            self.conn.rollback()
            return False
    
    def add_gold(self, user_id: int, amount: int, source: str = "action") -> bool:
        """Добавляет золото пользователю"""
        try:
            self.cursor.execute(
                "UPDATE dragons SET gold = gold + ? WHERE user_id = ?",
                (amount, user_id)
            )
            
            # Записываем событие получения золота
            if amount > 0:
                self.log_game_event(user_id, 'gold_earned', {
                    'amount': amount,
                    'source': source,
                    'new_balance': self.get_gold(user_id) + amount
                })
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка добавления золота: {e}")
            self.conn.rollback()
            return False
    
    def get_gold(self, user_id: int) -> int:
        """Получает количество золота"""
        self.cursor.execute(
            "SELECT gold FROM dragons WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def add_experience(self, user_id: int, amount: int, source: str = "action") -> Optional[int]:
        """Добавляет опыт дракону и проверяет уровень"""
        try:
            self.cursor.execute(
                "UPDATE dragons SET experience = experience + ? WHERE user_id = ?",
                (amount, user_id)
            )
            
            # Записываем событие получения опыта
            if amount > 0:
                self.log_game_event(user_id, 'xp_earned', {
                    'amount': amount,
                    'source': source
                })
            
            # Проверяем уровень
            self.cursor.execute(
                "SELECT level, experience FROM dragons WHERE user_id = ?",
                (user_id,)
            )
            result = self.cursor.fetchone()
            if not result:
                return None
            
            level, exp = result
            
            # Каждый уровень требует 100 опыта
            new_level = level + (exp // 100)
            if new_level > level:
                self.cursor.execute(
                    "UPDATE dragons SET level = ?, experience = ? WHERE user_id = ?",
                    (new_level, exp % 100, user_id)
                )
                
                # Записываем событие повышения уровня
                self.log_game_event(user_id, 'level_up', {
                    'old_level': level,
                    'new_level': new_level,
                    'total_xp': exp
                })
                
                self.conn.commit()
                return new_level
            
            self.conn.commit()
            return None
        except Exception as e:
            print(f"❌ Ошибка добавления опыта: {e}")
            self.conn.rollback()
            return None
    
    def update_habit(self, user_id: int, habit_type: str, habit_time: str = None) -> Dict:
        """Обновляет привычку и возвращает статистику"""
        try:
            self.cursor.execute('''
                SELECT streak, last_performed, total_performed, best_streak 
                FROM habits 
                WHERE user_id = ? AND habit_type = ?
            ''', (user_id, habit_type))
            
            result = self.cursor.fetchone()
            now = datetime.now()
            today = now.date().isoformat()
            
            response = {
                'streak': 1,
                'total': 1,
                'best_streak': 1,
                'is_new_streak': False
            }
            
            if result:
                streak, last_performed, total, best_streak = result
                last_date = datetime.fromisoformat(last_performed).date() if last_performed else None
                
                if last_date and last_date.isoformat() == today:
                    response.update({
                        'streak': streak,
                        'total': total,
                        'best_streak': best_streak,
                        'is_new_streak': False
                    })
                    return response
                
                if last_date and (now.date() - last_date).days == 1:
                    streak += 1
                    response['is_new_streak'] = True
                else:
                    streak = 1
                    response['is_new_streak'] = False
                
                new_best_streak = max(streak, best_streak)
                total += 1
                
                self.cursor.execute('''
                    UPDATE habits 
                    SET streak = ?, last_performed = CURRENT_TIMESTAMP, 
                        habit_time = COALESCE(?, habit_time),
                        total_performed = ?, best_streak = ?
                    WHERE user_id = ? AND habit_type = ?
                ''', (streak, habit_time, total, new_best_streak, user_id, habit_type))
                
                response.update({
                    'streak': streak,
                    'total': total,
                    'best_streak': new_best_streak
                })
            else:
                response['is_new_streak'] = True
                self.cursor.execute('''
                    INSERT INTO habits (user_id, habit_type, habit_time, streak, last_performed, total_performed, best_streak)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, 1, 1)
                ''', (user_id, habit_type, habit_time))
            
            self.conn.commit()
            return response
        except Exception as e:
            print(f"❌ Ошибка обновления привычки: {e}")
            self.conn.rollback()
            return {'streak': 0, 'total': 0, 'best_streak': 0, 'is_new_streak': False}
    
    def get_habits(self, user_id: int) -> List[Dict]:
        """Получает все привычки пользователя"""
        self.cursor.execute('''
            SELECT habit_type, habit_time, streak, last_performed, total_performed, best_streak 
            FROM habits WHERE user_id = ?
            ORDER BY streak DESC
        ''', (user_id,))
        
        rows = self.cursor.fetchall()
        return [
            {
                'type': row[0], 
                'time': row[1], 
                'streak': row[2],
                'last_performed': row[3],
                'total': row[4],
                'best_streak': row[5]
            }
            for row in rows
        ]
    
    def record_action(self, user_id: int, action: str, dragon_response: str = "", 
                     character_trait: str = "") -> bool:
        """Записывает действие пользователя"""
        try:
            now = datetime.now()
            hour = now.hour
            day_of_week = now.weekday()  # 0 = Monday, 6 = Sunday
            
            self.cursor.execute('''
                INSERT INTO user_actions 
                (user_id, action_type, action_details, dragon_response, character_trait, hour_of_day, day_of_week)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, 'general', action, dragon_response, character_trait, hour, day_of_week))
            
            # Обновляем время последней активности
            self.cursor.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            
            # Обновляем статистику
            stat_column = None
            action_lower = action.lower()
            
            if "кофе" in action_lower:
                stat_column = "total_coffees"
            elif "корм" in action_lower or "feed" in action_lower:
                stat_column = "total_feeds"
            elif "обним" in action_lower or "hug" in action_lower:
                stat_column = "total_hugs"
            elif "игр" in action_lower or "game" in action_lower:
                stat_column = "total_games"
            elif "уход" in action_lower or "care" in action_lower:
                stat_column = "total_care"
            elif "сон" in action_lower or "sleep" in action_lower:
                stat_column = "total_sleep"
            elif "мини" in action_lower and "выигр" in action_lower:
                stat_column = "total_minigames_won"
            elif "мини" in action_lower and "проигр" in action_lower:
                stat_column = "total_minigames_lost"
            
            if stat_column:
                self.cursor.execute(
                    f"UPDATE user_stats SET {stat_column} = {stat_column} + 1 WHERE user_id = ?",
                    (user_id,)
                )
            
            # Обновляем статистику характерных сообщений
            if dragon_response:
                self.cursor.execute('''
                    UPDATE user_stats 
                    SET total_character_messages = total_character_messages + 1
                    WHERE user_id = ?
                ''', (user_id,))
            
            # Обновляем любимое действие и время
            self._update_favorite_stats(user_id, action, hour)
            
            # Обновляем ежедневную серию
            self._update_daily_streak(user_id)
            
            self.conn.commit()
            
            # Записываем игровое событие
            self.log_game_event(user_id, 'action_performed', {
                'action': action,
                'has_response': bool(dragon_response),
                'character_trait': character_trait,
                'hour': hour
            })
            
            return True
        except Exception as e:
            print(f"❌ Ошибка записи действия: {e}")
            self.conn.rollback()
            return False
    
    def _update_favorite_stats(self, user_id: int, action: str, hour: int):
        """Обновляет статистику любимых действий"""
        try:
            # Определяем тип действия
            action_type = "unknown"
            action_lower = action.lower()
            
            if "кофе" in action_lower:
                action_type = "кофе"
            elif "корм" in action_lower:
                action_type = "кормление"
            elif "обним" in action_lower:
                action_type = "обнимашки"
            elif "игр" in action_lower:
                action_type = "игры"
            elif "уход" in action_lower:
                action_type = "уход"
            elif "сон" in action_lower:
                action_type = "сон"
            
            # Определяем время суток
            time_of_day = "unknown"
            if 5 <= hour < 12:
                time_of_day = "утро"
            elif 12 <= hour < 17:
                time_of_day = "день"
            elif 17 <= hour < 22:
                time_of_day = "вечер"
            else:
                time_of_day = "ночь"
            
            # Пока просто обновляем, более сложную логику можно добавить позже
            self.cursor.execute('''
                UPDATE user_stats 
                SET favorite_action = COALESCE(favorite_action, ?),
                    favorite_time = COALESCE(favorite_time, ?)
                WHERE user_id = ? AND (favorite_action IS NULL OR favorite_time IS NULL)
            ''', (action_type, time_of_day, user_id))
            
        except Exception as e:
            print(f"❌ Ошибка обновления любимой статистики: {e}")
    
    def _update_daily_streak(self, user_id: int):
        """Обновляет ежедневную серию посещений"""
        try:
            self.cursor.execute('''
                SELECT daily_streak, last_daily_date, longest_daily_streak 
                FROM user_stats 
                WHERE user_id = ?
            ''', (user_id,))
            
            result = self.cursor.fetchone()
            if not result:
                return
            
            streak, last_date, longest_streak = result
            today = datetime.now().date()
            
            if not last_date:
                # Первое посещение
                new_streak = 1
            else:
                last_date_obj = datetime.strptime(last_date, '%Y-%m-%d').date() if isinstance(last_date, str) else last_date
                
                if (today - last_date_obj).days == 1:
                    # Последовательные дни
                    new_streak = streak + 1
                elif (today - last_date_obj).days == 0:
                    # Уже сегодня заходили
                    new_streak = streak
                else:
                    # Пропустили день
                    new_streak = 1
            
            new_longest_streak = max(new_streak, longest_streak)
            
            self.cursor.execute('''
                UPDATE user_stats 
                SET daily_streak = ?, last_daily_date = DATE('now'), longest_daily_streak = ?
                WHERE user_id = ?
            ''', (new_streak, new_longest_streak, user_id))
            
        except Exception as e:
            print(f"❌ Ошибка обновления ежедневной серии: {e}")
    
    def get_user_settings(self, user_id: int) -> Dict:
        """Получает настройки пользователя"""
        try:
            self.cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            if result:
                settings = dict(result)
                
                # Добавляем текущее время пользователя
                try:
                    user_tz = pytz.timezone(settings.get('timezone', 'Europe/Moscow'))
                    utc_now = datetime.now(pytz.UTC)
                    user_time = utc_now.astimezone(user_tz)
                    settings['current_user_time'] = user_time.strftime('%H:%M')
                    settings['current_user_date'] = user_time.strftime('%d.%m.%Y')
                except:
                    settings['current_user_time'] = "Ошибка времени"
                    settings['current_user_date'] = "Ошибка даты"
                
                return settings
            
            # Создаем настройки по умолчанию, если их нет
            self.cursor.execute('''
                INSERT INTO user_settings (user_id, timezone) 
                VALUES (?, ?)
            ''', (user_id, 'Europe/Moscow'))
            self.conn.commit()
            
            self.cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            return dict(result) if result else {}
        except Exception as e:
            print(f"❌ Ошибка получения настроек: {e}")
            return {}
    
    def update_user_setting(self, user_id: int, key: str, value: Any) -> bool:
        """Обновляет одну настройку пользователя"""
        try:
            # Проверяем существование настроек
            self.cursor.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
            if not self.cursor.fetchone():
                self.cursor.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)",
                    (user_id,)
                )
            
            # Обновляем конкретную настройку
            self.cursor.execute(
                f"UPDATE user_settings SET {key} = ? WHERE user_id = ?",
                (value, user_id)
            )
            
            # Записываем событие изменения настроек
            if key in ['timezone', 'notifications_enabled', 'daily_reminder_time']:
                self.log_game_event(user_id, 'settings_changed', {
                    'setting': key,
                    'new_value': value
                })
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления настройки {key}: {e}")
            self.conn.rollback()
            return False
    
    def update_user_settings(self, user_id: int, settings: Dict) -> bool:
        """Обновляет настройки пользователя"""
        try:
            # Проверяем существование настроек
            self.cursor.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
            if not self.cursor.fetchone():
                self.cursor.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)",
                    (user_id,)
                )
            
            # Формируем запрос обновления
            set_clause = []
            values = []
            
            for key, value in settings.items():
                set_clause.append(f"{key} = ?")
                values.append(value)
            
            values.append(user_id)
            
            query = f"""
                UPDATE user_settings 
                SET {', '.join(set_clause)}
                WHERE user_id = ?
            """
            
            self.cursor.execute(query, values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления настроек: {e}")
            self.conn.rollback()
            return False
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Получает статистику пользователя"""
        try:
            self.cursor.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            if result:
                stats = dict(result)
                # Парсим достижения
                stats['achievements'] = json.loads(stats['achievements']) if stats.get('achievements') else []
                
                # Добавляем дополнительную статистику
                stats['total_actions'] = (
                    stats.get('total_coffees', 0) +
                    stats.get('total_feeds', 0) +
                    stats.get('total_hugs', 0) +
                    stats.get('total_games', 0) +
                    stats.get('total_care', 0) +
                    stats.get('total_sleep', 0)
                )
                
                # Рассчитываем проценты
                total_minigames = stats.get('total_minigames_won', 0) + stats.get('total_minigames_lost', 0)
                if total_minigames > 0:
                    stats['win_rate'] = round((stats.get('total_minigames_won', 0) / total_minigames) * 100, 1)
                else:
                    stats['win_rate'] = 0
                
                # Получаем статистику дракона
                dragon_data = self.get_dragon(user_id)
                if dragon_data:
                    stats['dragon_level'] = dragon_data.get('level', 1)
                    stats['dragon_gold'] = dragon_data.get('gold', 50)
                    stats['dragon_name'] = dragon_data.get('name', 'Дракоша')
                    stats['character_trait'] = dragon_data.get('character', {}).get('основная_черта', 'неженка')
                
                return stats
            
            # Создаем статистику, если её нет
            self.cursor.execute(
                "INSERT INTO user_stats (user_id) VALUES (?)",
                (user_id,)
            )
            self.conn.commit()
            
            self.cursor.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            return dict(result) if result else {}
        except Exception as e:
            print(f"❌ Ошибка получения статистики: {e}")
            return {}
    
    def update_user_stats(self, user_id: int, stats: Dict) -> bool:
        """Обновляет статистику пользователя"""
        try:
            # Проверяем существование статистики
            self.cursor.execute("SELECT 1 FROM user_stats WHERE user_id = ?", (user_id,))
            if not self.cursor.fetchone():
                self.cursor.execute(
                    "INSERT INTO user_stats (user_id) VALUES (?)",
                    (user_id,)
                )
            
            # Обрабатываем достижения
            if 'achievements' in stats and isinstance(stats['achievements'], list):
                stats['achievements'] = json.dumps(stats['achievements'], ensure_ascii=False)
            
            # Формируем запрос обновления
            set_clause = []
            values = []
            
            for key, value in stats.items():
                set_clause.append(f"{key} = ?")
                values.append(value)
            
            values.append(user_id)
            
            query = f"""
                UPDATE user_stats 
                SET {', '.join(set_clause)}
                WHERE user_id = ?
            """
            
            self.cursor.execute(query, values)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления статистики: {e}")
            self.conn.rollback()
            return False
    
    def add_achievement(self, user_id: int, achievement: Dict) -> bool:
        """Добавляет достижение пользователю"""
        try:
            stats = self.get_user_stats(user_id)
            achievements = stats.get('achievements', [])
            
            # Проверяем, нет ли уже такого достижения
            achievement_id = achievement.get('id')
            for ach in achievements:
                if ach.get('id') == achievement_id:
                    return False
            
            achievements.append(achievement)
            stats['achievements'] = achievements
            
            # Записываем событие получения достижения
            self.log_game_event(user_id, 'achievement_unlocked', {
                'achievement_id': achievement_id,
                'achievement_name': achievement.get('name', 'Unknown'),
                'total_achievements': len(achievements)
            })
            
            return self.update_user_stats(user_id, stats)
        except Exception as e:
            print(f"❌ Ошибка добавления достижения: {e}")
            return False
    
    def get_all_users_with_dragons(self) -> List[int]:
        """Получает всех пользователей с драконами"""
        try:
            self.cursor.execute(
                "SELECT user_id FROM dragons WHERE user_id IS NOT NULL"
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения пользователей с драконами: {e}")
            return []
    
    def get_active_users(self, hours: int = 24) -> List[int]:
        """Получает пользователей, активных за последние N часов"""
        try:
            time_threshold = datetime.now() - timedelta(hours=hours)
            self.cursor.execute(
                "SELECT user_id FROM users WHERE last_active >= ?",
                (time_threshold.isoformat(),)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения активных пользователей: {e}")
            return []
    
    def get_users_with_notifications_enabled(self) -> List[int]:
        """Получает пользователей с включенными уведомлениями"""
        try:
            self.cursor.execute('''
                SELECT user_id FROM user_settings 
                WHERE notifications_enabled = 1
            ''')
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения пользователей с уведомлениями: {e}")
            return []
    
    def get_users_by_timezone(self, timezone: str) -> List[int]:
        """Получает пользователей по часовому поясу"""
        try:
            self.cursor.execute(
                "SELECT user_id FROM user_settings WHERE timezone = ?",
                (timezone,)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения пользователей по часовому поясу: {e}")
            return []
    
    def get_feeding_history(self, user_id: int, days: int = 7) -> List[datetime]:
        """Получает историю кормлений за последние N дней"""
        try:
            time_threshold = datetime.now() - timedelta(days=days)
            self.cursor.execute('''
                SELECT created_at FROM user_actions 
                WHERE user_id = ? 
                AND (action_type LIKE '%корм%' OR action_type LIKE '%feed%')
                AND created_at >= ?
                ORDER BY created_at DESC
            ''', (user_id, time_threshold.isoformat()))
            
            return [datetime.fromisoformat(row[0]) for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения истории кормлений: {e}")
            return []
    
    def get_daily_actions(self, user_id: int, date: datetime = None) -> Dict[str, int]:
        """Получает количество действий за день"""
        try:
            if date is None:
                date = datetime.now()
            
            date_str = date.date().isoformat()
            
            self.cursor.execute('''
                SELECT action_type, COUNT(*) as count
                FROM user_actions 
                WHERE user_id = ? AND DATE(created_at) = ?
                GROUP BY action_type
                ORDER BY count DESC
            ''', (user_id, date_str))
            
            result = self.cursor.fetchall()
            return {row[0]: row[1] for row in result} if result else {}
        except Exception as e:
            print(f"❌ Ошибка получения ежедневных действий: {e}")
            return {}
    
    def get_dragon_count(self) -> int:
        """Получает общее количество драконов"""
        self.cursor.execute("SELECT COUNT(*) FROM dragons")
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def get_top_dragons(self, limit: int = 10) -> List[Dict]:
        """Получает топ драконов по уровню"""
        self.cursor.execute('''
            SELECT d.user_id, d.name, d.level, d.experience, d.character_trait,
                   d.total_xp_earned, d.days_with_dragon,
                   u.username
            FROM dragons d
            LEFT JOIN users u ON d.user_id = u.user_id
            ORDER BY d.level DESC, d.experience DESC, d.total_xp_earned DESC
            LIMIT ?
        ''', (limit,))
        
        rows = self.cursor.fetchall()
        return [
            {
                'user_id': row[0],
                'name': row[1],
                'level': row[2],
                'experience': row[3],
                'character_trait': row[4],
                'total_xp_earned': row[5],
                'days_with_dragon': row[6],
                'username': row[7] or 'Аноним'
            }
            for row in rows
        ] if rows else []
    
    def get_dragon_statistics(self) -> Dict:
        """Получает общую статистику по всем драконам"""
        try:
            stats = {}
            
            # Общее количество драконов
            self.cursor.execute("SELECT COUNT(*) FROM dragons")
            stats['total_dragons'] = self.cursor.fetchone()[0]
            
            # Средний уровень
            self.cursor.execute("SELECT AVG(level) FROM dragons")
            stats['avg_level'] = round(self.cursor.fetchone()[0] or 0, 1)
            
            # Общее золото
            self.cursor.execute("SELECT SUM(gold) FROM dragons")
            stats['total_gold'] = self.cursor.fetchone()[0] or 0
            
            # Распределение по характерам
            self.cursor.execute('''
                SELECT character_trait, COUNT(*) as count
                FROM dragons
                GROUP BY character_trait
                ORDER BY count DESC
            ''')
            character_stats = self.cursor.fetchall()
            stats['character_distribution'] = {row[0]: row[1] for row in character_stats}
            
            # Самый популярный характер
            if character_stats:
                stats['most_popular_character'] = character_stats[0][0]
            
            return stats
        except Exception as e:
            print(f"❌ Ошибка получения статистики драконов: {e}")
            return {}
    
    def cleanup_old_data(self, days: int = 30) -> int:
        """Очищает старые данные (действия старше N дней)"""
        try:
            time_threshold = datetime.now() - timedelta(days=days)
            
            # Удаляем старые действия
            self.cursor.execute(
                "DELETE FROM user_actions WHERE created_at < ?",
                (time_threshold.isoformat(),)
            )
            actions_deleted = self.cursor.rowcount
            
            # Удаляем старые игровые события
            self.cursor.execute(
                "DELETE FROM game_events WHERE created_at < ?",
                (time_threshold.isoformat(),)
            )
            events_deleted = self.cursor.rowcount
            
            # Удаляем старую историю покупок
            self.cursor.execute(
                "DELETE FROM purchase_history WHERE purchased_at < ?",
                (time_threshold.isoformat(),)
            )
            purchases_deleted = self.cursor.rowcount
            
            self.conn.commit()
            return actions_deleted + events_deleted + purchases_deleted
        except Exception as e:
            print(f"❌ Ошибка очистки данных: {e}")
            return 0
    
    def get_user_timezone(self, user_id: int) -> str:
        """Получает часовой пояс пользователя"""
        settings = self.get_user_settings(user_id)
        return settings.get('timezone', 'Europe/Moscow')
    
    def set_user_timezone(self, user_id: int, timezone: str) -> bool:
        """Устанавливает часовой пояс пользователя"""
        return self.update_user_settings(user_id, {'timezone': timezone})
    
    def reset_user_data(self, user_id: int) -> bool:
        """Сбрасывает данные пользователя (кроме самого пользователя)"""
        try:
            # Удаляем дракона
            self.cursor.execute("DELETE FROM dragons WHERE user_id = ?", (user_id,))
            # Удаляем инвентарь
            self.cursor.execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
            # Удаляем привычки
            self.cursor.execute("DELETE FROM habits WHERE user_id = ?", (user_id,))
            # Удаляем действия
            self.cursor.execute("DELETE FROM user_actions WHERE user_id = ?", (user_id,))
            # Удаляем игровые события
            self.cursor.execute("DELETE FROM game_events WHERE user_id = ?", (user_id,))
            # Удаляем историю покупок
            self.cursor.execute("DELETE FROM purchase_history WHERE user_id = ?", (user_id,))
            # Сбрасываем настройки
            self.cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
            # Сбрасываем статистику
            self.cursor.execute("DELETE FROM user_stats WHERE user_id = ?", (user_id,))
            
            # Создаем настройки и статистику по умолчанию
            self.cursor.execute(
                "INSERT INTO user_settings (user_id, timezone) VALUES (?, ?)",
                (user_id, 'Europe/Moscow')
            )
            self.cursor.execute(
                "INSERT INTO user_stats (user_id) VALUES (?)",
                (user_id,)
            )
            
            self.conn.commit()
            print(f"✅ Данные пользователя {user_id} сброшены")
            return True
        except Exception as e:
            print(f"❌ Ошибка сброса данных: {e}")
            self.conn.rollback()
            return False
    
    def backup_dragon_data(self, user_id: int) -> Optional[Dict]:
        """Создает бэкап данных дракона"""
        try:
            dragon = self.get_dragon(user_id)
            if not dragon:
                return None
            
            inventory = self.get_inventory(user_id)
            habits = self.get_habits(user_id)
            stats = self.get_user_stats(user_id)
            settings = self.get_user_settings(user_id)
            
            return {
                'dragon': dragon,
                'inventory': inventory,
                'habits': habits,
                'stats': stats,
                'settings': settings,
                'backup_date': datetime.now().isoformat(),
                'user_id': user_id
            }
        except Exception as e:
            print(f"❌ Ошибка создания бэкапа: {e}")
            return None
    
    def get_last_action_time(self, user_id: int, action_type: str = None) -> Optional[datetime]:
        """Получает время последнего действия"""
        try:
            if action_type:
                self.cursor.execute('''
                    SELECT created_at FROM user_actions 
                    WHERE user_id = ? AND action_details LIKE ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (user_id, f"%{action_type}%"))
            else:
                self.cursor.execute('''
                    SELECT created_at FROM user_actions 
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (user_id,))
            
            result = self.cursor.fetchone()
            if result and result[0]:
                return datetime.fromisoformat(result[0])
            return None
        except Exception as e:
            print(f"❌ Ошибка получения времени действия: {e}")
            return None
    
    def get_last_action(self, user_id: int) -> Optional[str]:
        """Получает описание последнего действия"""
        try:
            self.cursor.execute('''
                SELECT action_details, dragon_response, created_at 
                FROM user_actions 
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            
            result = self.cursor.fetchone()
            if result:
                details, response, timestamp = result
                time_ago = self._get_time_ago(datetime.fromisoformat(timestamp))
                return f"{details} ({time_ago})" + (f"\nОтвет: {response}" if response else "")
            return None
        except Exception as e:
            print(f"❌ Ошибка получения последнего действия: {e}")
            return None
    
    def _get_time_ago(self, past_time: datetime) -> str:
        """Возвращает строку 'сколько времени назад'"""
        now = datetime.now()
        diff = now - past_time
        
        if diff.days > 0:
            return f"{diff.days} дней назад"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours} часов назад"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes} минут назад"
        else:
            return "только что"
    
    def get_action_history(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Получает историю действий пользователя"""
        try:
            self.cursor.execute('''
                SELECT action_type, action_details, dragon_response, character_trait, created_at 
                FROM user_actions 
                WHERE user_id = ?
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = self.cursor.fetchall()
            return [
                {
                    'type': row[0],
                    'details': row[1],
                    'response': row[2],
                    'character': row[3],
                    'time': datetime.fromisoformat(row[4]),
                    'time_ago': self._get_time_ago(datetime.fromisoformat(row[4]))
                }
                for row in rows
            ]
        except Exception as e:
            print(f"❌ Ошибка получения истории действий: {e}")
            return []
    
    def get_character_action_stats(self, user_id: int) -> Dict[str, int]:
        """Получает статистику действий по характерам"""
        try:
            self.cursor.execute('''
                SELECT character_trait, COUNT(*) as count
                FROM user_actions 
                WHERE user_id = ? AND character_trait IS NOT NULL AND character_trait != ''
                GROUP BY character_trait
                ORDER BY count DESC
            ''', (user_id,))
            
            rows = self.cursor.fetchall()
            return {row[0]: row[1] for row in rows} if rows else {}
        except Exception as e:
            print(f"❌ Ошибка получения статистики характеров: {e}")
            return {}
    
    def log_game_event(self, user_id: int, event_type: str, event_data: Dict = None):
        """Записывает игровое событие для аналитики"""
        try:
            data_json = json.dumps(event_data or {}, ensure_ascii=False)
            self.cursor.execute('''
                INSERT INTO game_events (user_id, event_type, event_data)
                VALUES (?, ?, ?)
            ''', (user_id, event_type, data_json))
            self.conn.commit()
        except Exception as e:
            print(f"❌ Ошибка записи игрового события: {e}")
    
    def get_recent_events(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получает последние игровые события"""
        try:
            self.cursor.execute('''
                SELECT event_type, event_data, created_at
                FROM game_events
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (user_id, limit))
            
            rows = self.cursor.fetchall()
            events = []
            
            for row in rows:
                event_type, event_data_json, created_at = row
                try:
                    event_data = json.loads(event_data_json) if event_data_json else {}
                except:
                    event_data = {}
                
                events.append({
                    'type': event_type,
                    'data': event_data,
                    'time': datetime.fromisoformat(created_at),
                    'time_ago': self._get_time_ago(datetime.fromisoformat(created_at))
                })
            
            return events
        except Exception as e:
            print(f"❌ Ошибка получения событий: {e}")
            return []
    
    def get_purchase_history(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Получает историю покупок"""
        try:
            self.cursor.execute('''
                SELECT item_name, quantity, price, category, purchased_at
                FROM purchase_history
                WHERE user_id = ?
                ORDER BY purchased_at DESC
                LIMIT ?
            ''', (user_id, limit))
            
            rows = self.cursor.fetchall()
            return [
                {
                    'item': row[0],
                    'quantity': row[1],
                    'price': row[2],
                    'category': row[3],
                    'time': datetime.fromisoformat(row[4]),
                    'total': row[1] * row[2]
                }
                for row in rows
            ]
        except Exception as e:
            print(f"❌ Ошибка получения истории покупок: {e}")
            return []
    
    def get_daily_report(self, user_id: int, date: datetime = None) -> Dict:
        """Получает ежедневный отчет о деятельности"""
        try:
            if date is None:
                date = datetime.now()
            
            date_str = date.date().isoformat()
            
            # Получаем статистику за день
            self.cursor.execute('''
                SELECT 
                    COUNT(*) as total_actions,
                    COUNT(DISTINCT action_type) as unique_actions,
                    GROUP_CONCAT(DISTINCT character_trait) as characters_used
                FROM user_actions 
                WHERE user_id = ? AND DATE(created_at) = ?
            ''', (user_id, date_str))
            
            stats_row = self.cursor.fetchone()
            
            # Получаем самые частые действия
            self.cursor.execute('''
                SELECT action_type, COUNT(*) as count
                FROM user_actions 
                WHERE user_id = ? AND DATE(created_at) = ?
                GROUP BY action_type
                ORDER BY count DESC
                LIMIT 3
            ''', (user_id, date_str))
            
            top_actions = self.cursor.fetchall()
            
            # Получаем изменение уровня и золота
            self.cursor.execute('''
                SELECT level, experience, gold
                FROM dragons
                WHERE user_id = ?
            ''', (user_id,))
            
            dragon_row = self.cursor.fetchone()
            
            report = {
                'date': date_str,
                'total_actions': stats_row[0] if stats_row else 0,
                'unique_actions': stats_row[1] if stats_row else 0,
                'characters_used': (stats_row[2] or '').split(',') if stats_row and stats_row[2] else [],
                'top_actions': [{'action': row[0], 'count': row[1]} for row in top_actions],
                'dragon_level': dragon_row[0] if dragon_row else 1,
                'dragon_gold': dragon_row[2] if dragon_row else 0,
                'has_activity': (stats_row and stats_row[0] > 0) if stats_row else False
            }
            
            return report
        except Exception as e:
            print(f"❌ Ошибка получения ежедневного отчета: {e}")
            return {}
    
    def close(self):
        """Закрывает соединение с базой"""
        try:
            self.conn.close()
            print("✅ Соединение с базой данных закрыто")
        except Exception as e:
            print(f"❌ Ошибка закрытия базы: {e}")


# ===== СОЗДАНИЕ ГЛОБАЛЬНОГО ЭКЗЕМПЛЯРА =====
_db_instance = None

def get_db(db_name="dragons.db"):
    """Получает глобальный экземпляр базы данных (Singleton)"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DragonDatabase(db_name)
        dragon_count = _db_instance.get_dragon_count()
        dragon_stats = _db_instance.get_dragon_statistics()
        
        print(f"✅ База данных инициализирована.")
        print(f"   Драконов в базе: {dragon_count}")
        if dragon_stats:
            print(f"   Средний уровень: {dragon_stats.get('avg_level', 0)}")
            if 'most_popular_character' in dragon_stats:
                print(f"   Самый популярный характер: {dragon_stats['most_popular_character']}")
    return _db_instance

def init_database(db_name="dragons.db"):
    """Явная инициализация базы данных"""
    return get_db(db_name)


# СОЗДАЕМ ЭКЗЕМПЛЯР СРАЗУ ПРИ ИМПОРТЕ
db = get_db()  # Это ЭКЗЕМПЛЯР, а не функция!

print(f"🐉 Модуль базы данных v6.0 (исправленный) загружен.")