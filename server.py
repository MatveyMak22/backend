import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://matveymak22.github.io/Cas")
# ID админов через запятую
ADMIN_IDS = [int(x) for x in os.getenv("776092053", "0").split(",") if x.strip().isdigit()]

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
pool: asyncpg.Pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 1000.00,
                referrer_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Таблица матчей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id SERIAL PRIMARY KEY,
                sport TEXT,
                team_home TEXT,
                team_away TEXT,
                start_time TIMESTAMP,
                status TEXT DEFAULT 'scheduled', -- scheduled, live, finished
                score_home INT DEFAULT 0,
                score_away INT DEFAULT 0,
                odds_home NUMERIC(5, 2),
                odds_draw NUMERIC(5, 2),
                odds_away NUMERIC(5, 2),
                current_minute INT DEFAULT 0
            )
        """)
        # Таблица ставок
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                match_id INT,
                amount NUMERIC(10, 2),
                bet_selection TEXT, -- home, draw, away
                coefficient NUMERIC(5, 2),
                status TEXT DEFAULT 'active', -- active, won, lost
                potential_win NUMERIC(10, 2),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

# --- SPORTS DATA ---
SPORTS_CONFIG = {
    "football": {"duration": 90, "name": "Футбол", "score_chance": 0.08},
    "hockey": {"duration": 60, "name": "Хоккей", "score_chance": 0.12},
    "basketball": {"duration": 48, "name": "Баскетбол", "score_chance": 0.40},
}

TEAMS = {
    "football": ["Зенит", "Спартак", "ЦСКА", "Динамо", "Краснодар", "Локомотив", "Ростов", "Рубин", "Сочи", "Урал"],
    "hockey": ["Ак Барс", "СКА", "ЦСКА", "Авангард", "Металлург", "Динамо М", "Салават Юлаев", "Трактор"],
    "basketball": ["ЦСКА", "Зенит", "УНИКС", "Локомотив-Кубань", "Нижний Новгород", "Парма", "Енисей", "Автодор"]
}

# --- BACKGROUND TASKS (ENGINE) ---

async def sports_engine():
    """Главный цикл спортивного движка"""
    while True:
        try:
            async with pool.acquire() as conn:
                now = datetime.utcnow()
                
                # 1. ОБНОВЛЕНИЕ LIVE МАТЧЕЙ
                live_matches = await conn.fetch("SELECT * FROM matches WHERE status = 'live'")
                for m in live_matches:
                    sport = m['sport']
                    duration = SPORTS_CONFIG[sport]['duration']
                    new_minute = m['current_minute'] + 1
                    
                    # Логика изменения счета (простая симуляция)
                    s_home = m['score_home']
                    s_away = m['score_away']
                    
                    if random.random() < SPORTS_CONFIG[sport]['score_chance']:
                        if random.random() > 0.5:
                            s_home += 1 if sport != 'basketball' else random.randint(2, 3)
                        else:
                            s_away += 1 if sport != 'basketball' else random.randint(2, 3)

                    if new_minute >= duration:
                        # Завершаем матч
                        await conn.execute("""
                            UPDATE matches SET status = 'finished', current_minute = $1, score_home = $2, score_away = $3 
                            WHERE id = $4
                        """, duration, s_home, s_away, m['id'])
                        await settle_bets(conn, m['id'], s_home, s_away)
                    else:
                        # Обновляем таймер и счет
                        await conn.execute("""
                            UPDATE matches SET current_minute = $1, score_home = $2, score_away = $3 
                            WHERE id = $4
                        """, new_minute, s_home, s_away, m['id'])

                # 2. ЗАПУСК ЗАПЛАНИРОВАННЫХ МАТЧЕЙ
                await conn.execute("UPDATE matches SET status = 'live' WHERE status = 'scheduled' AND start_time <= $1", now)

                # 3. ГЕНЕРАЦИЯ НОВЫХ МАТЧЕЙ (если мало предстоящих)
                upcoming_count = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status = 'scheduled'")
                if upcoming_count < 10:
                    await generate_matches(conn)

        except Exception as e:
            logger.error(f"Engine error: {e}")
        
        await asyncio.sleep(60) # Обновление раз в минуту (реальное время)

async def settle_bets(conn, match_id, score_home, score_away):
    """Рассчет ставок после матча"""
    bets = await conn.fetch("SELECT * FROM bets WHERE match_id = $1 AND status = 'active'", match_id)
    
    result = "draw"
    if score_home > score_away: result = "home"
    elif score_away > score_home: result = "away"

    for bet in bets:
        won = False
        if bet['bet_selection'] == result:
            won = True
        
        # Для баскетбола и хоккея ничьи редки/нет, но оставим для простоты логику 1x2
        
        if won:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id = $2", bet['potential_win'], bet['user_id'])
            await conn.execute("UPDATE bets SET status = 'won' WHERE id = $1", bet['id'])
        else:
            await conn.execute("UPDATE bets SET status = 'lost' WHERE id = $1", bet['id'])

async def generate_matches(conn):
    """Создает расписание, избегая коллизий команд"""
    now = datetime.utcnow()
    
    # Получаем команды, которые уже играют или будут играть в ближайшие 6 часов
    busy_teams_rows = await conn.fetch("""
        SELECT team_home, team_away FROM matches 
        WHERE status IN ('live', 'scheduled')
    """)
    busy_teams = set()
    for r in busy_teams_rows:
        busy_teams.add(r['team_home'])
        busy_teams.add(r['team_away'])

    for sport, teams_list in TEAMS.items():
        available_teams = [t for t in teams_list if t not in busy_teams]
        if len(available_teams) < 2:
            continue
        
        random.shuffle(available_teams)
        
        # Создаем пару
        team_a = available_teams.pop()
        team_b = available_teams.pop()
        
        # Время начала: от +5 минут до +3 часов
        start_delay = random.randint(5, 180)
        start_time = now + timedelta(minutes=start_delay)
        
        # Коэффициенты (рандомно, но с маржой)
        raw_prob_a = random.uniform(0.3, 0.6)
        raw_prob_b = random.uniform(0.3, 0.6)
        if raw_prob_a + raw_prob_b > 0.9: raw_prob_b = 0.9 - raw_prob_a
        raw_prob_draw = 1 - (raw_prob_a + raw_prob_b)
        
        # Добавляем маржу букмекера
        margin = 0.95
        odds_home = round(1 / raw_prob_a * margin, 2)
        odds_away = round(1 / raw_prob_b * margin, 2)
        odds_draw = round(1 / raw_prob_draw * margin, 2) if sport == 'football' else 1.01 # Упрощение

        await conn.execute("""
            INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, sport, team_a, team_b, start_time, odds_home, odds_draw, odds_away)
        
        # Добавляем в busy для текущей итерации
        busy_teams.add(team_a)
        busy_teams.add(team_b)

# --- TELEGRAM BOT (AIOGRAM) ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Создаем пользователя при старте
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username, referrer_id) 
            VALUES ($1, $2, $3) 
            ON CONFLICT (telegram_id) DO NOTHING
        """, message.from_user.id, message.from_user.username, None)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎰 Играть сейчас", web_app=WebAppInfo(url=FRONTEND_URL))]
    ])
    await message.answer("Добро пожаловать в Casino & Sports!", reply_markup=kb)

@dp.message(Command("add"))
async def cmd_add_balance(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, user_id, amount = message.text.split()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id = $2", float(amount), int(user_id))
        await message.answer(f"Начислено {amount} пользователю {user_id}")
    except:
        await message.answer("Ошибка. Формат: /add <id> <amount>")

@dp.message(Command("set"))
async def cmd_set_balance(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, user_id, amount = message.text.split()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET balance = $1 WHERE telegram_id = $2", float(amount), int(user_id))
        await message.answer(f"Баланс установлен {amount} пользователю {user_id}")
    except:
        await message.answer("Ошибка. Формат: /set <id> <amount>")

@dp.message(Command("stat"))
async def cmd_stat(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with pool.acquire() as conn:
        users_cnt = await conn.fetchval("SELECT COUNT(*) FROM users")
        bets_sum = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM bets")
    await message.answer(f"👥 Пользователей: {users_cnt}\n💰 Оборот: {bets_sum}")

# --- FASTAPI SERVER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(sports_engine()) # Start simulation
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook" if os.getenv('RENDER_EXTERNAL_HOSTNAME') else None
    if webhook_url:
        await bot.set_webhook(webhook_url)
    yield
    await bot.delete_webhook()
    if pool: await pool.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # В проде лучше указать конкретный домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class BetRequest(BaseModel):
    match_id: int
    selection: str # home, draw, away
    amount: float
    coefficient: float

class GameResult(BaseModel):
    game: str
    amount: float # Отрицательное если проигрыш, положительное если выигрыш

# API Routes
@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)

@app.get("/api/init")
async def init_user(tg_id: int, username: str = ""):
    """Инициализация при входе в Mini App"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username) VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET username = $2
            RETURNING balance
        """, tg_id, username)
        return {"balance": row['balance']}

@app.get("/api/matches")
async def get_matches():
    async with pool.acquire() as conn:
        # Live matches
        live = await conn.fetch("SELECT * FROM matches WHERE status = 'live' ORDER BY start_time ASC")
        # Upcoming
        upcoming = await conn.fetch("SELECT * FROM matches WHERE status = 'scheduled' ORDER BY start_time ASC LIMIT 20")
        
        # Helper to dict
        def to_dict(rows):
            return [dict(r) for r in rows]
            
        return {"live": to_dict(live), "upcoming": to_dict(upcoming)}

@app.post("/api/bet")
async def place_bet(bet: BetRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        # Проверка баланса
        balance = await conn.fetchval("SELECT balance FROM users WHERE telegram_id = $1", tg_id)
        if balance < bet.amount:
            raise HTTPException(400, "Недостаточно средств")
        
        # Списание и запись
        async with conn.transaction():
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id = $2", bet.amount, tg_id)
            potential_win = bet.amount * bet.coefficient
            await conn.execute("""
                INSERT INTO bets (user_id, match_id, amount, bet_selection, coefficient, potential_win)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, tg_id, bet.match_id, bet.amount, bet.selection, bet.coefficient, potential_win)
            
    return {"status": "ok", "new_balance": float(balance) - bet.amount}

@app.get("/api/history")
async def get_history(request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        active = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id = $1 AND b.status = 'active'
            ORDER BY b.created_at DESC
        """, tg_id)
        history = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id = $1 AND b.status != 'active'
            ORDER BY b.created_at DESC LIMIT 50
        """, tg_id)
        
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

@app.post("/api/game")
async def update_balance_game(res: GameResult, request: Request):
    """Эндпоинт для мини-игр (Dice/Mines)"""
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        balance = await conn.fetchval("SELECT balance FROM users WHERE telegram_id = $1", tg_id)
        
        if res.amount < 0 and (balance + res.amount < 0):
             raise HTTPException(400, "Недостаточно средств")

        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id = $2", res.amount, tg_id)
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id = $1", tg_id)
    
    return {"new_balance": new_bal}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
