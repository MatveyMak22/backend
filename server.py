import asyncio
import logging
import os
import random
import json
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE")
DATABASE_URL = os.getenv("postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
FRONTEND_URL = os.getenv("https://matveymak22.github.io/Cas")
ADMIN_IDS = [int(x) for x in os.getenv("776092053", "0").split(",") if x.strip().isdigit()]

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pool: asyncpg.Pool = None

# --- DATABASE SETUP ---
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 5000.00
            )
        """)
        # score_details хранит JSON типа [[6,4], [2,6], [0,0]]
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id SERIAL PRIMARY KEY,
                sport TEXT,
                team_home TEXT,
                team_away TEXT,
                start_time TIMESTAMP,
                status TEXT DEFAULT 'scheduled',
                score_home INT DEFAULT 0, 
                score_away INT DEFAULT 0,
                score_details TEXT DEFAULT '[]', 
                odds_home NUMERIC(5, 2),
                odds_draw NUMERIC(5, 2),
                odds_away NUMERIC(5, 2),
                current_minute INT DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                match_id INT,
                game_type TEXT, -- 'sport', 'mines', 'dice', 'crash'
                amount NUMERIC(10, 2),
                bet_selection TEXT,
                coefficient NUMERIC(5, 2),
                status TEXT DEFAULT 'active',
                potential_win NUMERIC(10, 2),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Таблица для активных краш игр (чтобы сервер знал точку краша)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crash_games (
                user_id BIGINT PRIMARY KEY,
                crash_point NUMERIC(5, 2),
                bet_amount NUMERIC(10, 2),
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

# --- DATASETS ---
TEAMS = {
    "football": [
        "Манчестер Сити", "Реал Мадрид", "Арсенал", "Бавария", "ПСЖ", "Интер", "Ливерпуль", "Барселона", 
        "Спартак Москва", "Зенит", "ЦСКА", "Краснодар", "Динамо", "Локомотив", "Ростов", "Ювентус"
    ],
    "hockey": [
        "ЦСКА", "СКА", "Ак Барс", "Авангард", "Металлург Мг", "Динамо М", "Салават Юлаев", "Локомотив",
        "Тампа-Бэй", "Колорадо", "Вегас", "Торонто", "Бостон", "Эдмонтон", "Рейнджерс", "Трактор"
    ],
    "basketball": [
        "Лейкерс", "Голден Стэйт", "Бостон", "Майами", "ЦСКА", "Зенит", "УНИКС", "Реал Мадрид",
        "Барселона", "Фенербахче", "Олимпиакос", "Локомотив-Кубань", "Парма", "Химки"
    ],
    "tennis": [
        "Даниил Медведев", "Новак Джокович", "Карлос Алькарас", "Янник Синнер", "Андрей Рублев", 
        "Александр Зверев", "Стефанос Циципас", "Хольгер Руне", "Карен Хачанов", "Бен Шелтон"
    ],
    "table_tennis": [
        "Фан Чжэньдун", "Ма Лун", "Ван Чуцинь", "Лян Цзингунь", "Томоказу Харимото", 
        "Дмитрий Овчаров", "Тимо Болл", "Линь Юньжу", "Уго Кальдерано", "Чжан Бэн"
    ]
}

# --- ENGINE LOGIC ---
async def generate_matches(conn):
    now = datetime.utcnow()
    existing = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')")
    if existing > 15: return

    for sport, teams in TEAMS.items():
        if random.random() < 0.7: continue # Не создаем все сразу
        
        t1, t2 = random.sample(teams, 2)
        start_delay = random.randint(1, 60)
        start_time = now + timedelta(minutes=start_delay)
        
        # Коэффициенты
        p1 = random.uniform(0.3, 0.6)
        p2 = 0.93 - p1 # Маржа
        k1 = round(1/p1, 2)
        k2 = round(1/p2, 2)
        kx = 0
        
        if sport in ['football', 'hockey']:
            px = random.uniform(0.2, 0.3)
            p1 -= px/2
            p2 -= px/2
            k1 = round(1/p1, 2)
            k2 = round(1/p2, 2)
            kx = round(1/px, 2)
        
        # Начальная структура сетов
        sets = []
        if sport == 'tennis': sets = [[0,0], [0,0], [0,0]] # Max 3 sets
        elif sport == 'table_tennis': sets = [[0,0], [0,0], [0,0], [0,0], [0,0]] # Max 5 sets
        
        await conn.execute("""
            INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away, score_details)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, sport, t1, t2, start_time, k1, kx, k2, json.dumps(sets))

async def sports_engine():
    while True:
        try:
            async with pool.acquire() as conn:
                await generate_matches(conn)
                
                # Update Live
                live = await conn.fetch("SELECT * FROM matches WHERE status = 'live'")
                for m in live:
                    sport = m['sport']
                    s1, s2 = m['score_home'], m['score_away']
                    details = json.loads(m['score_details'])
                    finished = False
                    
                    # --- FOOTBALL / HOCKEY / BASKET ---
                    if sport in ['football', 'hockey', 'basketball']:
                        minute = m['current_minute'] + 1
                        dur = 90 if sport == 'football' else (60 if sport == 'hockey' else 48)
                        
                        # Chance to score
                        chance = 0.08 if sport == 'football' else (0.15 if sport == 'hockey' else 0.4)
                        if random.random() < chance:
                            if random.random() > 0.5: s1 += (1 if sport != 'basketball' else random.randint(2,3))
                            else: s2 += (1 if sport != 'basketball' else random.randint(2,3))
                        
                        if minute >= dur: finished = True
                        
                        await conn.execute("UPDATE matches SET current_minute=$1, score_home=$2, score_away=$3 WHERE id=$4", 
                                           minute, s1, s2, m['id'])

                    # --- TENNIS (Best of 3) ---
                    elif sport == 'tennis':
                        # Find current active set
                        active_set_idx = -1
                        for i, s in enumerate(details):
                            # Set logic: Win if >=6 and diff >=2. Max 3 sets.
                            if not ((s[0] >= 6 or s[1] >= 6) and abs(s[0]-s[1]) >= 2) and not (s[0]==7 or s[1]==7):
                                active_set_idx = i
                                break
                        
                        if active_set_idx != -1:
                            # Play point in set
                            if random.random() < 0.2: # Speed of points
                                if random.random() > 0.5: details[active_set_idx][0] += 1
                                else: details[active_set_idx][1] += 1
                        
                        # Calc global score (sets won)
                        sets_w1 = sum(1 for s in details if (s[0]>=6 and s[0]-s[1]>=2) or s[0]==7)
                        sets_w2 = sum(1 for s in details if (s[1]>=6 and s[1]-s[0]>=2) or s[1]==7)
                        
                        s1, s2 = sets_w1, sets_w2
                        if sets_w1 == 2 or sets_w2 == 2: finished = True
                        
                        await conn.execute("UPDATE matches SET score_home=$1, score_away=$2, score_details=$3 WHERE id=$4", 
                                           s1, s2, json.dumps(details), m['id'])

                    # --- TABLE TENNIS (Best of 5) ---
                    elif sport == 'table_tennis':
                        active_set_idx = -1
                        for i, s in enumerate(details):
                            # Set logic: to 11, win by 2
                            if not ((s[0]>=11 or s[1]>=11) and abs(s[0]-s[1])>=2):
                                active_set_idx = i
                                break
                        
                        if active_set_idx != -1:
                            if random.random() < 0.3:
                                if random.random() > 0.5: details[active_set_idx][0] += 1
                                else: details[active_set_idx][1] += 1
                        
                        sets_w1 = sum(1 for s in details if (s[0]>=11 and abs(s[0]-s[1])>=2))
                        sets_w2 = sum(1 for s in details if (s[1]>=11 and abs(s[1]-s[0])>=2))
                        
                        s1, s2 = sets_w1, sets_w2
                        if sets_w1 == 3 or sets_w2 == 3: finished = True

                        await conn.execute("UPDATE matches SET score_home=$1, score_away=$2, score_details=$3 WHERE id=$4", 
                                           s1, s2, json.dumps(details), m['id'])
                    
                    if finished:
                        await conn.execute("UPDATE matches SET status='finished' WHERE id=$1", m['id'])
                        await settle_bets(conn, m['id'], s1, s2)

                # Start scheduled
                await conn.execute("UPDATE matches SET status='live' WHERE status='scheduled' AND start_time <= NOW()")

        except Exception as e:
            logger.error(f"Engine: {e}")
        await asyncio.sleep(5)

async def settle_bets(conn, match_id, s1, s2):
    res = 'draw'
    if s1 > s2: res = 'home'
    elif s2 > s1: res = 'away'
    
    bets = await conn.fetch("SELECT * FROM bets WHERE match_id=$1 AND status='active'", match_id)
    for b in bets:
        won = (b['bet_selection'] == res)
        if won:
            win = b['potential_win']
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", win, b['user_id'])
            await conn.execute("UPDATE bets SET status='won' WHERE id=$1", b['id'])
        else:
            await conn.execute("UPDATE bets SET status='lost' WHERE id=$1", b['id'])

# --- API ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(sports_engine())
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class BetModel(BaseModel):
    match_id: int
    selection: str
    amount: float
    coefficient: float

class GameModel(BaseModel):
    game: str
    amount: float

class CrashStart(BaseModel):
    bet: float

class CrashCashout(BaseModel):
    multiplier: float

@app.get("/api/init")
async def init_user(tg_id: int, username: str = ""):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username) VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET username = $2
        """, tg_id, username)
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"balance": bal}

@app.get("/api/matches")
async def get_matches():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM matches WHERE status IN ('live', 'scheduled') ORDER BY status, start_time LIMIT 30")
        res = []
        for r in rows:
            d = dict(r)
            d['score_details'] = json.loads(d['score_details'])
            d['start_time'] = d['start_time'].isoformat()
            res.append(d)
        return res

@app.get("/api/history")
async def get_history(request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        active = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id = $1 AND b.status = 'active'
            ORDER BY b.created_at DESC
        """, tg_id)
        history = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id = $1 AND b.status != 'active'
            ORDER BY b.created_at DESC LIMIT 20
        """, tg_id)
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

@app.post("/api/bet")
async def place_bet(data: BetModel, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.amount: raise HTTPException(400, "Low balance")
        
        async with conn.transaction():
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.amount, tg_id)
            win = data.amount * data.coefficient
            await conn.execute("""
                INSERT INTO bets (user_id, match_id, game_type, amount, bet_selection, coefficient, potential_win)
                VALUES ($1, $2, 'sport', $3, $4, $5, $6)
            """, tg_id, data.match_id, data.amount, data.selection, data.coefficient, win)
            
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"status": "ok", "new_balance": new_bal}

@app.post("/api/game")
async def game_result(data: GameModel, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if data.amount < 0 and (bal + data.amount < 0): raise HTTPException(400, "Low balance")
        
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", data.amount, tg_id)
        
        # Log to history (simplified)
        status = 'won' if data.amount > 0 else 'lost'
        win_amt = data.amount if data.amount > 0 else 0
        bet_amt = abs(data.amount) if data.amount < 0 else 0 
        
        # Для простоты логи мини-игр пишем в bets без match_id
        await conn.execute("""
            INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
            VALUES ($1, $2, $3, $4, $5, 1.0)
        """, tg_id, data.game, bet_amt, status, win_amt)
        
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"new_balance": new_bal}

# --- CRASH GAME LOGIC ---
@app.post("/api/crash/start")
async def crash_start(data: CrashStart, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.bet: raise HTTPException(400, "Low balance")

        # 1. Generate Crash Point (Simple Alg: 1 / rand(0,1)) with house edge
        # E.g., 3% instant crash
        if random.random() < 0.03:
            crash_point = 1.00
        else:
            # Exponential distribution
            crash_point = round(0.99 / (1 - random.random()), 2)
            if crash_point > 50: crash_point = 50.0 # Cap

        # 2. Deduct balance
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.bet, tg_id)
        
        # 3. Save active game
        await conn.execute("""
            INSERT INTO crash_games (user_id, crash_point, bet_amount, is_active)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (user_id) DO UPDATE 
            SET crash_point=$2, bet_amount=$3, is_active=TRUE
        """, tg_id, crash_point, data.bet)

        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"status": "started", "balance": new_bal}

@app.post("/api/crash/cashout")
async def crash_cashout(data: CrashCashout, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        game = await conn.fetchrow("SELECT * FROM crash_games WHERE user_id=$1 AND is_active=TRUE", tg_id)
        if not game:
            raise HTTPException(400, "No active game")
        
        real_crash = float(game['crash_point'])
        user_mult = float(data.multiplier)
        bet = float(game['bet_amount'])
        
        win_amount = 0
        status = 'lost'

        if user_mult <= real_crash:
            # Win
            win_amount = bet * user_mult
            status = 'won'
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", win_amount, tg_id)
        else:
            # User sent multiplier higher than actual crash (Lag or Cheat) -> Lost
            pass 

        # Close game
        await conn.execute("UPDATE crash_games SET is_active=FALSE WHERE user_id=$1", tg_id)
        
        # Log History
        await conn.execute("""
            INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
            VALUES ($1, 'crash', $2, $3, $4, $5)
        """, tg_id, bet, status, win_amount, user_mult)

        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"status": status, "crash_point": real_crash, "win": win_amount, "balance": new_bal}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
