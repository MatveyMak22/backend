import asyncio
import logging
import sys
import random
import time
import os
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo
import asyncpg

# ===========================
# ⚙️ НАСТРОЙКИ
# ===========================
BOT_TOKEN = "7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9" 
ADMIN_IDS = [776092053] 
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require" # ССЫЛКА НА NEON DB
FRONTEND_URL = "https://matveymak22.github.io/Cas" 

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pool = None

# ===========================
# 🏆 СПОРТИВНАЯ БАЗА
# ===========================
MATCHES = []

TEAMS = {
    'football': [
        'Зенит', 'Спартак', 'ЦСКА', 'Динамо', 'Краснодар', 'Локомотив', 'Ростов', 'Крылья Советов',
        'Реал Мадрид', 'Барселона', 'Атлетико', 'Севилья', 'Валенсия', 'Манчестер Сити', 'Арсенал',
        'Ливерпуль', 'МЮ', 'Челси', 'Тоттенхэм', 'Бавария', 'Боруссия Д', 'Байер', 'ПСЖ', 'Монако',
        'Ювентус', 'Интер', 'Милан', 'Наполи', 'Рома', 'Лацио', 'Бенфика', 'Порту', 'Аякс'
    ],
    'hockey': [
        'Ак Барс', 'Авангард', 'ЦСКА', 'СКА', 'Металлург Мг', 'Салават Юлаев', 'Трактор', 'Динамо М',
        'Автомобилист', 'Локомотив', 'Северсталь', 'Торпедо', 'Спартак', 'Сочи', 'Барыс', 'Амур',
        'Адмирал', 'Сибирь', 'Нефтехимик', 'Витязь', 'Куньлунь', 'Минск Динамо', 'Рейнджерс', 'Брюинз'
    ],
    'basketball': [
        'Лейкерс', 'Голден Стэйт', 'Бостон Селтикс', 'Чикаго Буллз', 'Майами Хит', 'Бруклин Нетс',
        'Даллас Маверикс', 'Денвер Наггетс', 'Финикс Санз', 'Милуоки Бакс', 'ЦСКА', 'Зенит', 'УНИКС',
        'Локомотив-Кубань', 'Реал Мадрид Баскет', 'Барселона Баскет', 'Фенербахче', 'Олимпиакос'
    ],
    'table_tennis': [ # Лига Про и подобные
        'Иванов А.', 'Петров В.', 'Сидоров С.', 'Кузнецов Д.', 'Смирнов Е.', 'Попов М.', 
        'Васильев К.', 'Михайлов А.', 'Новиков И.', 'Федоров П.', 'Морозов Г.', 'Волков Д.',
        'Лебедев А.', 'Семенов Р.', 'Егоров М.', 'Павлов К.'
    ]
}

# ===========================
# 🧠 ЛОГИКА СПОРТА
# ===========================
def generate_schedule():
    global MATCHES
    # Чистим старые завершенные (оставляем историю на пару часов)
    now = time.time() * 1000
    MATCHES = [m for m in MATCHES if not m.get('finished') or (now - m.get('timestamp') < 7200000)]
    
    if len(MATCHES) > 15: return # Если матчей много, не генерируем

    for cat, team_list in TEAMS.items():
        tms = list(team_list)
        random.shuffle(tms)
        
        while len(tms) >= 2:
            t1 = tms.pop()
            t2 = tms.pop()
            
            # 30% Live, 70% Future (до 30 часов)
            is_live = random.random() < 0.3
            match_id = random.randint(100000, 999999)
            
            if is_live:
                offset = random.randint(1, 40) # Идет N минут
                start_time = now - (offset * 60000)
                cur_time = offset
            else:
                wait_min = random.randint(10, 1800) # до 30 часов
                start_time = now + (wait_min * 60000)
                cur_time = 0

            # Коэффициенты (Базовые)
            base_k = round(random.uniform(1.6, 2.8), 2)
            
            MATCHES.append({
                'id': match_id,
                'sport': cat,
                'isLive': is_live,
                't1': t1, 't2': t2,
                's1': 0, 's2': 0,
                'time': cur_time,
                'startTime': start_time,
                'sets': [[0,0]] if cat in ['table_tennis'] else None, # Детальный счет по сетам
                'setScore': [0,0] if cat in ['table_tennis'] else None, # Общий счет по сетам
                # Рынки ставок
                'k': {
                    'p1': base_k,
                    'x': round(random.uniform(3.0, 4.5), 2),
                    'p2': round(random.uniform(1.6, 2.8), 2),
                    'tm': 1.85, 'tb': 1.85 # Тотал Меньше/Больше
                },
                'total_val': random.choice([2.5, 3.5, 4.5, 150.5, 200.5]), # Значение тотала (зависит от спорта, упрощено)
                'finished': False
            })
            if len([m for m in MATCHES if m['sport'] == cat]) >= 5: break

async def settle_bet(bet, match, result_str, total_score):
    win_amount = 0
    status = 'lose'
    
    # Логика проверки
    won = False
    if bet['choice'] == 'p1' and result_str == '1': won = True
    elif bet['choice'] == 'p2' and result_str == '2': won = True
    elif bet['choice'] == 'x' and result_str == 'x': won = True
    elif bet['choice'] == 'tm' and total_score < match['total_val']: won = True
    elif bet['choice'] == 'tb' and total_score > match['total_val']: won = True
    
    async with pool.acquire() as conn:
        if won:
            win_amount = bet['amount'] * bet['coeff']
            status = 'win'
            # Обновляем статистику и баланс
            await conn.execute("UPDATE users SET balance = balance + $1, total_won = total_won + $1 WHERE user_id = $2", win_amount, bet['user_id'])
        else:
            # Обновляем проигрыш
            await conn.execute("UPDATE users SET total_lost = total_lost + $1 WHERE user_id = $2", bet['amount'], bet['user_id'])

        # В историю
        details = f"{match['t1']} vs {match['t2']} ({match['s1']}:{match['s2']})"
        await conn.execute("""
            INSERT INTO history (user_id, game, bet, win, coeff, details, status) 
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, bet['user_id'], f"Спорт: {match['sport'].upper()}", bet['amount'], win_amount, bet['coeff'], details, status)
        
        # Удаляем из активных
        await conn.execute("DELETE FROM sports_bets WHERE id = $1", bet['id'])

async def sport_ticker():
    while True:
        await asyncio.sleep(60) # РЕАЛЬНОЕ ВРЕМЯ (1 мин = 1 мин)
        now = time.time() * 1000
        
        for m in MATCHES:
            if m['finished']: continue
            
            # Старт матча
            if not m['isLive'] and now >= m['startTime']:
                m['isLive'] = True
                m['time'] = 0
            
            if m['isLive']:
                m['time'] += 1
                cat = m['sport']
                
                # Шансы на гол/очки
                chance = 0.1 # 10%
                if cat == 'basketball': chance = 0.9 # Часто
                if cat == 'table_tennis': chance = 0.7

                if random.random() < chance:
                    who = 0 if random.random() > 0.5 else 1
                    
                    if cat == 'table_tennis':
                        cur = len(m['sets']) - 1
                        m['sets'][cur][who] += 1
                        p1, p2 = m['sets'][cur][0], m['sets'][cur][1]
                        # Сет до 11
                        if (p1 >= 11 and p1-p2>=2) or (p2 >= 11 and p2-p1>=2):
                            win_set = 0 if p1 > p2 else 1
                            m['setScore'][win_set] += 1
                            if sum(m['setScore']) < 5: # Играем до 3 побед (макс 5 сетов)
                                m['sets'].append([0,0])
                            else:
                                m['finished'] = True # Матч окончен
                        
                        m['s1'], m['s2'] = m['setScore'][0], m['setScore'][1]

                    elif cat == 'basketball':
                        pts = random.choice([2, 3])
                        if who == 0: m['s1'] += pts
                        else: m['s2'] += pts
                    else:
                        if who == 0: m['s1'] += 1
                        else: m['s2'] += 1

                # Время вышло
                dur = 90 if cat=='football' else (60 if cat=='hockey' else 48)
                if cat != 'table_tennis' and m['time'] >= dur:
                    m['finished'] = True

                # Если матч закончился - рассчитываем
                if m['finished']:
                    res = 'x'
                    if m['s1'] > m['s2']: res = '1'
                    elif m['s2'] > m['s1']: res = '2'
                    total = m['s1'] + m['s2']
                    
                    async with pool.acquire() as conn:
                        bets = await conn.fetch("SELECT * FROM sports_bets WHERE match_id = $1", m['id'])
                        for b in bets:
                            asyncio.create_task(settle_bet(b, m, res, total))

        if len([m for m in MATCHES if not m['finished']]) < 5:
            generate_schedule()

# ===========================
# 🖥 API & DB
# ===========================
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, 
                balance DOUBLE PRECISION DEFAULT 10000.0, 
                total_won DOUBLE PRECISION DEFAULT 0,
                total_lost DOUBLE PRECISION DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY, user_id BIGINT, game TEXT, 
                bet DOUBLE PRECISION, win DOUBLE PRECISION, coeff DOUBLE PRECISION, 
                details TEXT, status TEXT, timestamp TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sports_bets (
                id SERIAL PRIMARY KEY, user_id BIGINT, match_id INTEGER, 
                choice TEXT, amount DOUBLE PRECISION, coeff DOUBLE PRECISION,
                details TEXT
            )
        """)

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

@app.get("/api/init/{user_id}")
async def init_user(user_id: int):
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not u:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            u = {'balance': 10000.0, 'total_won': 0, 'total_lost': 0}
        
        hist = await conn.fetch("SELECT * FROM history WHERE user_id = $1 ORDER BY id DESC LIMIT 20", user_id)
        active = await conn.fetch("SELECT * FROM sports_bets WHERE user_id = $1", user_id)
        
        return {
            "user": dict(u),
            "matches": [m for m in MATCHES], # Отдаем все матчи
            "history": [dict(h) for h in hist],
            "active_bets": [dict(a) for a in active]
        }

@app.post("/api/bet/sport")
async def bet_sport(data: dict):
    # data: user_id, match_id, choice ('p1','x','tm'...), amount, coeff, match_name
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", data['user_id'])
        if u['balance'] < data['amount']: return {"status": "error", "msg": "Недостаточно средств"}
        
        await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", data['amount'], data['user_id'])
        await conn.execute("""
            INSERT INTO sports_bets (user_id, match_id, choice, amount, coeff, details)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, data['user_id'], data['match_id'], data['choice'], data['amount'], data['coeff'], data['match_name'])
        
        return {"status": "ok", "new_balance": u['balance'] - data['amount']}

@app.post("/api/game/result")
async def game_result(data: dict):
    # CRASH / MINES / DICE
    # data: user_id, game ('Crash', 'Mines'...), bet, win, coeff
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", data['user_id'])
        
        # Проверка баланса (если ставка не была списана на клиенте)
        # В этой архитектуре мы доверяем клиенту списание 'bet', но начисляем 'win'
        # Правильнее: сначала списать /api/game/start, потом начислить /api/game/end.
        # Для упрощения: Клиент шлет ИТОГ. 
        # Баланс = Баланс - Ставка + Выигрыш.
        
        new_bal = u['balance'] - data['bet'] + data['win']
        if new_bal < 0: return {"status": "error"}
        
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_bal, data['user_id'])
        
        if data['win'] > 0:
            await conn.execute("UPDATE users SET total_won = total_won + $1 WHERE user_id = $2", data['win'], data['user_id'])
            status = 'win'
        else:
            await conn.execute("UPDATE users SET total_lost = total_lost + $1 WHERE user_id = $2", data['bet'], data['user_id'])
            status = 'lose'
            
        await conn.execute("""
            INSERT INTO history (user_id, game, bet, win, coeff, status, details) 
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, data['user_id'], data['game'], data['bet'], data['win'], data['coeff'], status, "Мини-игра")
        
        return {"status": "ok", "new_balance": new_bal}

@app.post("/api/admin/set")
async def adm_set(data: dict):
    if data['user_id'] not in ADMIN_IDS: return {"status": "error"}
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", float(data['amount']), data['user_id'])
    return {"status": "ok"}

@dp.message(CommandStart())
async def start(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="🎰 ОТКРЫТЬ", web_app=WebAppInfo(url=FRONTEND_URL))]], resize_keyboard=True)
    await msg.answer("Твое казино готово!", reply_markup=kb)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))