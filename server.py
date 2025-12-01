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
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo
import asyncpg

# ==========================================
# ⚙️ НАСТРОЙКИ (ЗАПОЛНИТЕ ЭТО!)
# ==========================================

# 1. Токен от BotFather
BOT_TOKEN = "7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9" 

# 2. Ваш цифровой ID (для админки). Узнать в @getmyid_bot
ADMIN_IDS = [776092053] 

# 3. Ссылка на базу данных Neon (которую вы копировали, начинается на postgresql://)
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# 4. Ссылка на ваш сайт (GitHub Pages). Если её пока нет, оставьте google.com
FRONTEND_URL = "https://matveymak22.github.io/Cas"

# ==========================================

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
        
        # Генерация LIVE матчей (1-2 на категорию)
        live_count = 2
        for i in range(live_count):
            if len(tms) < 2: break
            t1, t2 = tms.pop(), tms.pop()
            offset = random.randint(10, 80) # Матч идет уже столько минут
            
            MATCHES.append({
                'id': random.randint(10000, 99999),
                'sport': cat, 'isLive': True,
                't1': t1, 't2': t2,
                's1': random.randint(0, 3) if cat != 'basket' else random.randint(60, 90),
                's2': random.randint(0, 3) if cat != 'basket' else random.randint(60, 90),
                'time': offset,
                'sets': [[0,0]] if cat in ['tennis', 'table_tennis'] else None,
                'setScore': [0,0] if cat in ['tennis', 'table_tennis'] else None,
                'k1': round(random.uniform(1.5, 2.5), 2),
                'kx': round(random.uniform(2.5, 4.0), 2),
                'k2': round(random.uniform(1.5, 2.5), 2),
                'finished': False,
                'timestamp': now - (offset * 60000)
            })

        # Генерация БУДУЩИХ матчей
        for i in range(3):
            if len(tms) < 2: break
            t1, t2 = tms.pop(), tms.pop()
            mins_future = (i + 1) * 45 + random.randint(0, 30)
            MATCHES.append({
                'id': random.randint(10000, 99999),
                'sport': cat, 'isLive': False,
                't1': t1, 't2': t2,
                's1': 0, 's2': 0, 'time': 0,
                'sets': None, 'setScore': None,
                'k1': round(random.uniform(1.5, 2.5), 2),
                'kx': round(random.uniform(2.5, 4.0), 2),
                'k2': round(random.uniform(1.5, 2.5), 2),
                'finished': False,
                'timestamp': now + (mins_future * 60000)
            })

async def sport_ticker():
    while True:
        await asyncio.sleep(2) # Обновляем раз в 2 секунды
        for m in MATCHES:
            if m['isLive'] and not m['finished']:
                m['time'] += 1
                
                # Логика случайного гола/очка
                if random.random() < 0.15: 
                    who = 0 if random.random() > 0.5 else 1
                    
                    if m['sport'] in ['tennis', 'table_tennis']:
                        # Теннисная логика
                        cur = len(m['sets']) - 1
                        m['sets'][cur][who] += 1
                        p1, p2 = m['sets'][cur][0], m['sets'][cur][1]
                        # Победа в сете (до 11)
                        if p1 >= 11 and (p1 - p2) >= 2:
                            m['setScore'][0] += 1
                            m['sets'].append([0, 0])
                        elif p2 >= 11 and (p2 - p1) >= 2:
                            m['setScore'][1] += 1
                            m['sets'].append([0, 0])
                        
                        m['s1'], m['s2'] = m['setScore'][0], m['setScore'][1]
                        
                    elif m['sport'] == 'basket':
                        m['s1' if who==0 else 's2'] += (3 if random.random()>0.7 else 2)
                    else:
                        m['s1' if who==0 else 's2'] += 1

# === БД ===
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance DOUBLE PRECISION DEFAULT 10000.0,
                ref_count INTEGER DEFAULT 0,
                ref_earn DOUBLE PRECISION DEFAULT 0,
                referrer_id BIGINT
            )
        ''')
        # Таблица истории
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

# Разрешаем запросы с GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === API ENDPOINTS ===

# 1. Получить список матчей
@app.get("/api/matches")
async def get_matches():
    return MATCHES

# 2. Инициализация (Баланс + История + Матчи сразу)
@app.get("/api/init/{user_id}")
async def init_user(user_id: int, ref_id: int = None):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        
        if not user:
            start_bal = 10000.0
            if ref_id and ref_id != user_id:
                await conn.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = $1", ref_id)
            
            await conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES ($1, $2, $3)", 
                               user_id, start_bal, ref_id)
            bal = start_bal
            rc, re = 0, 0
        else:
            bal = user['balance']
            rc, re = user['ref_count'], user['ref_earn']
        
        # Получаем историю
        rows = await conn.fetch("SELECT game, win, bet, coeff FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 15", user_id)
        hist = [{"game": r['game'], "win": r['win'], "bet": r['bet'], "coeff": r['coeff']} for r in rows]
        
        return {
            "balance": bal,
            "ref_count": rc,
            "ref_earn": re,
            "history": hist,
            "matches": MATCHES
        }

# 3. Сделать ставку
@app.post("/api/bet")
async def process_bet(data: dict):
    uid = data['user_id']
    game = data['game']
    bet = float(data['bet'])
    win = float(data['win'])
    coeff = float(data['coeff'])
    
    async with pool.acquire() as conn:
        res = await conn.fetchrow("SELECT balance, referrer_id FROM users WHERE user_id = $1", uid)
        
        if not res: 
            return {"status": "error", "msg": "User not found"}
        
        if res['balance'] < bet:
            return {"status": "error", "msg": "No money"}
        
        # Обновляем баланс
        new_bal = res['balance'] - bet + win
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, uid)
        
        # Записываем в историю
        await conn.execute("INSERT INTO history (user_id, game, bet, win, coeff) VALUES ($1, $2, $3, $4, $5)", 
                           uid, game, bet, win, coeff)
        
        # Рефералка (10% от проигрыша)
        if res['referrer_id'] and win == 0:
            bonus = bet * 0.10
            await conn.execute("UPDATE users SET balance = balance + $1, ref_earn = ref_earn + $1 WHERE user_id = $2", 
                               bonus, res['referrer_id'])
            
        return {"status": "ok", "new_balance": new_bal}

# 4. Админка (Установить баланс)
@app.post("/api/admin/set")
async def admin_set_balance(data: dict):
    # Проверка на админа
    if data['user_id'] not in ADMIN_IDS: 
        return {"status": "error", "msg": "Access denied"}
    
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", float(data['amount']), data['user_id'])
        
    return {"status": "ok"}

# === BOT COMMANDS ===
@dp.message(CommandStart())
async def start(msg: types.Message):
    args = msg.text.split()
    ref = f"?start={args[1]}" if len(args) > 1 else ""
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="🎰 Играть", web_app=WebAppInfo(url=f"{FRONTEND_URL}{ref}"))]], resize_keyboard=True)
    await msg.answer("Добро пожаловать в Казино! Нажмите кнопку ниже.", reply_markup=kb)

if __name__ == "__main__":
    import uvicorn
    # Render передает порт через переменную окружения, локально 8000
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
