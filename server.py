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

# --- CONFIGURATION (ВСТАВЬ СВОИ ДАННЫЕ НИЖЕ) ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 👇👇👇 ЗАПОЛНИ ЭТИ 3 СТРОЧКИ СВОИМИ ДАННЫМИ 👇👇👇

# 1. Твой токен от BotFather
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE" 

# 2. Твоя ссылка на базу данных (из Neon)
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# 3. Ссылка на твой сайт (GitHub Pages)
FRONTEND_URL = "https://matveymak22.github.io/Cas" 

# 👆👆👆 БОЛЬШЕ НИЧЕГО ТРОГАТЬ НЕ НУЖНО 👆👆👆


pool: asyncpg.Pool = None

# --- DATABASE SETUP ---
async def init_db():
    global pool
    # Проверка, что ты заполнил данные
    if "..." in DATABASE_URL or "ТВОЙ" in DATABASE_URL:
        logger.critical("❌ ТЫ ЗАБЫЛ ВСТАВИТЬ СВОИ ДАННЫЕ В КОД SERVER.PY!")
        return

    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            # Создаем таблицы
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
        logger.info("✅ База данных успешно подключена и таблицы созданы!")
    except Exception as e:
        logger.error(f"❌ ОШИБКА ПОДКЛЮЧЕНИЯ К БАЗЕ: {e}")

# --- SPORTS DATA (БОЛЬШОЙ СПИСОК КОМАНД НА РУССКОМ) ---
TEAMS = {
    "football": [
        "Зенит", "Спартак Москва", "ЦСКА", "Краснодар", "Динамо Москва", "Локомотив", "Ростов", "Крылья Советов",
        "Реал Мадрид", "Барселона", "Манчестер Сити", "Ливерпуль", "Арсенал", "Челси", "Манчестер Юнайтед",
        "Бавария", "Боруссия Д", "ПСЖ", "Интер", "Милан", "Ювентус", "Наполи", "Атлетико Мадрид"
    ],
    "hockey": [
        "ЦСКА", "СКА", "Ак Барс", "Авангард", "Металлург Мг", "Динамо Мск", "Салават Юлаев", "Трактор", "Автомобилист",
        "Вашингтон Кэпиталз", "Тампа-Бэй Лайтнинг", "Питтсбург Пингвинз", "Колорадо Эвеланш", "Эдмонтон Ойлерз", 
        "Торонто Мейпл Лифс", "Нью-Йорк Рейнджерс", "Вегас Голден Найтс"
    ],
    "tennis": [
        "Даниил Медведев", "Новак Джокович", "Карлос Алькарас", "Янник Синнер", "Андрей Рублев", 
        "Александр Зверев", "Стефанос Циципас", "Хольгер Руне", "Карен Хачанов", "Каспер Рууд",
        "Хуберт Хуркач", "Алекс де Минор", "Тейлор Фриц", "Григор Димитров"
    ],
    "table_tennis": [
        "Фан Чжэньдун", "Ма Лун", "Ван Чуцинь", "Лян Цзингунь", "Томоказу Харимото", 
        "Дмитрий Овчаров", "Тимо Болл", "Линь Юньжу", "Уго Кальдерано", "Чжан Бэн",
        "Владимир Самсонов", "Кристиан Карлссон", "Трулс Морегард"
    ],
    "basketball": [
        "ЦСКА", "Зенит", "УНИКС", "Локомотив-Кубань", "Пари Нижний Новгород", "Енисей",
        "Лейкерс", "Голден Стэйт", "Бостон Селтикс", "Майами Хит", "Чикаго Буллз", 
        "Бруклин Нетс", "Денвер Наггетс", "Даллас Маверикс", "Реал Мадрид", "Барселона"
    ]
}

async def sports_engine():
    """Генерация матчей"""
    while True:
        try:
            if pool:
                async with pool.acquire() as conn:
                    # 1. Создаем матчи если пусто (держим около 15 активных/предстоящих)
                    count = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')")
                    if count < 15:
                        for sport, teams_list in TEAMS.items():
                            # Берем случайные команды
                            if random.random() > 0.6: continue # Не создаем слишком много сразу
                            t1, t2 = random.sample(teams_list, 2)
                            
                            # Время начала (от сейчас до +2 часов)
                            start = datetime.utcnow() + timedelta(minutes=random.randint(2, 120))
                            
                            # Наборы сетов для тенниса (пустые заготовки)
                            sets = []
                            if sport == 'tennis': sets = [[0,0], [0,0], [0,0]]
                            elif sport == 'table_tennis': sets = [[0,0], [0,0], [0,0], [0,0], [0,0]]
                            
                            # Генерируем коэффициенты (рандом с маржой)
                            k1 = round(random.uniform(1.4, 2.8), 2)
                            k2 = round(random.uniform(1.4, 3.5), 2)
                            # Ничья только в футболе и хоккее
                            kx = round(random.uniform(2.8, 4.5), 2) if sport in ['football', 'hockey'] else 0
                            
                            await conn.execute("""
                                INSERT INTO matches (sport, team_home, team_away, start_time, odds_home, odds_draw, odds_away, score_details)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """, sport, t1, t2, start, k1, kx, k2, json.dumps(sets))
                    
                    # 2. Обновляем Live матчи
                    live = await conn.fetch("SELECT * FROM matches WHERE status='live'")
                    for m in live:
                        s1, s2 = m['score_home'], m['score_away']
                        details = json.loads(m['score_details'])
                        sport = m['sport']
                        
                        # Простая симуляция изменения счета
                        # Шанс изменения счета зависит от вида спорта
                        chance = 0.15 # 15% шанс каждое обновление (раз в 5 сек)
                        
                        if random.random() < chance:
                            if random.random() > 0.5: s1 += 1
                            else: s2 += 1
                            
                            # Для тенниса обновляем визуально первый сет (упрощенно)
                            if len(details) > 0:
                                details[0][0] = s1
                                details[0][1] = s2
                        
                        finished = False
                        # Условия завершения
                        if sport == 'football' and m['current_minute'] >= 90: finished = True
                        elif sport == 'hockey' and m['current_minute'] >= 60: finished = True
                        elif sport == 'basketball' and m['current_minute'] >= 48: finished = True
                        elif sport == 'tennis' and (s1 >= 6 or s2 >= 6): finished = True 
                        elif sport == 'table_tennis' and (s1 >= 11 or s2 >= 11): finished = True
                        
                        if finished:
                            await conn.execute("UPDATE matches SET status='finished' WHERE id=$1", m['id'])
                            # Выплата выигрышей
                            win_sel = 'home' if s1 > s2 else ('away' if s2 > s1 else 'draw')
                            bets = await conn.fetch("SELECT * FROM bets WHERE match_id=$1 AND status='active'", m['id'])
                            for b in bets:
                                if b['bet_selection'] == win_sel:
                                    await conn.execute("UPDATE users SET balance=balance+$1 WHERE telegram_id=$2", b['potential_win'], b['user_id'])
                                    await conn.execute("UPDATE bets SET status='won' WHERE id=$1", b['id'])
                                else:
                                    await conn.execute("UPDATE bets SET status='lost' WHERE id=$1", b['id'])
                        else:
                            await conn.execute("UPDATE matches SET score_home=$1, score_away=$2, score_details=$3, current_minute=current_minute+1 WHERE id=$4", 
                                               s1, s2, json.dumps(details), m['id'])

                    # 3. Запуск запланированных матчей
                    await conn.execute("UPDATE matches SET status='live' WHERE status='scheduled' AND start_time <= NOW()")
        except Exception as e:
            logger.error(f"Engine loop error: {e}")
        await asyncio.sleep(5)

# --- BOT & APP ---
bot = None
dp = Dispatcher()

# Запускаем бота, только если токен реальный
if BOT_TOKEN and "ТВОЙ" not in BOT_TOKEN:
    bot = Bot(token=BOT_TOKEN)
else:
    logger.warning("⚠️ BOT_TOKEN не заполнен в коде! Бот не работает, но API активно.")

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
                logger.info(f"Webhook установлен: {webhook_url}")
            except: pass
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
        # Сортируем: сначала LIVE, потом ближайшие по времени
        rows = await conn.fetch("SELECT * FROM matches WHERE status IN ('live', 'scheduled') ORDER BY status ASC, start_time ASC LIMIT 40")
        return [{**dict(r), 'score_details': json.loads(r['score_details']), 'start_time': r['start_time'].isoformat()} for r in rows]

@app.get("/api/history")
async def api_history(request: Request):
    if not pool: return {"active":[], "history":[]}
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    async with pool.acquire() as conn:
        active = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id=$1 AND b.status='active' ORDER BY b.created_at DESC
        """, tg_id)
        history = await conn.fetch("""
            SELECT b.*, m.team_home, m.team_away 
            FROM bets b LEFT JOIN matches m ON b.match_id = m.id 
            WHERE b.user_id=$1 AND b.status!='active' ORDER BY b.created_at DESC LIMIT 20
        """, tg_id)
        return {"active": [dict(r) for r in active], "history": [dict(r) for r in history]}

@app.post("/api/bet")
async def api_bet(data: BetRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    if data.amount < 50: raise HTTPException(400, "Мин ставка 50р")
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.amount: raise HTTPException(400, "Нет денег")
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.amount, tg_id)
        await conn.execute("INSERT INTO bets (user_id, match_id, game_type, amount, bet_selection, coefficient, potential_win) VALUES ($1, $2, 'sport', $3, $4, $5, $6)", tg_id, data.match_id, data.amount, data.bet_selection, data.coefficient, data.amount * data.coefficient)
        return {"status": "ok", "new_balance": float(bal) - data.amount}

@app.post("/api/game")
async def api_game(data: GameRequest, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    if data.bet_amount < 10: raise HTTPException(400, "Мин ставка 10р")
    async with pool.acquire() as conn:
        # Проверка баланса при старте игры (amount < 0)
        if data.amount < 0:
            bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
            if bal < abs(data.amount): raise HTTPException(400, "Нет денег")

        await conn.execute("UPDATE users SET balance = balance + $1 WHERE telegram_id=$2", data.amount, tg_id)
        status = 'won' if data.amount > 0 else 'lost'
        await conn.execute("INSERT INTO bets (user_id, game_type, amount, status, potential_win) VALUES ($1, $2, $3, $4, $5)", tg_id, data.game, data.bet_amount, status, data.amount if data.amount > 0 else 0)
        return {"new_balance": await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)}

@app.post("/api/crash/start")
async def crash_start(data: CrashStart, request: Request):
    tg_id = int(request.headers.get("X-Telegram-ID", 0))
    if data.bet < 10: raise HTTPException(400, "Мин ставка 10р")
    async with pool.acquire() as conn:
        bal = await conn.fetchval("SELECT balance FROM users WHERE telegram_id=$1", tg_id)
        if bal < data.bet: raise HTTPException(400, "Low balance")
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE telegram_id=$2", data.bet, tg_id)
        cp = round(0.99 / (1 - random.random()), 2)
        if cp > 30: cp = 30.0
        if random.random() < 0.05: cp = 1.0 # Мгновенный краш
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
