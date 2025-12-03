#!/usr/bin/env python3
"""
Royal Bet - Telegram Mini App Backend
Senior Fullstack Developer Implementation
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
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.sql import func

# Aiogram imports
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# CONFIGURATION
# ============================

# ВНИМАНИЕ: Для продакшена используйте переменные окружения!
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"  # Замените на реальный токен
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"  # Замените на реальный URL Neon.tech
FRONTEND_URL = "https://matveymak22.github.io/Cas"  # Замените на ваш GitHub Pages URL

# Проверка конфигурации
if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("⚠️ ВНИМАНИЕ: BOT_TOKEN не установлен!")
if not DATABASE_URL or "localhost" in DATABASE_URL:
    print("⚠️ ВНИМАНИЕ: Используется локальная база данных!")

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
    sport = Column(String(50))  # football, hockey, basketball, tennis, table_tennis
    team_home = Column(String(100))
    team_away = Column(String(100))
    score_home = Column(Integer, default=0)
    score_away = Column(Integer, default=0)
    score_details = Column(JSON)  # Для сетов в теннисе
    status = Column(String(20), default="scheduled")  # scheduled, live, finished
    odds_home = Column(Numeric(5, 2), default=2.00)
    odds_draw = Column(Numeric(5, 2), default=3.00)
    odds_away = Column(Numeric(5, 2), default=2.50)
    start_time = Column(DateTime)
    current_minute = Column(Integer, default=0)  # Текущая минута матча
    period = Column(String(20), default="1st")  # Период/сет

class Bet(Base):
    __tablename__ = "bets"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'))
    match_id = Column(Integer, ForeignKey('matches.id'), nullable=True)
    game_type = Column(String(20))  # sport, mines, dice, crash
    amount = Column(Numeric(10, 2))
    status = Column(String(20), default="active")  # active, won, lost
    potential_win = Column(Numeric(10, 2))
    odds = Column(Numeric(5, 2))
    selected_outcome = Column(String(50))  # home, draw, away, odd, even и т.д.
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
    dice_bet: Optional[str] = None  # odd, even

class CashoutRequest(BaseModel):
    user_id: int
    crash_id: int

# ============================
# APPLICATION SETUP
# ============================

app = FastAPI(title="Royal Bet API", version="1.0.0")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене ограничьте домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
engine = None
async_session = None

# ============================
# DATABASE INITIALIZATION
# ============================

async def init_db():
    """Инициализация базы данных"""
    global engine, async_session
    
    try:
        engine = create_async_engine(DATABASE_URL, echo=False)
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # Создание таблиц
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ База данных успешно инициализирована")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        return False

# ============================
# SPORTS SIMULATION ENGINE
# ============================

class SportsSimulator:
    """Движок симуляции спортивных матчей"""
    
    # Базы данных реальных команд (на русском)
    FOOTBALL_TEAMS = [
        "Зенит", "Спартак", "ЦСКА", "Локомотив", "Динамо",
        "Краснодар", "Ростов", "Ахмат", "Урал", "Крылья Советов",
        "Реал Мадрид", "Барселона", "Бавария", "Манчестер Юнайтед",
        "Ливерпуль", "Манчестер Сити", "Челси", "Арсенал", "Ювентус",
        "Милан", "Интер", "ПСЖ"
    ]
    
    HOCKEY_TEAMS = [
        "СКА", "ЦСКА", "Авангард", "Металлург Мг", "Салават Юлаев",
        "Трактор", "Динамо Мск", "Спартак", "Локомотив", "Торпедо",
        "Вашингтон Кэпиталз", "Питтсбург Пингвинз", "Чикаго Блэкхокс",
        "Бостон Брюинз", "Торонто Мейпл Лифс", "Детройт Ред Уингз",
        "Монреаль Канадиенс"
    ]
    
    BASKETBALL_TEAMS = [
        "ЦСКА", "Зенит", "Локомотив-Кубань", "УНИКС", "Химки",
        "Парма", "Автодор", "Нижний Новгород", "Енисей",
        "Лос-Анджелес Лейкерс", "Голден Стэйт Уорриорз", "Чикаго Буллз",
        "Бостон Селтикс", "Майами Хит", "Сан-Антонио Спёрс"
    ]
    
    TENNIS_PLAYERS = [
        "Новак Джокович", "Карлос Алькарас", "Даниил Медведев",
        "Рафаэль Надаль", "Янник Синнер", "Андрей Рублев",
        "Стефанос Циципас", "Александр Зверев", "Хуберт Хуркач",
        "Тейлор Фритц", "Феликс Оже-Альяссим", "Карен Хачанов"
    ]
    
    TABLE_TENNIS_PLAYERS = [
        "Фань Чжэньдун", "Ван Чуцинь", "Ма Лун", "Лян Цзинкунь",
        "Тимо Болль", "Дмитрий Овчаров", "Линь Гаоюань",
        "Томокадзу Харамото", "Коки Нива", "Хуго Кальдерона"
    ]
    
    def __init__(self, db_session):
        self.db = db_session
        self.running = False
    
    async def generate_matches(self):
        """Генерация матчей, если их меньше 15"""
        try:
            async with self.db() as session:
                # Подсчет текущих активных матчей
                result = await session.execute(
                    "SELECT COUNT(*) FROM matches WHERE status IN ('scheduled', 'live')"
                )
                count = result.scalar()
                
                if count < 15:
                    to_generate = 15 - count
                    
                    for _ in range(to_generate):
                        # Случайный выбор вида спорта
                        sport = random.choice(['football', 'hockey', 'basketball', 'tennis', 'table_tennis'])
                        
                        if sport == 'football':
                            team1, team2 = random.sample(self.FOOTBALL_TEAMS, 2)
                            odds1 = round(random.uniform(1.5, 3.0), 2)
                            odds2 = round(random.uniform(1.5, 3.0), 2)
                            odds_draw = round(random.uniform(2.5, 3.5), 2)
                            start_time = datetime.now() + timedelta(
                                minutes=random.randint(5, 120)
                            )
                            
                        elif sport == 'hockey':
                            team1, team2 = random.sample(self.HOCKEY_TEAMS, 2)
                            odds1 = round(random.uniform(1.5, 2.8), 2)
                            odds2 = round(random.uniform(1.5, 2.8), 2)
                            odds_draw = round(random.uniform(2.8, 3.8), 2)
                            start_time = datetime.now() + timedelta(
                                minutes=random.randint(5, 90)
                            )
                            
                        elif sport == 'basketball':
                            team1, team2 = random.sample(self.BASKETBALL_TEAMS, 2)
                            odds1 = round(random.uniform(1.3, 2.5), 2)
                            odds2 = round(random.uniform(1.3, 2.5), 2)
                            odds_draw = round(random.uniform(15.0, 25.0), 2)  # Ничья в баскетболе редка
                            start_time = datetime.now() + timedelta(
                                minutes=random.randint(5, 60)
                            )
                            
                        elif sport == 'tennis':
                            team1, team2 = random.sample(self.TENNIS_PLAYERS, 2)
                            odds1 = round(random.uniform(1.2, 2.2), 2)
                            odds2 = round(random.uniform(1.2, 2.2), 2)
                            odds_draw = None  # В теннисе нет ничьи
                            start_time = datetime.now() + timedelta(
                                minutes=random.randint(5, 45)
                            )
                            
                        else:  # table_tennis
                            team1, team2 = random.sample(self.TABLE_TENNIS_PLAYERS, 2)
                            odds1 = round(random.uniform(1.2, 2.0), 2)
                            odds2 = round(random.uniform(1.2, 2.0), 2)
                            odds_draw = None
                            start_time = datetime.now() + timedelta(
                                minutes=random.randint(5, 30)
                            )
                        
                        # Создание матча
                        match = Match(
                            sport=sport,
                            team_home=team1,
                            team_away=team2,
                            odds_home=odds1,
                            odds_draw=odds_draw,
                            odds_away=odds2,
                            start_time=start_time,
                            score_details={} if sport not in ['tennis', 'table_tennis'] else {
                                "sets": [],
                                "current_set": 1,
                                "games_home": 0,
                                "games_away": 0
                            }
                        )
                        
                        session.add(match)
                    
                    await session.commit()
                    logger.info(f"✅ Сгенерировано {to_generate} новых матчей")
        
        except Exception as e:
            logger.error(f"❌ Ошибка генерации матчей: {e}")
    
    async def simulate_match(self, match: Match):
        """Симуляция одного матча"""
        try:
            async with self.db() as session:
                # Обновляем матч
                session.add(match)
                
                if match.status == "scheduled" and match.start_time <= datetime.now():
                    match.status = "live"
                
                if match.status == "live":
                    # Логика симуляции в зависимости от вида спорта
                    if match.sport == 'football':
                        await self._simulate_football(match)
                    elif match.sport == 'hockey':
                        await self._simulate_hockey(match)
                    elif match.sport == 'basketball':
                        await self._simulate_basketball(match)
                    elif match.sport in ['tennis', 'table_tennis']:
                        await self._simulate_tennis(match)
                    
                    # Проверка окончания матча
                    if self._is_match_finished(match):
                        match.status = "finished"
                        await self._settle_bets(match.id)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"❌ Ошибка симуляции матча {match.id}: {e}")
    
    async def _simulate_football(self, match: Match):
        """Симуляция футбольного матча"""
        # Увеличиваем минуту
        if match.current_minute < 90:
            match.current_minute += random.randint(1, 3)
        
        # Шанс гола
        if random.random() < 0.03:  # 3% шанс гола за шаг симуляции
            if random.random() < 0.5:
                match.score_home += 1
            else:
                match.score_away += 1
        
        # Смена тайма
        if match.current_minute == 45:
            match.period = "2nd"
        elif match.current_minute > 90:
            match.period = "finished"
    
    async def _simulate_hockey(self, match: Match):
        """Симуляция хоккейного матча"""
        # Хоккей - больше голов
        if match.current_minute < 60:
            match.current_minute += random.randint(1, 2)
        
        # Шанс гола в хоккее выше
        if random.random() < 0.05:  # 5% шанс
            if random.random() < 0.5:
                match.score_home += 1
            else:
                match.score_away += 1
        
        # Периоды
        if match.current_minute == 20:
            match.period = "2nd"
        elif match.current_minute == 40:
            match.period = "3rd"
        elif match.current_minute > 60:
            match.period = "finished"
    
    async def _simulate_basketball(self, match: Match):
        """Симуляция баскетбольного матча"""
        # Баскетбол - много очков
        if match.current_minute < 48:
            match.current_minute += 1
        
        # Каждую минуту шанс на очки
        if random.random() < 0.8:  # 80% шанс на очки
            points = random.choice([2, 2, 3])  # Чаще 2 очка
            if random.random() < 0.5:
                match.score_home += points
            else:
                match.score_away += points
        
        # Четверти
        quarters = ["1st", "2nd", "3rd", "4th"]
        quarter_idx = min(match.current_minute // 12, 3)
        match.period = quarters[quarter_idx]
        
        if match.current_minute >= 48:
            match.period = "finished"
    
    async def _simulate_tennis(self, match: Match):
        """Симуляция теннисного матча"""
        # Инициализация деталей счета
        if not match.score_details:
            match.score_details = {
                "sets": [],
                "current_set": 1,
                "games_home": 0,
                "games_away": 0,
                "points_home": 0,
                "points_away": 0
            }
        
        details = match.score_details
        
        # Логика теннисного гейма
        points = ["0", "15", "30", "40", "AD", "GAME"]
        
        # Шанс выиграть очко
        if random.random() < 0.5:
            details["points_home"] = min(details["points_home"] + 1, 5)
        else:
            details["points_away"] = min(details["points_away"] + 1, 5)
        
        # Проверка выигрыша гейма
        if details["points_home"] == 5:  # GAME
            details["games_home"] += 1
            details["points_home"] = 0
            details["points_away"] = 0
        elif details["points_away"] == 5:
            details["games_away"] += 1
            details["points_home"] = 0
            details["points_away"] = 0
        
        # Проверка выигрыша сета
        games_to_win = 2 if match.sport == 'tennis' else 3  # Настольный теннис до 3 побед
        
        if details["games_home"] >= games_to_win or details["games_away"] >= games_to_win:
            # Завершение сета
            set_result = {
                "set": details["current_set"],
                "home": details["games_home"],
                "away": details["games_away"]
            }
            
            if "sets" not in details:
                details["sets"] = []
            details["sets"].append(set_result)
            
            # Обновление общего счета
            if details["games_home"] > details["games_away"]:
                match.score_home += 1
            else:
                match.score_away += 1
            
            # Сброс для нового сета
            details["current_set"] += 1
            details["games_home"] = 0
            details["games_away"] = 0
        
        match.score_details = details
        
        # Общий счет для отображения
        match.score_home = len([s for s in details.get("sets", []) if s["home"] > s["away"]])
        match.score_away = len([s for s in details.get("sets", []) if s["away"] > s["home"]])
    
    def _is_match_finished(self, match: Match) -> bool:
        """Проверка окончания матча"""
        if match.sport in ['football', 'hockey']:
            return match.current_minute >= (90 if match.sport == 'football' else 60)
        elif match.sport == 'basketball':
            return match.current_minute >= 48
        elif match.sport == 'tennis':
            return match.score_home >= 2 or match.score_away >= 2
        elif match.sport == 'table_tennis':
            return match.score_home >= 3 or match.score_away >= 3
        return True
    
    async def _settle_bets(self, match_id: int):
        """Расчет ставок после окончания матча"""
        try:
            async with self.db() as session:
                # Получаем матч
                match_result = await session.execute(
                    "SELECT * FROM matches WHERE id = :id",
                    {"id": match_id}
                )
                match = match_result.scalar()
                
                if not match:
                    return
                
                # Определяем победителя
                winner = None
                if match.score_home > match.score_away:
                    winner = "home"
                elif match.score_away > match.score_home:
                    winner = "away"
                elif match.score_home == match.score_away and match.sport != 'tennis':
                    winner = "draw"
                
                # Обновляем ставки
                bets_result = await session.execute(
                    "SELECT * FROM bets WHERE match_id = :match_id AND status = 'active'",
                    {"match_id": match_id}
                )
                bets = bets_result.scalars().all()
                
                for bet in bets:
                    if bet.selected_outcome == winner:
                        # Выигрыш
                        bet.status = "won"
                        await session.execute(
                            "UPDATE users SET balance = balance + :win WHERE telegram_id = :user_id",
                            {"win": bet.potential_win, "user_id": bet.user_id}
                        )
                    else:
                        # Проигрыш
                        bet.status = "lost"
                    
                    bet.settled_at = datetime.now()
                
                await session.commit()
                logger.info(f"✅ Рассчитаны ставки для матча {match_id}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка расчета ставок: {e}")
    
    async def run_simulation(self):
        """Запуск симуляции в фоне"""
        self.running = True
        
        while self.running:
            try:
                # Генерация матчей
                await self.generate_matches()
                
                # Симуляция активных матчей
                async with self.db() as session:
                    matches_result = await session.execute(
                        "SELECT * FROM matches WHERE status IN ('scheduled', 'live')"
                    )
                    matches = matches_result.scalars().all()
                    
                    for match in matches:
                        await self.simulate_match(match)
                
                # Пауза между обновлениями
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в симуляции: {e}")
                await asyncio.sleep(10)

# ============================
# GAME LOGIC
# ============================

class GamesManager:
    """Менеджер мини-игр"""
    
    @staticmethod
    async def play_mines(user_id: int, amount: Decimal, mines_count: int) -> Dict[str, Any]:
        """Игра Mines"""
        # Проверка баланса
        async with async_session() as session:
            user_result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": user_id}
            )
            user = user_result.scalar()
            
            if not user or user < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Расчет коэффициента
            cells = 25
            safe_cells = cells - mines_count
            probability = safe_cells / cells
            multiplier = round(1 / probability, 2)
            
            # Генерация поля
            field = [0] * cells
            mine_positions = random.sample(range(cells), mines_count)
            for pos in mine_positions:
                field[pos] = 1
            
            # Списание средств
            await session.execute(
                "UPDATE users SET balance = balance - :amount WHERE telegram_id = :user_id",
                {"amount": amount, "user_id": user_id}
            )
            
            # Создание ставки
            bet = Bet(
                user_id=user_id,
                game_type="mines",
                amount=amount,
                potential_win=amount * Decimal(multiplier),
                odds=multiplier,
                selected_outcome=str(mines_count),
                status="active"
            )
            
            session.add(bet)
            await session.commit()
            
            # Получаем ID ставки
            bet_id_result = await session.execute(
                "SELECT id FROM bets WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1",
                {"user_id": user_id}
            )
            bet_id = bet_id_result.scalar()
            
            return {
                "bet_id": bet_id,
                "multiplier": multiplier,
                "field": field,
                "mines_count": mines_count
            }
    
    @staticmethod
    async def cashout_mines(user_id: int, bet_id: int) -> Dict[str, Any]:
        """Забрать выигрыш в Mines"""
        async with async_session() as session:
            # Получаем ставку
            bet_result = await session.execute(
                "SELECT * FROM bets WHERE id = :bet_id AND user_id = :user_id AND status = 'active'",
                {"bet_id": bet_id, "user_id": user_id}
            )
            bet = bet_result.scalar()
            
            if not bet:
                raise HTTPException(status_code=404, detail="Ставка не найдена")
            
            # Начисляем выигрыш
            await session.execute(
                "UPDATE users SET balance = balance + :win WHERE telegram_id = :user_id",
                {"win": bet.potential_win, "user_id": user_id}
            )
            
            bet.status = "won"
            bet.settled_at = datetime.now()
            await session.commit()
            
            return {
                "success": True,
                "win_amount": float(bet.potential_win),
                "new_balance": await GamesManager._get_balance(user_id)
            }
    
    @staticmethod
    async def play_dice(user_id: int, amount: Decimal, bet_type: str) -> Dict[str, Any]:
        """Игра Dice"""
        # Проверка баланса
        async with async_session() as session:
            user_result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": user_id}
            )
            user = user_result.scalar()
            
            if not user or user < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Бросок кубика
            dice_roll = random.randint(1, 6)
            is_even = dice_roll % 2 == 0
            
            # Определение выигрыша
            multiplier = 2.0  # Коэффициент 2x
            win = False
            
            if (bet_type == "even" and is_even) or (bet_type == "odd" and not is_even):
                win = True
            
            # Списание/начисление средств
            if win:
                win_amount = amount * Decimal(multiplier)
                await session.execute(
                    "UPDATE users SET balance = balance + :win WHERE telegram_id = :user_id",
                    {"win": win_amount, "user_id": user_id}
                )
                status = "won"
            else:
                await session.execute(
                    "UPDATE users SET balance = balance - :amount WHERE telegram_id = :user_id",
                    {"amount": amount, "user_id": user_id}
                )
                status = "lost"
            
            # Создание записи о ставке
            bet = Bet(
                user_id=user_id,
                game_type="dice",
                amount=amount,
                potential_win=amount * Decimal(multiplier) if win else Decimal(0),
                odds=multiplier,
                selected_outcome=bet_type,
                status=status,
                settled_at=datetime.now() if not win else None
            )
            
            session.add(bet)
            await session.commit()
            
            return {
                "dice_result": dice_roll,
                "win": win,
                "win_amount": float(win_amount) if win else 0,
                "new_balance": await GamesManager._get_balance(user_id),
                "bet_id": bet.id
            }
    
    @staticmethod
    async def start_crash(user_id: int, amount: Decimal) -> Dict[str, Any]:
        """Начало игры Crash"""
        # Проверка баланса
        async with async_session() as session:
            user_result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": user_id}
            )
            user = user_result.scalar()
            
            if not user or user < amount:
                raise HTTPException(status_code=400, detail="Недостаточно средств")
            
            # Генерация точки краша
            # 5% шанс мгновенного краша (1.00)
            if random.random() < 0.05:
                crash_point = Decimal("1.00")
            else:
                # Генерация от 1.01 до 30.00+
                crash_point = Decimal(random.uniform(1.01, 30.00))
            
            # Списание средств
            await session.execute(
                "UPDATE users SET balance = balance - :amount WHERE telegram_id = :user_id",
                {"amount": amount, "user_id": user_id}
            )
            
            # Создание игры
            game = CrashGame(
                user_id=user_id,
                crash_point=crash_point,
                bet_amount=amount,
                is_active=True
            )
            
            session.add(game)
            await session.commit()
            
            # Получаем ID игры
            game_id_result = await session.execute(
                "SELECT id FROM crash_games WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1",
                {"user_id": user_id}
            )
            game_id = game_id_result.scalar()
            
            return {
                "game_id": game_id,
                "crash_point": float(crash_point),
                "bet_amount": float(amount)
            }
    
    @staticmethod
    async def cashout_crash(user_id: int, game_id: int) -> Dict[str, Any]:
        """Забрать выигрыш в Crash"""
        async with async_session() as session:
            # Получаем игру
            game_result = await session.execute(
                "SELECT * FROM crash_games WHERE id = :game_id AND user_id = :user_id AND is_active = true",
                {"game_id": game_id, "user_id": user_id}
            )
            game = game_result.scalar()
            
            if not game:
                raise HTTPException(status_code=404, detail="Игра не найдена")
            
            # Получаем текущий множитель (симулируем)
            # В реальном приложении здесь была бы логика расчета текущего множителя
            current_multiplier = Decimal(random.uniform(1.0, float(game.crash_point) - 0.5))
            
            if current_multiplier >= game.crash_point:
                # Краш - игрок проиграл
                win_amount = Decimal(0)
                game.is_active = False
                status = "lost"
            else:
                # Успешный вывод
                win_amount = game.bet_amount * current_multiplier
                await session.execute(
                    "UPDATE users SET balance = balance + :win WHERE telegram_id = :user_id",
                    {"win": win_amount, "user_id": user_id}
                )
                game.is_active = False
                game.current_multiplier = current_multiplier
                status = "won"
            
            # Создание записи о ставке
            bet = Bet(
                user_id=user_id,
                game_type="crash",
                amount=game.bet_amount,
                potential_win=win_amount,
                odds=float(current_multiplier),
                selected_outcome="cashout",
                status=status,
                settled_at=datetime.now()
            )
            
            session.add(bet)
            await session.commit()
            
            return {
                "success": True,
                "multiplier": float(current_multiplier),
                "win_amount": float(win_amount),
                "new_balance": await GamesManager._get_balance(user_id)
            }
    
    @staticmethod
    async def _get_balance(user_id: int) -> float:
        """Получение баланса пользователя"""
        async with async_session() as session:
            result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": user_id}
            )
            balance = result.scalar()
            return float(balance) if balance else 0.0

# ============================
# TELEGRAM BOT HANDLERS
# ============================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """Обработчик команды /start"""
    # Создаем или получаем пользователя
    async with async_session() as session:
        user_result = await session.execute(
            "SELECT * FROM users WHERE telegram_id = :telegram_id",
            {"telegram_id": message.from_user.id}
        )
        user = user_result.scalar()
        
        if not user:
            # Создание нового пользователя
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username or f"user_{message.from_user.id}",
                balance=5000.00
            )
            session.add(user)
            await session.commit()
        
        # Отправляем приветственное сообщение с кнопкой Mini App
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

# ============================
# API ENDPOINTS
# ============================

@app.on_event("startup")
async def startup_event():
    """Запуск приложения"""
    logger.info("🚀 Запуск Royal Bet API...")
    
    # Инициализация базы данных
    db_ok = await init_db()
    
    if not db_ok:
        logger.error("⚠️ Не удалось инициализировать БД, но API продолжает работу")
    
    # Запуск симуляции в фоне
    simulator = SportsSimulator(async_session)
    asyncio.create_task(simulator.run_simulation())
    
    logger.info("✅ Royal Bet API запущен!")

@app.post("/api/init")
async def api_init(request: InitRequest):
    """Инициализация пользователя"""
    # В реальном приложении здесь была бы верификация данных из Telegram
    # Для простоты используем mock-данные
    
    user_data = {
        "id": 123456789,
        "username": "test_user",
        "first_name": "Тестовый",
        "last_name": "Пользователь"
    }
    
    # Создаем или получаем пользователя
    async with async_session() as session:
        user_result = await session.execute(
            "SELECT * FROM users WHERE telegram_id = :telegram_id",
            {"telegram_id": user_data["id"]}
        )
        user = user_result.scalar()
        
        if not user:
            user = User(
                telegram_id=user_data["id"],
                username=user_data["username"],
                balance=5000.00
            )
            session.add(user)
            await session.commit()
        
        return {
            "success": True,
            "user": {
                "id": user.telegram_id,
                "username": user.username,
                "balance": float(user.balance)
            }
        }

@app.get("/api/matches")
async def get_matches(sport: Optional[str] = None):
    """Получение списка матчей"""
    try:
        async with async_session() as session:
            query = "SELECT * FROM matches WHERE status IN ('scheduled', 'live')"
            params = {}
            
            if sport:
                query += " AND sport = :sport"
                params["sport"] = sport
            
            query += " ORDER BY start_time ASC"
            
            result = await session.execute(query, params)
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
        logger.error(f"❌ Ошибка получения матчей: {e}")
        return {"matches": []}

@app.post("/api/bet")
async def place_bet(bet_request: BetRequest):
    """Размещение ставки"""
    try:
        # Валидация минимальной ставки
        min_bet = Decimal("50.00") if bet_request.game_type == "sport" else Decimal("10.00")
        
        if bet_request.amount < min_bet:
            raise HTTPException(
                status_code=400,
                detail=f"Минимальная ставка: {min_bet} ₽"
            )
        
        async with async_session() as session:
            # Проверка баланса
            user_result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": bet_request.user_id}
            )
            balance = user_result.scalar()
            
            if not balance or balance < bet_request.amount:
                raise HTTPException(
                    status_code=400,
                    detail="Недостаточно средств"
                )
            
            # Получаем коэффициенты
            odds = bet_request.odds
            if not odds and bet_request.match_id:
                match_result = await session.execute(
                    "SELECT odds_home, odds_draw, odds_away FROM matches WHERE id = :match_id",
                    {"match_id": bet_request.match_id}
                )
                match = match_result.first()
                
                if match:
                    if bet_request.outcome == "home":
                        odds = match.odds_home
                    elif bet_request.outcome == "draw":
                        odds = match.odds_draw
                    elif bet_request.outcome == "away":
                        odds = match.odds_away
            
            if not odds:
                odds = Decimal("2.00")
            
            # Расчет потенциального выигрыша
            potential_win = bet_request.amount * odds
            
            # Списание средств
            await session.execute(
                "UPDATE users SET balance = balance - :amount WHERE telegram_id = :user_id",
                {"amount": bet_request.amount, "user_id": bet_request.user_id}
            )
            
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
            
            session.add(bet)
            await session.commit()
            
            # Получаем ID ставки
            bet_id_result = await session.execute(
                "SELECT id FROM bets WHERE user_id = :user_id ORDER BY created_at DESC LIMIT 1",
                {"user_id": bet_request.user_id}
            )
            bet_id = bet_id_result.scalar()
            
            # Получаем новый баланс
            new_balance_result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": bet_request.user_id}
            )
            new_balance = new_balance_result.scalar()
            
            return {
                "success": True,
                "bet_id": bet_id,
                "potential_win": float(potential_win),
                "new_balance": float(new_balance)
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка размещения ставки: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.post("/api/game")
async def game_action(game_request: GameRequest):
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
            
            result = await GamesManager.play_mines(
                game_request.user_id,
                game_request.amount,
                game_request.mines_count
            )
            
        elif game_request.game_type == "dice":
            if not game_request.dice_bet:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите тип ставки (odd/even)"
                )
            
            result = await GamesManager.play_dice(
                game_request.user_id,
                game_request.amount,
                game_request.dice_bet
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
        logger.error(f"❌ Ошибка в игре: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.post("/api/crash/start")
async def crash_start(game_request: GameRequest):
    """Начало игры Crash"""
    try:
        if game_request.amount < Decimal("10.00"):
            raise HTTPException(
                status_code=400,
                detail="Минимальная ставка в Crash: 10 ₽"
            )
        
        result = await GamesManager.start_crash(
            game_request.user_id,
            game_request.amount
        )
        
        return {"success": True, **result}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка начала Crash: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.post("/api/crash/cashout")
async def crash_cashout(cashout_request: CashoutRequest):
    """Вывод в игре Crash"""
    try:
        result = await GamesManager.cashout_crash(
            cashout_request.user_id,
            cashout_request.crash_id
        )
        
        return {"success": True, **result}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка вывода в Crash: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.post("/api/mines/cashout")
async def mines_cashout(cashout_request: CashoutRequest):
    """Вывод в игре Mines"""
    try:
        result = await GamesManager.cashout_mines(
            cashout_request.user_id,
            cashout_request.crash_id  # Здесь это bet_id
        )
        
        return {"success": True, **result}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка вывода в Mines: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

@app.get("/api/history")
async def get_history(user_id: int, limit: int = 20):
    """Получение истории ставок"""
    try:
        async with async_session() as session:
            result = await session.execute(
                """
                SELECT 
                    b.*,
                    m.team_home,
                    m.team_away,
                    m.sport
                FROM bets b
                LEFT JOIN matches m ON b.match_id = m.id
                WHERE b.user_id = :user_id
                ORDER BY b.created_at DESC
                LIMIT :limit
                """,
                {"user_id": user_id, "limit": limit}
            )
            
            bets = result.fetchall()
            
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
                    "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
                    "match_info": {
                        "teams": f"{bet.team_home} vs {bet.team_away}" if bet.team_home else None,
                        "sport": bet.sport
                    } if bet.team_home else None
                })
            
            return {"history": history}
    
    except Exception as e:
        logger.error(f"❌ Ошибка получения истории: {e}")
        return {"history": []}

@app.get("/api/balance")
async def get_balance(user_id: int):
    """Получение баланса"""
    try:
        async with async_session() as session:
            result = await session.execute(
                "SELECT balance FROM users WHERE telegram_id = :user_id",
                {"user_id": user_id}
            )
            balance = result.scalar()
            
            if not balance:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            return {"balance": float(balance)}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения баланса: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")

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
