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

# ==========================================
# ⚙️ НАСТРОЙКИ (ВСТАВЬТЕ СВОИ ДАННЫЕ)
# ==========================================
BOT_TOKEN = "7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9"
ADMIN_IDS = [776092053] # ВАШ ID (числом)
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require" # ССЫЛКА НА БАЗУ NEON
FRONTEND_URL = "https://matveymak22.github.io/Cas" # ССЫЛКА НА САЙТ

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pool = None

# ==========================================
# 🏆 СПОРТИВНЫЕ ДАННЫЕ
# ==========================================
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
    'table_tennis': [ 
        'Иванов А.', 'Петров В.', 'Сидоров С.', 'Кузнецов Д.', 
        'Смирнов Е.', 'Попов М.', 'Васильев К.', 'Михайлов А.'
    ]
}

# Цвета для форм (как на скриншотах)
COLORS = ['#ff9800', '#212121', '#1f6feb', '#e3b341', '#2ea043', '#da3633', '#8b949e', '#ffffff']

def generate_schedule():
    global MATCHES
    MATCHES = [m for m in MATCHES if not m.get('finished')]
    if len(MATCHES) >= 8: return

    now = time.time() * 1000
    
    for cat, team_list in TEAMS.items():
        tms = list(team_list)
        random.shuffle(tms)
        
        while len(tms) >= 2:
            t1 = tms.pop()
            t2 = tms.pop()
            
            is_live = random.random() < 0.4
            match_id = random.randint(100000, 999999)
            
            if is_live:
                start_offset = random.randint(5, 40)
                start_time = now - (start_offset * 60000)
                current_time = start_offset
            else:
                wait_time = random.randint(10, 300)
                start_time = now + (wait_time * 60000)
                current_time = 0

            # Начальный счет
            s1, s2 = 0, 0
            if is_live:
                if cat == 'basketball':
                    s1, s2 = random.randint(30, 60), random.randint(30, 60)
                elif cat not in ['tennis', 'table_tennis']:
                    s1, s2 = random.randint(0, 2), random.randint(0, 2)

            MATCHES.append({
                'id': match_id,
                'sport': cat,
                'isLive': is_live,
                't1': t1, 't2': t2,
                's1': s1, 's2': s2,
                'time': current_time,
                'startTime': start_time,
                # Для красивого отображения форм
                'c1': random.choice(COLORS),
                'c2': random.choice(COLORS),
                # Для тенниса
                'sets': [[0,0]] if cat in ['tennis', 'table_tennis'] else None,
                'setScore': [0,0] if cat in ['tennis', 'table_tennis'] else None,
                # Кэфы
                'k1': round(random.uniform(1.4, 2.9), 2),
                'kx': round(random.uniform(2.8, 4.5), 2),
                'k2': round(random.uniform(1.4, 2.9), 2),
                'finished': False
            })
            
            if len([m for m in MATCHES if m['sport'] == cat]) >= 2: break

# Расчет ставок
async def settle_match(match):
    res = 'x'
    if match['s1'] > match['s2']: res = '1'
    elif match['s2'] > match['s1']: res = '2'
    
    async with pool.acquire() as conn:
        bets = await conn.fetch("SELECT * FROM sports_bets WHERE match_id = $1", match['id'])
        for bet in bets:
            uid = bet['user_id']
            amount = bet['amount']
            choice = bet['choice']
            coeff = bet['coeff']
            
            win_amount = 0
            
            if choice == res:
                win_amount = amount * coeff
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", win_amount, uid)
            
            desc = f"{match['t1']} vs {match['t2']}"
            detail = f"Счет {match['s1']}:{match['s2']} (Исх: {res})"
            
            await conn.execute("""
                INSERT INTO history (user_id, game, bet, win, coeff, details) 
                VALUES ($1, $2, $3, $4, $5, $6)
            """, uid, desc, amount, win_amount, coeff, detail)
            
            await conn.execute("DELETE FROM sports_bets WHERE id = $1", bet['id'])

async def sport_ticker():
    while True:
        await asyncio.sleep(60) # РЕАЛЬНОЕ ВРЕМЯ (1 минута)
        now = time.time() * 1000
        
        for m in MATCHES:
            if m['finished']: continue
            
            if not m['isLive']:
                if now >= m['startTime']: m['isLive'] = True
                continue

            m['time'] += 1
            cat = m['sport']
            
            # Логика счета
            chance = 0.1
            if cat == 'basketball': chance = 0.8
            if cat in ['tennis', 'table_tennis']: chance = 0.6 

            if random.random() < chance:
                who = 0 if random.random() > 0.5 else 1
                
                if cat in ['tennis', 'table_tennis']:
                    cur = len(m['sets']) - 1
                    m['sets'][cur][who] += 1
                    limit = 11 if cat == 'table_tennis' else 6
                    p1, p2 = m['sets'][cur][0], m['sets'][cur][1]
                    
                    if p1 >= limit and (p1-p2) >= 2:
                        m['setScore'][0]+=1; m['sets'].append([0,0])
                    elif p2 >= limit and (p2-p1) >= 2:
                        m['setScore'][1]+=1; m['sets'].append([0,0])
                    
                    m['s1'], m['s2'] = m['setScore'][0], m['setScore'][1]
                    
                    # Победа (Best of 3 или 5)
                    win_limit = 2 if cat == 'table_tennis' else 2
                    if m['setScore'][0] == win_limit or m['setScore'][1] == win_limit:
                        m['finished'] = True
                        asyncio.create_task(settle_match(m))

                elif cat == 'basketball':
                    m['s1' if who==0 else 's2'] += random.choice([2, 3])
                else:
                    m['s1' if who==0 else 's2'] += 1

            # Время матча
            dur = 90
            if cat == 'hockey': dur = 60
            if cat == 'basketball': dur = 48
            
            if cat not in ['tennis', 'table_tennis'] and m['time'] >= dur:
                m['finished'] = True
                asyncio.create_task(settle_match(m))
        
        if len([m for m in MATCHES if not m['finished']]) < 5:
            generate_schedule()

# === БД ===
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance DOUBLE PRECISION DEFAULT 10000.0, ref_count INTEGER DEFAULT 0, ref_earn DOUBLE PRECISION DEFAULT 0, referrer_id BIGINT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet DOUBLE PRECISION, win DOUBLE PRECISION, coeff DOUBLE PRECISION, details TEXT, timestamp TIMESTAMP DEFAULT NOW())")
        await conn.execute("CREATE TABLE IF NOT EXISTS sports_bets (id SERIAL PRIMARY KEY, user_id BIGINT, match_id INTEGER, choice TEXT, amount DOUBLE PRECISION, coeff DOUBLE PRECISION, timestamp TIMESTAMP DEFAULT NOW())")

# === СЕРВЕР ===
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

@app.get("/api/matches")
async def api_matches():
    return [m for m in MATCHES if not m['finished']]

@app.get("/api/user/{user_id}")
async def api_user(user_id: int):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            bal = 10000.0
            rc, re = 0, 0
        else:
            bal, rc, re = user['balance'], user['ref_count'], user['ref_earn']
        
        hist = await conn.fetch("SELECT * FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 20", user_id)
        # Преобразуем в список словарей
        h_list = []
        for r in hist:
            h_list.append({
                "game": r['game'], "win": float(r['win']), "bet": float(r['bet']),
                "coeff": float(r['coeff']), "details": r['details']
            })
            
        active = await conn.fetch("SELECT * FROM sports_bets WHERE user_id = $1", user_id)
        a_list = []
        for r in active:
            match = next((m for m in MATCHES if m['id'] == r['match_id']), None)
            name = f"{match['t1']} - {match['t2']}" if match else "Матч завершен"
            a_list.append({"game": name, "bet": float(r['amount']), "coeff": float(r['coeff']), "choice": r['choice']})

        return {"balance": float(bal), "ref_count": rc, "ref_earn": float(re), "history": h_list, "active_bets": a_list}

@app.post("/api/bet/sport")
async def bet_sport(data: dict):
    uid, amount = data['user_id'], float(data['amount'])
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", uid)
        if not u or u['balance'] < amount: return {"status": "error", "msg": "No money"}
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", amount, uid)
        await conn.execute("INSERT INTO sports_bets (user_id, match_id, choice, amount, coeff) VALUES ($1, $2, $3, $4, $5)", uid, data['match_id'], data['choice'], amount, float(data['coeff']))
        return {"status": "ok", "new_balance": u['balance'] - amount}

@app.post("/api/bet/instant")
async def bet_instant(data: dict):
    uid, bet, win = data['user_id'], float(data['bet']), float(data['win'])
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", uid)
        if not u or u['balance'] < bet: return {"status": "error"}
        new_bal = u['balance'] - bet + win
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, uid)
        res_str = "Победа" if win > 0 else "Проигрыш"
        await conn.execute("INSERT INTO history (user_id, game, bet, win, coeff, details) VALUES ($1, $2, $3, $4, $5, $6)", uid, data['game'], bet, win, float(data['coeff']), res_str)
        return {"status": "ok", "new_balance": new_bal}

@app.post("/api/admin/set")
async def admin_set(data: dict):
    if data['user_id'] not in ADMIN_IDS: return {"status": "error"}
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", float(data['amount']), data['user_id'])
    return {"status": "ok"}

@dp.message(CommandStart())
async def start(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="🎰 Играть", web_app=WebAppInfo(url=FRONTEND_URL))]], resize_keyboard=True)
    await msg.answer("Добро пожаловать в RoyalBet!", reply_markup=kb)

# Админ команды
@dp.message(Command("add"))
async def admin_add(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        _, uid, val = msg.text.split()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(val), int(uid))
        await msg.answer("✅")
    except: await msg.answer("Error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))