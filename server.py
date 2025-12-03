#!/usr/bin/env python3
"""
Royal Bet - Telegram Mini App Backend
Production Ready Version
"""

import os
import asyncio
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal

# FastAPI imports
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# Database imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.future import select

# Aiogram imports
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# CONFIGURATION - ПРОДАКШЕН НАСТРОЙКИ
# ============================

# ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА РЕАЛЬНЫЕ!
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"  # Ваш реальный токен
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"  # Neon.tech URL
FRONTEND_URL = "https://matveymak22.github.io/Cas"  # Ваш GitHub Pages

# Проверка конфигурации
if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
    print("⚠️ ВНИМАНИЕ: BOT_TOKEN не установлен!")
    BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"  # Демо токен

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================
# DATABASE MODELS
# ============================

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    balance = Column(Numeric(10, 2), default=5000.00)
    created_at = Column(DateTime, server_default=func.now())

class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    sport = Column(String(50))
    team_home = Column(String(100))
    team_away = Column(String(100))
    score_home = Column(Integer, default=0)
    score_away = Column(Integer, default=0)
    score_details = Column(JSON)
    status = Column(String(20), default="scheduled")
    odds_home = Column(Numeric(5, 2), default=2.00)
    odds_draw = Column(Numeric(5, 2), default=3.00)
    odds_away = Column(Numeric(5, 2), default=2.50)
    start_time = Column(DateTime)
    current_minute = Column(Integer, default=0)
    period = Column(String(20), default="1st")

class Bet(Base):
    __tablename__ = "bets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'))
    match_id = Column(Integer, ForeignKey('matches.id'), nullable=True)
    game_type = Column(String(20))
    amount = Column(Numeric(10, 2))
    status = Column(String(20), default="active")
    potential_win = Column(Numeric(10, 2))
    odds = Column(Numeric(5, 2))
    selected_outcome = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
    settled_at = Column(DateTime, nullable=True)

class CrashGame(Base):
    __tablename__ = "crash_games"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'))
    crash_point = Column(Numeric(5, 2))
    bet_amount = Column(Numeric(10, 2))
    current_multiplier = Column(Numeric(5, 2), default=1.00)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

# ============================
# PYDANTIC SCHEMAS
# ============================

class InitRequest(BaseModel):
    initData: str

class BetRequest(BaseModel):
    user_id: int
    match_id: Optional[int] = None
    game_type: str
    amount: Decimal = Field(gt=0)
    outcome: str
    odds: Optional[Decimal] = None

class GameRequest(BaseModel):
    user_id: int
    game_type: str
    amount: Decimal = Field(gt=0)
    mines_count: Optional[int] = Field(None, ge=3, le=24)
    dice_bet: Optional[str] = None

class CashoutRequest(BaseModel):
    user_id: int
    crash_id: int

# ============================
# APPLICATION SETUP
# ============================

app = FastAPI(title="Royal Bet API", version="1.0.0")

# Настройка CORS для Telegram Mini Apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
engine = None
AsyncSessionLocal = None

# ============================
# DATABASE INITIALIZATION
# ============================

async def init_db():
    """Инициализация базы данных"""
    global engine, AsyncSessionLocal
    
    try:
        # Создание движка с пулом соединений
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )
        
        # Создание фабрики сессий
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Создание таблиц
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ База данных успешно инициализирована")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        # Создаем фейковую сессию для продолжения работы
        AsyncSessionLocal = None
        return False

async def get_db():
    """Получение сессии базы данных"""
    if AsyncSessionLocal is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# ============================
# SIMPLE MATCH GENERATION
# ============================

async def generate_initial_matches():
    """Генерация начальных матчей"""
    try:
        async with AsyncSessionLocal() as session:
            # Проверяем количество существующих матчей
            result = await session.execute(select(Match))
            existing_matches = result.scalars().all()
            
            if len(existing_matches) >= 10:
                return
            
            # Списки команд
            football_teams = ["Зенит", "Спартак", "ЦСКА", "Локомотив", "Динамо", "Краснодар"]
            hockey_teams = ["СКА", "ЦСКА", "Авангард", "Металлург", "Салават Юлаев"]
            tennis_players = ["Джокович", "Алькарас", "Медведев", "Надаль", "Синнер"]
            
            sports = [
                ("football", football_teams, "⚽ Футбол"),
                ("hockey", hockey_teams, "🏒 Хоккей"),
                ("tennis", tennis_players, "🎾 Теннис"),
            ]
            
            # Создаем 10 матчей
            for i in range(10):
                sport_type, teams, _ = random.choice(sports)
                
                if sport_type == "tennis":
                    team1, team2 = random.sample(teams, 2)
                    odds1 = round(random.uniform(1.2, 2.2), 2)
                    odds2 = round(random.uniform(1.2, 2.2), 2)
                    odds_draw = None
                else:
                    team1, team2 = random.sample(teams, 2)
                    odds1 = round(random.uniform(1.5, 3.0), 2)
                    odds2 = round(random.uniform(1.5, 3.0), 2)
                    odds_draw = round(random.uniform(2.5, 3.5), 2)
                
                # Время начала - от 5 до 120 минут от текущего времени
                start_time = datetime.now() + timedelta(minutes=random.randint(5, 120))
                
                match = Match(
                    sport=sport_type,
                    team_home=team1,
                    team_away=team2,
                    odds_home=odds1,
                    odds_draw=odds_draw,
                    odds_away=odds2,
                    start_time=start_time,
                    status="scheduled"
                )
                
                session.add(match)
            
            await session.commit()
            logger.info("✅ Сгенерировано начальных матчей")
            
    except Exception as e:
        logger.error(f"❌ Ошибка генерации матчей: {e}")

# ============================
# SIMPLE GAMES LOGIC
# ============================

class GameManager:
    """Менеджер игр"""
    
    @staticmethod
    async def play_mines(user_id: int, amount: Decimal, mines_count: int, db_session) -> Dict[str, Any]:
        """Игра Mines"""
        try:
            # Получаем пользователя
            result = await db_session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Расчет коэффициента
            cells = 25
            safe_cells = cells - mines_count
            probability = safe_cells / cells
            multiplier = round(1 / probability, 2)
            
            # Списание средств
            user.balance -= amount
            
            # Создание ставки
            bet = Bet(
                user_id=user_id,
                game_type="mines",
                amount=amount,
                potential_win=amount * multiplier,
                odds=multiplier,
                selected_outcome=str(mines_count),
                status="active"
            )
            
            db_session.add(bet)
            await db_session.commit()
            
            # Получаем ID ставки
            await db_session.refresh(bet)
            
            return {
                "success": True,
                "bet_id": bet.id,
                "multiplier": multiplier,
                "mines_count": mines_count,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def cashout_mines(user_id: int, bet_id: int, db_session) -> Dict[str, Any]:
        """Забрать выигрыш в Mines"""
        try:
            # Получаем ставку
            result = await db_session.execute(
                select(Bet).where(
                    Bet.id == bet_id,
                    Bet.user_id == user_id,
                    Bet.status == "active"
                )
            )
            bet = result.scalar_one_or_none()
            
            if not bet:
                raise HTTPException(status_code=404, detail="Ставка не найдена")
            
            # Получаем пользователя
            result = await db_session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Начисляем выигрыш
            user.balance += bet.potential_win
            bet.status = "won"
            bet.settled_at = datetime.now()
            
            await db_session.commit()
            
            return {
                "success": True,
                "win_amount": float(bet.potential_win),
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def play_dice(user_id: int, amount: Decimal, bet_type: str, db_session) -> Dict[str, Any]:
        """Игра Dice"""
        try:
            # Получаем пользователя
            result = await db_session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Бросок кубика
            dice_roll = random.randint(1, 6)
            is_even = dice_roll % 2 == 0
            
            # Определение выигрыша
            multiplier = Decimal("2.0")
            win = (bet_type == "even" and is_even) or (bet_type == "odd" and not is_even)
            
            if win:
                win_amount = amount * multiplier
                user.balance += win_amount
                status = "won"
                potential_win = win_amount
            else:
                user.balance -= amount
                status = "lost"
                potential_win = Decimal("0")
            
            # Создание ставки
            bet = Bet(
                user_id=user_id,
                game_type="dice",
                amount=amount,
                potential_win=potential_win,
                odds=multiplier,
                selected_outcome=bet_type,
                status=status,
                settled_at=datetime.now() if not win else None
            )
            
            db_session.add(bet)
            await db_session.commit()
            
            return {
                "success": True,
                "dice_result": dice_roll,
                "win": win,
                "win_amount": float(win_amount) if win else 0,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def start_crash(user_id: int, amount: Decimal, db_session) -> Dict[str, Any]:
        """Начало игры Crash"""
        try:
            # Получаем пользователя
            result = await db_session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Генерация точки краша (5% шанс мгновенного краша)
            if random.random() < 0.05:
                crash_point = Decimal("1.00")
            else:
                crash_point = Decimal(str(round(random.uniform(1.01, 10.00), 2)))
            
            # Списание средств
            user.balance -= amount
            
            # Создание игры
            game = CrashGame(
                user_id=user_id,
                crash_point=crash_point,
                bet_amount=amount,
                is_active=True
            )
            
            db_session.add(game)
            await db_session.commit()
            await db_session.refresh(game)
            
            return {
                "success": True,
                "game_id": game.id,
                "crash_point": float(crash_point),
                "bet_amount": float(amount)
            }
            
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def cashout_crash(user_id: int, game_id: int, db_session) -> Dict[str, Any]:
        """Забрать выигрыш в Crash"""
        try:
            # Получаем игру
            result = await db_session.execute(
                select(CrashGame).where(
                    CrashGame.id == game_id,
                    CrashGame.user_id == user_id,
                    CrashGame.is_active == True
                )
            )
            game = result.scalar_one_or_none()
            
            if not game:
                raise HTTPException(status_code=404, detail="Игра не найдена")
            
            # Получаем пользователя
            result = await db_session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Генерация текущего множителя (симуляция)
            current_multiplier = Decimal(str(round(random.uniform(1.0, float(game.crash_point) - 0.1), 2)))
            
            if current_multiplier >= game.crash_point:
                # Краш - проигрыш
                win_amount = Decimal("0")
                status = "lost"
                game.is_active = False
            else:
                # Успешный вывод
                win_amount = game.bet_amount * current_multiplier
                user.balance += win_amount
                status = "won"
                game.is_active = False
                game.current_multiplier = current_multiplier
            
            # Создание записи о ставке
            bet = Bet(
                user_id=user_id,
                game_type="crash",
                amount=game.bet_amount,
                potential_win=win_amount,
                odds=current_multiplier,
                selected_outcome="cashout",
                status=status,
                settled_at=datetime.now()
            )
            
            db_session.add(bet)
            await db_session.commit()
            
            return {
                "success": True,
                "multiplier": float(current_multiplier),
                "win_amount": float(win_amount),
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

# ============================
# TELEGRAM BOT HANDLERS
# ============================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """Обработчик команды /start"""
    try:
        async with AsyncSessionLocal() as session:
            # Создаем или получаем пользователя
            result = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    telegram_id=message.from_user.id,
                    username=message.from_user.username or f"user_{message.from_user.id}",
                    balance=5000.00
                )
                session.add(user)
                await session.commit()
            
            # Создаем кнопку для открытия Mini App
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text="🎮 Открыть Royal Bet",
                        web_app=WebAppInfo(url=FRONTEND_URL)
                    )]
                ]
            )
            
            await message.answer(
                f"🎉 Добро пожаловать в *Royal Bet*, {hbold(message.from_user.first_name)}!\n\n"
                f"Ваш стартовый баланс: *5000 ₽*\n\n"
                f"Нажмите кнопку ниже, чтобы начать игру!",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in command_start_handler: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

# ============================
# API ENDPOINTS
# ============================

@app.on_event("startup")
async def startup_event():
    """Запуск приложения"""
    logger.info("🚀 Запуск Royal Bet API...")
    
    # Инициализация базы данных
    db_ok = await init_db()
    
    if db_ok:
        # Генерация начальных матчей
        await generate_initial_matches()
        
        # Запуск бота в фоне
        asyncio.create_task(start_bot())
    else:
        logger.warning("⚠️ База данных не инициализирована, API продолжает работу в ограниченном режиме")
    
    logger.info("✅ Royal Bet API запущен!")

async def start_bot():
    """Запуск бота"""
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "status": "online",
        "service": "Royal Bet API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/init")
async def api_init(request: InitRequest, db: AsyncSession = Depends(get_db)):
    """Инициализация пользователя"""
    try:
        # В реальном приложении здесь должна быть верификация данных из Telegram
        # Для демо используем mock-данные
        
        mock_user_id = 123456789
        mock_username = "demo_user"
        
        # Создаем или получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == mock_user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=mock_user_id,
                username=mock_username,
                balance=5000.00
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        return {
            "success": True,
            "user": {
                "id": user.telegram_id,
                "username": user.username,
                "balance": float(user.balance)
            }
        }
        
    except Exception as e:
        logger.error(f"Error in /api/init: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/matches")
async def get_matches(sport: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Получение списка матчей"""
    try:
        query = select(Match).where(Match.status.in_(["scheduled", "live"])).order_by(Match.start_time)
        
        if sport and sport != "all":
            query = query.where(Match.sport == sport)
        
        result = await db.execute(query)
        matches = result.scalars().all()
        
        matches_list = []
        for match in matches:
            match_dict = {
                "id": match.id,
                "sport": match.sport,
                "team_home": match.team_home,
                "team_away": match.team_away,
                "score_home": match.score_home,
                "score_away": match.score_away,
                "score_details": match.score_details or {},
                "status": match.status,
                "odds_home": float(match.odds_home),
                "odds_draw": float(match.odds_draw) if match.odds_draw else None,
                "odds_away": float(match.odds_away),
                "start_time": match.start_time.isoformat() if match.start_time else None,
                "current_minute": match.current_minute,
                "period": match.period
            }
            matches_list.append(match_dict)
        
        return {"matches": matches_list}
        
    except Exception as e:
        logger.error(f"Error in /api/matches: {e}")
        return {"matches": []}

@app.post("/api/bet")
async def place_bet(bet_request: BetRequest, db: AsyncSession = Depends(get_db)):
    """Размещение ставки"""
    try:
        # Валидация минимальной ставки
        min_bet = Decimal("50.00") if bet_request.game_type == "sport" else Decimal("10.00")
        
        if bet_request.amount < min_bet:
            raise HTTPException(
                status_code=400,
                detail=f"Минимальная ставка: {min_bet} ₽"
            )
        
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == bet_request.user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        if user.balance < bet_request.amount:
            raise HTTPException(status_code=400, detail="Недостаточно средств")
        
        # Получаем коэффициенты
        odds = bet_request.odds
        if not odds and bet_request.match_id:
            result = await db.execute(
                select(Match).where(Match.id == bet_request.match_id)
            )
            match = result.scalar_one_or_none()
            
            if match:
                if bet_request.outcome == "home":
                    odds = match.odds_home
                elif bet_request.outcome == "draw":
                    odds = match.odds_draw if match.odds_draw else Decimal("0")
                elif bet_request.outcome == "away":
                    odds = match.odds_away
        
        if not odds:
            odds = Decimal("2.00")
        
        # Расчет потенциального выигрыша
        potential_win = bet_request.amount * odds
        
        # Списание средств
        user.balance -= bet_request.amount
        
        # Создание ставки
        bet = Bet(
            user_id=bet_request.user_id,
            match_id=bet_request.match_id,
            game_type=bet_request.game_type,
            amount=bet_request.amount,
            odds=odds,
            selected_outcome=bet_request.outcome,
            potential_win=potential_win,
            status="active"
        )
        
        db.add(bet)
        await db.commit()
        await db.refresh(bet)
        await db.refresh(user)
        
        return {
            "success": True,
            "bet_id": bet.id,
            "potential_win": float(potential_win),
            "new_balance": float(user.balance)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/bet: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/game")
async def game_action(game_request: GameRequest, db: AsyncSession = Depends(get_db)):
    """Действие в мини-игре"""
    try:
        # Валидация минимальной ставки
        if game_request.amount < Decimal("10.00"):
            raise HTTPException(
                status_code=400,
                detail="Минимальная ставка в играх: 10 ₽"
            )
        
        if game_request.game_type == "mines":
            if not game_request.mines_count:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите количество мин"
                )
            
            result = await GameManager.play_mines(
                game_request.user_id,
                game_request.amount,
                game_request.mines_count,
                db
            )
            
        elif game_request.game_type == "dice":
            if not game_request.dice_bet:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите тип ставки (odd/even)"
                )
            
            result = await GameManager.play_dice(
                game_request.user_id,
                game_request.amount,
                game_request.dice_bet,
                db
            )
            
        else:
            raise HTTPException(
                status_code=400,
                detail="Неподдерживаемый тип игры"
            )
        
        return {"success": True, **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/crash/start")
async def crash_start(game_request: GameRequest, db: AsyncSession = Depends(get_db)):
    """Начало игры Crash"""
    try:
        if game_request.amount < Decimal("10.00"):
            raise HTTPException(
                status_code=400,
                detail="Минимальная ставка в Crash: 10 ₽"
            )
        
        result = await GameManager.start_crash(
            game_request.user_id,
            game_request.amount,
            db
        )
        
        return {"success": True, **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/crash/start: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/crash/cashout")
async def crash_cashout(cashout_request: CashoutRequest, db: AsyncSession = Depends(get_db)):
    """Вывод в игре Crash"""
    try:
        result = await GameManager.cashout_crash(
            cashout_request.user_id,
            cashout_request.crash_id,
            db
        )
        
        return {"success": True, **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/crash/cashout: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/mines/cashout")
async def mines_cashout(cashout_request: CashoutRequest, db: AsyncSession = Depends(get_db)):
    """Вывод в игре Mines"""
    try:
        result = await GameManager.cashout_mines(
            cashout_request.user_id,
            cashout_request.crash_id,  # Здесь это bet_id
            db
        )
        
        return {"success": True, **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/mines/cashout: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/history")
async def get_history(user_id: int, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Получение истории ставок"""
    try:
        query = (
            select(Bet)
            .where(Bet.user_id == user_id)
            .order_by(Bet.created_at.desc())
            .limit(limit)
        )
        
        result = await db.execute(query)
        bets = result.scalars().all()
        
        history = []
        for bet in bets:
            history.append({
                "id": bet.id,
                "game_type": bet.game_type,
                "amount": float(bet.amount),
                "potential_win": float(bet.potential_win),
                "odds": float(bet.odds),
                "status": bet.status,
                "outcome": bet.selected_outcome,
                "created_at": bet.created_at.isoformat() if bet.created_at else None,
                "settled_at": bet.settled_at.isoformat() if bet.settled_at else None
            })
        
        return {"history": history}
        
    except Exception as e:
        logger.error(f"Error in /api/history: {e}")
        return {"history": []}

@app.get("/api/balance")
async def get_balance(user_id: int, db: AsyncSession = Depends(get_db)):
    """Получение баланса"""
    try:
        result = await db.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return {"balance": float(user.balance)}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Проверка работоспособности"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Royal Bet API"
    }

# ============================
# MAIN ENTRY POINT
# ============================

if __name__ == "__main__":
    import uvicorn
    
    # Запуск FastAPI сервера
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
