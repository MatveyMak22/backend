import os
import random
import threading
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

# Flask imports
from flask import Flask, request, jsonify
from flask_cors import CORS

# Database imports (SQLAlchemy + psycopg2)
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

# Aiogram imports (Bot)
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# КОНФИГУРАЦИЯ
# ============================

BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
# Твой URL базы данных Neon
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require"
FRONTEND_URL = "https://matveymak22.github.io/Cas"

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============================
# БАЗА ДАННЫХ (SETUP)
# ============================

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

# Модели
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
    odds_home = Column(Numeric(5, 2))
    odds_draw = Column(Numeric(5, 2), nullable=True)
    odds_away = Column(Numeric(5, 2))
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

# Инициализация БД с большим количеством данных
def init_db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    # 1. Создаем демо-юзера
    if not session.query(User).filter_by(telegram_id=123456789).first():
        user = User(telegram_id=123456789, username="demo_user", balance=5000.00)
        session.add(user)
    
    # 2. Проверяем, есть ли матчи. Если мало - генерируем много новых.
    if session.query(Match).count() < 10:
        logger.info("Generating extended match data...")
        
        # Списки команд и игроков
        football_teams = [
            "Real Madrid", "Barcelona", "Man City", "Liverpool", "Arsenal", 
            "Bayern Munich", "PSG", "Juventus", "Inter Milan", "AC Milan",
            "Zenit", "Spartak Moscow", "CSKA Moscow", "Krasnodar", "Dynamo Moscow",
            "Chelsea", "Man United", "Borussia Dortmund", "Atletico Madrid"
        ]
        
        hockey_teams = [
            "Tampa Bay Lightning", "Colorado Avalanche", "Washington Capitals", "Vegas Golden Knights",
            "SKA St. Petersburg", "CSKA Moscow", "Avangard Omsk", "Ak Bars Kazan",
            "Metallurg Mg", "Dynamo Moscow", "Boston Bruins", "Toronto Maple Leafs"
        ]
        
        basketball_teams = [
            "LA Lakers", "Golden State Warriors", "Boston Celtics", "Chicago Bulls",
            "Miami Heat", "CSKA Moscow", "Real Madrid", "Barcelona", "Anadolu Efes"
        ]
        
        tennis_players = [
            "N. Djokovic", "C. Alcaraz", "D. Medvedev", "J. Sinner", "A. Zverev",
            "A. Rublev", "H. Rune", "S. Tsitsipas", "R. Nadal", "K. Khachanov"
        ]
        
        table_tennis_players = [
            "Fan Zhendong", "Ma Long", "Wang Chuqin", "T. Harimoto", 
            "D. Ovtcharov", "Truls Moregard", "Lin Yun-Ju", "Hugo Calderano"
        ]

        # Генерация 50 матчей
        for _ in range(50):
            # Выбор спорта с весами (футбола больше)
            sport_choice = random.choices(
                ['football', 'hockey', 'basketball', 'tennis', 'table_tennis'],
                weights=[40, 25, 15, 10, 10],
                k=1
            )[0]

            if sport_choice == 'football':
                teams = football_teams
                has_draw = True
            elif sport_choice == 'hockey':
                teams = hockey_teams
                has_draw = True
            elif sport_choice == 'basketball':
                teams = basketball_teams
                has_draw = False # В ставках часто без ничьей (с ОТ)
            elif sport_choice == 'tennis':
                teams = tennis_players
                has_draw = False
            else:
                teams = table_tennis_players
                has_draw = False

            # Выбираем 2 разные команды
            t1, t2 = random.sample(teams, 2)
            
            # Генерация коэффициентов (фаворит/аутсайдер)
            is_balanced = random.choice([True, False])
            if is_balanced:
                odds1 = round(random.uniform(1.85, 2.70), 2)
                odds2 = round(random.uniform(1.85, 2.70), 2)
            else:
                odds1 = round(random.uniform(1.15, 1.60), 2)
                odds2 = round(random.uniform(3.50, 8.00), 2)
            
            # Время матча (смешиваем Live и Scheduled)
            is_live = random.random() < 0.3 # 30% матчей сейчас идут
            if is_live:
                status = "live"
                start_time = datetime.utcnow() - timedelta(minutes=random.randint(5, 90))
                score_h = random.randint(0, 3)
                score_a = random.randint(0, 3)
            else:
                status = "scheduled"
                start_time = datetime.utcnow() + timedelta(hours=random.randint(1, 48))
                score_h = 0
                score_a = 0

            match = Match(
                sport=sport_choice,
                team_home=t1,
                team_away=t2,
                score_home=score_h,
                score_away=score_a,
                status=status,
                start_time=start_time,
                odds_home=odds1,
                odds_away=odds2,
                odds_draw=round(random.uniform(2.8, 4.5), 2) if has_draw else None,
                current_minute=random.randint(10, 85) if status == 'live' else 0,
                period="2nd Half" if status == 'live' and random.random() > 0.5 else "1st Half"
            )
            session.add(match)
            
        logger.info("✅ Database seeded with extensive match data!")
    
    session.commit()
    session.close()

# ============================
# ЛОГИКА ИГР (Game Manager)
# ============================

def play_mines_logic(user_id, amount, mines_count, session):
    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user or user.balance < amount:
        return {"error": "Недостаточно средств"}

    safe_cells = 25 - mines_count
    multiplier = round(25 / safe_cells * 0.95, 2)
    if multiplier < 1.01: multiplier = 1.01

    user.balance -= Decimal(amount)
    potential_win = Decimal(amount) * Decimal(multiplier)

    bet = Bet(
        user_id=user_id, game_type="mines", amount=amount,
        potential_win=potential_win, odds=multiplier,
        selected_outcome=str(mines_count), status="active"
    )
    session.add(bet)
    session.commit()
    return {"success": True, "bet_id": bet.id, "new_balance": float(user.balance)}

def play_dice_logic(user_id, amount, bet_type, session):
    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user or user.balance < amount:
        return {"error": "Недостаточно средств"}

    dice_roll = random.randint(1, 6)
    is_even = (dice_roll % 2 == 0)
    win = (bet_type == "even" and is_even) or (bet_type == "odd" and not is_even)
    multiplier = 1.95 
    
    if win:
        change = float(amount) * (multiplier - 1)
        status = "won"
    else:
        change = -float(amount)
        status = "lost"
        
    user.balance += Decimal(change)
    win_amount = Decimal(amount) * Decimal(multiplier) if win else 0

    bet = Bet(
        user_id=user_id, game_type="dice", amount=amount,
        potential_win=win_amount, odds=multiplier,
        selected_outcome=bet_type, status=status, settled_at=datetime.utcnow()
    )
    session.add(bet)
    session.commit()
    
    return {
        "success": True, "dice_result": dice_roll, "win": win, 
        "win_amount": float(win_amount), "new_balance": float(user.balance)
    }

# ============================
# API ROUTES (FLASK)
# ============================

@app.route('/api/init', methods=['POST'])
def api_init():
    user_id = 123456789 # Fallback
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        user = User(telegram_id=user_id, username="NewPlayer", balance=5000.00)
        session.add(user)
        session.commit()
    response = {
        "success": True,
        "user": {"id": user.telegram_id, "username": user.username, "balance": float(user.balance)}
    }
    session.close()
    return jsonify(response)

@app.route('/api/balance', methods=['GET'])
def get_balance():
    user_id = request.args.get('user_id')
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    bal = float(user.balance) if user else 0.0
    session.close()
    return jsonify({"balance": bal})

@app.route('/api/matches', methods=['GET'])
def get_matches():
    sport = request.args.get('sport')
    session = SessionLocal()
    query = session.query(Match).filter(Match.status.in_(["scheduled", "live"]))
    if sport and sport != 'all':
        query = query.filter_by(sport=sport)
    
    matches = query.order_by(Match.start_time.asc()).all()
    result = []
    for m in matches:
        # Для лайва обновляем время (симуляция)
        period = m.period
        if m.status == "live":
            period = f"{m.current_minute}'"
        
        result.append({
            "id": m.id, "sport": m.sport, 
            "team_home": m.team_home, "team_away": m.team_away,
            "score_home": m.score_home, "score_away": m.score_away,
            "odds_home": float(m.odds_home), "odds_away": float(m.odds_away),
            "odds_draw": float(m.odds_draw) if m.odds_draw else None,
            "status": m.status, "start_time": m.start_time.isoformat(),
            "period": period
        })
    session.close()
    return jsonify({"matches": result})

@app.route('/api/bet', methods=['POST'])
def place_bet():
    data = request.json
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    
    if not user or user.balance < Decimal(data['amount']):
        session.close()
        return jsonify({"success": False, "message": "No money"}), 400
        
    user.balance -= Decimal(data['amount'])
    bet = Bet(
        user_id=user.telegram_id, match_id=data.get('match_id'),
        game_type=data.get('game_type', 'sport'), amount=data['amount'],
        odds=data.get('odds', 1.0), selected_outcome=data.get('outcome'),
        potential_win=Decimal(data['amount']) * Decimal(data.get('odds', 1.0))
    )
    session.add(bet)
    session.commit()
    res = {"success": True, "new_balance": float(user.balance), "potential_win": float(bet.potential_win)}
    session.close()
    return jsonify(res)

@app.route('/api/game', methods=['POST'])
def game_action():
    data = request.json
    session = SessionLocal()
    try:
        if data['game_type'] == 'mines':
            res = play_mines_logic(data['user_id'], data['amount'], int(data.get('mines_count', 3)), session)
        elif data['game_type'] == 'dice':
            res = play_dice_logic(data['user_id'], data['amount'], data.get('dice_bet'), session)
        else:
            res = {"error": "Unknown game"}
        
        if "error" in res:
             return jsonify({"success": False, "message": res["error"]}), 400
        return jsonify(res)
    finally:
        session.close()

@app.route('/api/mines/cashout', methods=['POST'])
def mines_cashout():
    data = request.json
    session = SessionLocal()
    bet = session.query(Bet).filter_by(id=data['crash_id'], status='active').first()
    if not bet:
        session.close()
        return jsonify({"success": False}), 400
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    user.balance += bet.potential_win
    bet.status = "won"
    bet.settled_at = datetime.utcnow()
    res = {"success": True, "win_amount": float(bet.potential_win), "new_balance": float(user.balance)}
    session.commit()
    session.close()
    return jsonify(res)

@app.route('/api/crash/start', methods=['POST'])
def crash_start():
    data = request.json
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    if not user or user.balance < Decimal(data['amount']):
        session.close()
        return jsonify({"success": False}), 400
    
    crash_point = round(random.uniform(1.0, 5.0), 2)
    if random.random() < 0.1: crash_point = 1.0
    
    user.balance -= Decimal(data['amount'])
    game = CrashGame(
        user_id=user.telegram_id, crash_point=crash_point, 
        bet_amount=data['amount'], is_active=True
    )
    session.add(game)
    session.commit()
    res = {
        "success": True, "game_id": game.id, 
        "crash_point": float(crash_point), "new_balance": float(user.balance)
    }
    session.close()
    return jsonify(res)

@app.route('/api/crash/cashout', methods=['POST'])
def crash_cashout():
    data = request.json
    session = SessionLocal()
    game = session.query(CrashGame).filter_by(id=data['crash_id'], is_active=True).first()
    if not game:
        session.close()
        return jsonify({"success": False}), 400
        
    multiplier = float(game.crash_point) - 0.1
    if multiplier < 1.01: multiplier = 1.01
    
    win_amount = Decimal(game.bet_amount) * Decimal(multiplier)
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    user.balance += win_amount
    game.is_active = False
    
    bet = Bet(
        user_id=user.telegram_id, game_type="crash", amount=game.bet_amount,
        potential_win=win_amount, odds=multiplier, status="won",
        selected_outcome="cashout", settled_at=datetime.utcnow()
    )
    session.add(bet)
    session.commit()
    res = {
        "success": True, "win_amount": float(win_amount), 
        "new_balance": float(user.balance), "multiplier": multiplier
    }
    session.close()
    return jsonify(res)

@app.route('/api/history', methods=['GET'])
def get_history():
    user_id = request.args.get('user_id')
    session = SessionLocal()
    bets = session.query(Bet).filter_by(user_id=user_id).order_by(Bet.created_at.desc()).limit(20).all()
    history = []
    for b in bets:
        history.append({
            "game_type": b.game_type, "amount": float(b.amount),
            "status": b.status, "odds": float(b.odds),
            "outcome": b.selected_outcome, "created_at": b.created_at.isoformat()
        })
    session.close()
    return jsonify({"history": history})

# ============================
# BOT LOGIC
# ============================

async def start_bot_async():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="🎮 Play Royal Bet", web_app=WebAppInfo(url=FRONTEND_URL))
        ]])
        await message.answer(f"Привет, {hbold(message.from_user.first_name)}! Сделай ставку сейчас!", reply_markup=kb)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot_async())
    loop.close()

# ============================
# ЗАПУСК
# ============================

if __name__ == "__main__":
    init_db()
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
