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
# ⚙️ НАСТРОЙКИ (ЗАПОЛНИТЕ!)
# ==========================================
BOT_TOKEN = "7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9" 
ADMIN_IDS = [776092053] # Ваш ID цифрами
# Ссылка на базу данных Neon (PostgreSQL)
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require" 
# Ссылка на ваш сайт на GitHub Pages
FRONTEND_URL = "https://matveymak22.github.io/Cas"

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

# Длительность матчей в минутах (реальное время)
DURATIONS = {
    'football': 90,
    'hockey': 60,
    'basketball': 48,
    'tennis': 0, # Теннис играется до победы в сетах, время условно
    'table_tennis': 0
}

def generate_schedule():
    global MATCHES
    # Удаляем старые завершенные матчи
    MATCHES = [m for m in MATCHES if not m.get('finished')]
    
    # Если матчей достаточно, не генерируем новые
    if len(MATCHES) >= 6: return

    now = time.time()
    
    for cat, team_list in TEAMS.items():
        # Перемешиваем команды
        available_teams = list(team_list)
        random.shuffle(available_teams)
        
        # Создаем пары. Берем по 2 команды, пока есть.
        while len(available_teams) >= 2:
            t1 = available_teams.pop()
            t2 = available_teams.pop()
            
            # Решаем: матч уже идет (Live) или будет скоро
            is_live = random.random() < 0.4 # 40% матчей Live
            
            match_id = random.randint(100000, 999999)
            
            if is_live:
                start_offset = random.randint(5, 40) # Идет уже N минут
                start_time = now - (start_offset * 60)
                current_time = start_offset
            else:
                # Начнется через 10 мин - 5 часов
                wait_time = random.randint(10, 300) 
                start_time = now + (wait_time * 60)
                current_time = 0

            MATCHES.append({
                'id': match_id,
                'sport': cat,
                'isLive': is_live,
                't1': t1, 't2': t2,
                's1': random.randint(0, 2) if is_live and cat not in ['basket', 'tennis'] else 0,
                's2': random.randint(0, 2) if is_live and cat not in ['basket', 'tennis'] else 0,
                'time': current_time,
                'startTime': start_time,
                # Теннис/Настольный: сеты
                'sets': [[0,0]] if cat in ['tennis', 'table_tennis'] else None,
                'setScore': [0,0] if cat in ['tennis', 'table_tennis'] else None,
                # Коэффициенты
                'k1': round(random.uniform(1.6, 2.8), 2),
                'kx': round(random.uniform(2.8, 4.5), 2),
                'k2': round(random.uniform(1.6, 2.8), 2),
                'finished': False
            })
            
            # Ограничиваем кол-во матчей одного вида спорта, чтобы не забивать ленту
            if len([m for m in MATCHES if m['sport'] == cat]) >= 3:
                break

# Расчет ставок
async def settle_match(match):
    logging.info(f"🏁 Матч завершен: {match['t1']} vs {match['t2']} ({match['s1']}:{match['s2']})")
    
    # Определяем исход
    res = 'x'
    if match['s1'] > match['s2']: res = '1'
    elif match['s2'] > match['s1']: res = '2'
    
    async with pool.acquire() as conn:
        # Получаем ставки на этот матч
        bets = await conn.fetch("SELECT * FROM sports_bets WHERE match_id = $1", match['id'])
        
        for bet in bets:
            uid = bet['user_id']
            amount = bet['amount']
            choice = bet['choice']
            coeff = bet['coeff']
            
            win_amount = 0
            
            if choice == res:
                win_amount = amount * coeff
                # Начисляем выигрыш на баланс
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", win_amount, uid)
            
            # Переносим в историю
            match_desc = f"{match['t1']} vs {match['t2']}"
            await conn.execute("""
                INSERT INTO history (user_id, game, bet, win, coeff, details) 
                VALUES ($1, $2, $3, $4, $5, $6)
            """, uid, match_desc, amount, win_amount, coeff, f"{match['sport']} | Счет {match['s1']}:{match['s2']}")
            
            # Удаляем из активных
            await conn.execute("DELETE FROM sports_bets WHERE id = $1", bet['id'])

async def sport_ticker():
    while True:
        # Реальное время: ждем 60 секунд
        await asyncio.sleep(60)
        
        now = time.time()
        
        for m in MATCHES:
            if m['finished']: continue
            
            # Если матч еще не начался, проверяем время
            if not m['isLive']:
                if now >= m['startTime']:
                    m['isLive'] = True
                    logging.info(f"▶️ Начался матч: {m['t1']} vs {m['t2']}")
                continue

            # Если матч идет (LIVE)
            m['time'] += 1
            cat = m['sport']
            
            # --- ЛОГИКА ГОЛОВ ---
            # Шанс события в эту минуту
            chance = 0.08 # 8% шанс гола в минуту
            if cat == 'basketball': chance = 0.8 # В баскетболе очки часто
            if cat in ['tennis', 'table_tennis']: chance = 0.6 

            if random.random() < chance:
                who = 0 if random.random() > 0.5 else 1
                
                if cat in ['tennis', 'table_tennis']:
                    # Сеты и геймы
                    cur_set = len(m['sets']) - 1
                    m['sets'][cur_set][who] += 1
                    p1, p2 = m['sets'][cur_set][0], m['sets'][cur_set][1]
                    limit = 11 if cat == 'table_tennis' else 6
                    
                    if p1 >= limit and (p1 - p2) >= 2:
                        m['setScore'][0] += 1; m['sets'].append([0,0])
                    elif p2 >= limit and (p2 - p1) >= 2:
                        m['setScore'][1] += 1; m['sets'].append([0,0])
                    
                    m['s1'], m['s2'] = m['setScore'][0], m['setScore'][1]
                    
                    # Конец игры по сетам (например до 2 побед)
                    if m['setScore'][0] == 2 or m['setScore'][1] == 2:
                        m['finished'] = True
                        asyncio.create_task(settle_match(m))

                elif cat == 'basketball':
                    points = random.choice([2, 3])
                    if who == 0: m['s1'] += points
                    else: m['s2'] += points
                else:
                    # Футбол / Хоккей
                    if who == 0: m['s1'] += 1
                    else: m['s2'] += 1

            # Проверка времени окончания
            duration = DURATIONS.get(cat, 90)
            if duration > 0 and m['time'] >= duration:
                m['finished'] = True
                asyncio.create_task(settle_match(m))
        
        # Обновляем список (удаляем старые, добавляем новые)
        generate_schedule()

# ==========================================
# 💾 БАЗА ДАННЫХ И API
# ==========================================
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance DOUBLE PRECISION DEFAULT 10000.0, ref_count INTEGER DEFAULT 0, ref_earn DOUBLE PRECISION DEFAULT 0, referrer_id BIGINT)")
        # Добавил поле details для деталей матча
        await conn.execute("CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, bet DOUBLE PRECISION, win DOUBLE PRECISION, coeff DOUBLE PRECISION, details TEXT, timestamp TIMESTAMP DEFAULT NOW())")
        await conn.execute("CREATE TABLE IF NOT EXISTS sports_bets (id SERIAL PRIMARY KEY, user_id BIGINT, match_id INTEGER, choice TEXT, amount DOUBLE PRECISION, coeff DOUBLE PRECISION, timestamp TIMESTAMP DEFAULT NOW())")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    generate_schedule()
    asyncio.create_task(sport_ticker()) # Запуск таймера
    asyncio.create_task(dp.start_polling(bot))
    yield
    await bot.session.close()
    await pool.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/matches")
async def api_matches():
    # Отдаем фронту только нужные данные
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
        
        # История (последние 20)
        hist = await conn.fetch("SELECT * FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 20", user_id)
        history_list = [{
            "game": h['game'], "win": h['win'], "bet": h['bet'], 
            "coeff": h['coeff'], "details": h['details']
        } for h in hist]
        
        # Активные ставки
        active = await conn.fetch("SELECT * FROM sports_bets WHERE user_id = $1", user_id)
        active_list = []
        for ab in active:
            # Ищем инфо о матче
            match = next((m for m in MATCHES if m['id'] == ab['match_id']), None)
            match_name = f"{match['t1']} vs {match['t2']}" if match else "Матч завершается..."
            active_list.append({
                "game": match_name, "bet": ab['amount'], "coeff": ab['coeff'], 
                "choice": ab['choice']
            })

        return {"balance": bal, "ref_count": rc, "ref_earn": re, "history": history_list, "active_bets": active_list}

@app.post("/api/bet/sport")
async def bet_sport(data: dict):
    uid, mid, choice, amount, k = data['user_id'], data['match_id'], data['choice'], float(data['amount']), float(data['coeff'])
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", uid)
        if not u or u['balance'] < amount: return {"status": "error", "msg": "No money"}
        
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", amount, uid)
        await conn.execute("INSERT INTO sports_bets (user_id, match_id, choice, amount, coeff) VALUES ($1, $2, $3, $4, $5)", uid, mid, choice, amount, k)
        return {"status": "ok", "new_balance": u['balance'] - amount}

@app.post("/api/bet/instant")
async def bet_instant(data: dict):
    uid, game, bet, win, k = data['user_id'], data['game'], float(data['bet']), float(data['win']), float(data['coeff'])
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", uid)
        if not u or u['balance'] < bet: return {"status": "error"}
        
        new_bal = u['balance'] - bet + win
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, uid)
        # Для мгновенных игр детали простые
        res_str = "Победа" if win > 0 else "Проигрыш"
        await conn.execute("INSERT INTO history (user_id, game, bet, win, coeff, details) VALUES ($1, $2, $3, $4, $5, $6)", 
                           uid, game, bet, win, k, res_str)
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
    await msg.answer("Добро пожаловать!", reply_markup=kb)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
