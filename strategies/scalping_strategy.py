import numpy as np
import pandas as pd
from typing import Dict, Optional
from indicators.vwap import calculate_vwap
from indicators.obv import calculate_obv

class ScalpingStrategy:
    def __init__(self, client, config, logger):
        self.client = client
        self.config = config
        self.logger = logger
        self.strategy_config = config['strategy']
        
        # Scalping-specific parameters
        self.short_term_period = 5
        self.long_term_period = 15
        self.obv_threshold = 1.5
        self.min_price_movement = 0.002  # 0.2%
        
    async def analyze_market(self, symbol: str) -> Optional[Dict]:
        """Generate scalping signals for a symbol"""
        try:
            # Get recent price data
            df = await self.client.get_klines(symbol, "1m", limit=100)
            if len(df) < self.long_term_period:
                return None
                
            # Calculate indicators
            df['vwap'] = calculate_vwap(df, self.short_term_period)
            df['obv'], df['obv_sma'] = calculate_obv(df, self.long_term_period)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # Scalping signal conditions
            long_signal = (
                latest['close'] > latest['vwap'] and
                latest['obv'] > latest['obv_sma'] * self.obv_threshold and
                (latest['close'] - latest['vwap']) / latest['vwap'] > self.min_price_movement
            )
            
            short_signal = (
                latest['close'] < latest['vwap'] and
                latest['obv'] < latest['obv_sma'] / self.obv_threshold and
                (latest['vwap'] - latest['close']) / latest['vwap'] > self.min_price_movement
            )
            
            if not (long_signal or short_signal):
                return None
                
            # Calculate position size
            balance = await self.client.get_account_balance()
            usdt_balance = balance.get('USDT', 0)
            
            if usdt_balance <= 0:
                return None
                
            leverage = self._calculate_leverage(df)
            risk_amount = usdt_balance * self.config['trading']['risk_per_trade']
            position_size = (risk_amount * leverage) / latest['close']
            
            # Calculate stop loss and take profit
            atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
            stop_loss, take_profit = self._calculate_levels(
                latest['close'],
                long_signal,
                atr
            )
            
            return {
                'symbol': symbol,
                'signal': 'BUY' if long_signal else 'SELL',
                'price': latest['close'],
                'size': position_size,
                'leverage': leverage,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'strategy': 'scalping'
            }
            
        except Exception as e:
            self.logger.error(f"Scalping analysis error for {symbol}: {str(e)}")
            return None
            
    def _calculate_leverage(self, df: pd.DataFrame) -> int:
        """Calculate dynamic leverage based on volatility"""
        volatility = df['close'].pct_change().std()
        
        if volatility < 0.001:  # Very low volatility
            return self.config['trading']['max_leverage']
        elif volatility < 0.003:  # Moderate volatility
            return int(self.config['trading']['max_leverage'] * 0.7)
        else:  # High volatility
            return self.config['trading']['min_leverage']
            
    def _calculate_levels(self, price: float, is_long: bool, atr: float) -> tuple:
        """Calculate stop loss and take profit levels"""
        if is_long:
            stop_loss = price - (atr * 1.2)
            take_profit = price + (atr * 0.8)  # Smaller TP for scalping
        else:
            stop_loss = price + (atr * 1.2)
            take_profit = price - (atr * 0.8)
            
        return stop_loss, take_profit