import os
import random
import threading
import asyncio
import logging
import json
from urllib.parse import parse_qs, unquote
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, JSON, Text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

# ============================
# КОНФИГУРАЦИЯ
# ============================

BOT_TOKEN = "8055430766:AAEfGZOVbLhOjASjlVUmOMJuc89SjT_IkmE"
# Вставь свой URL базы данных Neon
DATABASE_URL = "postgresql://neondb_owner:npg_FTJrHNW28UAP@ep-spring-forest-affemvmu-pooler.c-2.us-west-2.aws.neon.tech/neondb?sslmode=require"
FRONTEND_URL = "https://matveymak22.github.io/Cas" 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ============================
# БАЗА ДАННЫХ
# ============================

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
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
    status = Column(String(20), default="scheduled")
    start_time = Column(DateTime)
    
    # Основные исходы
    odds_home = Column(Numeric(5, 2))
    odds_draw = Column(Numeric(5, 2), nullable=True)
    odds_away = Column(Numeric(5, 2))
    
    # Детальные ставки (храним в JSON для гибкости)
    # Структура: { "total_over": 1.85, "total_under": 1.85, "handicap1": 1.9, "handicap2": 1.9, "total_val": 2.5 }
    details = Column(JSON, default={})
    
    current_minute = Column(Integer, default=0)
    period = Column(String(20), default="1st")

class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    game_type = Column(String(20)) # sport, mines, dice, crash
    amount = Column(Numeric(10, 2))
    status = Column(String(20), default="active") # active, won, lost, cashed_out
    potential_win = Column(Numeric(10, 2), default=0)
    odds = Column(Numeric(5, 2), default=1.0)
    selected_outcome = Column(String(100)) # "home", "mines_3", "crash_2.0"
    
    # Для Mines и Crash храним состояние игры здесь
    game_data = Column(JSON, default={}) 
    
    created_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)

def init_db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    if session.query(Match).count() < 10:
        logger.info("Generating extended match data...")
        teams_list = [
            ("Real Madrid", "Barcelona"), ("Man City", "Arsenal"), ("Liverpool", "Chelsea"),
            ("Bayern", "Dortmund"), ("PSG", "Monaco"), ("Juventus", "Milan"),
            ("Zenit", "Spartak"), ("CSKA", "Dynamo")
        ]
        
        for t1, t2 in teams_list:
            # Генерация доп. коэффициентов
            total_val = 2.5
            odds_over = round(random.uniform(1.7, 2.1), 2)
            odds_under = round(random.uniform(1.7, 2.1), 2)
            handicap_val = -1.5
            h1 = round(random.uniform(2.0, 3.5), 2)
            h2 = round(random.uniform(1.3, 1.6), 2)

            details = {
                "total_val": total_val,
                "total_over": odds_over,
                "total_under": odds_under,
                "handicap_val": handicap_val,
                "handicap1": h1,
                "handicap2": h2,
                "both_score_yes": round(random.uniform(1.6, 2.2), 2),
                "both_score_no": round(random.uniform(1.6, 2.2), 2)
            }

            match = Match(
                sport="football",
                team_home=t1, team_away=t2,
                odds_home=round(random.uniform(1.5, 4.0), 2),
                odds_away=round(random.uniform(1.5, 4.0), 2),
                odds_draw=round(random.uniform(3.0, 4.5), 2),
                start_time=datetime.utcnow() + timedelta(hours=random.randint(1, 48)),
                status="scheduled",
                details=details
            )
            session.add(match)
        session.commit()
    session.close()

# ============================
# ПАРСИНГ ДАННЫХ TELEGRAM
# ============================

def get_user_from_init_data(init_data_str):
    """
    Извлекает данные пользователя из initData (Telegram WebApp).
    """
    if not init_data_str or init_data_str == 'mock':
        return 123456789, "Test User" # Fallback для браузера

    try:
        # initData приходит как URL-encoded строка
        parsed = parse_qs(init_data_str)
        if 'user' in parsed:
            user_json = parsed['user'][0]
            user_data = json.loads(user_json)
            user_id = int(user_data.get('id'))
            first_name = user_data.get('first_name', '')
            username = user_data.get('username', first_name)
            return user_id, username
    except Exception as e:
        logger.error(f"Error parsing initData: {e}")
    
    return 123456789, "Test User"

# ============================
# API ROUTES
# ============================

@app.route('/api/init', methods=['POST'])
def api_init():
    data = request.json
    init_data = data.get('initData')
    
    user_id, username = get_user_from_init_data(init_data)
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user:
        user = User(telegram_id=user_id, username=username, balance=5000.00)
        session.add(user)
        session.commit()
    else:
        # Обновим ник, если сменился
        if user.username != username:
            user.username = username
            session.commit()
            
    response = {
        "success": True,
        "user": {
            "id": user.telegram_id,
            "username": user.username,
            "balance": float(user.balance)
        }
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
        result.append({
            "id": m.id, "sport": m.sport, 
            "team_home": m.team_home, "team_away": m.team_away,
            "score_home": m.score_home, "score_away": m.score_away,
            "odds_home": float(m.odds_home), "odds_away": float(m.odds_away),
            "odds_draw": float(m.odds_draw) if m.odds_draw else None,
            "status": m.status, "start_time": m.start_time.isoformat(),
            "period": f"{m.current_minute}'" if m.status == 'live' else m.period,
            "details": m.details # Передаем доп. ставки
        })
    session.close()
    return jsonify({"matches": result})

@app.route('/api/bet', methods=['POST'])
def place_bet():
    # Ставки на спорт
    data = request.json
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    
    if not user or user.balance < Decimal(data['amount']):
        session.close()
        return jsonify({"success": False, "message": "Недостаточно средств"}), 400
        
    user.balance -= Decimal(data['amount'])
    bet = Bet(
        user_id=user.telegram_id, match_id=data.get('match_id'),
        game_type=data.get('game_type', 'sport'), amount=data['amount'],
        odds=data.get('odds', 1.0), selected_outcome=data.get('outcome'),
        potential_win=Decimal(data['amount']) * Decimal(data.get('odds', 1.0))
    )
    session.add(bet)
    session.commit()
    res = {"success": True, "new_balance": float(user.balance)}
    session.close()
    return jsonify(res)

# ============================
# ЛОГИКА MINES (Пошаговая)
# ============================

@app.route('/api/mines/start', methods=['POST'])
def mines_start():
    data = request.json
    user_id = data.get('user_id')
    amount = float(data.get('amount'))
    mines_count = int(data.get('mines_count', 3))
    
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    
    if not user or user.balance < Decimal(amount):
        session.close()
        return jsonify({"success": False, "message": "Недостаточно средств"}), 400
    
    # Списываем баланс
    user.balance -= Decimal(amount)
    
    # Генерируем поле (серверная сторона)
    # 0 - безопасно, 1 - мина
    field = [0] * 25
    mine_indices = random.sample(range(25), mines_count)
    for idx in mine_indices:
        field[idx] = 1
        
    game_state = {
        "field": field, # Храним поле, но не отдаем клиенту
        "mines_count": mines_count,
        "revealed_indices": [],
        "is_active": True
    }
    
    bet = Bet(
        user_id=user_id, game_type="mines", amount=amount,
        status="active", odds=1.0, selected_outcome=f"mines_{mines_count}",
        game_data=game_state
    )
    session.add(bet)
    session.commit()
    
    res = {
        "success": True, 
        "game_id": bet.id, 
        "new_balance": float(user.balance)
    }
    session.close()
    return jsonify(res)

@app.route('/api/mines/reveal', methods=['POST'])
def mines_reveal():
    data = request.json
    game_id = data.get('game_id')
    cell_index = int(data.get('cell_index'))
    
    session = SessionLocal()
    bet = session.query(Bet).filter_by(id=game_id, status="active").first()
    
    if not bet:
        session.close()
        return jsonify({"success": False, "message": "Игра не найдена"}), 400
        
    state = bet.game_data # Копия состояния
    field = state['field']
    
    if cell_index in state['revealed_indices']:
        session.close()
        return jsonify({"success": False, "message": "Клетка уже открыта"})
    
    # Логика хода
    if field[cell_index] == 1:
        # БУМ! Мина
        bet.status = "lost"
        bet.settled_at = datetime.utcnow()
        # Показываем все мины
        session.commit()
        return jsonify({
            "success": True,
            "status": "boom",
            "field": field # Отдаем поле, чтобы показать мины
        })
    else:
        # Безопасно
        state['revealed_indices'].append(cell_index)
        bet.game_data = state # Обновляем JSON в БД
        
        # Считаем множитель
        total_cells = 25
        mines = state['mines_count']
        opened = len(state['revealed_indices'])
        # Формула множителя (классическая для казино)
        # Шанс угадать 1 раз: (25-mines)/25. Множитель = 0.95 / шанс (0.95 - маржа)
        # Тут упрощенная прогрессия
        multiplier = 1.0
        for i in range(opened):
            safe_remaining = total_cells - mines - i
            total_remaining = total_cells - i
            multiplier *= (total_remaining / safe_remaining)
        
        multiplier = round(multiplier * 0.95, 2) # 5% маржа
        bet.odds = multiplier
        bet.potential_win = bet.amount * Decimal(multiplier)
        
        # Обновляем запись в БД
        # Чтобы SQLAlchemy увидел изменение в JSON
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(bet, "game_data")
        
        session.commit()
        
        return jsonify({
            "success": True,
            "status": "safe",
            "multiplier": multiplier,
            "potential_win": float(bet.potential_win)
        })

@app.route('/api/mines/cashout', methods=['POST'])
def mines_cashout():
    data = request.json
    game_id = data.get('game_id')
    
    session = SessionLocal()
    bet = session.query(Bet).filter_by(id=game_id, status="active").first()
    
    if not bet:
        session.close()
        return jsonify({"success": False, "message": "Игра не активна"}), 400
        
    state = bet.game_data
    opened = len(state['revealed_indices'])
    
    user = session.query(User).filter_by(telegram_id=bet.user_id).first()
    
    # ЛОГИКА 80%, если не открыто ни одной клетки
    if opened == 0:
        win_amount = bet.amount * Decimal(0.8)
        bet.status = "surrendered" # Сдался
    else:
        win_amount = bet.potential_win
        bet.status = "won"
        
    user.balance += win_amount
    bet.settled_at = datetime.utcnow()
    
    session.commit()
    
    res = {
        "success": True,
        "win_amount": float(win_amount),
        "new_balance": float(user.balance)
    }
    session.close()
    return jsonify(res)

# ============================
# ДРУГИЕ ИГРЫ (Dice, Crash)
# ============================

@app.route('/api/game', methods=['POST'])
def game_general():
    # Для Dice используем старый эндпоинт, Mines переехал на /api/mines/start
    data = request.json
    if data.get('game_type') == 'dice':
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=data['user_id']).first()
        if not user or user.balance < Decimal(data['amount']):
            session.close()
            return jsonify({"success": False, "message": "No money"}), 400
            
        user.balance -= Decimal(data['amount'])
        
        dice = random.randint(1, 6)
        bet_type = data.get('dice_bet')
        win = (dice % 2 == 0 and bet_type == 'even') or (dice % 2 != 0 and bet_type == 'odd')
        
        win_amt = 0
        if win:
            win_amt = float(data['amount']) * 1.95
            user.balance += Decimal(win_amt)
            
        bet = Bet(user_id=user.telegram_id, game_type='dice', amount=data['amount'], status='won' if win else 'lost', selected_outcome=bet_type)
        session.add(bet)
        session.commit()
        
        res = {"success": True, "dice_result": dice, "win": win, "win_amount": win_amt, "new_balance": float(user.balance)}
        session.close()
        return jsonify(res)
    return jsonify({"error": "Use specific endpoints"})

@app.route('/api/crash/start', methods=['POST'])
def crash_start():
    data = request.json
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    if not user or user.balance < Decimal(data['amount']):
        session.close()
        return jsonify({"success": False}), 400
    
    user.balance -= Decimal(data['amount'])
    
    # Точка краша
    point = round(random.uniform(1.0, 5.0), 2)
    if random.random() < 0.1: point = 1.0
    
    game = CrashGame(user_id=user.telegram_id, crash_point=point, bet_amount=data['amount'], is_active=True)
    session.add(game)
    session.commit()
    
    res = {"success": True, "game_id": game.id, "crash_point": float(point), "new_balance": float(user.balance)}
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
        
    mult = float(game.crash_point) - 0.1
    if mult < 1.01: mult = 1.01
    
    win = Decimal(game.bet_amount) * Decimal(mult)
    user = session.query(User).filter_by(telegram_id=data['user_id']).first()
    user.balance += win
    game.is_active = False
    
    bet = Bet(user_id=user.telegram_id, game_type='crash', amount=game.bet_amount, status='won', potential_win=win)
    session.add(bet)
    session.commit()
    
    res = {"success": True, "win_amount": float(win), "new_balance": float(user.balance), "multiplier": mult}
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
            "game_type": b.game_type, "amount": float(b.amount), "status": b.status,
            "odds": float(b.odds), "outcome": b.selected_outcome, "created_at": b.created_at.isoformat()
        })
    session.close()
    return jsonify({"history": history})

# ============================
# BOT
# ============================

async def start_bot_async():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="🎰 Играть сейчас", web_app=WebAppInfo(url=FRONTEND_URL))
        ]])
        await message.answer(f"Привет, {hbold(message.from_user.first_name)}! Твой баланс ждет.", reply_markup=kb)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot error: {e}")

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_bot_async())
    loop.close()

if __name__ == "__main__":
    init_db()
    bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
