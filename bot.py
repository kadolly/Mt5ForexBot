import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

# ---- CONFIG ----
RISK_PER_TRADE = 0.01  # 1% risk per trade
MAX_DAILY_LOSS = 0.05  # 5% daily loss max
MAX_CONCURRENT_TRADES = 2
STOP_LOSS_PIPS = 5
TAKE_PROFIT_PIPS = 7
MIN_ATR = 0.0003  # avoid dead sessions
TRADE_SESSION = (7, 17)  # London/New York (UTC hours)
SYMBOL = 'EURUSD'

def initialize_mt5():
    if not mt5.initialize():
        print("MT5 initialization failed")
        return False
    return True

def get_tick_data(symbol, n=500, timeframe=mt5.TIMEFRAME_M1):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    df = pd.DataFrame(rates)
    if not df.empty:
        df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_atr(df, period=14):
    df['H-L'] = df['high'] - df['low']
    df['H-PC'] = abs(df['high'] - df['close'].shift(1))
    df['L-PC'] = abs(df['low'] - df['close'].shift(1))
    tr = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    return tr.rolling(window=period).mean().iloc[-1]

def check_scalp_signal(symbol):
    df1 = get_tick_data(symbol, 50, mt5.TIMEFRAME_M1)
    df5 = get_tick_data(symbol, 50, mt5.TIMEFRAME_M5)
    if df1.empty or df5.empty:
        return None

    # ATR volatility filter
    atr = calculate_atr(df1)
    if atr < MIN_ATR:
        return None

    # Multi-timeframe: EMA trend
    df1['ema'] = df1['close'].ewm(span=8).mean()
    df5['ema'] = df5['close'].ewm(span=8).mean()
    fast_trend = df1['close'].iloc[-1] > df1['ema'].iloc[-1]
    slow_trend = df5['close'].iloc[-1] > df5['ema'].iloc[-1]

    # Simple momentum
    momentum = df1['close'].iloc[-1] - df1['close'].iloc[-5]

    # Only trade with trend, after small pullback
    if fast_trend and slow_trend and momentum > 0.0002:
        return 'BUY'
    elif not fast_trend and not slow_trend and momentum < -0.0002:
        return 'SELL'
    return None

def calc_lot_size(symbol, stop_loss_pips, risk_per_trade):
    acc_info = mt5.account_info()
    balance = acc_info.balance
    price = mt5.symbol_info_tick(symbol).ask
    one_pip = 0.0001
    risk_amount = balance * risk_per_trade
    lot_size = risk_amount / (stop_loss_pips * one_pip * 100000)
    return max(0.01, round(lot_size, 2))

def execute_order(symbol, action, lot_size, stop_loss_pips, take_profit_pips, deviation=10):
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if action == 'BUY' else tick.bid
    point = mt5.symbol_info(symbol).point

    if action == 'BUY':
        sl = price - stop_loss_pips * point * 10
        tp = price + take_profit_pips * point * 10
        order_type = mt5.ORDER_TYPE_BUY
    else:
        sl = price + stop_loss_pips * point * 10
        tp = price - take_profit_pips * point * 10
        order_type = mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": 20240629,
        "comment": f"SCALP-{action}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    print(f"Trade executed: {action} {lot_size} lots at {price}, SL: {sl}, TP: {tp}")
    print(result)
    return result

def manage_positions(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return

    # Risk: close all if too many open
    if len(positions) > MAX_CONCURRENT_TRADES:
        for pos in positions:
            close_position(pos)

    # Risk: daily loss limit
    today = datetime.now().date()
    closed_orders = mt5.history_deals_get(datetime(today.year, today.month, today.day), datetime.now())
    daily_loss = sum([o.profit for o in closed_orders if o.entry == 1])
    if daily_loss < -MAX_DAILY_LOSS * mt5.account_info().balance:
        print("Max daily loss hit. Stopping trading.")
        for pos in positions:
            close_position(pos)

def close_position(position):
    symbol = position.symbol
    lot = position.volume
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = mt5.symbol_info_tick(symbol).bid if order_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(symbol).ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "deviation": 10,
        "magic": 20240629,
        "comment": "SCALP-CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    mt5.order_send(request)

def run_scalper(symbol=SYMBOL):
    if not initialize_mt5():
        return

    print(f"Starting scalper on {symbol}...")

    try:
        while True:
            now = datetime.utcnow()
            if not (TRADE_SESSION[0] <= now.hour <= TRADE_SESSION[1]):
                print("Out of trading session.")
                time.sleep(60)
                continue

            manage_positions(symbol)
            signal = check_scalp_signal(symbol)
            if signal:
                lot = calc_lot_size(symbol, STOP_LOSS_PIPS, RISK_PER_TRADE)
                execute_order(symbol, signal, lot, STOP_LOSS_PIPS, TAKE_PROFIT_PIPS)
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nShutting down scalper...")
    finally:
        mt5.shutdown()

def run_backtest(symbol=SYMBOL, start_days_ago=30):
    if not initialize_mt5():
        return

    print(f"Backtesting {symbol}...")
    df = get_tick_data(symbol, n=5000)
    wins = 0
    losses = 0
    trades = []
    for i in range(20, len(df)):
        sub_df = df.iloc[i-20:i]
        price = sub_df['close'].iloc[-1]
        signal = check_scalp_signal(symbol)
        if signal == 'BUY':
            entry = price
            exit = entry + TAKE_PROFIT_PIPS * 0.0001
            if sub_df['high'].max() >= exit:
                wins += 1
            else:
                losses += 1
        elif signal == 'SELL':
            entry = price
            exit = entry - TAKE_PROFIT_PIPS * 0.0001
            if sub_df['low'].min() <= exit:
                wins += 1
            else:
                losses += 1
    print(f"Backtest completed: Wins: {wins}, Losses: {losses}, Win rate: {wins/(wins+losses):.2%}")
    mt5.shutdown()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        run_backtest()
    else:
        run_scalper()
