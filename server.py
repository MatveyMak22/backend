import asyncio
import logging
import sys
import random
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo
import asyncpg # <--- ТЕПЕРЬ ИСПОЛЬЗУЕМ POSTGRES

# === НАСТРОЙКИ ===
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
ADMIN_IDS = [7421386195] 

# ВСТАВЬТЕ СЮДА ССЫЛКУ ИЗ NEON.TECH (postgres://...)
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require'"

# ССЫЛКА НА ВАШ GITHUB PAGES (ФРОНТЕНД)
FRONTEND_URL = "https://matveymak22.github.io/Cas"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pool = None # Пул соединений с БД

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
        start_time_offset = random.randint(10, 80)
        MATCHES.append({
            'id': random.randint(1000, 9999), 'cat': cat, 'isLive': True,
            't1': tms.pop() if tms else "A", 't2': tms.pop() if tms else "B",
            's1': random.randint(0, 3), 's2': random.randint(0, 3),
            'time': start_time_offset, 'sets': [[0,0]] if cat == 'tennis' else None,
            'setScore': [0,0] if cat == 'tennis' else None,
            'timestamp': now - (start_time_offset * 60000)
        })
        for i in range(3):
            mins_future = (i + 1) * 45 + random.randint(0, 30)
            MATCHES.append({
                'id': random.randint(1000, 9999), 'cat': cat, 'isLive': False,
                't1': tms.pop() if tms else "A", 't2': tms.pop() if tms else "B",
                's1': 0, 's2': 0, 'time': 0, 'sets': None,
                'timestamp': now + (mins_future * 60000)
            })

async def sport_ticker():
    while True:
        await asyncio.sleep(1)
        for m in MATCHES:
            if m['isLive']:
                m['time'] += 1
                if random.random() < 0.15:
                    who = 0 if random.random() > 0.5 else 1
                    if m['cat'] == 'tennis':
                        idx = len(m['sets']) - 1
                        m['sets'][idx][who] += 1
                        if m['sets'][idx][who] >= 11 and (m['sets'][idx][who] - m['sets'][idx][1-who] >= 2):
                            m['setScore'][who] += 1
                            m['sets'].append([0, 0])
                        m['s1'], m['s2'] = m['setScore'][0], m['setScore'][1]
                    elif m['cat'] == 'basketball':
                        m['s1' if who==0 else 's2'] += (3 if random.random()>0.7 else 2)
                    else:
                        m['s1' if who==0 else 's2'] += 1

# === ИНИЦИАЛИЗАЦИЯ БД (POSTGRES) ===
async def init_db():
    global pool
    # Создаем пул соединений
    pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with pool.acquire() as conn:
        # Создаем таблицы (Синтаксис Postgres)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance DOUBLE PRECISION DEFAULT 50.0,
                ref_count INTEGER DEFAULT 0,
                ref_earn DOUBLE PRECISION DEFAULT 0,
                referrer_id BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                game TEXT,
                bet DOUBLE PRECISION,
                win DOUBLE PRECISION,
                coeff DOUBLE PRECISION
            )
        ''')

# === FASTAPI ===
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/matches")
async def get_matches():
    return MATCHES

@app.get("/api/user/{user_id}")
async def get_user(user_id: int, ref_id: int = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        
        if not user:
            start_bal = 50.0
            if ref_id and ref_id != user_id:
                await conn.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = $1", ref_id)
            
            await conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES ($1, $2, $3)", 
                               user_id, start_bal, ref_id)
            return {"balance": start_bal, "ref_count": 0, "ref_earn": 0, "history": []}
        
        rows = await conn.fetch("SELECT game, win, bet, coeff FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 10", user_id)
        hist = [{"game": r['game'], "w": r['win'], "bet": r['bet'], "coeff": r['coeff']} for r in rows]
        
        return {"balance": user['balance'], "ref_count": user['ref_count'], "ref_earn": user['ref_earn'], "history": hist}

@app.post("/api/bet")
async def place_bet(data: dict):
    user_id = data['user_id']
    bet = float(data['bet'])
    win = float(data['win'])
    
    async with pool.acquire() as conn:
        res = await conn.fetchrow("SELECT balance, referrer_id FROM users WHERE user_id = $1", user_id)
        if not res: return {"status": "error"}
        
        bal, ref_id = res['balance'], res['referrer_id']
        new_bal = bal - bet + win
        
        if new_bal < 0: return {"status": "error"}
        
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, user_id)
        await conn.execute("INSERT INTO history (user_id, game, bet, win, coeff) VALUES ($1, $2, $3, $4, $5)", 
                           user_id, data['game'], bet, win, data['coeff'])
        
        if ref_id and win == 0:
            bonus = bet * 0.1
            await conn.execute("UPDATE users SET balance = balance + $1, ref_earn = ref_earn + $1 WHERE user_id = $2", 
                               bonus, ref_id)
            
        return {"status": "ok", "new_balance": new_bal}

# === BOT ===
@dp.message(CommandStart())
async def start(msg: types.Message):
    args = msg.text.split()
    ref = f"?start={args[1]}" if len(args) > 1 else ""
    # Не забудьте обновить FRONTEND_URL выше
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="🎰 Играть", web_app=WebAppInfo(url=f"{FRONTEND_URL}{ref}"))]], resize_keyboard=True)
    await msg.answer("Казино готово! Жми кнопку.", reply_markup=kb)

if __name__ == "__main__":
    import uvicorn
    # Render требует слушать порт, который он передает в $PORT, или по умолчанию 10000
    # Но для локального теста оставим 8000. В Render в настройках укажем команду запуска.

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
