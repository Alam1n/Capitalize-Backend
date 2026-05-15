import requests
import sqlite3
import os
import time
import yfinance as yf
from textblob import TextBlob
from dotenv import load_dotenv

# 1. SETUP & PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
DB_PATH = os.path.join(BASE_DIR, 'capitalz_expert.db')
FINNHUB_KEY = os.getenv("finnhub_api_key")

def get_proxy():
    if "/home/AlaminAPI" in os.path.abspath(__file__):
        return {"http": "http://proxy.server:3128", "https": "http://proxy.server:3128"}
    return None


# --- FUNCTION 2: MARKET SENTIMENT (YFINANCE) ---
def update_macro_sentiment():
    print("📈 Updating Market Sentiment (Risk-On/Risk-Off)...")
    tickers = ["^VIX", "SPY", "^TNX", "^NDX", "^GSPC", "^DJI"]
    
    try:
        data = yf.download(tickers, period="2d", progress=False)['Close']
        
        vix = data['^VIX'].iloc[-1]
        spy_change = (data['SPY'].iloc[-1] / data['SPY'].iloc[-2]) - 1
        yield_change = data['^TNX'].iloc[-1] - data['^TNX'].iloc[-2]

        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM manual_entries WHERE impact = 'sentiment'")

            mood = "RISK_OFF" if (vix > 22 or spy_change < -0.015) else "RISK_ON"

            if mood == "RISK_ON":
                for asset in ['AUD', 'NZD', 'GBP', 'CAD', 'EUR']:
                    cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES (?, 'Risk-On Flow', 3, 'sentiment')", (asset,))
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('JPY', 'Safe Haven Outflow', -2, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('CHF', 'Safe Haven Outflow', -1, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('NAS100', 'Risk-On: Tech Lead', 5, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('US500', 'Risk-On: Broad Demand', 4, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('US30', 'Risk-On: Blue Chip', 3, 'sentiment')")
            else:
                for asset in ['AUD', 'NZD', 'GBP', 'CAD', 'EUR']:
                    cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES (?, 'Risk-Off Pressure', -3, 'sentiment')", (asset,))
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('JPY', 'Risk-Off Haven', 5, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('CHF', 'Risk-Off Haven', 3, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('NAS100', 'Risk-Off: Tech Selling', -6, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('US500', 'Risk-Off: Liquidating', -4, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('US30', 'Risk-Off: Dow Drop', -3, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('XAU', 'Gold: Haven Demand', 4, 'sentiment')")

            if yield_change > 0.03:
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('USD', 'Yield Support', 4, 'sentiment')")
                cursor.execute("INSERT INTO manual_entries (currency, event_name, points, impact) VALUES ('XAU', 'Yield Pressure', -4, 'sentiment')")
            
            conn.commit()
            print(f"✅ Sentiment Complete. Mood: {mood}")
    except Exception as e:
        print(f"❌ Sentiment Update Failed: {e}")


# --- FUNCTION 1: FOREX FACTORY (Calendar & Scores) ---
def sync_forex_factory():
    print("🚀 Syncing Global Economic Feed (Forex Factory)...")
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, proxies=get_proxy(), timeout=15)
        events = r.json()
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Clean only upcoming calendar entries, keep the historic scoring logs
            cursor.execute("DELETE FROM manual_entries WHERE impact LIKE 'calendar_%'")

            for ev in events:
                # 🎯 CAPTURING BOTH HIGH AND MEDIUM
                if ev['impact'] in ['High', 'Medium']:
                    currency = ev['country']
                    title = f"[FF] {ev['title']}"
                    impact_tag = f"calendar_{ev['impact'].lower()}" # 'calendar_high' or 'calendar_medium'
                    
                    # Store the event
                    cursor.execute('''
                        INSERT INTO manual_entries (currency, event_name, actual, forecast, impact, points)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (currency, title, ev.get('actual',''), ev.get('forecast',''), impact_tag, 0))
            
            conn.commit()
            print(f"✅ Calendar Synced (High & Medium events captured).")
    except Exception as e:
        print(f"❌ FF Sync Failed: {e}") 
        

# --- FUNCTION 2: NEWS FEED (Finnhub) ---
def sync_news():
    print("📡 Fetching Global News Headlines (Finnhub)...")
    url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_KEY}"
    
    # Retry logic: Try 3 times before giving up
    for attempt in range(3):
        try:
            # Increased timeout to (connect=5s, read=30s)
            r = requests.get(url, proxies=get_proxy(), timeout=(5, 30))
            r.raise_for_status()
            articles = r.json()
            
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM manual_entries WHERE impact = 'news_feed'")
                for art in articles[:10]:
                    title = art.get('headline', 'No Title')
                    sentiment = round(TextBlob(title).sentiment.polarity, 3)
                    # STORE THE FULL TITLE - DON'T CUT IT HERE
                    cursor.execute("""
                        INSERT INTO manual_entries (currency, event_name, actual, impact, points) 
                        VALUES (?, ?, ?, ?, ?)
                    """, ('MACRO', title, sentiment, 'news_feed', 0))
                conn.commit()
            print("✅ News Feed Updated successfully.")
            return # Exit function on success
            
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout):
            print(f"⚠️ Timeout on attempt {attempt+1}... retrying.")
            time.sleep(2) # Short wait before retry
        except Exception as e:
            print(f"❌ News Error: {e}")
            break # Exit on non-timeout errors
        
# --- FUNCTION 3: METALS & INDICES (Yahoo Finance) ---
def sync_metals_and_indices():
    print("💎 Syncing Metals & Indices Prices...")
    # XAU=F (Gold), SI=F (Silver), CL=F (Oil)
    tickers = {"XAU": "GC=F", "XAG": "SI=F", "NAS100": "^NDX", "US500": "^GSPC", "US30": "^DJI"}
    try:
        data = yf.download(list(tickers.values()), period="2d", progress=False)['Close']
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Clean only the price-action points, not the sentiment points
            cursor.execute("DELETE FROM manual_entries WHERE event_name = 'Price Action'")
            
            for asset, ticker in tickers.items():
                change = (data[ticker].iloc[-1] / data[ticker].iloc[-2]) - 1
                points = 10 if change > 0.005 else (-10 if change < -0.005 else 0)
                cursor.execute("INSERT INTO manual_entries (currency, event_name, actual, points, impact) VALUES (?,?,?,?,?)",
                               (asset, 'Price Action', round(data[ticker].iloc[-1], 2), points, 'technical'))
            conn.commit()
        print("✅ Metals & Indices Synced.")
    except Exception as e: print(f"❌ Metals Error: {e}")

# --- MASTER RUNNER ---
def run_all():
    sync_forex_factory()
    sync_metals_and_indices()
    sync_news()
    update_macro_sentiment()
    print("\n🏁 FULL MARKET ENGINE SYNC COMPLETE.")

if __name__ == "__main__":
    run_all()