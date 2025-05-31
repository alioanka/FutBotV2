import pandas as pd
import numpy as np

def calculate_obv(df, period=14):
    """
    Calculate On-Balance Volume (OBV)
    """
    obv = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
    obv_sma = obv.rolling(window=period).mean()
    
    return obv, obv_sma