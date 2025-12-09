import asyncio
import logging
import os
import sys
from pathlib import Path
from threading import Thread # Для запуска сервера-обманки

# Добавляем Flask для Render
from flask import Flask

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, BotCommand # <--- Добавили BotCommand для меню

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ================= КОНФИГУРАЦИЯ =================
# Вставь свои ключи сюда
BOT_TOKEN = "8055430766:AAFOiwd06FIxkUXWnszcTY3YOgWUz4-NEYY"
GOOGLE_API_KEY = "AIzaSyBnfoqQOiJpmIXeYIgtq2Lwgn_PutxXskc"

# Папка для временных файлов
TEMP_FOLDER = Path("temp_files")
TEMP_FOLDER.mkdir(exist_ok=True)

# Настройка Gemini
genai.configure(api_key=GOOGLE_API_KEY)

# Настройки безопасности (отключаем цензуру)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Роли бота
ROLES = {
    "default": "Ты — NeonGPT, умный и полезный ИИ-помощник. Твой стиль общения нейтральный и вежливый. Ты используешь Markdown для форматирования.",
    "coder": "Ты — Senior Developer. Отвечай только по существу, приводи примеры кода на Python или других языках. Минимум слов, максимум кода. Используй блоки кода ```.",
    "friend": "Ты — мой лучший друг. Общайся неформально, на 'ты', используй сленг, смайлики. Будь эмоциональным и поддерживающим.",
    "angry": "Ты — злой и саркастичный робот. Ты ненавидишь отвечать на глупые вопросы, но всё же отвечаешь, сопровождая это едкими комментариями."
}

user_sessions = {}

# ================= FLASK СЕРВЕР (ОБМАНКА ДЛЯ RENDER) =================
app = Flask('')

@app.route('/')
def home():
    return "I'm alive! NeonGPT is running."

def run_http_server():
    # Render сам передает порт, если нет - используем 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_http_server)
    t.start()

# ================= ИНИЦИАЛИЗАЦИЯ БОТА =================
dp = Dispatcher()
# Прокси больше нет, просто чистый бот
bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_model(mode="default"):
    system_instruction = ROLES.get(mode, ROLES["default"])
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash-exp", # Быстрая модель с большими лимитами
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

# ================= ХЕНДЛЕРЫ КОМАНД =================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"👋 **Привет! Я NeonGPT.**\n\n"
        f"Я готов общаться, писать код, смотреть картинки и слушать голосовые.\n\n"
        f"👇 **Нажми кнопку Меню слева внизу**, чтобы выбрать режим!"
    )

@dp.message(Command("reset", "clear"))
async def cmd_reset(message: Message):
    user_id = message.from_user.id
    current_mode = user_sessions.get(user_id, {}).get('mode', 'default')
    get_chat_session(user_id, mode=current_mode, force_new=True)
    await message.answer("🧹 **Память очищена!** Я забыл наш предыдущий разговор.")

# --- Удобные команды для смены режимов ---

@dp.message(Command("coder"))
async def mode_coder(message: Message):
    await set_mode(message, "coder")

@dp.message(Command("friend"))
async def mode_friend(message: Message):
    await set_mode(message, "friend")

@dp.message(Command("angry"))
async def mode_angry(message: Message):
    await set_mode(message, "angry")

@dp.message(Command("default"))
async def mode_default(message: Message):
    await set_mode(message, "default")

async def set_mode(message: Message, mode: str):
    user_id = message.from_user.id
    get_chat_session(user_id, mode=mode, force_new=True)
    await message.answer(f"🎭 Режим переключен: **{mode.upper()}**\n{ROLES[mode][:50]}...")

# ================= ОБРАБОТКА КОНТЕНТА =================

@dp.message(F.photo)
async def photo_handler(message: Message):
    processing_msg = await message.answer("👀 **Смотрю...**")
    try:
        photo = message.photo[-1]
        file_path = await download_file(photo.file_id, f"{message.from_user.id}.jpg")
        
        uploaded_file = genai.upload_file(path=file_path)
        
        # Ждем обработки файла
        import time
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)

        prompt = message.caption if message.caption else "Опиши подробно, что на фото."
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
        response = await chat.send_message_async(["Послушай это и ответь.", uploaded_file])
        
        await processing_msg.edit_text(response.text)
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await processing_msg.edit_text(f"🔴 Ошибка: {e}")

@dp.message(F.text)
async def text_handler(message: Message):
    user_id = message.from_user.id
    if message.text.startswith('/'): return # Игнорируем команды
    
    bot_msg = await message.answer("⏳")
    try:
        chat = get_chat_session(user_id)
        response = await chat.send_message_async(message.text)
        
        if len(response.text) > 4000:
            # Если ответ слишком длинный для одного сообщения
            await bot_msg.delete()
            for x in range(0, len(response.text), 4000):
                await message.answer(response.text[x:x+4000])
        else:
            await bot_msg.edit_text(response.text)
    except Exception as e:
        await bot_msg.edit_text(f"🔴 Ошибка: {e}")

# ================= ГЛАВНАЯ ФУНКЦИЯ =================
async def main():
    # 1. Запускаем сервер (чтобы Render не спал)
    keep_alive()
    
    # 2. Настраиваем кнопку МЕНЮ в Telegram
    commands = [
        BotCommand(command="start", description="🚀 Перезапуск"),
        BotCommand(command="reset", description="🧹 Забыть диалог"),
        BotCommand(command="coder", description="👨‍💻 Режим: Программист"),
        BotCommand(command="friend", description="🍺 Режим: Друг"),
        BotCommand(command="angry", description="🤬 Режим: Токсик"),
        BotCommand(command="default", description="🤖 Режим: Обычный"),
    ]
    await bot.set_my_commands(commands)
    
    print("🚀 NeonGPT запущен на Render! Меню обновлено.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен.")


