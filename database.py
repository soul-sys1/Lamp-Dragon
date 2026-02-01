"""
БАЗА ДАННЫХ ДЛЯ ДРАКОНОВ
Хранит всех драконов в SQLite базе
"""
import sqlite3
import json
from datetime import datetime

class DragonDatabase:
    def __init__(self, db_name="dragons.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        """Создаем таблицы, если их нет"""
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                dragon_data TEXT NOT NULL,  -- JSON со всеми данными
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица инвентаря
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_type TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
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
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
    
    def user_exists(self, user_id):
        """Проверяет, есть ли пользователь в базе"""
        self.cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None
    
    def dragon_exists(self, user_id):
        """Проверяет, есть ли дракон у пользователя"""
        self.cursor.execute("SELECT 1 FROM dragons WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone() is not None
    
    def create_user(self, user_id, username):
        """Создает нового пользователя"""
        if not self.user_exists(user_id):
            self.cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            self.conn.commit()
    
    def create_dragon(self, user_id, dragon_data):
        """Создает нового дракона"""
        if not self.dragon_exists(user_id):
            # Правильная структура дракона для сохранения в JSON
            dragon_json = {
                'name': dragon_data.get('name', 'Дракоша'),
                'character': dragon_data.get('character', {
                    'main_trait': dragon_data.get('character_trait', 'неженка'),
                    'mood': 'спокойный',
                    'energy': 100,
                    'hunger': 50,
                    'health': 100
                }),
                'level': dragon_data.get('level', 1),
                'experience': dragon_data.get('experience', 0),
                'gold': dragon_data.get('gold', 50),
                'last_fed': datetime.now().isoformat(),
                'last_played': datetime.now().isoformat(),
                'created': datetime.now().isoformat()
            }
            
            self.cursor.execute('''
                INSERT INTO dragons 
                (user_id, name, character_trait, level, experience, gold, dragon_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                dragon_json['name'],
                dragon_json['character']['main_trait'],
                dragon_json['level'],
                dragon_json['experience'],
                dragon_json['gold'],
                json.dumps(dragon_json, ensure_ascii=False)
            ))
            
            # Создаем начальный инвентарь
            initial_items = [
                (user_id, 'food', 'кофейные_зерна', 10),
                (user_id, 'food', 'печенье', 5),
                (user_id, 'food', 'шоколад', 2),
                (user_id, 'drink', 'вода', 3),
            ]
            
            for item in initial_items:
                self.cursor.execute('''
                    INSERT INTO inventory (user_id, item_type, item_name, quantity)
                    VALUES (?, ?, ?, ?)
                ''', item)
            
            self.conn.commit()
            return True
        return False
    
    def get_dragon(self, user_id):
        """Получает данные дракона"""
        self.cursor.execute(
            "SELECT dragon_data FROM dragons WHERE user_id = ?", 
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result:
            try:
                data = json.loads(result[0])
                # Убедимся, что структура правильная
                if 'character' not in data:
                    data['character'] = {
                        'main_trait': data.get('character_trait', 'неженка'),
                        'mood': 'спокойный',
                        'energy': 100,
                        'hunger': 50,
                        'health': 100
                    }
                return data
            except json.JSONDecodeError:
                # Если JSON поврежден, создаем нового дракона
                self.cursor.execute(
                    "DELETE FROM dragons WHERE user_id = ?",
                    (user_id,)
                )
                self.conn.commit()
        return None
    
    def update_dragon(self, user_id, dragon_data):
        """Обновляет данные дракона"""
        # Обновляем дракона с правильной структурой
        dragon_json = {
            'name': dragon_data.get('name', 'Дракоша'),
            'character': dragon_data.get('character', {
                'main_trait': dragon_data.get('character_trait', 'неженка'),
                'mood': dragon_data.get('mood', 'спокойный'),
                'energy': dragon_data.get('energy', 100),
                'hunger': dragon_data.get('hunger', 50),
                'health': dragon_data.get('health', 100)
            }),
            'level': dragon_data.get('level', 1),
            'experience': dragon_data.get('experience', 0),
            'gold': dragon_data.get('gold', 50),
            'last_interaction': datetime.now().isoformat()
        }
        
        # Если есть временные метки, сохраняем их
        if 'last_fed' in dragon_data:
            dragon_json['last_fed'] = dragon_data['last_fed']
        if 'last_played' in dragon_data:
            dragon_json['last_played'] = dragon_data['last_played']
        if 'created' in dragon_data:
            dragon_json['created'] = dragon_data['created']
        
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
            json.dumps(dragon_json, ensure_ascii=False),
            dragon_json['name'],
            dragon_json['character']['main_trait'],
            dragon_json['level'],
            dragon_json['experience'],
            dragon_json['gold'],
            user_id
        ))
        self.conn.commit()
    
    def get_inventory(self, user_id):
        """Получает инвентарь пользователя"""
        self.cursor.execute(
            "SELECT item_name, quantity FROM inventory WHERE user_id = ? AND quantity > 0",
            (user_id,)
        )
        return {row[0]: row[1] for row in self.cursor.fetchall()}
    
    def update_inventory(self, user_id, item_name, quantity_change):
        """Обновляет количество предмета в инвентаре"""
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
            # Добавляем новый предмет
            if quantity_change > 0:
                # Определяем тип предмета по названию
                item_type = 'food'
                if 'зерн' in item_name:
                    item_type = 'coffee'
                elif 'чашк' in item_name or 'кружк' in item_name:
                    item_type = 'cup'
                
                self.cursor.execute('''
                    INSERT INTO inventory (user_id, item_type, item_name, quantity)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, item_type, item_name, quantity_change))
        
        self.conn.commit()
        return True
    
    def add_gold(self, user_id, amount):
        """Добавляет золото пользователю"""
        self.cursor.execute(
            "UPDATE dragons SET gold = gold + ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()
    
    def get_gold(self, user_id):
        """Получает количество золота"""
        self.cursor.execute(
            "SELECT gold FROM dragons WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def add_experience(self, user_id, amount):
        """Добавляет опыт дракону"""
        self.cursor.execute(
            "UPDATE dragons SET experience = experience + ? WHERE user_id = ?",
            (amount, user_id)
        )
        self.conn.commit()
        
        # Проверяем уровень
        self.cursor.execute(
            "SELECT level, experience FROM dragons WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result:
            level, exp = result
            # Каждый уровень требует 100 опыта
            new_level = level + (exp // 100)
            if new_level > level:
                self.cursor.execute(
                    "UPDATE dragons SET level = ?, experience = ? WHERE user_id = ?",
                    (new_level, exp % 100, user_id)
                )
                self.conn.commit()
                return new_level  # Возвращаем новый уровень
        return None
    
    def update_habit(self, user_id, habit_type, habit_time):
        """Обновляет привычку"""
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
                # Уже сегодня выполняли
                return streak
            
            # Проверяем, был ли вчера
            if last_date and (datetime.now().date() - last_date).days == 1:
                streak += 1
            else:
                streak = 1
            
            self.cursor.execute('''
                UPDATE habits 
                SET streak = ?, last_performed = CURRENT_TIMESTAMP, habit_time = ?
                WHERE user_id = ? AND habit_type = ?
            ''', (streak, habit_time, user_id, habit_type))
        else:
            # Новая привычка
            streak = 1
            self.cursor.execute('''
                INSERT INTO habits (user_id, habit_type, habit_time, streak, last_performed)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, habit_type, habit_time, streak))
        
        self.conn.commit()
        return streak
    
    def get_habits(self, user_id):
        """Получает все привычки пользователя"""
        self.cursor.execute(
            "SELECT habit_type, habit_time, streak FROM habits WHERE user_id = ?",
            (user_id,)
        )
        return [
            {'type': row[0], 'time': row[1], 'streak': row[2]}
            for row in self.cursor.fetchall()
        ]
    
    def close(self):
        """Закрывает соединение с базой"""
        self.conn.close()

# Создаем глобальный экземпляр базы данных
db = DragonDatabase()