from capitalize_auto import run_all
from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import pandas as pd
import subprocess
import requests
from datetime import datetime
import os 
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required



app = Flask(__name__)
CORS(app) # Allows React to access the API

bcrypt = Bcrypt(app)
# Fallback string ensures local execution never breaks if .env isn't set up
app.config['JWT_SECRET_KEY'] = os.getenv("JWT_SECRET_KEY", "1c168dc16f8d989dc7982e58fc352429")
jwt = JWTManager(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'capitalz_expert.db')

@app.route('/api/login', methods=['POST'])
def login():
    
    data = request.json
    username = data.get('username')
    password = data.get('password')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and bcrypt.check_password_hash(user[1], password):
        # Successful Login
        access_token = create_access_token(identity=str(user[0]))
        return jsonify(access_token=access_token), 200
    
    return jsonify({"msg": "Invalid username or password"}), 401



def get_score_map():
    
    all_assets = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF', 'XAU', 'XAG', 'NAS100', 'US500', 'US30']
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT currency, SUM(points) as score FROM manual_entries WHERE timestamp > DATETIME('now', '-7 days') GROUP BY currency"
    df = pd.read_sql_query(query, conn)
    print("--- RAW DATA FROM DB ---")
    print(df) # Check if EUR, GBP, etc. are even in this list!
    conn.close()

    base_df = pd.DataFrame(all_assets, columns=['currency'])
    final_df = pd.merge(base_df, df, on='currency', how='left').fillna(0)
    return dict(zip(final_df.currency, final_df.score))



@app.route('/api/dashboard', methods=['GET']) 
@jwt_required()
def get_dashboard():
    run_all()
    scores = get_score_map()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    set

    # Fetch News - Explicitly naming keys and ensuring floats
    cursor.execute("SELECT event_name, actual FROM manual_entries WHERE impact = 'news_feed' ORDER BY timestamp DESC LIMIT 5")
    news_feed = []
    for row in cursor.fetchall():
        try:
            sent_val = float(row[1]) if row[1] else 0.0
        except:
            sent_val = 0.0
            
        news_feed.append({
            "title": str(row[0]), 
            "sentiment": sent_val
        })
        
    # Fetch Calendar (Distinct events, High/Medium only)
    cursor.execute("""
        SELECT DISTINCT event_name, impact 
        FROM manual_entries 
        WHERE impact LIKE 'calendar_%' 
        ORDER BY timestamp DESC LIMIT 8
    """)
    calendar = [{"event": row[0], "rank": row[1].split('_')[1]} for row in cursor.fetchall()]

    conn.close()
    def get_bias(s):
        if s >= 10: return "BULLISH", "signal-buy"
        if s <= -10: return "BEARISH", "signal-sell"
        return "NEUTRAL", "signal-neutral"

    # 1. Currencies (Existing logic)
    currencies = []
    for asset in ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']:
        s = int(scores.get(asset, 0))
        if s >= 50: status, sc = "STRONG BUY", "signal-strong-buy"
        elif s >= 10: status, sc = "BUY", "signal-buy"
        elif s <= -50: status, sc = "STRONG SELL", "signal-strong-sell"
        elif s <= -10: status, sc = "SELL", "signal-sell"
        else: status, sc = "NEUTRAL", "signal-neutral"
        currencies.append({"asset": asset, "score": s, "status": status, "signal_class": sc})

    # 2. Metals
    gold_status, gold_class = get_bias(scores.get('XAU', 0))
    silver_status, silver_class = get_bias(scores.get('XAG', 0))
    
    # 3.  Indices Bias
    nas_status, nas_class = get_bias(scores.get('NAS100', 0))
    sp_status, sp_class = get_bias(scores.get('US500', 0))
    dow_status, dow_class = get_bias(scores.get('US30', 0))

    # 4. Pair Bias
    pairs = []
    for base, quote in [("AUD", "USD"), ("EUR", "USD"), ("GBP", "USD"), ("USD", "JPY")]:
        diff = scores.get(base, 0) - scores.get(quote, 0)
        pairs.append({
            "pair": f"{base}{quote}",
            "score": int(diff),
            "bias": "STRONG BULLISH" if diff >= 10 else "STRONG BEARISH" if diff <= -10 else "NEUTRAL"
        })

    # --- 5. ADVANCED TACTICAL ENGINE ---
    recommendations = []
    
    # Pull scores for comparison
    usd_s = scores.get('USD', 0)
    jpy_s = scores.get('JPY', 0) # Safe Haven Proxy
    aud_s = scores.get('AUD', 0) # Risk Proxy
    xau_s = scores.get('XAU', 0)
    nas_s = scores.get('NAS100', 0)

    # A. CONFLICT DETECTION (The "Edge" Feature)
    # If USD is strong, Gold should be weak. If both are strong, it's a trap.
    if usd_s > 20 and xau_s > 20:
        recommendations.append("⚠️ CONFLICT: Both USD and Gold are rising. Market is uncertain—reduce position sizes.")
    
    # B. THE "NO TRADE ZONE"
    all_scores = [abs(s) for s in scores.values()]
    if max(all_scores) < 10:
        recommendations.append("🛑 NO-TRADE ZONE: Volatility is too low. Sitting on hands is a position.")

    # C. TODAY'S FOCUS (Strongest vs Weakest)
    # Sort currencies to find the absolute best pair
    currency_list = {k: v for k, v in scores.items() if k in ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']}
    strongest = max(currency_list, key=currency_list.get)
    weakest = min(currency_list, key=currency_list.get)
    
    if scores[strongest] - scores[weakest] > 40:
        recommendations.append(f"🎯 TOP FOCUS: {strongest}{weakest} represents the strongest trend today.")

    # D. NARRATIVE LOGIC (Indices vs Rates)
    if nas_s < -20 and usd_s > 20:
        recommendations.append("📉 TECH PRESSURE: Rising USD/Rates are choking NASDAQ. Look for sell-side setups.")

    if not recommendations:
        recommendations.append("⚖️ Ranging markets. Scalp within levels or wait for US session open.")
    # Confidence Calculation
    conf = 5
    if usd_s > 20 and xau_s < -10: conf += 3
    if scores.get('JPY', 0) < 0 and aud_s > 0: conf += 2

   
    return jsonify({
        "confidence": min(conf, 10),
        "currencies": currencies,
        "pairs": pairs,
        "news": news_feed,
        "calendar": calendar,
        "recommendations": recommendations,
        "metals": {
            "gold": {"score": int(scores.get('XAU', 0)), "status": gold_status, "class": gold_class},
            "silver": {"score": int(scores.get('XAG', 0)), "status": silver_status, "class": silver_class}
        },
        "indices": {
            "nas100": {"score": int(scores.get('NAS100', 0)), "status": nas_status, "class": nas_class},
            "sp500": {"score": int(scores.get('US500', 0)), "status": sp_status, "class": sp_class},
            "us30": {"score": int(scores.get('US30', 0)), "status": dow_status, "class": dow_class}
        },
        "recommendations": recommendations,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000)) 
    app.run(host='0.0.0.0', port=port)
