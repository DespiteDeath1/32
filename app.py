# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request
import logging
from datetime import datetime
import requests
import random
from cachetools import TTLCache

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("main")

app = Flask(__name__)

#settings
CACHE_TIMINGS = {
    'ETH': 54, 
    'BTC': 60,
    'SOL': 66,
    'BNB': 70,
    'ARB': 75
}

price_caches = {
    symbol: TTLCache(maxsize=1, ttl=timing) 
    for symbol, timing in CACHE_TIMINGS.items()
}

TIMEFRAME_RANGES = {
    "10m": (-0.15, 0.15),
    "20m": (-0.3, 0.3),
    "1d": {
        "min_change": 0.2,
        "range": (-2, 2)
    }
}

TOPIC_MAP = {
    1: ("ETH", "10m"),
    2: ("ETH", "1d"),
    3: ("BTC", "10m"),
    4: ("BTC", "1d"),
    5: ("SOL", "10m"),
    6: ("SOL", "1d"),
    7: ("ETH", "20m"),
    8: ("BNB", "20m"),
    9: ("ARB", "20m")
}

def get_current_price(symbol):
    cache = price_caches[symbol]
    cache_key = f"{symbol}_price"
    
    if cache_key in cache:
        cached_price = cache[cache_key]
        logger.debug(f"Using cached price for {symbol}: {cached_price}")
        return cached_price
    
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            current_price = float(response.json()["price"])
            cache[cache_key] = current_price
            logger.info(f"[API REQUEST] New price fetched for {symbol}: {current_price} (will be cached for {CACHE_TIMINGS[symbol]} seconds)")
            return current_price
        else:
            if cache_key in cache:
                old_price = cache[cache_key]
                logger.warning(f"Failed to get new price for {symbol}, using last known price: {old_price}")
                return old_price
            raise Exception(f"Failed to get price for {symbol}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        if cache_key in cache:
            old_price = cache[cache_key]
            logger.warning(f"Error fetching price for {symbol}, using last known price: {old_price}. Error: {str(e)}")
            return old_price
        raise Exception(f"Failed to get price and no cached price available for {symbol}: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {str(e)}")
        raise

def generate_smart_daily_prediction(current_price: float, worker_id: int) -> float:
    current_minute = datetime.now().replace(second=0, microsecond=0).timestamp()
    random.seed(current_minute + worker_id)
    
    direction = 1 if random.random() > 0.5 else -1
    
    min_change = TIMEFRAME_RANGES["1d"]["min_change"]
    min_range, max_range = TIMEFRAME_RANGES["1d"]["range"]
    
    if direction > 0:
        change_percent = random.uniform(min_change, max_range)
    else:
        change_percent = random.uniform(min_range, -min_change)
    
    predicted_price = current_price * (1 + change_percent / 100)
    logger.info(f"Daily prediction | Worker {worker_id} | Base price: {current_price:.2f} | "
                f"Change: {change_percent:+.3f}% | Predicted: {predicted_price:.2f}")
    
    return predicted_price

def generate_prediction(current_price: float, timeframe: str, worker_id: int) -> float:
    current_minute = datetime.now().replace(second=0, microsecond=0).timestamp()
    random.seed(current_minute + worker_id)
    
    if timeframe == "1d":
        return generate_smart_daily_prediction(current_price, worker_id)
    
    min_change, max_change = TIMEFRAME_RANGES[timeframe]
    change_percent = random.uniform(min_change, max_change)
    predicted_price = current_price * (1 + change_percent / 100)
    
    logger.info(f"Worker {worker_id} | {timeframe} prediction | Base price: {current_price:.2f} | "
                f"Change: {change_percent:+.3f}% | Predicted: {predicted_price:.2f}")
    return predicted_price

@app.route("/inference/<int:topic_id>")
def get_inference(topic_id):
    if topic_id not in TOPIC_MAP:
        return jsonify({"error": "Unsupported topic ID"}), 400

    try:
        worker_id = int(request.args.get('worker_id', 0))
        token, timeframe = TOPIC_MAP[topic_id]
        
        current_price = get_current_price(token)
        prediction = generate_prediction(current_price, timeframe, worker_id)
        
        return str(prediction)

    except Exception as e:
        logger.error(f"Error during inference: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health_check():
    status = {
        "status": "healthy",
        "cached_prices": {}
    }
    
    for symbol in CACHE_TIMINGS.keys():
        cache = price_caches[symbol]
        cache_key = f"{symbol}_price"
        if cache_key in cache:
            status["cached_prices"][symbol] = {
                "price": cache[cache_key],
            }
    
    return jsonify(status)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)