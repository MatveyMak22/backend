import os
import asyncio
import logging
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
import aiohttp_cors

# --- КОНФИГУРАЦИЯ ---
# Токен бота (вставь свой или добавь в переменные окружения)
API_TOKEN = os.getenv('BOT_TOKEN', '7543820227:AAGY4q-Y2Z7J7X-X9q9Y4q-Y2Z7J7X-X9q9')

# Ссылка на базу данных PostgreSQL (вставь свою или из переменных окружения)
# Пример: postgresql://user:pass@host:5432/dbname
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require')

# ID Админов (числа через запятую)
ADMIN_IDS = [776092053]

# Ссылка на твой HTML сайт (GitHub Pages)
WEB_APP_URL = 'https://matveymak22.github.io/Cas' 

# --- БАЗА ДАННЫХ (PostgreSQL) ---
async def init_db(app):
    # Создаем пул соединений
    app['db'] = await asyncpg.create_pool(dsn=DATABASE_URL)
    # Создаем таблицу, если нет
    async with app['db'].acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance BIGINT DEFAULT 15000
            )
        ''')

async def close_db(app):
    await app['db'].close()

async def get_balance(pool, user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT balance FROM users WHERE user_id = $1', user_id)
        if row:
            return row['balance']
        else:
            # Новый юзер - создаем
            await conn.execute('INSERT INTO users (user_id, balance) VALUES ($1, 15000)', user_id)
            return 15000

async def update_balance(pool, user_id, new_balance):
    async with pool.acquire() as conn:
        # Сначала убедимся, что юзер существует
        await get_balance(pool, user_id)
        await conn.execute('UPDATE users SET balance = $1 WHERE user_id = $2', new_balance, user_id)

# --- ТЕЛЕГРАМ БОТ ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    # Получаем пул соединений из приложения (хак для доступа к БД из бота)
    pool = app['db']
    bal = await get_balance(pool, msg.from_user.id)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=WEB_APP_URL))]
    ], resize_keyboard=True)
    
    await msg.answer(
        f"👋 Привет, {msg.from_user.first_name}!\n"
        f"💰 Твой баланс: <b>{bal} ₽</b>\n"
        f"Жми кнопку ниже, чтобы начать игру!",
        reply_markup=kb, parse_mode="HTML"
    )

@dp.message(Command("setbal"))
async def cmd_setbal(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return await msg.answer("⛔ У вас нет прав админа.")
    
    try:
        # Формат: /setbal 12345678 50000
        _, target_id, amount = msg.text.split()
        pool = app['db']
        await update_balance(pool, int(target_id), int(amount))
        await msg.answer(f"✅ Баланс игрока <code>{target_id}</code> изменен на {amount} ₽", parse_mode="HTML")
    except:
        await msg.answer("⚠️ Ошибка. Используй: /setbal ID СУММА")

# --- API (ВЕБ-СЕРВЕР) ---
routes = web.RouteTableDef()

@routes.get('/')
async def handle_home(req):
    return web.Response(text="Casino Server is Running with PostgreSQL!")

@routes.get('/api/user')
async def handle_get_user(req):
    try:
        user_id = int(req.query.get('id'))
        pool = req.app['db']
        bal = await get_balance(pool, user_id)
        return web.json_response({'id': user_id, 'balance': bal})
    except Exception as e:
        print(f"Error: {e}")
        return web.json_response({'error': str(e)}, status=400)

@routes.post('/api/save')
async def handle_save_game(req):
    try:
        data = await req.json()
        user_id = int(data.get('id'))
        new_bal = int(data.get('balance'))
        
        pool = req.app['db']
        await update_balance(pool, user_id, new_bal)
        
        return web.json_response({'status': 'ok', 'new_balance': new_bal})
    except Exception as e:
        print(f"Error save: {e}")
        return web.json_response({'error': str(e)}, status=400)

# --- ЗАПУСК ---
async def start_background_tasks(app):
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    
    # Подключаем БД при старте
    app.on_startup.append(init_db)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(close_db)
    
    app.add_routes(routes)
    
    # Настройка CORS (чтобы GitHub Pages мог стучаться на сервер)
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    for route in list(app.router.routes()):
        cors.add(route)
        
    # Render использует порт из переменной окружения
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host='0.0.0.0', port=port)
