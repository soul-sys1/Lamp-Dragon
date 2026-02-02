"""
БАЗА ДАННЫХ ДЛЯ ДРАКОНОВ v5.1
Хранит всех драконов в SQLite базе с обновленными функциями
Вода удалена из начального инвентаря
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

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
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица инвентаря
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
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
                last_performed TIMESTAMP
            )
        ''')
        
        # Таблица действий пользователя (для уведомлений)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action_type TEXT NOT NULL,
                action_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица настроек пользователя
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
                timezone TEXT DEFAULT 'UTC',
                notifications_enabled INTEGER DEFAULT 1
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
                achievements TEXT DEFAULT '[]'
            )
        ''')
        
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
                self.cursor.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)",
                    (user_id,)
                )
                
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
        """Создает нового дракона"""
        try:
            if not self.dragon_exists(user_id):
                # Сначала убедимся, что пользователь существует
                if not self.user_exists(user_id):
                    self.create_user(user_id, "Unknown")
                
                self.cursor.execute('''
                    INSERT INTO dragons 
                    (user_id, name, character_trait, level, experience, gold, dragon_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    dragon_data.get('name', 'Дракоша'),
                    dragon_data.get('character', {}).get('основная_черта', 'неженка'),
                    dragon_data.get('level', 1),
                    dragon_data.get('experience', 0),
                    dragon_data.get('gold', 50),
                    json.dumps(dragon_data, ensure_ascii=False)
                ))
                
                # Создаем начальный инвентарь (ВОДА УДАЛЕНА)
                initial_items = [
                    (user_id, 'кофейные_зерна', 10),
                    (user_id, 'печенье', 5),
                    (user_id, 'шоколад', 2),
                    (user_id, 'зефир', 1),
                    (user_id, 'пряник', 1)
                ]
                
                for item in initial_items:
                    try:
                        self.cursor.execute('''
                            INSERT INTO inventory (user_id, item_name, quantity)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id, item_name) 
                            DO UPDATE SET quantity = quantity + excluded.quantity
                        ''', item)
                    except Exception as e:
                        print(f"❌ Ошибка добавления предмета {item[1]}: {e}")
                
                self.conn.commit()
                print(f"✅ Создан дракон: {dragon_data.get('name', 'Дракоша')} для пользователя {user_id}")
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
                dragon_data.get('character', {}).get('основная_черта', 'неженка'),
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
        """Получает инвентарь пользователя"""
        self.cursor.execute(
            "SELECT item_name, quantity FROM inventory WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchall()
        return {row[0]: row[1] for row in result} if result else {}
    
    def update_inventory(self, user_id: int, item_name: str, quantity_change: int) -> bool:
        """Обновляет количество предмета в инвентаре"""
        try:
            # Проверяем, есть ли предмет
            self.cursor.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?",
                (user_id, item_name)
            )
            result = self.cursor.fetchone()
            
            if result:
                new_quantity = result[0] + quantity_change
                if new_quantity <= 0:
                    # Удаляем предмет, если количество 0 или меньше
                    self.cursor.execute(
                        "DELETE FROM inventory WHERE user_id = ? AND item_name = ?",
                        (user_id, item_name)
                    )
                else:
                    # Обновляем количество
                    self.cursor.execute('''
                        UPDATE inventory 
                        SET quantity = ? 
                        WHERE user_id = ? AND item_name = ?
                    ''', (new_quantity, user_id, item_name))
            else:
                # Добавляем новый предмет только если количество положительное
                if quantity_change > 0:
                    self.cursor.execute('''
                        INSERT INTO inventory (user_id, item_name, quantity)
                        VALUES (?, ?, ?)
                    ''', (user_id, item_name, quantity_change))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка обновления инвентаря: {e}")
            self.conn.rollback()
            return False
    
    def add_gold(self, user_id: int, amount: int) -> bool:
        """Добавляет золото пользователю"""
        try:
            self.cursor.execute(
                "UPDATE dragons SET gold = gold + ? WHERE user_id = ?",
                (amount, user_id)
            )
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
    
    def add_experience(self, user_id: int, amount: int) -> Optional[int]:
        """Добавляет опыт дракону и проверяет уровень"""
        try:
            self.cursor.execute(
                "UPDATE dragons SET experience = experience + ? WHERE user_id = ?",
                (amount, user_id)
            )
            
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
                self.conn.commit()
                return new_level
            
            self.conn.commit()
            return None
        except Exception as e:
            print(f"❌ Ошибка добавления опыта: {e}")
            self.conn.rollback()
            return None
    
    def update_habit(self, user_id: int, habit_type: str, habit_time: str = None) -> int:
        """Обновляет привычку"""
        try:
            self.cursor.execute('''
                SELECT streak, last_performed FROM habits 
                WHERE user_id = ? AND habit_type = ?
            ''', (user_id, habit_type))
            
            result = self.cursor.fetchone()
            today = datetime.now().date().isoformat()
            
            if result:
                streak, last_performed = result
                last_date = datetime.fromisoformat(last_performed).date() if last_performed else None
                
                if last_date and last_date.isoformat() == today:
                    return streak
                
                if last_date and (datetime.now().date() - last_date).days == 1:
                    streak += 1
                else:
                    streak = 1
                
                self.cursor.execute('''
                    UPDATE habits 
                    SET streak = ?, last_performed = CURRENT_TIMESTAMP, habit_time = COALESCE(?, habit_time)
                    WHERE user_id = ? AND habit_type = ?
                ''', (streak, habit_time, user_id, habit_type))
            else:
                streak = 1
                self.cursor.execute('''
                    INSERT INTO habits (user_id, habit_type, habit_time, streak, last_performed)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (user_id, habit_type, habit_time, streak))
            
            self.conn.commit()
            return streak
        except Exception as e:
            print(f"❌ Ошибка обновления привычки: {e}")
            self.conn.rollback()
            return 0
    
    def get_habits(self, user_id: int) -> List[Dict]:
        """Получает все привычки пользователя"""
        self.cursor.execute(
            "SELECT habit_type, habit_time, streak, last_performed FROM habits WHERE user_id = ?",
            (user_id,)
        )
        rows = self.cursor.fetchall()
        return [
            {
                'type': row[0], 
                'time': row[1], 
                'streak': row[2],
                'last_performed': row[3]
            }
            for row in rows
        ]
    
    def record_action(self, user_id: int, action: str) -> bool:
        """Записывает действие пользователя"""
        try:
            self.cursor.execute('''
                INSERT INTO user_actions (user_id, action_type, action_details)
                VALUES (?, ?, ?)
            ''', (user_id, 'general', action))
            
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
            
            if stat_column:
                self.cursor.execute(
                    "UPDATE user_stats SET {} = {} + 1 WHERE user_id = ?".format(stat_column, stat_column),
                    (user_id,)
                )
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Ошибка записи действия: {e}")
            self.conn.rollback()
            return False
    
    def get_user_settings(self, user_id: int) -> Dict:
        """Получает настройки пользователя"""
        try:
            self.cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
            
            # Создаем настройки по умолчанию, если их нет
            self.cursor.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)",
                (user_id,)
            )
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
                "UPDATE user_settings SET {} = ? WHERE user_id = ?".format(key),
                (value, user_id)
            )
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
    
    def get_feeding_history(self, user_id: int, days: int = 7) -> List[datetime]:
        """Получает историю кормлений за последние N дней"""
        try:
            time_threshold = datetime.now() - timedelta(days=days)
            self.cursor.execute('''
                SELECT created_at FROM user_actions 
                WHERE user_id = ? 
                AND (action_type LIKE '%корм%' OR action_type LIKE '%feed%')
                AND created_at >= ?
                ORDER BY created_at
            ''', (user_id, time_threshold.isoformat()))
            
            return [datetime.fromisoformat(row[0]) for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"❌ Ошибка получения истории кормлений: {e}")
            return []
    
    def get_dragon_count(self) -> int:
        """Получает общее количество драконов"""
        self.cursor.execute("SELECT COUNT(*) FROM dragons")
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def get_top_dragons(self, limit: int = 10) -> List[Dict]:
        """Получает топ драконов по уровню"""
        self.cursor.execute('''
            SELECT d.user_id, d.name, d.level, d.experience
            FROM dragons d
            ORDER BY d.level DESC, d.experience DESC
            LIMIT ?
        ''', (limit,))
        
        rows = self.cursor.fetchall()
        return [
            {
                'user_id': row[0],
                'name': row[1],
                'level': row[2],
                'experience': row[3]
            }
            for row in rows
        ] if rows else []
    
    def cleanup_old_data(self, days: int = 30) -> int:
        """Очищает старые данные (действия старше N дней)"""
        try:
            time_threshold = datetime.now() - timedelta(days=days)
            self.cursor.execute(
                "DELETE FROM user_actions WHERE created_at < ?",
                (time_threshold.isoformat(),)
            )
            deleted = self.cursor.rowcount
            self.conn.commit()
            return deleted
        except Exception as e:
            print(f"❌ Ошибка очистки данных: {e}")
            return 0
    
    def get_user_timezone(self, user_id: int) -> str:
        """Получает часовой пояс пользователя"""
        settings = self.get_user_settings(user_id)
        return settings.get('timezone', 'UTC')
    
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
            # Сбрасываем настройки
            self.cursor.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
            # Сбрасываем статистику
            self.cursor.execute("DELETE FROM user_stats WHERE user_id = ?", (user_id,))
            
            # Создаем настройки и статистику по умолчанию
            self.cursor.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)",
                (user_id,)
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
            
            return {
                'dragon': dragon,
                'inventory': inventory,
                'habits': habits,
                'stats': stats,
                'backup_date': datetime.now().isoformat()
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
                SELECT action_details FROM user_actions 
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            
            result = self.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            print(f"❌ Ошибка получения последнего действия: {e}")
            return None
    
    def get_action_history(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Получает историю действий пользователя"""
        try:
            self.cursor.execute('''
                SELECT action_type, action_details, created_at 
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
                    'time': datetime.fromisoformat(row[2])
                }
                for row in rows
            ]
        except Exception as e:
            print(f"❌ Ошибка получения истории действий: {e}")
            return []
    
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
        print(f"✅ База данных инициализирована. Драконов в базе: {_db_instance.get_dragon_count()}")
    return _db_instance

def init_database(db_name="dragons.db"):
    """Явная инициализация базы данных"""
    return get_db(db_name)


# СОЗДАЕМ ЭКЗЕМПЛЯР СРАЗУ ПРИ ИМПОРТЕ
db = get_db()  # Это ЭКЗЕМПЛЯР, а не функция!

print(f"🐉 Модуль базы данных загружен. Текущее количество драконов: {db.get_dragon_count()}")