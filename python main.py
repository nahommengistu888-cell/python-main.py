import MetaTrader5 as mt5
import pandas as pd
import time

# ---------------- Settings ----------------
BASE_SYMBOL = "XAUUSD"            # Exness may add a suffix like 'm'
TIMEFRAME = mt5.TIMEFRAME_M1
LOT = 0.01
MAGIC = 202611
EMA_FAST, EMA_SLOW = 9, 21
RSI_PERIOD = 14
ATR_PERIOD = 14
SL_ATR = 1.5
TP_ATR = 2.0
MAX_SPREAD_POINTS = 50            # Adjust after checking the demo spread
MAX_DAILY_LOSS_PCT = 3.0

SYMBOL = None                     # Filled automatically in main()

# ---------------- Helpers ----------------
def find_symbol():
    for s in mt5.symbols_get():
        if s.name.upper().startswith(BASE_SYMBOL):
            return s.name
    return None

def get_filling_mode():
    info = mt5.symbol_info(SYMBOL)
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN

# ---------------- Indicators ----------------
def get_data(n=200):
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df

def add_indicators(df):
    df["ema_f"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_s"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()
    return df

# ---------------- Signal ----------------
def get_signal(df):
    prev, last = df.iloc[-3], df.iloc[-2]
    cross_up = prev.ema_f <= prev.ema_s and last.ema_f > last.ema_s
    cross_dn = prev.ema_f >= prev.ema_s and last.ema_f < last.ema_s

    if cross_up and 50 < last.rsi < 70:
        return "BUY", last.atr
    if cross_dn and 30 < last.rsi < 50:
        return "SELL", last.atr
    return None, last.atr

# ---------------- Orders ----------------
def has_open_position():
    pos = mt5.positions_get(symbol=SYMBOL)
    return any(p.magic == MAGIC for p in pos) if pos else False

def daily_loss_exceeded(start_balance):
    acc = mt5.account_info()
    loss_pct = (start_balance - acc.equity) / start_balance * 100
    return loss_pct >= MAX_DAILY_LOSS_PCT

def send_order(side, atr):
    info = mt5.symbol_info(SYMBOL)
    tick = mt5.symbol_info_tick(SYMBOL)
    spread_points = (tick.ask - tick.bid) / info.point
    if spread_points > MAX_SPREAD_POINTS:
        print(f"Spread too high ({spread_points:.0f}), order not sent")
        return

    if side == "BUY":
        price = tick.ask
        sl = price - SL_ATR * atr
        tp = price + TP_ATR * atr
        otype = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + SL_ATR * atr
        tp = price - TP_ATR * atr
        otype = mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT,
        "type": otype,
        "price": price,
        "sl": round(sl, info.digits),
        "tp": round(tp, info.digits),
        "deviation": 20,
        "magic": MAGIC,
        "comment": "gold-scalper",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_mode(),
    }
    result = mt5.order_send(request)
    if result is None:
        print("order_send returned None:", mt5.last_error())
    elif result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order FAILED: retcode={result.retcode}, comment={result.comment}")
    else:
        print("Order placed successfully, ticket:", result.order)

# ---------------- Main ----------------
def main():
    global SYMBOL
    if not mt5.initialize():
        print("Could not connect to MT5:", mt5.last_error())
        return

    SYMBOL = find_symbol()
    if SYMBOL is None:
        print("No XAUUSD symbol found. Check Market Watch in MT5.")
        mt5.shutdown()
        return
    if not mt5.symbol_select(SYMBOL, True):
        print("Could not select symbol:", SYMBOL)
        mt5.shutdown()
        return
    print("Using symbol:", SYMBOL)

    account = mt5.account_info()
    if account is None:
        print("No account info. Log in to your demo account in MT5.")
        mt5.shutdown()
        return
    start_balance = account.balance
    last_bar_time = None
    print("Scalper started...")

    try:
        while True:
            if daily_loss_exceeded(start_balance):
                print("Daily loss limit reached. Stopped.")
                break

            df = get_data()
            if df is None:
                print("No price data:", mt5.last_error())
                time.sleep(5)
                continue
            df = add_indicators(df)
            bar_time = df.iloc[-2]["time"]

            if bar_time != last_bar_time:
                last_bar_time = bar_time
                if not has_open_position():
                    side, atr = get_signal(df)
                    if side and atr > 0:
                        print(f"{side} signal at {bar_time}")
                        send_order(side, atr)

            time.sleep(5)
    except KeyboardInterrupt:
        print("Stopped manually")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
