#!/usr/bin/env python3
"""
Royal Bet - Telegram Mini App Backend
Complete Version with Telegram Bot
"""

import os
import asyncio
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal
from contextlib import asynccontextmanager

# FastAPI imports
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Database imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, JSON
from sqlalchemy.sql import text
from sqlalchemy.future import select

# Aiogram imports
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# CONFIGURATION
# ============================

# IMPORTANT: Set these values!
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"  # Your bot token
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
FRONTEND_URL = "https://matveymak22.github.io/Cas"  # Your GitHub Pages URL

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================
# TELEGRAM BOT SETUP
# ============================

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================
# DATABASE SETUP
# ============================

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    balance = Column(Numeric(10, 2), default=5000.00)
    created_at = Column(DateTime, default=datetime.utcnow)

class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True)
    sport = Column(String(50))
    team_home = Column(String(100))
    team_away = Column(String(100))
    score_home = Column(Integer, default=0)
    score_away = Column(Integer, default=0)
    score_details = Column(JSON, default={})
    status = Column(String(20), default="scheduled")
    odds_home = Column(Numeric(5, 2), default=2.00)
    odds_draw = Column(Numeric(5, 2), default=3.00)
    odds_away = Column(Numeric(5, 2), default=2.50)
    start_time = Column(DateTime)
    current_minute = Column(Integer, default=0)
    period = Column(String(20), default="1st")

class Bet(Base):
    __tablename__ = "bets"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    match_id = Column(Integer, nullable=True)
    game_type = Column(String(20))
    amount = Column(Numeric(10, 2))
    status = Column(String(20), default="active")
    potential_win = Column(Numeric(10, 2))
    odds = Column(Numeric(5, 2))
    selected_outcome = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)

class CrashGame(Base):
    __tablename__ = "crash_games"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    crash_point = Column(Numeric(5, 2))
    bet_amount = Column(Numeric(10, 2))
    current_multiplier = Column(Numeric(5, 2), default=1.00)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Database engine and session
engine = None
AsyncSessionLocal = None

async def init_database():
    """Initialize PostgreSQL database"""
    global engine, AsyncSessionLocal
    
    try:
        logger.info("🔄 Initializing PostgreSQL database...")
        
        # Create async engine
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True
        )
        
        # Test connection
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Database tables created")
        
        # Create session factory
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Initialize demo data
        await init_demo_data()
        
        logger.info("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return False

async def init_demo_data():
    """Initialize demo data"""
    try:
        async with AsyncSessionLocal() as session:
            # Check if we have users
            result = await session.execute(select(User))
            users = result.scalars().all()
            
            if not users:
                # Create demo user
                demo_user = User(
                    telegram_id=123456789,
                    username="demo_user",
                    balance=5000.00
                )
                session.add(demo_user)
                await session.commit()
                logger.info("✅ Created demo user")
            
            # Check if we have matches
            result = await session.execute(select(Match))
            matches = result.scalars().all()
            
            if len(matches) < 5:
                await generate_initial_matches(session)
            
    except Exception as e:
        logger.error(f"Error initializing demo data: {e}")

async def generate_initial_matches(session):
    """Generate initial matches"""
    try:
        football_teams = ["Зенит", "Спартак", "ЦСКА", "Локомотив", "Динамо", "Краснодар"]
        hockey_teams = ["СКА", "ЦСКА", "Авангард", "Металлург", "Салават Юлаев"]
        tennis_players = ["Джокович", "Алькарас", "Медведев", "Надаль", "Синнер"]
        basketball_teams = ["ЦСКА", "Зенит", "Локомотив", "УНИКС", "Химки"]
        table_tennis_players = ["Ма Лун", "Фань Чжэньдун", "Тимо Болль", "Дмитрий Овчаров"]
        
        sports_data = [
            ("football", football_teams, True),
            ("hockey", hockey_teams, True),
            ("basketball", basketball_teams, True),
            ("tennis", tennis_players, False),
            ("table_tennis", table_tennis_players, False),
        ]
        
        for i in range(10):
            sport, teams, has_draw = random.choice(sports_data)
            team1, team2 = random.sample(teams, 2)
            
            odds1 = round(random.uniform(1.3, 2.5), 2)
            odds2 = round(random.uniform(1.3, 2.5), 2)
            odds_draw = round(random.uniform(2.5, 3.5), 2) if has_draw else None
            
            # Random start time within next 2 hours
            start_time = datetime.utcnow() + timedelta(minutes=random.randint(5, 120))
            
            match = Match(
                sport=sport,
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
        logger.info("✅ Generated initial matches")
        
    except Exception as e:
        logger.error(f"Error generating matches: {e}")
        await session.rollback()

# ============================
# TELEGRAM BOT HANDLERS
# ============================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """Handle /start command"""
    try:
        async with AsyncSessionLocal() as session:
            # Get or create user
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
            
            # Create button for Mini App
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

async def start_bot():
    """Start Telegram bot polling"""
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

# ============================
# MATCH SIMULATION
# ============================

async def match_simulation_task():
    """Background match simulation"""
    while True:
        try:
            if AsyncSessionLocal is None:
                await asyncio.sleep(10)
                continue
                
            async with AsyncSessionLocal() as session:
                # Get active matches
                result = await session.execute(
                    select(Match).where(Match.status.in_(["scheduled", "live"]))
                )
                matches = result.scalars().all()
                
                current_time = datetime.utcnow()
                
                for match in matches:
                    # Start live matches
                    if match.status == "scheduled" and match.start_time <= current_time:
                        match.status = "live"
                        logger.info(f"Match {match.id} started live")
                    
                    # Simulate live matches
                    if match.status == "live":
                        await simulate_match(session, match)
                    
                    session.add(match)
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Error in match simulation: {e}")
        
        await asyncio.sleep(5)

async def simulate_match(session, match: Match):
    """Simulate a match"""
    try:
        if match.sport in ["football", "hockey"]:
            if random.random() < 0.05:
                if random.random() < 0.5:
                    match.score_home += 1
                else:
                    match.score_away += 1
            
            match.current_minute = min(match.current_minute + 1, 90)
            
            if match.current_minute >= 90:
                match.status = "finished"
        
        elif match.sport == "basketball":
            if random.random() < 0.3:
                points = random.choice([2, 2, 3])
                if random.random() < 0.5:
                    match.score_home += points
                else:
                    match.score_away += points
            
            match.current_minute = min(match.current_minute + 1, 48)
            
            if match.current_minute >= 48:
                match.status = "finished"
        
        else:  # Tennis/Table Tennis
            if not match.score_details:
                match.score_details = {"sets": []}
            
            # Simple simulation
            if random.random() < 0.5:
                match.score_home += 1
            else:
                match.score_away += 1
            
            sets_to_win = 2 if match.sport == "tennis" else 3
            if match.score_home >= sets_to_win or match.score_away >= sets_to_win:
                match.status = "finished"
    
    except Exception as e:
        logger.error(f"Error simulating match: {e}")

# ============================
# GAME MANAGER
# ============================

class GameManager:
    """Game logic manager"""
    
    @staticmethod
    async def play_mines(user_id: int, amount: Decimal, mines_count: int, session: AsyncSession) -> Dict[str, Any]:
        """Play Mines game"""
        try:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Convert to float for comparison
            amount_float = float(amount)
            if user.balance < amount_float:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Calculate multiplier
            cells = 25
            safe_cells = cells - mines_count
            probability = safe_cells / cells
            multiplier = round(1 / probability, 2)
            
            # Deduct amount
            user.balance -= amount_float
            potential_win = amount_float * multiplier
            
            # Create bet
            bet = Bet(
                user_id=user_id,
                game_type="mines",
                amount=amount_float,
                potential_win=potential_win,
                odds=multiplier,
                selected_outcome=str(mines_count),
                status="active"
            )
            
            session.add(bet)
            await session.commit()
            await session.refresh(bet)
            
            return {
                "success": True,
                "bet_id": bet.id,
                "multiplier": multiplier,
                "mines_count": mines_count,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in play_mines: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @staticmethod
    async def cashout_mines(user_id: int, bet_id: int, session: AsyncSession) -> Dict[str, Any]:
        """Cashout Mines game"""
        try:
            # Get bet
            result = await session.execute(
                select(Bet).where(
                    Bet.id == bet_id,
                    Bet.user_id == user_id,
                    Bet.status == "active"
                )
            )
            bet = result.scalar_one_or_none()
            
            if not bet:
                raise HTTPException(status_code=404, detail="Bet not found")
            
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Add winnings
            user.balance += bet.potential_win
            bet.status = "won"
            bet.settled_at = datetime.utcnow()
            
            await session.commit()
            
            return {
                "success": True,
                "win_amount": float(bet.potential_win),
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in cashout_mines: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @staticmethod
    async def play_dice(user_id: int, amount: Decimal, bet_type: str, session: AsyncSession) -> Dict[str, Any]:
        """Play Dice game"""
        try:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Convert to float
            amount_float = float(amount)
            if user.balance < amount_float:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Roll dice
            dice_roll = random.randint(1, 6)
            is_even = dice_roll % 2 == 0
            
            # Determine win
            multiplier = 2.0
            win = (bet_type == "even" and is_even) or (bet_type == "odd" and not is_even)
            
            if win:
                win_amount = amount_float * multiplier
                user.balance += win_amount
                status = "won"
                potential_win = win_amount
            else:
                user.balance -= amount_float
                status = "lost"
                potential_win = 0.0
            
            # Create bet
            bet = Bet(
                user_id=user_id,
                game_type="dice",
                amount=amount_float,
                potential_win=potential_win,
                odds=multiplier,
                selected_outcome=bet_type,
                status=status,
                settled_at=datetime.utcnow() if not win else None
            )
            
            session.add(bet)
            await session.commit()
            
            return {
                "success": True,
                "dice_result": dice_roll,
                "win": win,
                "win_amount": win_amount if win else 0,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in play_dice: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @staticmethod
    async def start_crash(user_id: int, amount: Decimal, session: AsyncSession) -> Dict[str, Any]:
        """Start Crash game"""
        try:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Convert to float
            amount_float = float(amount)
            if user.balance < amount_float:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Generate crash point (5% instant crash)
            if random.random() < 0.05:
                crash_point = 1.00
            else:
                crash_point = round(random.uniform(1.01, 5.00), 2)
            
            # Deduct amount
            user.balance -= amount_float
            
            # Create crash game
            game = CrashGame(
                user_id=user_id,
                crash_point=crash_point,
                bet_amount=amount_float,
                is_active=True
            )
            
            session.add(game)
            await session.commit()
            await session.refresh(game)
            
            return {
                "success": True,
                "game_id": game.id,
                "crash_point": crash_point,
                "bet_amount": amount_float
            }
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in start_crash: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @staticmethod
    async def cashout_crash(user_id: int, game_id: int, session: AsyncSession) -> Dict[str, Any]:
        """Cashout Crash game"""
        try:
            # Get game
            result = await session.execute(
                select(CrashGame).where(
                    CrashGame.id == game_id,
                    CrashGame.user_id == user_id,
                    CrashGame.is_active == True
                )
            )
            game = result.scalar_one_or_none()
            
            if not game:
                raise HTTPException(status_code=404, detail="Game not found")
            
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Generate current multiplier
            current_multiplier = round(random.uniform(1.0, float(game.crash_point) - 0.1), 2)
            
            if current_multiplier >= game.crash_point:
                # Crash - lose
                win_amount = 0.0
                status = "lost"
                game.is_active = False
            else:
                # Successful cashout
                win_amount = game.bet_amount * current_multiplier
                user.balance += win_amount
                status = "won"
                game.is_active = False
                game.current_multiplier = current_multiplier
            
            # Create bet record
            bet = Bet(
                user_id=user_id,
                game_type="crash",
                amount=game.bet_amount,
                potential_win=win_amount,
                odds=current_multiplier,
                selected_outcome="cashout",
                status=status,
                settled_at=datetime.utcnow()
            )
            
            session.add(bet)
            await session.commit()
            
            return {
                "success": True,
                "multiplier": current_multiplier,
                "win_amount": win_amount,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Error in cashout_crash: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

# ============================
# APPLICATION LIFESPAN
# ============================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle"""
    logger.info("🚀 Starting Royal Bet API...")
    
    # Initialize database
    db_ok = await init_database()
    
    if db_ok:
        # Start background tasks
        asyncio.create_task(match_simulation_task())
        logger.info("✅ Background tasks started")
    
    # Start Telegram bot in background
    bot_task = asyncio.create_task(start_bot())
    
    yield
    
    logger.info("🛑 Stopping Royal Bet API...")
    
    # Stop bot
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

# ============================
# FASTAPI APP
# ============================

app = FastAPI(
    title="Royal Bet API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================
# API ENDPOINTS
# ============================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "status": "online",
        "service": "Royal Bet API",
        "version": "1.0.0",
        "bot": "running",
        "frontend": FRONTEND_URL,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check"""
    try:
        if AsyncSessionLocal:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            db_status = "connected"
        else:
            db_status = "not_initialized"
        
        return {
            "status": "healthy",
            "database": db_status,
            "bot_token": "configured" if BOT_TOKEN else "missing",
            "frontend_url": FRONTEND_URL,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.post("/api/init")
async def api_init(request: Request):
    """Initialize user from Telegram WebApp"""
    try:
        data = await request.json()
        init_data = data.get("initData", "")
        
        # Parse Telegram WebApp initData (simplified)
        # In production, verify the signature properly
        
        # For demo, use user from query params or create new
        query_params = dict(request.query_params)
        user_id = query_params.get("user_id", 123456789)
        
        async with AsyncSessionLocal() as session:
            # Get or create user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    telegram_id=user_id,
                    username=f"user_{user_id}",
                    balance=5000.00
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            
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
async def get_matches(sport: Optional[str] = None):
    """Get matches"""
    try:
        async with AsyncSessionLocal() as session:
            query = select(Match).where(Match.status.in_(["scheduled", "live"]))
            
            if sport and sport != "all":
                query = query.where(Match.sport == sport)
            
            query = query.order_by(Match.start_time.asc())
            
            result = await session.execute(query)
            matches = result.scalars().all()
            
            matches_list = []
            for match in matches:
                matches_list.append({
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
                })
            
            return {"matches": matches_list}
            
    except Exception as e:
        logger.error(f"Error in /api/matches: {e}")
        return {"matches": []}

@app.post("/api/bet")
async def place_bet(request: Request):
    """Place a bet"""
    try:
        data = await request.json()
        
        user_id = data.get("user_id")
        match_id = data.get("match_id")
        game_type = data.get("game_type", "sport")
        amount = float(data.get("amount", 0))
        outcome = data.get("outcome")
        odds = data.get("odds")
        
        # Validate
        min_bet = 50.00 if game_type == "sport" else 10.00
        if amount < min_bet:
            raise HTTPException(status_code=400, detail=f"Minimum bet: {min_bet} ₽")
        
        async with AsyncSessionLocal() as session:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Get odds
            odds_float = 2.00
            if odds:
                odds_float = float(odds)
            elif match_id:
                result = await session.execute(
                    select(Match).where(Match.id == match_id)
                )
                match = result.scalar_one_or_none()
                if match:
                    if outcome == "home":
                        odds_float = float(match.odds_home)
                    elif outcome == "draw":
                        odds_float = float(match.odds_draw) if match.odds_draw else 0
                    elif outcome == "away":
                        odds_float = float(match.odds_away)
            
            # Calculate win
            potential_win = amount * odds_float
            
            # Deduct amount
            user.balance -= amount
            
            # Create bet
            bet = Bet(
                user_id=user_id,
                match_id=match_id,
                game_type=game_type,
                amount=amount,
                potential_win=potential_win,
                odds=odds_float,
                selected_outcome=outcome,
                status="active"
            )
            
            session.add(bet)
            await session.commit()
            await session.refresh(bet)
            
            return {
                "success": True,
                "bet_id": bet.id,
                "potential_win": potential_win,
                "new_balance": float(user.balance)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/bet: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/game")
async def game_action(request: Request):
    """Play game"""
    try:
        data = await request.json()
        
        user_id = data.get("user_id")
        game_type = data.get("game_type")
        amount = float(data.get("amount", 0))
        mines_count = data.get("mines_count")
        dice_bet = data.get("dice_bet")
        
        if amount < 10.00:
            raise HTTPException(status_code=400, detail="Minimum bet: 10 ₽")
        
        async with AsyncSessionLocal() as session:
            if game_type == "mines":
                if not mines_count:
                    raise HTTPException(status_code=400, detail="Specify mines count")
                
                result = await GameManager.play_mines(
                    user_id,
                    Decimal(str(amount)),
                    mines_count,
                    session
                )
                
            elif game_type == "dice":
                if not dice_bet:
                    raise HTTPException(status_code=400, detail="Specify bet type")
                
                result = await GameManager.play_dice(
                    user_id,
                    Decimal(str(amount)),
                    dice_bet,
                    session
                )
                
            else:
                raise HTTPException(status_code=400, detail="Invalid game type")
            
            return {"success": True, **result}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/crash/start")
async def crash_start(request: Request):
    """Start crash game"""
    try:
        data = await request.json()
        
        user_id = data.get("user_id")
        amount = float(data.get("amount", 0))
        
        if amount < 10.00:
            raise HTTPException(status_code=400, detail="Minimum bet: 10 ₽")
        
        async with AsyncSessionLocal() as session:
            result = await GameManager.start_crash(
                user_id,
                Decimal(str(amount)),
                session
            )
            
            return {"success": True, **result}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/crash/start: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/crash/cashout")
async def crash_cashout(request: Request):
    """Cashout crash"""
    try:
        data = await request.json()
        
        user_id = data.get("user_id")
        crash_id = data.get("crash_id")
        
        async with AsyncSessionLocal() as session:
            result = await GameManager.cashout_crash(
                user_id,
                crash_id,
                session
            )
            
            return {"success": True, **result}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/crash/cashout: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/mines/cashout")
async def mines_cashout(request: Request):
    """Cashout mines"""
    try:
        data = await request.json()
        
        user_id = data.get("user_id")
        crash_id = data.get("crash_id")  # bet_id for mines
        
        async with AsyncSessionLocal() as session:
            result = await GameManager.cashout_mines(
                user_id,
                crash_id,
                session
            )
            
            return {"success": True, **result}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/mines/cashout: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/history")
async def get_history(user_id: int, limit: int = 20):
    """Get bet history"""
    try:
        async with AsyncSessionLocal() as session:
            query = (
                select(Bet)
                .where(Bet.user_id == user_id)
                .order_by(Bet.created_at.desc())
                .limit(limit)
            )
            
            result = await session.execute(query)
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
async def get_balance(user_id: int):
    """Get balance"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            return {"balance": float(user.balance)}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/balance: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ============================
# MAIN ENTRY POINT
# ============================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
