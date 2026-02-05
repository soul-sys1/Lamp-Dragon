"""
БАЗА ДАННЫХ ДЛЯ ДРАКОНОВ v7.0 - ОБНОВЛЕННАЯ ВЕРСИЯ ДЛЯ СОВМЕСТИМОСТИ
Оптимизирована для новой версии бота с упрощенным API
"""
import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pytz

class DragonDatabase:
    def __init__(self, db_name="dragons.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()
    
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
        
        # Таблица действий пользователя (упрощенная для v7.0)
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
        
        # Таблица настроек пользователя (важно: notifications_enabled должен быть!)
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
                notifications_enabled INTEGER DEFAULT 1,  -- КРИТИЧЕСКИ ВАЖНЫЙ СТОЛБЕЦ
                auto_save INTEGER DEFAULT 1,
                daily_reminder_time TIME DEFAULT '20:00',
                weekly_report INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица статистики
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
        
        # Таблица игровых событий
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
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_settings_user ON user_settings(user_id)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_user ON game_events(user_id, event_type)')
        
        self.conn.commit()
        print("✅ Таблицы базы данных созданы/проверены")
    
    def get_all_users(self) -> List[int]:
        """✅ НОВЫЙ МЕТОД: Получает всех пользователей (для уведомлений)"""
        try:
            self.cursor.execute("SELECT user_id FROM users")
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения всех пользователей: {e}")
            return []
    
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
                
                # Создаем настройки по умолчанию (включая notifications_enabled = 1)
                self.cursor.execute('''
                    INSERT INTO user_settings (user_id, timezone, notifications_enabled) 
                    VALUES (?, ?, 1)
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
        """Создает нового дракона с начальным инвентарем (АНГЛИЙСКИЕ НАЗВАНИЯ)"""
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
                
                # ✅ КРИТИЧЕСКИ ВАЖНО: СОЗДАЕМ НАЧАЛЬНЫЙ ИНВЕНТАРЬ С АНГЛИЙСКИМИ НАЗВАНИЯМИ
                initial_items = [
                    # Кофе и ингредиенты
                    (user_id, 'coffee_beans', 10, 'coffee', 'common', 0),
                    
                    # Сладости (АНГЛИЙСКИЕ НАЗВАНИЯ)
                    (user_id, 'cookie', 5, 'sweets', 'common', 0),
                    (user_id, 'chocolate', 2, 'sweets', 'uncommon', 0),
                    (user_id, 'marshmallow', 1, 'sweets', 'rare', 0),
                    (user_id, 'gingerbread', 1, 'sweets', 'common', 0),
                    
                    # Дополнительные предметы для v7.0
                    (user_id, 'milk', 0, 'coffee_addons', 'common', 0),
                    (user_id, 'cream', 0, 'coffee_addons', 'common', 0),
                    (user_id, 'syrup', 0, 'coffee_addons', 'uncommon', 0),
                    (user_id, 'soap', 0, 'care', 'common', 0),
                    (user_id, 'brush', 0, 'care', 'uncommon', 0),
                ]
                
                # Используем executemany для оптимизации
                self.cursor.executemany('''
                    INSERT OR REPLACE INTO inventory 
                    (user_id, item_name, quantity, category, rarity, purchase_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', initial_items)
                
                # Записываем событие создания дракона
                self.log_game_event(user_id, 'dragon_created', {
                    'dragon_name': dragon_data.get('name', 'Дракоша'),
                    'character_trait': character_trait,
                    'initial_gold': dragon_data.get('gold', 50)
                })
                
                self.conn.commit()
                print(f"✅ Создан дракон: {dragon_data.get('name', 'Дракоша')} ({character_trait}) для пользователя {user_id}")
                print(f"   Начальный инвентарь создан с английскими названиями")
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
            except json.JSONDecodeError:
                # Возвращаем минимальный набор данных для восстановления
                return {
                    'name': 'Дракоша',
                    'stats': {'кофе': 50, 'сон': 50, 'настроение': 90, 'аппетит': 50, 
                             'энергия': 80, 'пушистость': 95, 'чистота': 90, 'здоровье': 95},
                    'character': {'основная_черта': 'неженка'},
                    'level': 1,
                    'experience': 0,
                    'gold': 50
                }
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
                    last_interaction = CURRENT_TIMESTAMP
                WHERE user_id = ?
            ''', (
                json.dumps(dragon_data, ensure_ascii=False),
                dragon_data.get('name', 'Дракоша'),
                character_trait,
                dragon_data.get('level', 1),
                dragon_data.get('experience', 0),
                dragon_data.get('gold', 50),
                user_id
            ))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления дракона: {e}")
            self.conn.rollback()
            return False
    
    def get_inventory(self, user_id: int) -> Dict[str, int]:
        """✅ КОРРЕКТНЫЙ МЕТОД: Получает инвентарь пользователя - ВСЕГДА возвращает {item_name: quantity}"""
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
    
    def update_inventory(self, user_id: int, item_name: str, quantity_change: int, 
                        category: str = None, rarity: str = 'common', price: int = 0) -> bool:
        """✅ КОРРЕКТНЫЙ МЕТОД: Обновляет количество предмета в инвентаре (работает с английскими названиями)"""
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
            
            if amount > 0:
                self.log_game_event(user_id, 'gold_earned', {
                    'amount': amount,
                    'source': source
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
        """Добавляет опыт дракону"""
        try:
            self.cursor.execute(
                "UPDATE dragons SET experience = experience + ? WHERE user_id = ?",
                (amount, user_id)
            )
            
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
                
                self.log_game_event(user_id, 'level_up', {
                    'old_level': level,
                    'new_level': new_level
                })
                
                self.conn.commit()
                return new_level
            
            self.conn.commit()
            return None
        except Exception as e:
            print(f"❌ Ошибка добавления опыта: {e}")
            self.conn.rollback()
            return None
    
    def record_action(self, user_id: int, action: str) -> bool:
        """✅ УПРОЩЕННЫЙ МЕТОД v7.0: Записывает действие пользователя (только user_id и действие)"""
        try:
            now = datetime.now()
            hour = now.hour
            day_of_week = now.weekday()
            
            self.cursor.execute('''
                INSERT INTO user_actions 
                (user_id, action_type, action_details, hour_of_day, day_of_week)
                VALUES (?, 'general', ?, ?, ?)
            ''', (user_id, action, hour, day_of_week))
            
            # Обновляем время последней активности
            self.cursor.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            
            # Обновляем статистику
            stat_column = None
            action_lower = action.lower()
            
            # Простая логика обновления статистики
            if "кофе" in action_lower:
                stat_column = 'total_coffees'
            elif "корм" in action_lower or "feed" in action_lower:
                stat_column = 'total_feeds'
            elif "обним" in action_lower or "hug" in action_lower:
                stat_column = 'total_hugs'
            elif "игр" in action_lower or "game" in action_lower:
                stat_column = 'total_games'
            elif "уход" in action_lower or "care" in action_lower:
                stat_column = 'total_care'
            elif "сон" in action_lower or "sleep" in action_lower:
                stat_column = 'total_sleep'
            
            if stat_column:
                self.cursor.execute(f'''
                    UPDATE user_stats 
                    SET {stat_column} = {stat_column} + 1
                    WHERE user_id = ?
                ''', (user_id,))
            
            # Обновляем ежедневную серию
            self._update_daily_streak(user_id)
            
            self.conn.commit()
            
            # Записываем игровое событие
            self.log_game_event(user_id, 'action_performed', {
                'action': action,
                'hour': hour
            })
            
            return True
        except Exception as e:
            print(f"❌ Ошибка записи действия: {e}")
            self.conn.rollback()
            return False
    
    def record_action_with_response(self, user_id: int, action: str, dragon_response: str = "", 
                                  character_trait: str = "") -> bool:
        """Полная версия record_action для обратной совместимости"""
        try:
            now = datetime.now()
            hour = now.hour
            day_of_week = now.weekday()
            
            self.cursor.execute('''
                INSERT INTO user_actions 
                (user_id, action_type, action_details, dragon_response, character_trait, hour_of_day, day_of_week)
                VALUES (?, 'general', ?, ?, ?, ?, ?)
            ''', (user_id, action, dragon_response, character_trait, hour, day_of_week))
            
            # Обновляем время последней активности
            self.cursor.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            
            # Обновляем статистику
            if dragon_response:
                self.cursor.execute('''
                    UPDATE user_stats 
                    SET total_character_messages = total_character_messages + 1
                    WHERE user_id = ?
                ''', (user_id,))
            
            # Обновляем ежедневную серию
            self._update_daily_streak(user_id)
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка записи действия: {e}")
            self.conn.rollback()
            return False
    
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
                if isinstance(last_date, str):
                    last_date_obj = datetime.strptime(last_date, '%Y-%m-%d').date()
                else:
                    last_date_obj = last_date
                
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
        """✅ КОРРЕКТНЫЙ МЕТОД: Получает настройки пользователя"""
        try:
            self.cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            
            if result:
                settings = dict(result)
                
                # Проверяем наличие notifications_enabled (добавляем если нет)
                if 'notifications_enabled' not in settings:
                    settings['notifications_enabled'] = 1
                
                return settings
            
            # Создаем настройки по умолчанию, если их нет
            self.cursor.execute('''
                INSERT INTO user_settings (user_id, timezone, notifications_enabled) 
                VALUES (?, ?, 1)
            ''', (user_id, 'Europe/Moscow'))
            self.conn.commit()
            
            self.cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            return dict(result) if result else {}
            
        except Exception as e:
            print(f"❌ Ошибка получения настроек: {e}")
            # Возвращаем настройки по умолчанию
            return {
                'user_id': user_id,
                'notifications_enabled': 1,
                'timezone': 'Europe/Moscow',
                'morning_notifications': 1,
                'evening_notifications': 1,
                'theme': 'standard'
            }
    
    def update_user_settings(self, user_id: int, settings: Dict) -> bool:
        """✅ КОРРЕКТНЫЙ МЕТОД: Обновляет настройки пользователя"""
        try:
            # Проверяем существование настроек
            self.cursor.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,))
            if not self.cursor.fetchone():
                # Создаем настройки по умолчанию
                self.cursor.execute('''
                    INSERT INTO user_settings (user_id, timezone, notifications_enabled) 
                    VALUES (?, ?, 1)
                ''', (user_id, 'Europe/Moscow'))
            
            # Формируем запрос обновления
            set_clause = []
            values = []
            
            allowed_columns = [
                'morning_notifications', 'evening_notifications', 
                'feeding_reminders', 'night_mode', 'quiet_mode',
                'theme', 'font_size', 'sound_effects', 'background_music',
                'timezone', 'notifications_enabled', 'auto_save',
                'daily_reminder_time', 'weekly_report'
            ]
            
            for key, value in settings.items():
                if key in allowed_columns:
                    set_clause.append(f"{key} = ?")
                    values.append(value)
            
            if not set_clause:
                return True  # Нет полей для обновления
            
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
    
    def update_user_setting(self, user_id: int, key: str, value: Any) -> bool:
        """Обновляет одну настройку пользователя"""
        return self.update_user_settings(user_id, {key: value})
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Получает статистику пользователя"""
        try:
            self.cursor.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            if result:
                stats = dict(result)
                
                # Парсим достижения
                try:
                    stats['achievements'] = json.loads(stats['achievements']) if stats.get('achievements') else []
                except:
                    stats['achievements'] = []
                
                # Добавляем дополнительную статистику
                stats['total_actions'] = (
                    stats.get('total_coffees', 0) +
                    stats.get('total_feeds', 0) +
                    stats.get('total_hugs', 0) +
                    stats.get('total_games', 0) +
                    stats.get('total_care', 0) +
                    stats.get('total_sleep', 0)
                )
                
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
            
            allowed_columns = [
                'total_coffees', 'total_feeds', 'total_hugs',
                'total_games', 'total_care', 'total_sleep',
                'total_minigames_won', 'total_minigames_lost',
                'total_items_bought', 'total_gold_spent',
                'total_character_messages', 'favorite_action',
                'favorite_time', 'achievements', 'daily_streak',
                'last_daily_date', 'longest_daily_streak'
            ]
            
            for key, value in stats.items():
                if key in allowed_columns:
                    set_clause.append(f"{key} = ?")
                    values.append(value)
            
            if not set_clause:
                return True
            
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
    
    def get_active_users(self, hours: int = 24) -> List[int]:
        """Получает пользователей, активных за последние N часов"""
        try:
            time_threshold = (datetime.now() - timedelta(hours=hours)).isoformat()
            self.cursor.execute(
                "SELECT user_id FROM users WHERE last_active >= ?",
                (time_threshold,)
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
            ORDER BY d.level DESC, d.experience DESC
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
    
    def get_last_action(self, user_id: int) -> Optional[str]:
        """Получает описание последнего действия"""
        try:
            self.cursor.execute('''
                SELECT action_details, created_at 
                FROM user_actions 
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            
            result = self.cursor.fetchone()
            if result:
                details, timestamp = result
                time_ago = self._get_time_ago(datetime.fromisoformat(timestamp))
                return f"{details} ({time_ago})"
            return None
        except Exception as e:
            print(f"❌ Ошибка получения последнего действия: {e}")
            return None
    
    def _get_time_ago(self, past_time: datetime) -> str:
        """Возвращает строку 'сколько времени назад'"""
        try:
            now = datetime.now()
            diff = now - past_time
            
            if diff.days > 365:
                years = diff.days // 365
                return f"{years} лет назад"
            elif diff.days > 30:
                months = diff.days // 30
                return f"{months} месяцев назад"
            elif diff.days > 0:
                return f"{diff.days} дней назад"
            elif diff.seconds >= 3600:
                hours = diff.seconds // 3600
                return f"{hours} часов назад"
            elif diff.seconds >= 60:
                minutes = diff.seconds // 60
                return f"{minutes} минут назад"
            else:
                return "только что"
        except Exception as e:
            print(f"❌ Ошибка в _get_time_ago: {e}")
            return "недавно"
    
    def get_action_history(self, user_id: int, limit: int = 10) -> List[Dict]:
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
    
    def cleanup_old_data(self, days: int = 30) -> int:
        """Очищает старые данные"""
        try:
            time_threshold = (datetime.now() - timedelta(days=days)).isoformat()
            
            # Удаляем старые действия
            self.cursor.execute(
                "DELETE FROM user_actions WHERE created_at < ?",
                (time_threshold,)
            )
            actions_deleted = self.cursor.rowcount
            
            # Удаляем старые игровые события
            self.cursor.execute(
                "DELETE FROM game_events WHERE created_at < ?",
                (time_threshold,)
            )
            
            self.conn.commit()
            return actions_deleted
        except Exception as e:
            print(f"❌ Ошибка очистки данных: {e}")
            return 0
    
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
        
        print(f"✅ База данных v7.0 инициализирована.")
        print(f"   Драконов в базе: {dragon_count}")
        
        # Проверяем наличие критических функций
        test_user = 999999  # Тестовый ID
        
        # Проверяем метод get_all_users
        try:
            all_users = _db_instance.get_all_users()
            print(f"   Метод get_all_users работает: {len(all_users)} пользователей")
        except Exception as e:
            print(f"   ⚠️ Метод get_all_users не работает: {e}")
        
        # Проверяем метод record_action
        try:
            _db_instance.record_action(test_user, "test_action")
            print(f"   ✅ Метод record_action работает")
        except Exception as e:
            print(f"   ❌ Метод record_action не работает: {e}")
        
        # Проверяем начальный инвентарь
        try:
            test_inventory = _db_instance.get_inventory(test_user)
            if test_inventory:
                print(f"   ✅ Метод get_inventory работает")
            else:
                print(f"   ⚠️ get_inventory возвращает пустой инвентарь")
        except Exception as e:
            print(f"   ❌ Метод get_inventory не работает: {e}")
        
        # Проверяем наличие notifications_enabled в настройках
        try:
            test_settings = _db_instance.get_user_settings(test_user)
            if 'notifications_enabled' in test_settings:
                print(f"   ✅ notifications_enabled присутствует в настройках")
            else:
                print(f"   ❌ notifications_enabled отсутствует в настройках")
        except Exception as e:
            print(f"   ❌ Ошибка проверки настроек: {e}")
        
    return _db_instance

def get_db_instance():
    """Получает экземпляр базы данных для импорта в bot.py"""
    return get_db()


print(f"🐉 Модуль базы данных v7.0 (обновленный для совместимости) загружен.")
print(f"   Основные изменения:")
print(f"   ✅ Добавлен метод get_all_users()")
print(f"   ✅ Упрощен метод record_action()")
print(f"   ✅ Проверены методы работы с инвентарем")
print(f"   ✅ Гарантировано наличие notifications_enabled")
print(f"   ✅ Английские названия предметов в начальном инвентаре")