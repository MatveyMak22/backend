import requests
import sqlite3
import time
import threading
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from sklearn.ensemble import RandomForestClassifier
import numpy as np

# ================= CONFIG =================
TOKEN = "8055430766:AAFOiwd06FIxkUXWnszcTY3YOgWUz4-NEYY"
DB_NAME = "nft.db"
FETCH_INTERVAL = 60

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nfts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        floor REAL,
        sales INTEGER,
        listings INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        label INTEGER
    )
    """)

    conn.commit()
    conn.close()

# ================= API =================

def fetch_nfts():
    url = "https://api.tgmrkt.io/api/v1/gifts/saling"

    json_data = {
        "count": 20,
        "cursor": ""
    }

    try:
        response = requests.post(url, json=json_data, timeout=10)
        return response.json().get("data", [])
    except:
        return []

# ================= SAVE =================

def save_nfts(nfts):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for nft in nfts:
        price = nft.get("price", 0)
        floor = nft.get("floorPrice", 0)

        label = 1 if floor > price else 0  # простая логика прибыли

        cursor.execute("""
        INSERT INTO nfts (name, price, floor, sales, listings, label)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            nft.get("name"),
            price,
            floor,
            nft.get("sales", 0),
            nft.get("listings", 0),
            label
        ))

    conn.commit()
    conn.close()

# ================= AI =================

model = RandomForestClassifier()
trained = False

def train_model():
    global trained

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT price, floor, sales, listings, label FROM nfts
    """)
    data = cursor.fetchall()
    conn.close()

    if len(data) < 50:
        return

    X = []
    y = []

    for row in data:
        price, floor, sales, listings, label = row

        if floor == 0:
            continue

        discount = (floor - price) / floor
        liquidity = sales / max(listings, 1)

        X.append([price, floor, discount, liquidity])
        y.append(label)

    if len(X) < 20:
        return

    model.fit(X, y)
    trained = True
    print("AI trained!")

def predict_nft(nft):
    if not trained:
        return 0.5

    price = nft["price"]
    floor = nft["floor"]
    sales = nft["sales"]
    listings = nft["listings"]

    if floor == 0:
        return 0

    discount = (floor - price) / floor
    liquidity = sales / max(listings, 1)

    X = np.array([[price, floor, discount, liquidity]])
    return model.predict_proba(X)[0][1]

# ================= ANALYSIS =================

def get_best_ai():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, price, floor, sales, listings
    FROM nfts
    ORDER BY timestamp DESC
    LIMIT 30
    """)

    rows = cursor.fetchall()
    conn.close()

    results = []

    for r in rows:
        nft = {
            "name": r[0],
            "price": r[1],
            "floor": r[2],
            "sales": r[3],
            "listings": r[4],
        }

        score = predict_nft(nft)

        if score > 0.7:
            results.append((nft["name"], round(score, 2)))

    return sorted(results, key=lambda x: x[1], reverse=True)[:5]

# ================= COLLECTOR =================

def collector():
    while True:
        nfts = fetch_nfts()
        save_nfts(nfts)
        train_model()
        time.sleep(FETCH_INTERVAL)

# ================= TELEGRAM =================

keyboard = ReplyKeyboardMarkup(
    [
        ["🔥 Ликвидные", "💰 Лучшие AI"],
        ["📊 Статистика"]
    ],
    resize_keyboard=True
)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Ликвидные" in text:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT name, sales FROM nfts
        ORDER BY sales DESC LIMIT 5
        """)

        rows = cursor.fetchall()
        conn.close()

        msg = "🔥 Топ ликвидные:\n\n"
        for r in rows:
            msg += f"{r[0]} | sales: {r[1]}\n"

        await update.message.reply_text(msg)

    elif "Лучшие AI" in text:
        data = get_best_ai()

        msg = "🤖 AI рекомендует:\n\n"
        for d in data:
            msg += f"{d[0]} | score: {d[1]}\n"

        await update.message.reply_text(msg)

    elif "Статистика" in text:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM nfts")
        count = cursor.fetchone()[0]
        conn.close()

        await update.message.reply_text(f"📊 Собрано NFT: {count}")

    else:
        await update.message.reply_text("Выбери кнопку 👇", reply_markup=keyboard)

# ================= MAIN =================

def main():
    init_db()

    t = threading.Thread(target=collector)
    t.daemon = True
    t.start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT, handle))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()