import pandas as pd
from .atr import calculate_atr

def calculate_supertrend(df, period=10, multiplier=3):
    """
    Calculate SuperTrend indicator
    """
    atr = calculate_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)
    
    supertrend = [upper_band.iloc[0]]
    direction = [1]
    
    for i in range(1, len(df)):
        close = df['close'].iloc[i]
        prev_supertrend = supertrend[-1]
        
        if close > prev_supertrend:
            direction.append(1)
            supertrend.append(max(lower_band.iloc[i], prev_supertrend))
        else:
            direction.append(-1)
            supertrend.append(min(upper_band.iloc[i], prev_supertrend))
    
    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index)