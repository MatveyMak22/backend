#!/usr/bin/env python3
"""
Royal Bet - Telegram Mini App Backend
Production Ready Version with PostgreSQL
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
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# Database imports
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.sql import func, text
from sqlalchemy.future import select

# Aiogram imports
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# CONFIGURATION - REAL PRODUCTION
# ============================

# REAL CONFIG - MODIFY THESE!
BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
# Use this DATABASE_URL for Neon.tech PostgreSQL
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
FRONTEND_URL = "https://matveymak22.github.io/Cas"

# Проверка конфигурации
if not BOT_TOKEN or "YOUR_BOT_TOKEN" in BOT_TOKEN:
    print("⚠️ ВНИМАНИЕ: Установите реальный BOT_TOKEN!")
    raise ValueError("Please set BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================
# DATABASE SETUP
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

# Database engine and session
engine = None
AsyncSessionLocal = None

async def init_database():
    """Initialize database connection and create tables"""
    global engine, AsyncSessionLocal
    
    try:
        logger.info(f"Connecting to database: {DATABASE_URL[:50]}...")
        
        # Create async engine
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )
        
        # Test connection
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        # Create session factory
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return False

async def get_db():
    """Dependency for getting database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

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
# DATA INITIALIZATION
# ============================

async def init_demo_data():
    """Initialize demo data if database is empty"""
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
            
            if len(matches) < 10:
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
        
        for i in range(15):
            sport, teams, has_draw = random.choice(sports_data)
            team1, team2 = random.sample(teams, 2)
            
            odds1 = round(random.uniform(1.3, 2.5), 2)
            odds2 = round(random.uniform(1.3, 2.5), 2)
            odds_draw = round(random.uniform(2.5, 3.5), 2) if has_draw else None
            
            start_time = datetime.now() + timedelta(minutes=random.randint(5, 180))
            
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
# MATCH SIMULATION TASK
# ============================

async def match_simulation_task():
    """Background task for match simulation"""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Get all active matches
                result = await session.execute(
                    select(Match).where(Match.status.in_(["scheduled", "live"]))
                )
                matches = result.scalars().all()
                
                current_time = datetime.now()
                
                for match in matches:
                    # Start live matches
                    if match.status == "scheduled" and match.start_time <= current_time:
                        match.status = "live"
                    
                    # Simulate live matches
                    if match.status == "live":
                        await simulate_match(session, match)
                    
                    session.add(match)
                
                await session.commit()
                
                # Generate new matches if needed
                result = await session.execute(select(Match).where(Match.status.in_(["scheduled", "live"])))
                active_matches = result.scalars().all()
                
                if len(active_matches) < 10:
                    await generate_initial_matches(session)
                
        except Exception as e:
            logger.error(f"Error in match simulation: {e}")
        
        await asyncio.sleep(10)  # Update every 10 seconds

async def simulate_match(session, match: Match):
    """Simulate a single match"""
    # Different simulation for different sports
    if match.sport in ["football", "hockey"]:
        # Football/Hockey simulation
        if random.random() < 0.05:  # 5% chance of goal
            if random.random() < 0.5:
                match.score_home += 1
            else:
                match.score_away += 1
        
        match.current_minute = min(match.current_minute + 1, 90)
        
        if match.current_minute >= 90:
            match.status = "finished"
            await settle_match_bets(session, match.id)
    
    elif match.sport == "basketball":
        # Basketball simulation - more points
        if random.random() < 0.3:  # 30% chance of points
            points = random.choice([2, 2, 3])  # More 2-point shots
            if random.random() < 0.5:
                match.score_home += points
            else:
                match.score_away += points
        
        match.current_minute = min(match.current_minute + 1, 48)
        
        if match.current_minute >= 48:
            match.status = "finished"
            await settle_match_bets(session, match.id)
    
    else:
        # Tennis/Table Tennis simulation
        if not match.score_details:
            match.score_details = {
                "sets": [],
                "current_set": 1,
                "games_home": 0,
                "games_away": 0
            }
        
        # Simple tennis simulation
        if random.random() < 0.5:
            match.score_details["games_home"] += 1
        else:
            match.score_details["games_away"] += 1
        
        # Check if set is finished
        games_to_win = 2 if match.sport == "tennis" else 3
        if (match.score_details["games_home"] >= games_to_win or 
            match.score_details["games_away"] >= games_to_win):
            
            # Finish set
            if match.score_details["games_home"] > match.score_details["games_away"]:
                match.score_home += 1
            else:
                match.score_away += 1
            
            match.score_details["sets"].append({
                "set": match.score_details["current_set"],
                "home": match.score_details["games_home"],
                "away": match.score_details["games_away"]
            })
            
            # Reset for next set
            match.score_details["current_set"] += 1
            match.score_details["games_home"] = 0
            match.score_details["games_away"] = 0
        
        # Check if match is finished
        sets_to_win = 2 if match.sport == "tennis" else 3
        if match.score_home >= sets_to_win or match.score_away >= sets_to_win:
            match.status = "finished"
            await settle_match_bets(session, match.id)

async def settle_match_bets(session, match_id: int):
    """Settle all bets for finished match"""
    try:
        # Get the match
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        
        if not match:
            return
        
        # Determine winner
        winner = None
        if match.score_home > match.score_away:
            winner = "home"
        elif match.score_away > match.score_home:
            winner = "away"
        elif match.score_home == match.score_away and match.sport != "tennis" and match.sport != "table_tennis":
            winner = "draw"
        
        # Get all active bets for this match
        result = await session.execute(
            select(Bet).where(
                Bet.match_id == match_id,
                Bet.status == "active"
            )
        )
        bets = result.scalars().all()
        
        for bet in bets:
            if bet.selected_outcome == winner:
                # Win
                bet.status = "won"
                
                # Add winnings to user balance
                await session.execute(
                    text("UPDATE users SET balance = balance + :win WHERE telegram_id = :user_id"),
                    {"win": bet.potential_win, "user_id": bet.user_id}
                )
            else:
                # Lose
                bet.status = "lost"
            
            bet.settled_at = datetime.now()
            session.add(bet)
        
        await session.commit()
        logger.info(f"✅ Settled bets for match {match_id}")
        
    except Exception as e:
        logger.error(f"Error settling bets: {e}")
        await session.rollback()

# ============================
# GAME MANAGER
# ============================

class GameManager:
    """Manager for mini-games"""
    
    @staticmethod
    async def play_mines(user_id: int, amount: Decimal, mines_count: int, session: AsyncSession) -> Dict[str, Any]:
        """Play Mines game"""
        try:
            # Get user
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Calculate multiplier
            cells = 25
            safe_cells = cells - mines_count
            probability = safe_cells / cells
            multiplier = round(1 / probability, 2)
            
            # Deduct amount
            user.balance -= amount
            
            # Create bet
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
            raise HTTPException(status_code=500, detail=str(e))
    
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
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Add winnings
            user.balance += bet.potential_win
            bet.status = "won"
            bet.settled_at = datetime.now()
            
            await session.commit()
            
            return {
                "success": True,
                "win_amount": float(bet.potential_win),
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def play_dice(user_id: int, amount: Decimal, bet_type: str, session: AsyncSession) -> Dict[str, Any]:
        """Play Dice game"""
        try:
            # Get user
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Roll dice
            dice_roll = random.randint(1, 6)
            is_even = dice_roll % 2 == 0
            
            # Determine win
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
            
            # Create bet
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
            
            session.add(bet)
            await session.commit()
            
            return {
                "success": True,
                "dice_result": dice_roll,
                "win": win,
                "win_amount": float(win_amount) if win else 0,
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def start_crash(user_id: int, amount: Decimal, session: AsyncSession) -> Dict[str, Any]:
        """Start Crash game"""
        try:
            # Get user
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            if user.balance < amount:
                raise HTTPException(status_code=400, detail="Insufficient funds")
            
            # Generate crash point (5% instant crash)
            if random.random() < 0.05:
                crash_point = Decimal("1.00")
            else:
                crash_point = Decimal(str(round(random.uniform(1.01, 10.00), 2)))
            
            # Deduct amount
            user.balance -= amount
            
            # Create crash game
            game = CrashGame(
                user_id=user_id,
                crash_point=crash_point,
                bet_amount=amount,
                is_active=True
            )
            
            session.add(game)
            await session.commit()
            await session.refresh(game)
            
            return {
                "success": True,
                "game_id": game.id,
                "crash_point": float(crash_point),
                "bet_amount": float(amount)
            }
            
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    
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
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Generate current multiplier (simulation)
            current_multiplier = Decimal(str(round(random.uniform(1.0, float(game.crash_point) - 0.1), 2)))
            
            if current_multiplier >= game.crash_point:
                # Crash - lose
                win_amount = Decimal("0")
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
                settled_at=datetime.now()
            )
            
            session.add(bet)
            await session.commit()
            
            return {
                "success": True,
                "multiplier": float(current_multiplier),
                "win_amount": float(win_amount),
                "new_balance": float(user.balance)
            }
            
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))

# ============================
# APPLICATION LIFESPAN
# ============================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("🚀 Starting Royal Bet API...")
    
    # Initialize database
    db_ok = await init_database()
    
    if db_ok:
        # Initialize demo data
        await init_demo_data()
        
        # Start match simulation
        asyncio.create_task(match_simulation_task())
        logger.info("✅ Database and services initialized")
    else:
        logger.warning("⚠️ Running without database - using in-memory storage")
    
    yield
    
    logger.info("🛑 Stopping Royal Bet API...")

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
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Test database connection
        await db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/init")
async def api_init(request: InitRequest, db: AsyncSession = Depends(get_db)):
    """Initialize user"""
    try:
        # For demo, use fixed user ID
        # In production, parse Telegram WebApp data
        user_id = 123456789
        
        # Get or create user
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=user_id,
                username="demo_user",
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
async def get_matches(
    sport: Optional[str] = None, 
    db: AsyncSession = Depends(get_db)
):
    """Get matches list"""
    try:
        query = select(Match).where(Match.status.in_(["scheduled", "live"]))
        
        if sport and sport != "all":
            query = query.where(Match.sport == sport)
        
        query = query.order_by(Match.start_time)
        
        result = await db.execute(query)
        matches = result.scalars().all()
        
        matches_list = []
        for match in matches:
            match_data = {
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
            matches_list.append(match_data)
        
        return {"matches": matches_list}
        
    except Exception as e:
        logger.error(f"Error in /api/matches: {e}")
        return {"matches": []}

@app.post("/api/bet")
async def place_bet(bet_request: BetRequest, db: AsyncSession = Depends(get_db)):
    """Place a bet"""
    try:
        # Validate minimum bet
        min_bet = Decimal("50.00") if bet_request.game_type == "sport" else Decimal("10.00")
        
        if bet_request.amount < min_bet:
            raise HTTPException(
                status_code=400,
                detail=f"Minimum bet: {min_bet} ₽"
            )
        
        # Get user
        result = await db.execute(select(User).where(User.telegram_id == bet_request.user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.balance < bet_request.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds")
        
        # Get odds if not provided
        odds = bet_request.odds
        if not odds and bet_request.match_id:
            result = await db.execute(select(Match).where(Match.id == bet_request.match_id))
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
        
        # Calculate potential win
        potential_win = bet_request.amount * odds
        
        # Deduct amount
        user.balance -= bet_request.amount
        
        # Create bet
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
    """Play mini-game"""
    try:
        # Validate minimum bet
        if game_request.amount < Decimal("10.00"):
            raise HTTPException(
                status_code=400,
                detail="Minimum bet in games: 10 ₽"
            )
        
        if game_request.game_type == "mines":
            if not game_request.mines_count:
                raise HTTPException(
                    status_code=400,
                    detail="Specify number of mines"
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
                    detail="Specify bet type (odd/even)"
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
                detail="Unsupported game type"
            )
        
        return {"success": True, **result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /api/game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/crash/start")
async def crash_start(game_request: GameRequest, db: AsyncSession = Depends(get_db)):
    """Start Crash game"""
    try:
        if game_request.amount < Decimal("10.00"):
            raise HTTPException(
                status_code=400,
                detail="Minimum bet in Crash: 10 ₽"
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
    """Cashout Crash game"""
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
    """Cashout Mines game"""
    try:
        result = await GameManager.cashout_mines(
            cashout_request.user_id,
            cashout_request.crash_id,  # This is bet_id for mines
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
    """Get bet history"""
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
    """Get user balance"""
    try:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
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
# TELEGRAM BOT
# ============================

# Initialize bot
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """Handle /start command"""
    try:
        # Create or get user
        async with AsyncSessionLocal() as session:
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
                        text="🎮 Open Royal Bet",
                        web_app=WebAppInfo(url=FRONTEND_URL)
                    )]
                ]
            )
            
            await message.answer(
                f"🎉 Welcome to *Royal Bet*, {hbold(message.from_user.first_name)}!\n\n"
                f"Your starting balance: *5000 ₽*\n\n"
                f"Click the button below to start playing!",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in command_start_handler: {e}")
        await message.answer("An error occurred. Please try again later.")

async def start_bot():
    """Start Telegram bot"""
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

# ============================
# MAIN ENTRY POINT
# ============================

if __name__ == "__main__":
    import uvicorn
    
    # Start bot in background
    asyncio.create_task(start_bot())
    
    # Start FastAPI server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
