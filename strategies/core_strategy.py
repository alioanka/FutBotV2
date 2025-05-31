import pandas as pd
import numpy as np
from datetime import datetime
from indicators.atr import calculate_atr
from indicators.supertrend import calculate_supertrend
from indicators.rsi import calculate_rsi
from indicators.vwap import calculate_vwap
from indicators.obv import calculate_obv

class CoreStrategy:
    def __init__(self, client, config, logger):
        self.client = client
        self.config = config
        self.logger = logger
        self.strategy_config = config['strategy']
        
        # Initialize indicators
        self.atr_period = self.strategy_config['atr_period']
        self.supertrend_period = self.strategy_config['supertrend_period']
        self.supertrend_multiplier = self.strategy_config['supertrend_multiplier']
        self.rsi_period = self.strategy_config['rsi_period']
        self.rsi_overbought = self.strategy_config['rsi_overbought']
        self.rsi_oversold = self.strategy_config['rsi_oversold']
        self.vwap_period = self.strategy_config['vwap_period']
        self.obv_period = self.strategy_config['obv_period']
        
        self.logger.info("CoreStrategy initialized")

    async def analyze_market(self, symbol):
        self.logger.info(f"Analyzing {symbol}...")
        try:
            if 'pairs' not in self.config:
                raise ValueError("Missing pairs configuration")
                
            timeframes = self.config['pairs'].get('timeframes', ["1m"])
            signals = []
            
            for tf in timeframes:
                try:
                    df = await self.client.get_klines(symbol, tf, limit=100)
                    if df is None or len(df) < 50:
                        self.logger.warning(f"Insufficient data for {symbol} on {tf}")
                        continue
                        
                    signal = await self._analyze_timeframe(symbol, df, tf)
                    if signal:
                        signals.append(signal)
                        self.logger.info(f"{symbol} {tf} signal: {signal['signal']} (strength: {signal['strength']:.2f})")
                    else:
                        self.logger.info(f"No signal for {symbol} on {tf}")

                except Exception as e:
                    self.logger.error(f"Error analyzing {symbol} on {tf}: {str(e)}")

            if not signals:
                self.logger.info(f"No valid signals for {symbol}")
                return None
                
            consolidated = self._consolidate_signals(signals)
            self.logger.info(f"Final signal for {symbol}: {consolidated['signal']} (strength: {consolidated['strength']:.2f})")
            
            # Rest of your analysis code... 

            # Calculate position size and risk
            balance = await self.client.get_account_balance()
            usdt_balance = balance.get('USDT', 0)
            
            if usdt_balance <= 0:
                return None
                
            # Calculate volatility-adjusted leverage
            volatility = consolidated['atr'] / consolidated['price']
            leverage = self._calculate_leverage(volatility)
            
            # Calculate position size
            risk_amount = usdt_balance * self.config['trading']['risk_per_trade']
            # In analyze_market method:
            position_size = (risk_amount * leverage) / consolidated['price']
            precision = await self.client.get_precision(symbol)

            # Round to correct precision and ensure minimum quantity
            position_size = round(position_size, precision)
            min_qty = await self.client.get_min_qty(symbol)
            position_size = max(position_size, min_qty)

            # Final rounding after ensuring minimum
            position_size = round(position_size, precision)

            # Ensure minimum quantity
            min_qty = await self.client.get_min_qty(symbol)
            if position_size < min_qty:
                position_size = min_qty
            
            # Calculate stop loss and take profits
            stop_loss = self._calculate_stop_loss(
                consolidated['price'],
                consolidated['signal'],
                consolidated['atr']
            )
            
            take_profits = self._calculate_take_profits(
                consolidated['price'],
                consolidated['signal'],
                consolidated['atr']
            )
            
            return {
                'symbol': symbol,
                'signal': consolidated['signal'],
                'price': consolidated['price'],
                'size': position_size,
                'leverage': leverage,
                'stop_loss': stop_loss,
                'take_profits': take_profits,
                'atr': consolidated['atr'],
                'rsi': consolidated['rsi'],
                'strength': consolidated['strength'],  # Ensure this is included
                'timestamp': datetime.utcnow()
            }
            
        except Exception as e:
            self.logger.error(f"Analysis error for {symbol}: {str(e)}")
            return None
            
    async def _analyze_timeframe(self, symbol, df, timeframe):
        # Calculate all indicators
        df['atr'] = calculate_atr(df, self.atr_period)
        df['rsi'] = calculate_rsi(df, self.rsi_period)
        df['supertrend'], df['direction'] = calculate_supertrend(
            df, 
            self.supertrend_period, 
            self.supertrend_multiplier
        )
        df['vwap'] = calculate_vwap(df, self.vwap_period)
        df['obv'], df['obv_sma'] = calculate_obv(df, self.obv_period)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Signal conditions
        bullish = (
            latest['direction'] == 1 and
            latest['close'] > latest['vwap'] and
            latest['rsi'] < self.rsi_overbought and
            latest['obv'] > latest['obv_sma']
        )
        
        bearish = (
            latest['direction'] == -1 or
            latest['close'] < latest['vwap'] or
            latest['rsi'] > self.rsi_oversold or
            latest['obv'] < latest['obv_sma']
        )
        
        if bullish:
            return {
                'timeframe': timeframe,
                'signal': 'BUY',
                'price': latest['close'],
                'atr': latest['atr'],
                'rsi': latest['rsi'],
                'strength': self._calculate_signal_strength(df)
            }
        elif bearish:
            return {
                'timeframe': timeframe,
                'signal': 'SELL',
                'price': latest['close'],
                'atr': latest['atr'],
                'rsi': latest['rsi'],
                'strength': self._calculate_signal_strength(df)
            }
        return None

    def _calculate_signal_strength(self, df):
        latest = df.iloc[-1]
        
        # Weighted score calculation
        weights = {
            'trend': 0.3,
            'momentum': 0.3, 
            'volatility': 0.2,
            'volume': 0.2
        }
        
        trend_score = latest['direction']
        momentum_score = (50 - latest['rsi']) / 50
        volatility_score = latest['atr'] / df['close'].mean()
        volume_score = 1 if latest['volume'] > df['volume'].rolling(20).mean().iloc[-1] else 0
        
        total_score = (
            weights['trend'] * trend_score +
            weights['momentum'] * momentum_score +
            weights['volatility'] * volatility_score +
            weights['volume'] * volume_score
        )
        
        # Ensure score is between -1 and 1
        return max(min(total_score, 1), -1)

    def _consolidate_signals(self, signals):
        # Weight signals by timeframe and strength
        timeframe_weights = {
            '1m': 0.4,
            '5m': 0.3,
            '15m': 0.3
        }
        
        buy_signals = [s for s in signals if s['signal'] == 'BUY']
        sell_signals = [s for s in signals if s['signal'] == 'SELL']
        
        if not buy_signals and not sell_signals:
            return None
            
        # Calculate weighted average
        if len(buy_signals) > len(sell_signals):
            direction = 'BUY'
            weighted_signals = buy_signals
        else:
            direction = 'SELL'
            weighted_signals = sell_signals
            
        total_weight = 0
        weighted_price = 0
        weighted_atr = 0
        weighted_rsi = 0
        max_strength = 0
        
        for signal in weighted_signals:
            weight = timeframe_weights.get(signal['timeframe'], 0.1) * abs(signal['strength'])
            total_weight += weight
            weighted_price += signal['price'] * weight
            weighted_atr += signal['atr'] * weight
            weighted_rsi += signal['rsi'] * weight
            max_strength = max(max_strength, abs(signal['strength']))
            
        return {
            'signal': direction,
            'price': weighted_price / total_weight,
            'atr': weighted_atr / total_weight,
            'rsi': weighted_rsi / total_weight,
            'strength': max_strength
        }

    def _calculate_leverage(self, volatility):
        thresholds = self.config['trading']['volatility_thresholds']
        max_leverage = self.config['trading']['max_leverage']
        min_leverage = self.config['trading']['min_leverage']
        
        if volatility < thresholds['low']:
            return max_leverage
        elif volatility < thresholds['medium']:
            return max_leverage * 0.7
        else:
            return min_leverage

    def _calculate_stop_loss(self, price, signal, atr):
        if signal == 'BUY':
            return price - (atr * 1.5)
        else:
            return price + (atr * 1.5)

    def _calculate_take_profits(self, price, signal, atr):
        levels = self.config['strategy']['take_profit_levels']
        percentages = self.config['strategy']['take_profit_percentages']
        
        take_profits = []
        for level, pct in zip(levels, percentages):
            if signal == 'BUY':
                tp_price = price * (1 + level/100)
            else:
                tp_price = price * (1 - level/100)
                
            take_profits.append({
                'price': tp_price,
                'percentage': pct
            })
            
        return take_profits