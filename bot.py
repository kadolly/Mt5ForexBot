import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import time

# Initialize MT5 connection
def initialize_mt5():
    if not mt5.initialize():
        print("MT5 initialization failed")
        return False
    return True

# Ultra-fast market data fetching
def get_tick_data(symbol, n=100):
    ticks = mt5.copy_ticks_from(symbol, datetime.now(), n, mt5.COPY_TICKS_ALL)
    return pd.DataFrame(ticks)

# Scalping strategy (EMA + Tick Momentum)
def check_scalp_signal(symbol):
    df = get_tick_data(symbol)
    
    # Micro-EMA calculation (3-period)
    df['micro_ema'] = df['ask'].ewm(span=3).mean()
    
    # Tick momentum
    df['momentum'] = df['ask'].diff(3)
    
    # Entry conditions
    last = df.iloc[-1]
    if (last['ask'] > last['micro_ema'] and 
        last['momentum'] > 0.0002 and 
        df['ask'][-5:].std() < 0.0005):
        return 'BUY'
    elif (last['ask'] < last['micro_ema'] and 
          last['momentum'] < -0.0002 and 
          df['ask'][-5:].std() < 0.0005):
        return 'SELL'
    return None

# Lightning-fast order execution
def execute_order(symbol, action, lot_size=0.1, deviation=10):
    tick = mt5.symbol_info_tick(symbol)
    order_type = mt5.ORDER_TYPE_BUY if action == 'BUY' else mt5.ORDER_TYPE_SELL
    price = tick.ask if action == 'BUY' else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "deviation": deviation,
        "magic": 202406,
        "comment": f"SCALP-{action}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    return mt5.order_send(request)

# Micro-position management
def manage_positions(symbol):
    positions = mt5.positions_get(symbol=symbol)
    for pos in positions:
        current_profit = pos.profit
        if abs(current_profit) >= 0.5:  # Close at 50 cent profit/loss
            close_position(pos)

def close_position(position):
    tick = mt5.symbol_info_tick(position.symbol)
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.ask if order_type == mt5.ORDER_TYPE_SELL else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": order_type,
        "price": price,
        "deviation": 10,
        "magic": 202406,
        "comment": "SCALP-CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    mt5.order_send(request)

# Main execution loop
def run_scalper(symbol='EURUSD'):
    if not initialize_mt5():
        return
    
    print(f"Starting scalper on {symbol}...")
    
    try:
        while True:
            start_time = time.perf_counter()
            
            # Ultra-fast cycle
            signal = check_scalp_signal(symbol)
            if signal:
                execute_order(symbol, signal)
            
            manage_positions(symbol)
            
            # Precision timing (50ms cycles)
            cycle_time = (time.perf_counter() - start_time) * 1000
            if cycle_time < 50:
                time.sleep((50 - cycle_time) / 1000)
                
    except KeyboardInterrupt:
        print("\nShutting down scalper...")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    run_scalper()
