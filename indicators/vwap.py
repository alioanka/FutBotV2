import pandas as pd

def calculate_vwap(df, period=20):
    """
    Calculate Volume Weighted Average Price (VWAP)
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).rolling(window=period).sum() / df['volume'].rolling(window=period).sum()
    
    return vwap