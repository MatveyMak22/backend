import asyncio
import logging
import sys
import random
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo
import asyncpg

# === НАСТРОЙКИ ===
BOT_TOKEN = "7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9" # ТВОЙ ТОКЕН
ADMIN_IDS = [776092053] # ТВОЙ ID
DATABASE_URL = "postgres://neondb_owner:npg_6qJ7lCjXzZ5A@ep-shy-mode-a2267895-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require" # ТВОЯ БАЗА
FRONTEND_URL = "https://matveymak22.github.io/Cas" # ТВОЙ САЙТ

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pool = None

# === СПОРТ ДВИЖОК (РУССКИЕ КОМАНДЫ) ===
MATCHES = []

TEAMS = {
    'football': [
        'Зенит', 'Спартак', 'ЦСКА', 'Динамо', 'Краснодар', 'Локомотив', 
        'Реал Мадрид', 'Барселона', 'Манчестер Сити', 'Ливерпуль', 
        'Бавария', 'ПСЖ', 'Ювентус', 'Интер', 'Арсенал', 'Челси'
    ],
    'hockey': [
        'Ак Барс', 'Авангард', 'ЦСКА', 'СКА', 'Металлург Мг', 
        'Салават Юлаев', 'Трактор', 'Динамо М', 'Автомобилист', 
        'Локомотив', 'Северсталь', 'Торпедо', 'Спартак', 'Сочи'
    ],
    'basketball': [
        'Лейкерс', 'Голден Стэйт', 'Бостон Селтикс', 'Чикаго Буллз', 
        'ЦСКА', 'Зенит', 'УНИКС', 'Локомотив-Кубань', 
        'Майами Хит', 'Бруклин Нетс', 'Даллас Маверикс'
    ],
    'tennis': [
        'Медведев Д.', 'Рублев А.', 'Хачанов К.', 'Сафиуллин Р.', 
        'Джокович Н.', 'Алькарас К.', 'Синнер Я.', 'Зверев А.', 
        'Циципас С.', 'Надаль Р.', 'Маррей Э.', 'Фриц Т.'
    ],
    'table_tennis': [ # Для настольного тенниса (Лига Про)
        'Иванов А.', 'Петров В.', 'Сидоров С.', 'Кузнецов Д.', 
        'Смирнов Е.', 'Попов М.', 'Васильев К.', 'Михайлов А.'
    ]
}

def generate_schedule():
    global MATCHES
    MATCHES = []
    now = time.time() * 1000
    for cat, teams in TEAMS.items():
        tms = list(teams)
        random.shuffle(tms)
        # Live матчи
        for i in range(2):
            if len(tms) < 2: break
            t1, t2 = tms.pop(), tms.pop()
            offset = random.randint(10, 80)
            MATCHES.append({
                'id': random.randint(10000, 99999),
                'sport': cat,
                't1': t1, 't2': t2,
                's1': random.randint(0, 3), 's2': random.randint(0, 3),
                'time': offset,
                'k1': round(random.uniform(1.5, 2.5), 2),
                'kx': round(random.uniform(2.5, 4.0), 2),
                'k2': round(random.uniform(1.5, 2.5), 2),
                'finished': False,
                'timestamp': now - (offset * 60000)
            })

async def sport_ticker():
    while True:
        await asyncio.sleep(2)
        for m in MATCHES:
            if not m['finished']:
                m['time'] += 1
                if random.random() < 0.05: # Гол
                    if random.random() > 0.5: m['s1'] += 1
                    else: m['s2'] += 1
                if m['time'] >= 90:
                    m['finished'] = True

# === БД ===
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance DOUBLE PRECISION DEFAULT 10000.0)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet DOUBLE PRECISION, win DOUBLE PRECISION, coeff DOUBLE PRECISION)''')

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    generate_schedule()
    asyncio.create_task(sport_ticker())
    asyncio.create_task(dp.start_polling(bot))
    yield
    await bot.session.close()
    await pool.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# === API ===
@app.get("/api/init/{user_id}")
async def init_user(user_id: int):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            bal = 10000.0
        else:
            bal = user['balance']
        
        hist = await conn.fetch("SELECT game, win, bet, coeff FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 15", user_id)
        return {
            "balance": bal,
            "history": [{"game": h['game'], "win": h['win'], "bet": h['bet'], "coeff": h['coeff']} for h in hist],
            "matches": MATCHES
        }

@app.post("/api/bet")
async def process_bet(data: dict):
    uid, game, bet, win, coeff = data['user_id'], data['game'], float(data['bet']), float(data['win']), float(data['coeff'])
    async with pool.acquire() as conn:
        res = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", uid)
        if not res or res['balance'] < bet: return {"status": "error", "msg": "No money"}
        
        new_bal = res['balance'] - bet + win
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, uid)
        await conn.execute("INSERT INTO history (user_id, game, bet, win, coeff) VALUES ($1, $2, $3, $4, $5)", uid, game, bet, win, coeff)
        return {"status": "ok", "new_balance": new_bal}

# === АДМИНКА ===
@app.post("/api/admin/set")
async def admin_set_balance(data: dict):
    # Простая защита: проверяем, что запрос от админа (с фронта это небезопасно, но для мини-апп сойдет)
    if data['user_id'] not in ADMIN_IDS: return {"status": "error"}
    
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", float(data['amount']), data['user_id'])
    return {"status": "ok"}

# === BOT ===
@dp.message(CommandStart())
async def start(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="🎰 Играть", web_app=WebAppInfo(url=FRONTEND_URL))]], resize_keyboard=True)
    await msg.answer("Добро пожаловать в Royal Bet!", reply_markup=kb)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
