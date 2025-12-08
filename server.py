import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, FSInputFile
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
GOOGLE_API_KEY = "AIzaSyBnfoqQOiJpmIXeYIgtq2Lwgn_PutxXskc"

# Папка для временного сохранения голосовых и фото
TEMP_FOLDER = Path("temp_files")
TEMP_FOLDER.mkdir(exist_ok=True)

# Настройка Gemini
genai.configure(api_key=GOOGLE_API_KEY)

# Настройки безопасности (отключаем блокировки для свободы общения)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Словарь ролей (System Instructions)
ROLES = {
    "default": "Ты — NeonGPT, умный и полезный ИИ-помощник. Твой стиль общения нейтральный и вежливый. Ты используешь Markdown для форматирования.",
    "coder": "Ты — Senior Developer. Отвечай только по существу, приводи примеры кода на Python или других языках. Минимум слов, максимум кода. Используй блоки кода ```.",
    "friend": "Ты — мой лучший друг. Общайся неформально, на 'ты', используй сленг, смайлики. Будь эмоциональным и поддерживающим.",
    "angry": "Ты — злой и саркастичный робот. Ты ненавидишь отвечать на глупые вопросы, но всё же отвечаешь, сопровождая это едкими комментариями."
}

# Хранилище сессий пользователей: user_id -> {'chat': ChatSession, 'mode': str}
user_sessions = {}

# ================= ИНИЦИАЛИЗАЦИЯ =================
dp = Dispatcher()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_model(mode="default"):
    """Создает объект модели с нужной системной инструкцией"""
    system_instruction = ROLES.get(mode, ROLES["default"])
    return genai.GenerativeModel(
        model_name="models/gemini-2.5-flash", # Или gemini-2.0-flash-exp если доступна
        safety_settings=safety_settings,
        system_instruction=system_instruction
    )

def get_chat_session(user_id, mode="default", force_new=False):
    """Управляет сессией чата (памятью)"""
    if user_id not in user_sessions or force_new:
        model = get_model(mode)
        chat = model.start_chat(history=[])
        user_sessions[user_id] = {'chat': chat, 'mode': mode}
    return user_sessions[user_id]['chat']

async def download_file(file_id, file_name):
    """Скачивает файл из Telegram"""
    file = await bot.get_file(file_id)
    file_path = TEMP_FOLDER / file_name
    await bot.download_file(file.file_path, file_path)
    return file_path

# ================= ХЕНДЛЕРЫ (ОБРАБОТЧИКИ) =================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_name = message.from_user.full_name
    await message.answer(
        f"🟢 **NeonGPT Activated**\n\n"
        f"Привет, {user_name}! Я готов к работе.\n"
        f"Мои возможности:\n"
        f"🗣 Обычный диалог и код\n"
        f"📸 Понимаю фото\n"
        f"🎙 Слышу голосовые\n\n"
        f"⚙️ **Команды:**\n"
        f"`/mode coder` - Режим программиста\n"
        f"`/mode friend` - Режим друга\n"
        f"`/mode default` - Обычный режим\n"
        f"`/reset` - Сбросить память"
    )

@dp.message(Command("reset", "clear"))
async def cmd_reset(message: Message):
    user_id = message.from_user.id
    current_mode = user_sessions.get(user_id, {}).get('mode', 'default')
    get_chat_session(user_id, mode=current_mode, force_new=True)
    await message.answer("🔄 **Память очищена!** Начали с чистого листа.")

@dp.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject):
    """Переключение ролей"""
    mode = command.args
    if not mode or mode not in ROLES:
        await message.answer(f"Доступные режимы: {', '.join(ROLES.keys())}")
        return
    
    user_id = message.from_user.id
    # При смене режима всегда сбрасываем историю, чтобы применить новую системную инструкцию
    get_chat_session(user_id, mode=mode, force_new=True)
    await message.answer(f"🎭 Режим переключен на: **{mode}**")

@dp.message(F.photo)
async def photo_handler(message: Message):
    """Обработка изображений (Зрение)"""
    processing_msg = await message.answer("👀 **Смотрю на фото...**")
    
    try:
        # Скачиваем фото (берем самое большое)
        photo = message.photo[-1]
        file_path = await download_file(photo.file_id, f"{message.from_user.id}.jpg")
        
        # Загружаем в Gemini File API
        uploaded_file = genai.upload_file(path=file_path)
        
        # Получаем текст от пользователя (если есть подпись) или ставим дефолтный
        prompt = message.caption if message.caption else "Опиши подробно, что изображено на этой картинке."
        
        # Получаем сессию и отправляем
        chat = get_chat_session(message.from_user.id)
        response = await chat.send_message_async([prompt, uploaded_file])
        
        await processing_msg.edit_text(response.text)
        
        # Удаляем временный файл
        os.remove(file_path)
        
    except Exception as e:
        await processing_msg.edit_text(f"🔴 Ошибка зрения: {e}")

@dp.message(F.voice)
async def voice_handler(message: Message):
    """Обработка голосовых сообщений (Слух)"""
    processing_msg = await message.answer("👂 **Слушаю...**")
    
    try:
        # Скачиваем голосовое (обычно это .ogg)
        file_path = await download_file(message.voice.file_id, f"{message.from_user.id}.ogg")
        
        # Загружаем аудио в Gemini
        uploaded_file = genai.upload_file(path=file_path)
        
        # Gemini нужно время на обработку аудио (обычно пару секунд)
        import time
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)
            
        chat = get_chat_session(message.from_user.id)
        # Просим модель послушать и ответить
        response = await chat.send_message_async(["Послушай это аудиосообщение и ответь на него (или выполни просьбу из него).", uploaded_file])
        
        await processing_msg.edit_text(response.text)
        
        # Чистим файлы
        os.remove(file_path)
        
    except Exception as e:
        await processing_msg.edit_text(f"🔴 Ошибка слуха: {e}")

@dp.message(F.text)
async def text_handler(message: Message):
    """Обычный текстовый диалог"""
    user_id = message.from_user.id
    user_text = message.text
    
    # Игнорируем команды (они обрабатываются отдельно)
    if user_text.startswith('/'):
        return

    # Сообщение-заглушка
    bot_msg = await message.answer("🟢")
    
    try:
        chat = get_chat_session(user_id)
        response = await chat.send_message_async(user_text)
        
        # Форматирование кода делает сам Gemini через Markdown, Telegram его понимает
        # Если ответ очень длинный, разбиваем (простая реализация)
        if len(response.text) > 4000:
            await bot_msg.delete()
            for x in range(0, len(response.text), 4000):
                await message.answer(response.text[x:x+4000])
        else:
            await bot_msg.edit_text(response.text)
            
    except Exception as e:
        await bot_msg.edit_text(f"🔴 Ошибка: {e}\nПопробуй /reset")

# ================= ЗАПУСК =================
async def main():
    print("🚀 NeonGPT запущен! Нажми Ctrl+C для выхода.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен.")
