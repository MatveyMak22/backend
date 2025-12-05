import os
import random
import json
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from decimal import Decimal

from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# КОНФИГУРАЦИЯ
# ============================

BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
FRONTEND_URL = "https://matveymak22.github.io/Cas" 
# Твоя база данных Neon
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============================
# БАЗА ДАННЫХ
# ============================

engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=30)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(100))
    balance = Column(Numeric(12, 2), default=5000.00)
    created_at = Column(DateTime, default=datetime.utcnow)

class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    sport = Column(String(50))
    team_home = Column(String(100))
    team_away = Column(String(100))
    score_home = Column(Integer, default=0)
    score_away = Column(Integer, default=0)
    status = Column(String(20), default="scheduled")
    start_time = Column(DateTime)
    odds_home = Column(Numeric(5, 2))
    odds_draw = Column(Numeric(5, 2), nullable=True)
    odds_away = Column(Numeric(5, 2))
    period = Column(String(20), default="")
    score_details = Column(JSON, default={}) 
    details = Column(JSON, default={})       

class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    game_type = Column(String(20)) 
    amount = Column(Numeric(12, 2))
    status = Column(String(20), default="active")
    potential_win = Column(Numeric(12, 2), default=0)
    odds = Column(Numeric(10, 2), default=1.0)
    outcome = Column(String(100))
    match_info = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ActiveGame(Base):
    __tablename__ = "active_games"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    game_type = Column(String(20))
    bet_amount = Column(Numeric(12, 2))
    game_data = Column(JSON) 
    is_active = Column(Boolean, default=True)

def init_db():
    try:
        # Раскомментируй следующую строку один раз, если нужно сбросить старые таблицы с ошибками
        # Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        if session.query(Match).count() == 0:
            logger.info("Генерация матчей...")
            matches_data = [
                ("football", "Real Madrid", "Barcelona", True),
                ("football", "Man City", "Arsenal", True),
                ("hockey", "SKA", "CSKA", True),
                ("basketball", "Lakers", "Bulls", False),
                ("tennis", "Djokovic", "Nadal", False)
            ]
            for sport, t1, t2, has_draw in matches_data:
                details = {
                    "total_val": 2.5,
                    "total_over": round(random.uniform(1.6, 2.1), 2),
                    "total_under": round(random.uniform(1.6, 2.1), 2),
                    "handicap_val": -1.5,
                    "handicap1": round(random.uniform(1.9, 3.5), 2),
                    "handicap2": round(random.uniform(1.2, 1.5), 2)
                }
                match = Match(
                    sport=sport, team_home=t1, team_away=t2,
                    score_home=random.randint(0, 3), score_away=random.randint(0, 3),
                    status=random.choice(["live", "scheduled"]),
                    start_time=datetime.utcnow() + timedelta(minutes=random.randint(10, 300)),
                    odds_home=round(random.uniform(1.4, 3.5), 2),
                    odds_away=round(random.uniform(1.4, 3.5), 2),
                    odds_draw=round(random.uniform(2.8, 4.2), 2) if has_draw else None,
                    period="1st Half", details=details
                )
                session.add(match)
            session.commit()
        session.close()
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

# Проверка Telegram данных
def get_user_from_init_data(init_data_str):
    if not init_data_str:
        return None, None
    try:
        parsed = parse_qs(init_data_str)
        if 'user' in parsed:
            user_data = json.loads(parsed['user'][0])
            return int(user_data.get('id')), user_data.get('username') or user_data.get('first_name') or "User"
    except Exception as e:
        logger.error(f"Error parsing initData: {e}")
    return None, None

# ============================
# API ENDPOINTS
# ============================

@app.route('/api/init', methods=['POST'])
def api_init():
    data = request.json
    init_data = data.get('initData')
    
    # СТРОГАЯ ПРОВЕРКА: Если нет initData - ошибка
    if not init_data:
        return jsonify({"success": False, "message": "Only via Telegram"}), 403

    user_id, username = get_user_from_init_data(init_data)
    if user_id is None:
        return jsonify({"success": False, "message": "Invalid Auth"}), 403
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        user = User(telegram_id=user_id, username=username, balance=5000.00)
        session.add(user)
        session.commit()
    
    response = {
        "success": True,
        "user": {"id": user.telegram_id, "username": user.username, "balance": float(user.balance)}
    }
    session.close()
    return jsonify(response)

@app.route('/api/balance', methods=['GET'])
def api_balance():
    user_id = request.args.get('user_id')
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    bal = float(user.balance) if user else 0.0
    session.close()
    return jsonify({"balance": bal})

@app.route('/api/matches', methods=['GET'])
def api_matches():
    sport = request.args.get('sport', 'all')
    session = SessionLocal()
    query = session.query(Match)
    if sport != 'all':
        query = query.filter_by(sport=sport)
    matches = query.all()
    result = []
    for m in matches:
        result.append({
            "id": m.id, "sport": m.sport,
            "team_home": m.team_home, "team_away": m.team_away,
            "score_home": m.score_home, "score_away": m.score_away,
            "status": m.status, "start_time": m.start_time.isoformat(),
            "odds_home": float(m.odds_home), "odds_away": float(m.odds_away),
            "odds_draw": float(m.odds_draw) if m.odds_draw else None,
            "period": m.period, "details": m.details 
        })
    session.close()
    return jsonify({"matches": result})

@app.route('/api/bet', methods=['POST'])
def api_place_bet():
    data = request.json
    user_id = data.get('user_id')
    # ВАЖНО: Конвертация в Decimal
    amount_dec = Decimal(str(data.get('amount')))
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user or user.balance < amount_dec:
        session.close()
        return jsonify({"success": False, "message": "Недостаточно средств"})
    
    user.balance -= amount_dec
    
    match = session.query(Match).get(data.get('match_id'))
    match_info = {"teams": f"{match.team_home} vs {match.team_away}"} if match else {}
    
    odds_val = Decimal(str(data.get('odds', 1.0)))
    potential = amount_dec * odds_val
    
    bet = Bet(
        user_id=user_id, game_type="sport", amount=amount_dec,
        status="active", odds=odds_val, outcome=data.get('outcome'),
        match_info=match_info, potential_win=potential
    )
    session.add(bet)
    session.commit()
    
    new_bal = float(user.balance)
    session.close()
    return jsonify({"success": True, "new_balance": new_bal, "potential_win": float(potential)})

# --- ИГРЫ ---

@app.route('/api/game', methods=['POST'])
def api_game_start():
    data = request.json
    game_type = data.get('game_type')
    user_id = data.get('user_id')
    amount_dec = Decimal(str(data.get('amount')))
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user or user.balance < amount_dec:
        session.close()
        return jsonify({"success": False, "message": "Недостаточно средств"})
    
    user.balance -= amount_dec
    
    response = {}
    
    if game_type == 'dice':
        dice_res = random.randint(1, 6)
        bet_type = data.get('dice_bet')
        is_win = (dice_res % 2 == 0 and bet_type == 'even') or (dice_res % 2 != 0 and bet_type == 'odd')
        win_amt = Decimal(0)
        
        if is_win:
            win_amt = amount_dec * Decimal(2.0)
            user.balance += win_amt
            
        bet = Bet(user_id=user_id, game_type='dice', amount=amount_dec, status='won' if is_win else 'lost', odds=2.0, outcome=f"{bet_type} ({dice_res})")
        session.add(bet)
        response = {
            "success": True, "dice_result": dice_res,
            "win": is_win, "win_amount": float(win_amt),
            "new_balance": float(user.balance)
        }
        
    elif game_type == 'mines':
        mines_count = int(data.get('mines_count', 3))
        field = [0] * 25
        indices = random.sample(range(25), mines_count)
        for i in indices: field[i] = 1
            
        # revealed_count = 0 (важно для логики 80%)
        game_data = {"field": field, "mines_count": mines_count, "revealed_count": 0}
        
        active_game = ActiveGame(
            user_id=user_id, game_type='mines', bet_amount=amount_dec,
            game_data=game_data
        )
        session.add(active_game)
        session.commit()
        response = {
            "success": True, "bet_id": active_game.id,
            "field": field, "new_balance": float(user.balance)
        }
    
    session.commit()
    session.close()
    return jsonify(response)

@app.route('/api/mines/update', methods=['POST'])
def api_mines_update():
    # Клиент сообщает, что открыл клетку
    data = request.json
    game_id = data.get('crash_id')
    
    session = SessionLocal()
    game = session.query(ActiveGame).get(game_id)
    if game and game.is_active:
        current_data = dict(game.game_data)
        current_data['revealed_count'] = current_data.get('revealed_count', 0) + 1
        game.game_data = current_data
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(game, "game_data")
        session.commit()
    session.close()
    return jsonify({"success": True})

@app.route('/api/mines/cashout', methods=['POST'])
def api_mines_cashout():
    data = request.json
    game_id = data.get('crash_id')
    user_id = data.get('user_id')
    
    session = SessionLocal()
    game = session.query(ActiveGame).get(game_id)
    
    if not game or not game.is_active:
        session.close()
        return jsonify({"success": False, "message": "Игра не найдена"})
    
    revealed = game.game_data.get('revealed_count', 0)
    amount = game.bet_amount
    
    # ЛОГИКА 80%: Если ходов не было - возвращаем 80%
    if revealed == 0:
        win_amount = amount * Decimal('0.8')
        multiplier = 0.8
        status = 'refund'
    else:
        # Расчет выигрыша (упрощенный, но честный)
        mines = game.game_data['mines_count']
        multiplier = Decimal(1.0)
        # Симулируем расчет коэффициента за N ходов
        for i in range(revealed):
            safe_remaining = 25 - mines - i
            total_remaining = 25 - i
            if safe_remaining > 0:
                multiplier *= Decimal(total_remaining) / Decimal(safe_remaining)
            
        multiplier = multiplier * Decimal('0.95') # Маржа 5%
        win_amount = amount * multiplier
        status = 'won'

    user = session.query(User).filter_by(telegram_id=user_id).first()
    user.balance += win_amount
    game.is_active = False
    
    bet = Bet(
        user_id=user_id, game_type='mines', amount=amount, 
        status=status, odds=multiplier, outcome=f"mines_out_{revealed}", 
        potential_win=win_amount
    )
    session.add(bet)
    session.commit()
    
    new_bal = float(user.balance)
    session.close()
    return jsonify({"success": True, "new_balance": new_bal, "win_amount": float(win_amount)})

@app.route('/api/crash/start', methods=['POST'])
def api_crash_start():
    data = request.json
    user_id = data.get('user_id')
    amount_dec = Decimal(str(data.get('amount')))
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user or user.balance < amount_dec:
        session.close()
        return jsonify({"success": False, "message": "Недостаточно средств"})
    
    user.balance -= amount_dec
    
    crash_point = round(random.uniform(1.0, 5.0), 2)
    if random.random() < 0.1: crash_point = 1.0
    
    game = ActiveGame(user_id=user_id, game_type='crash', bet_amount=amount_dec, game_data={"crash_point": crash_point})
    session.add(game)
    session.commit()
    
    response = {
        "success": True, "game_id": game.id,
        "crash_point": float(crash_point), "new_balance": float(user.balance)
    }
    session.close()
    return jsonify(response)

@app.route('/api/crash/cashout', methods=['POST'])
def api_crash_cashout():
    data = request.json
    game_id = data.get('crash_id')
    user_id = data.get('user_id')
    
    session = SessionLocal()
    game = session.query(ActiveGame).get(game_id)
    
    if not game or not game.is_active:
        session.close()
        return jsonify({"success": False})
    
    crash_point = float(game.game_data['crash_point'])
    # Игрок выводит чуть раньше, чем крашнется
    user_mult_float = crash_point - 0.05
    if user_mult_float < 1.01: user_mult_float = 1.01
    user_mult_dec = Decimal(str(round(user_mult_float, 2)))
    
    win_amount = game.bet_amount * user_mult_dec
    
    user = session.query(User).filter_by(telegram_id=user_id).first()
    user.balance += win_amount
    game.is_active = False
    
    bet = Bet(
        user_id=user_id, game_type='crash', amount=game.bet_amount, 
        status='won', odds=user_mult_dec, outcome="cashout", 
        potential_win=win_amount
    )
    session.add(bet)
    session.commit()
    
    new_bal = float(user.balance)
    session.close()
    return jsonify({"success": True, "new_balance": new_bal, "win_amount": float(win_amount), "multiplier": float(user_mult_dec)})

@app.route('/api/history', methods=['GET'])
def api_history():
    user_id = request.args.get('user_id')
    session = SessionLocal()
    bets = session.query(Bet).filter_by(user_id=user_id).order_by(Bet.created_at.desc()).limit(20).all()
    history = []
    for b in bets:
        history.append({
            "game_type": b.game_type, "amount": float(b.amount),
            "status": b.status, "odds": float(b.odds),
            "outcome": b.outcome, "created_at": b.created_at.isoformat(),
            "match_info": b.match_info
        })
    session.close()
    return jsonify({"history": history})

async def start_bot_async():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="🎰 Играть в Royal Bet", web_app=WebAppInfo(url=FRONTEND_URL))
        ]])
        await message.answer(f"Привет, {hbold(message.from_user.first_name)}! Твой баланс ждет.", reply_markup=kb)
    try:
        await dp.start_polling(bot, handle_signals=False)
    except Exception as e:
        logger.error(f"Bot error: {e}")

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot_async())
    loop.close()

if __name__ == '__main__':
    init_db()
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
