import asyncio
import logging
import os
import sys
from pathlib import Path
from threading import Thread # Для запуска сервера в фоне

# Добавляем Flask для обмана Render
from flask import Flask

from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ================= КОНФИГУРАЦИЯ =================
# Вставьте свои ключи
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
GOOGLE_API_KEY = "AIzaSyBnfoqQOiJpmIXeYIgtq2Lwgn_PutxXskc"

# Папка для временных файлов
TEMP_FOLDER = Path("temp_files")
TEMP_FOLDER.mkdir(exist_ok=True)

# Настройка Gemini
genai.configure(api_key=GOOGLE_API_KEY)

# Настройки безопасности
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

ROLES = {
    "default": "Ты — NeonGPT, умный и полезный ИИ-помощник. Твой стиль общения нейтральный и вежливый. Ты используешь Markdown для форматирования.",
    "coder": "Ты — Senior Developer. Отвечай только по существу, приводи примеры кода на Python или других языках. Минимум слов, максимум кода. Используй блоки кода ```.",
    "friend": "Ты — мой лучший друг. Общайся неформально, на 'ты', используй сленг, смайлики. Будь эмоциональным и поддерживающим.",
    "angry": "Ты — злой и саркастичный робот. Ты ненавидишь отвечать на глупые вопросы, но всё же отвечаешь, сопровождая это едкими комментариями."
}

user_sessions = {}

# ================= FLASK СЕРВЕР (ОБМАНКА) =================
app = Flask('')

@app.route('/')
def home():
    return "I'm alive! Bot is running."

def run_http_server():
    # Render выдает порт через переменную окружения PORT, по умолчанию 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_http_server)
    t.start()

# ================= ИНИЦИАЛИЗАЦИЯ БОТА =================
dp = Dispatcher()

# На Render прокси НЕ НУЖНЫ, подключаемся напрямую
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_model(mode="default"):
    system_instruction = ROLES.get(mode, ROLES["default"])
    return genai.GenerativeModel(
        model_name="gemini-1.5-flash", # Используем Flash (бесплатно и много запросов)
        safety_settings=safety_settings,
        system_instruction=system_instruction
    )

def get_chat_session(user_id, mode="default", force_new=False):
    if user_id not in user_sessions or force_new:
        model = get_model(mode)
        chat = model.start_chat(history=[])
        user_sessions[user_id] = {'chat': chat, 'mode': mode}
    return user_sessions[user_id]['chat']

async def download_file(file_id, file_name):
    file = await bot.get_file(file_id)
    file_path = TEMP_FOLDER / file_name
    await bot.download_file(file.file_path, file_path)
    return file_path

# ================= ХЕНДЛЕРЫ =================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_name = message.from_user.full_name
    await message.answer(
        f"🟢 **NeonGPT Activated**\n\n"
        f"Привет, {user_name}! Я переехал на быстрый сервер Render 🚀.\n"
        f"⚙️ **Команды:** /mode coder, /mode friend, /reset"
    )

@dp.message(Command("reset", "clear"))
async def cmd_reset(message: Message):
    user_id = message.from_user.id
    current_mode = user_sessions.get(user_id, {}).get('mode', 'default')
    get_chat_session(user_id, mode=current_mode, force_new=True)
    await message.answer("🔄 **Память очищена!**")

@dp.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject):
    mode = command.args
    if not mode or mode not in ROLES:
        await message.answer(f"Доступные режимы: {', '.join(ROLES.keys())}")
        return
    
    user_id = message.from_user.id
    get_chat_session(user_id, mode=mode, force_new=True)
    await message.answer(f"🎭 Режим: **{mode}**")

@dp.message(F.photo)
async def photo_handler(message: Message):
    processing_msg = await message.answer("👀 **Смотрю...**")
    try:
        photo = message.photo[-1]
        file_path = await download_file(photo.file_id, f"{message.from_user.id}.jpg")
        
        uploaded_file = genai.upload_file(path=file_path)
        
        import time
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)

        prompt = message.caption if message.caption else "Что здесь?"
        chat = get_chat_session(message.from_user.id)
        response = await chat.send_message_async([prompt, uploaded_file])
        
        await processing_msg.edit_text(response.text)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await processing_msg.edit_text(f"🔴 Ошибка: {e}")

@dp.message(F.voice)
async def voice_handler(message: Message):
    processing_msg = await message.answer("👂 **Слушаю...**")
    try:
        file_path = await download_file(message.voice.file_id, f"{message.from_user.id}.ogg")
        
        uploaded_file = genai.upload_file(path=file_path)
        
        import time
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)
            
        chat = get_chat_session(message.from_user.id)
        response = await chat.send_message_async(["Послушай и ответь.", uploaded_file])
        
        await processing_msg.edit_text(response.text)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await processing_msg.edit_text(f"🔴 Ошибка: {e}")

@dp.message(F.text)
async def text_handler(message: Message):
    user_id = message.from_user.id
    if message.text.startswith('/'): return
    
    bot_msg = await message.answer("⏳") # Смайлик часов
    try:
        chat = get_chat_session(user_id)
        response = await chat.send_message_async(message.text)
        
        if len(response.text) > 4000:
            await bot_msg.delete()
            for x in range(0, len(response.text), 4000):
                await message.answer(response.text[x:x+4000])
        else:
            await bot_msg.edit_text(response.text)
    except Exception as e:
        await bot_msg.edit_text(f"🔴 Ошибка: {e}")

# ================= ЗАПУСК =================
async def main():
    # Запускаем веб-сервер в отдельном потоке
    keep_alive()
    print("🚀 NeonGPT запускается на Render...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен.")
