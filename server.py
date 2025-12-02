import asyncio
import logging
import os
import random
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE")
DATABASE_URL = os.getenv("postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
FRONTEND_URL = os.getenv("https://matveymak22.github.io/Cas")

# --- LIMITS ---
MIN_BET_SPORT = 50.0
MIN_BET_GAME = 10.0

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
                game_type TEXT, 
                amount NUMERIC(10, 2),
                bet_selection TEXT,
                coefficient NUMERIC(5, 2),
                status TEXT DEFAULT 'active',
                potential_win NUMERIC(10, 2),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
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
    "football": ["Ман Сити", "Реал", "Арсенал", "Бавария", "ПСЖ", "Интер", "Ливерпуль", "Барселона", "Ювентус", "Челси"],
    "hockey": ["ЦСКА", "СКА", "Ак Барс", "Авангард", "Металлург", "Динамо", "Тампа", "Колорадо"],
    "basketball": ["Лейкерс", "Голден Стэйт", "Бостон", "Майами", "ЦСКА", "Зенит", "Реал", "Барселона"],
    "tennis": ["Джокович", "Алькарас", "Медведев", "Синнер", "Рублев", "Зверев", "Циципас", "Надаль"],
    "table_tennis": ["Фан Чжэньдун", "Ма Лун", "Ван Чуцинь", "Харимото", "Овчаров", "Болл", "Линь Юньжу"]
}

# --- ENGINE ---
async def sports_engine():
    while True:
        try:
            async with pool.acquire() as conn:
                # 1. Generate Matches
                count = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')")
                if count < 15:
                    for sport, teams in TEAMS.items():
                        if random.random() > 0.6: continue
                        t1, t2 = random.sample(teams, 2)
                        start = datetime.utcnow() + timedelta(minutes=random.randint(1, 45))
                        
                        k1 = round(random.uniform(1.1, 2.5), 2)
                        k2 = round(random.uniform(1.1, 3.5), 2)
                        kx = 0 if sport in ['tennis', 'table_tennis'] else round(random.uniform(2.5, 4.5), 2)
                        
                        sets_init = [[0,0]] * (3 if sport == 'tennis' else (5 if sport == 'table_tennis' else 0))
                        
                        await conn.execute("""
                            INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away, score_details)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """, sport, t1, t2, start, k1, kx, k2, json.dumps(sets_init))

                # 2. Update Live Matches
                live_matches = await conn.fetch("SELECT * FROM matches WHERE status = 'live'")
                for m in live_matches:
                    sport = m['sport']
                    s1, s2 = m['score_home'], m['score_away']
                    details = json.loads(m['score_details'])
                    finished = False
                    
                    # Logic: Simple scoring for demo
                    if random.random() < 0.15:
                        if random.random() > 0.5: s1 += 1
                        else: s2 += 1
                        
                        # Set Logic Update (Simplified)
                        if sport in ['tennis', 'table_tennis'] and len(details) > 0:
                            # Just increment last set for demo visual
                            details[0][0] = s1
                            details[0][1] = s2

                    # Finish condition
                    limit = 5 if sport == 'football' else (10 if sport == 'hockey' else 100)
                    if s1 >= limit or s2 >= limit or m['current_minute'] > 90:
                        finished = True
                    
                    await conn.execute("UPDATE matches SET score_home=$1, score_away=$2, score_details=$3, current_minute=current_minute+1 WHERE id=$4",
                                       s1, s2, json.dumps(details), m['id'])
                    
                    if finished:
                        await conn.execute("UPDATE matches SET status='finished' WHERE id=$1", m['id'])
                        # Settle Bets
                        winner = 'home' if s1 > s2 else ('away' if s2 > s1 else 'draw')
                        bets = await conn.fetch("SELECT * FROM bets WHERE match_id=$1 AND status='active'", m['id'])
                        for b in bets:
                            is_win = b['bet_selection'] == winner
                            if is_win:
                                await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", b['potential_win'], b['user_id'])
                                await conn.execute("UPDATE bets SET status='won' WHERE id=$1", b['id'])
                            else:
                                await conn.execute("UPDATE bets SET status='lost' WHERE id=$1", b['id'])

                # 3. Start Scheduled
                await conn.execute("UPDATE matches SET status='live' WHERE status='scheduled' AND start_time <= NOW()")

        except Exception as e:
            logger.error(f"Engine Error: {e}")
        
        await asyncio.sleep(5)

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

# Models
class BetModel(BaseModel):
    match_id: int
    selection: str
    amount: float
    coefficient: float

class GameModel(BaseModel):
    game: str
    amount: float # Net change (+win or -loss)
    bet_amount: float # Original bet size for validation

class CrashStart(BaseModel):
    bet: float

class CrashCashout(BaseModel):
    multiplier: float

# Routes
@app.post("/webhook")
async def telegram_webhook(request: Request):
    return {}

@app.get("/api/init")
async def init_user(tg_id: int, username: str = ""):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username) VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET username = $2
        """, tg_id, username)
        return {"balance": await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)}

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
        active = await conn.fetch("SELECT * FROM bets WHERE user_id=$1 AND status='active' ORDER BY id DESC LIMIT 20", tg_id)
        history = await conn.fetch("SELECT * FROM bets WHERE user_id=$1 AND status!='active' ORDER BY id DESC LIMIT 20", tg_id)
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

@app.post("/api/bet")
async def place_bet(data: BetModel, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    
    if data.amount < MIN_BET_SPORT:
        raise HTTPException(400, f"Минимальная ставка {int(MIN_BET_SPORT)}₽")

    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.amount: raise HTTPException(400, "Недостаточно средств")
        
        async with conn.transaction():
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.amount, tg_id)
            win = data.amount * data.coefficient
            await conn.execute("""
                INSERT INTO bets (user_id, match_id, game_type, amount, bet_selection, coefficient, potential_win)
                VALUES ($1, $2, 'sport', $3, $4, $5, $6)
            """, tg_id, data.match_id, data.amount, data.selection, data.coefficient, win)
            
        return {"status": "ok", "new_balance": float(bal) - data.amount}

@app.post("/api/game")
async def game_result(data: GameModel, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    
    if data.bet_amount < MIN_BET_GAME:
        raise HTTPException(400, f"Минимальная ставка {int(MIN_BET_GAME)}₽")

    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        
        # Если проигрыш (amount < 0), проверяем, хватает ли денег
        if data.amount < 0 and (bal + data.amount < 0):
             raise HTTPException(400, "Недостаточно средств")

        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", data.amount, tg_id)
        
        # Запись в историю
        status = 'won' if data.amount > 0 else 'lost'
        win = data.amount if data.amount > 0 else 0
        await conn.execute("""
            INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
            VALUES ($1, $2, $3, $4, $5, 1.0)
        """, tg_id, data.game, data.bet_amount, status, win)
        
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"new_balance": new_bal}

@app.post("/api/crash/start")
async def crash_start(data: CrashStart, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    
    if data.bet < MIN_BET_GAME:
        raise HTTPException(400, f"Минимальная ставка {int(MIN_BET_GAME)}₽")

    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.bet: raise HTTPException(400, "Недостаточно средств")

        # Crash logic
        crash_point = round(0.99 / (1 - random.random()), 2)
        if crash_point > 30: crash_point = 30.0
        if random.random() < 0.05: crash_point = 1.00 # Instant crash

        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.bet, tg_id)
        await conn.execute("""
            INSERT INTO crash_games (user_id, crash_point, bet_amount, is_active)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET crash_point=$2, bet_amount=$3, is_active=TRUE
        """, tg_id, crash_point, data.bet)

        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"status": "started", "balance": new_bal}

@app.post("/api/crash/cashout")
async def crash_cashout(data: CrashCashout, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        game = await conn.fetchrow("SELECT * FROM crash_games WHERE user_id=$1 AND is_active=TRUE", tg_id)
        if not game: raise HTTPException(400, "Нет активной игры")
        
        real_crash = float(game['crash_point'])
        user_mult = float(data.multiplier)
        bet = float(game['bet_amount'])
        
        if user_mult <= real_crash:
            win = bet * user_mult
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", win, tg_id)
            await conn.execute("UPDATE crash_games SET is_active=FALSE WHERE user_id=$1", tg_id)
            
            # Log
            await conn.execute("""
                INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
                VALUES ($1, 'crash', $2, 'won', $3, $4)
            """, tg_id, bet, win, user_mult)
            
            new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
            return {"status": "won", "win": win, "balance": new_bal}
        else:
            await conn.execute("UPDATE crash_games SET is_active=FALSE WHERE user_id=$1", tg_id)
            await conn.execute("""
                INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
                VALUES ($1, 'crash', $2, 'lost', 0, $3)
            """, tg_id, bet, user_mult)
            return {"status": "lost", "crash_point": real_crash}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
