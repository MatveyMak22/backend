import asyncio
import logging
import os
import random
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Читаем переменные с защитой от None
BOT_TOKEN = os.getenv("8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE", "")
DATABASE_URL = os.getenv("postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://matveymak22.github.io/Cas")

pool: asyncpg.Pool = None

# --- DATABASE SETUP ---
async def init_db():
    global pool
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL не найден! Сайт не будет работать.")
        return

    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            # Создаем таблицы (Безопасно)
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
        logger.info("✅ База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")

# --- SPORTS DATA ---
TEAMS = {
    "football": ["Real Madrid", "Barca", "Man City", "Liverpool", "Bayern", "PSG", "Inter", "Arsenal"],
    "hockey": ["CSKA", "SKA", "Avangard", "Ak Bars", "Dynamo", "Metallurg"],
    "tennis": ["Djokovic", "Alcaraz", "Medvedev", "Sinner", "Rublev", "Zverev"],
    "basketball": ["Lakers", "Warriors", "Celtics", "Bulls", "Heat", "Nets"]
}

async def sports_engine():
    """Генерация матчей"""
    while True:
        try:
            if pool:
                async with pool.acquire() as conn:
                    # 1. Создаем матчи если пусто
                    count = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')")
                    if count < 10:
                        for sport, teams in TEAMS.items():
                            t1, t2 = random.sample(teams, 2)
                            start = datetime.utcnow() + timedelta(minutes=random.randint(1, 60))
                            sets = [[0,0]] * 3 if sport == 'tennis' else []
                            await conn.execute("""
                                INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away, score_details)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """, sport, t1, t2, start, 1.9, 3.5, 1.9, json.dumps(sets))
                    
                    # 2. Обновляем Live
                    live = await conn.fetch("SELECT * FROM matches WHERE status='live'")
                    for m in live:
                        s1, s2 = m['score_home'], m['score_away']
                        # Простая симуляция
                        if random.random() < 0.2:
                            if random.random() > 0.5: s1 += 1
                            else: s2 += 1
                        
                        finished = False
                        if m['current_minute'] > 90 or s1 > 5 or s2 > 5: finished = True
                        
                        if finished:
                            await conn.execute("UPDATE matches SET status='finished' WHERE id=$1", m['id'])
                        else:
                            await conn.execute("UPDATE matches SET score_home=$1, score_away=$2, current_minute=current_minute+1 WHERE id=$3", s1, s2, m['id'])

                    # 3. Запуск
                    await conn.execute("UPDATE matches SET status='live' WHERE status='scheduled' AND start_time <= NOW()")
        except Exception as e:
            logger.error(f"Engine loop error: {e}")
        await asyncio.sleep(5)

# --- BOT & APP ---
# Безопасная инициализация бота
bot = None
dp = Dispatcher()
if BOT_TOKEN and len(BOT_TOKEN) > 10:
    bot = Bot(token=BOT_TOKEN)
else:
    logger.warning("⚠️ BOT_TOKEN не найден или некорректен. Бот не запустится, но API будет работать.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(sports_engine())
    
    # Webhook
    if bot:
        webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook" if os.getenv('RENDER_EXTERNAL_HOSTNAME') else None
        if webhook_url:
            try:
                await bot.set_webhook(webhook_url)
                logger.info(f"Вебхук установлен: {webhook_url}")
            except Exception as e:
                logger.error(f"Ошибка вебхука: {e}")
    yield
    if bot: await bot.delete_webhook()
    if pool: await pool.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class BetRequest(BaseModel):
    match_id: int; selection: str; amount: float; coefficient: float
class GameRequest(BaseModel):
    game: str; amount: float; bet_amount: float
class CrashStart(BaseModel):
    bet: float
class CrashCashout(BaseModel):
    multiplier: float

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if bot:
        try:
            update = types.Update.model_validate(await request.json(), context={"bot": bot})
            await dp.feed_update(bot, update)
        except: pass
    return {}

@app.get("/api/init")
async def api_init(tg_id: int, username: str = "User"):
    if not pool: return {"balance": 0}
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (telegram_id, username) VALUES ($1, $2) ON CONFLICT (telegram_id) DO NOTHING", tg_id, username)
        return {"balance": await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)}

@app.get("/api/matches")
async def api_matches():
    if not pool: return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM matches WHERE status IN ('live', 'scheduled') LIMIT 30")
        return [{**dict(r), 'score_details': json.loads(r['score_details']), 'start_time': r['start_time'].isoformat()} for r in rows]

@app.get("/api/history")
async def api_history(request: Request):
    if not pool: return {"active":[], "history":[]}
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        active = await conn.fetch("SELECT * FROM bets WHERE user_id=$1 AND status='active' ORDER BY id DESC", tg_id)
        history = await conn.fetch("SELECT * FROM bets WHERE user_id=$1 AND status!='active' ORDER BY id DESC LIMIT 20", tg_id)
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

@app.post("/api/bet")
async def api_bet(data: BetRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.amount: raise HTTPException(400, "Нет денег")
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.amount, tg_id)
        await conn.execute("INSERT INTO bets (user_id, match_id, game_type, amount, bet_selection, coefficient, potential_win) VALUES ($1, $2, 'sport', $3, $4, $5, $6)", tg_id, data.match_id, data.amount, data.bet_selection, data.coefficient, data.amount * data.coefficient)
        return {"status": "ok", "new_balance": float(bal) - data.amount}

@app.post("/api/game")
async def api_game(data: GameRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", data.amount, tg_id)
        status = 'won' if data.amount > 0 else 'lost'
        await conn.execute("INSERT INTO bets (user_id, game_type, amount, status, potential_win) VALUES ($1, $2, $3, $4, $5)", tg_id, data.game, data.bet_amount, status, data.amount if data.amount > 0 else 0)
        return {"new_balance": await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)}

@app.post("/api/crash/start")
async def crash_start(data: CrashStart, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.bet: raise HTTPException(400, "Low balance")
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.bet, tg_id)
        cp = round(0.99 / (1 - random.random()), 2)
        await conn.execute("INSERT INTO crash_games (user_id, crash_point, bet_amount, is_active) VALUES ($1, $2, $3, TRUE) ON CONFLICT (user_id) DO UPDATE SET crash_point=$2, bet_amount=$3, is_active=TRUE", tg_id, cp, data.bet)
        return {"status": "started", "balance": float(bal) - data.bet}

@app.post("/api/crash/cashout")
async def crash_cashout(data: CrashCashout, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        g = await conn.fetchrow("SELECT * FROM crash_games WHERE user_id=$1 AND is_active=TRUE", tg_id)
        if not g: raise HTTPException(400, "No game")
        win = 0
        status = 'lost'
        if data.multiplier <= float(g['crash_point']):
            win = float(g['bet_amount']) * data.multiplier
            status = 'won'
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", win, tg_id)
        
        await conn.execute("UPDATE crash_games SET is_active=FALSE WHERE user_id=$1", tg_id)
        await conn.execute("INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient) VALUES ($1, 'crash', $2, $3, $4, $5)", tg_id, g['bet_amount'], status, win, data.multiplier)
        return {"status": status, "win": win, "crash_point": float(g['crash_point']), "balance": await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
