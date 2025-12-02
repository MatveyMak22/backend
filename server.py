import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Читаем переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")

# Проверка токена при старте (чтобы видеть в логах Render)
if not BOT_TOKEN:
    logger.critical("❌ ОШИБКА: BOT_TOKEN не найден! Проверь Environment Variables.")
else:
    logger.info(f"✅ Бот токен найден: {BOT_TOKEN[:5]}***")

# --- DATABASE POOL ---
pool: asyncpg.Pool = None

async def init_db():
    """Создание таблиц при старте"""
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                balance NUMERIC(10, 2) DEFAULT 5000.00
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
                status TEXT DEFAULT 'scheduled',
                score_home INT DEFAULT 0,
                score_away INT DEFAULT 0,
                odds_home NUMERIC(5, 2),
                odds_draw NUMERIC(5, 2),
                odds_away NUMERIC(5, 2),
                current_minute INT DEFAULT 0
            )
        """)
        # Таблица ставок (история)
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

# --- GAME ENGINE (SPORTS) ---
TEAMS = {
    "football": ["Real Madrid", "Barcelona", "Man City", "Liverpool", "Bayern", "PSG", "Juventus", "Inter", "Arsenal", "Chelsea"],
    "hockey": ["CSKA", "SKA", "Avangard", "Ak Bars", "Dynamo", "Metallurg", "Spartak", "Torpedo"],
    "basketball": ["Lakers", "Warriors", "Celtics", "Bulls", "Heat", "Nets", "CSKA Basket", "Real Basket"],
    "tennis": ["Djokovic", "Alcaraz", "Medvedev", "Sinner", "Rublev", "Zverev", "Tsitsipas", "Nadal"]
}

async def sports_engine():
    """Фоновая задача: генерация матчей и изменение счета"""
    while True:
        try:
            if not pool:
                await asyncio.sleep(1)
                continue

            async with pool.acquire() as conn:
                # 1. Генерация новых матчей (если мало)
                count = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')")
                if count < 15:
                    for sport, teams_list in TEAMS.items():
                        if random.random() > 0.4: continue # Не создаем слишком часто
                        
                        t1, t2 = random.sample(teams_list, 2)
                        start_time = datetime.utcnow() + timedelta(minutes=random.randint(1, 60))
                        
                        # Коэффициенты
                        k1 = round(random.uniform(1.2, 2.8), 2)
                        k2 = round(random.uniform(1.2, 3.5), 2)
                        # Ничья только для футбола/хоккея
                        kx = round(random.uniform(2.5, 4.0), 2) if sport in ['football', 'hockey'] else 0
                        
                        await conn.execute("""
                            INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """, sport, t1, t2, start_time, k1, kx, k2)

                # 2. Обновление LIVE матчей
                live_matches = await conn.fetch("SELECT * FROM matches WHERE status = 'live'")
                for m in live_matches:
                    sport = m['sport']
                    s1 = m['score_home']
                    s2 = m['score_away']
                    minute = m['current_minute'] + 1
                    
                    # Шанс гола
                    if random.random() < 0.15: 
                        if random.random() > 0.5: s1 += 1
                        else: s2 += 1
                    
                    # Условия окончания
                    finished = False
                    if sport == 'football' and minute >= 90: finished = True
                    if sport == 'hockey' and minute >= 60: finished = True
                    if sport == 'basketball' and minute >= 48: finished = True
                    if sport == 'tennis' and (s1 >= 2 or s2 >= 2): finished = True # Упрощенно до 2 сетов/очков

                    if finished:
                        await conn.execute("UPDATE matches SET status='finished', score_home=$1, score_away=$2 WHERE id=$3", s1, s2, m['id'])
                        # Рассчет ставок
                        winner = 'home' if s1 > s2 else ('away' if s2 > s1 else 'draw')
                        bets = await conn.fetch("SELECT * FROM bets WHERE match_id=$1 AND status='active'", m['id'])
                        for b in bets:
                            if b['bet_selection'] == winner:
                                await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", b['potential_win'], b['user_id'])
                                await conn.execute("UPDATE bets SET status='won' WHERE id=$1", b['id'])
                            else:
                                await conn.execute("UPDATE bets SET status='lost' WHERE id=$1", b['id'])
                    else:
                        await conn.execute("UPDATE matches SET current_minute=$1, score_home=$2, score_away=$3 WHERE id=$4", minute, s1, s2, m['id'])

                # 3. Запуск запланированных
                await conn.execute("UPDATE matches SET status='live' WHERE status='scheduled' AND start_time <= NOW()")

        except Exception as e:
            logger.error(f"Engine Error: {e}")
        
        await asyncio.sleep(5) # Тик раз в 5 секунд

# --- BOT SETUP ---
bot = Bot(token=BOT_TOKEN or "123:fake") # Фейк токен, чтобы не падало при импорте, валидация ниже
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Регистрируем юзера
    if pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (telegram_id, username) VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO NOTHING
            """, message.from_user.id, message.from_user.username)
            
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎰 Играть (WebApp)", web_app=WebAppInfo(url=FRONTEND_URL))]
    ])
    await message.answer("Добро пожаловать в Royal Bet!", reply_markup=kb)

# --- FASTAPI APP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing! Server might fail.")
    
    await init_db()
    asyncio.create_task(sports_engine())
    
    # Webhook
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook" if os.getenv('RENDER_EXTERNAL_HOSTNAME') else None
    if webhook_url and BOT_TOKEN:
        try:
            await bot.set_webhook(webhook_url)
            logger.info(f"Webhook set to {webhook_url}")
        except Exception as e:
            logger.error(f"Webhook fail: {e}")
    yield
    # Shutdown
    if BOT_TOKEN:
        await bot.delete_webhook()
    if pool:
        await pool.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API MODELS ---
class BetRequest(BaseModel):
    match_id: int
    selection: str
    amount: float
    coefficient: float

class GameRequest(BaseModel):
    game: str
    amount: float # Отрицательное число = ставка, Положительное = выигрыш

# --- API ENDPOINTS ---

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return {}

@app.get("/api/init")
async def api_init(tg_id: int, username: str = ""):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username) VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET username = $2
        """, tg_id, username)
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"balance": bal}

@app.get("/api/matches")
async def api_matches():
    async with pool.acquire() as conn:
        # Берем Live и ближайшие Scheduled
        live = await conn.fetch("SELECT * FROM matches WHERE status='live' ORDER BY start_time ASC")
        upcoming = await conn.fetch("SELECT * FROM matches WHERE status='scheduled' ORDER BY start_time ASC LIMIT 20")
        
        # Формируем единый список для фронтенда
        result = []
        for row in live + upcoming:
            m = dict(row)
            m['start_time'] = m['start_time'].isoformat() # Convert date to string
            result.append(m)
            
        return result # Фронт сам фильтрует live/upcoming по статусу

@app.post("/api/bet")
async def api_bet_sport(data: BetRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.amount:
            raise HTTPException(400, "Недостаточно средств")
        
        win_pot = data.amount * data.coefficient
        
        async with conn.transaction():
            await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.amount, tg_id)
            await conn.execute("""
                INSERT INTO bets (user_id, match_id, game_type, amount, bet_selection, coefficient, potential_win)
                VALUES ($1, $2, 'sport', $3, $4, $5, $6)
            """, tg_id, data.match_id, data.amount, data.selection, data.coefficient, win_pot)
            
        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"status": "ok", "new_balance": new_bal}

@app.post("/api/game")
async def api_game_result(data: GameRequest, request: Request):
    """
    Универсальный эндпоинт для игр (Mines, Dice).
    Фронтенд шлет amount: -100 (начало игры) или amount: 500 (выигрыш).
    """
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        
        # Проверка баланса при списании
        if data.amount < 0 and (bal + data.amount < 0):
            raise HTTPException(400, "Недостаточно средств")
            
        # Обновляем баланс
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", data.amount, tg_id)
        
        # Записываем в историю (упрощенно)
        status = 'won' if data.amount > 0 else 'lost'
        win_amount = data.amount if data.amount > 0 else 0
        bet_amount = abs(data.amount) if data.amount < 0 else 0
        
        # Логируем только если это значимое действие (можно настроить)
        # Для истории фронтенда: записываем как ставку
        await conn.execute("""
            INSERT INTO bets (user_id, game_type, amount, status, potential_win, coefficient)
            VALUES ($1, $2, $3, $4, $5, 1.0)
        """, tg_id, data.game, bet_amount, status, win_amount)

        new_bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        return {"new_balance": new_bal}

@app.get("/api/history")
async def api_history(request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID"))
    async with pool.acquire() as conn:
        active = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id=$1 AND b.status='active' ORDER BY b.created_at DESC
        """, tg_id)
        
        history = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id=$1 AND b.status!='active' ORDER BY b.created_at DESC LIMIT 30
        """, tg_id)
        
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
