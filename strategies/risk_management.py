import time
import numpy as np
from datetime import datetime, timedelta

class RiskManagement:
    def __init__(self, client, config, logger, notifier):
        self.client = client  # Add this line
        self.config = config
        self.logger = logger
        self.notifier = notifier
        self.trade_history = []
        self.last_trade_time = {}
        self.daily_pnl = 0
        self.daily_start_time = datetime.utcnow()
        self.position_strengths = {}  # {symbol: strength}
        
    def reset_daily_stats(self):
        if datetime.utcnow() - self.daily_start_time > timedelta(days=1):
            self.daily_pnl = 0
            self.daily_start_time = datetime.utcnow()
            
    async def can_trade(self, symbol: str, signal: dict) -> bool:
        """Check if we can trade this symbol with the given signal"""
        try:
            self.reset_daily_stats()
            
            # 1. Check if we already have an open position for this symbol
            positions = await self.client.get_position_risk()
            existing_pos = next((p for p in positions if p['symbol'] == symbol and float(p['positionAmt']) != 0), None)
            
            if existing_pos:
                self.logger.debug(f"Existing position found for {symbol} (size: {existing_pos['positionAmt']})")
                return False
                
            # 2. Check signal strength threshold
            signal_strength = abs(signal.get('strength', 0))
            min_strength = self.config['strategy'].get('min_signal_strength', 0.35)
            
            if signal_strength < min_strength:
                self.logger.debug(f"Signal strength {signal_strength:.2f} below minimum {min_strength:.2f}")
                return False
                
            # 3. Check daily loss limit
            max_daily_loss = float(self.config['risk'].get('max_daily_loss', 5))  # Default 5%
            if self.daily_pnl < -max_daily_loss:
                await self.notifier.send_alert(
                    f"⚠️ Daily loss limit reached: {self.daily_pnl:.2f}%",
                    "warning"
                )
                return False
                
            # 4. Check max concurrent positions
            max_positions = int(self.config['pairs'].get('max_concurrent_positions', 5))  # Default 5
            active_positions = [p for p in positions if float(p['positionAmt']) != 0]
            current_positions = len(active_positions)
            
            if current_positions >= max_positions:
                # Find weakest position to potentially replace
                weakest_symbol = min(
                    self.position_strengths.items(),
                    key=lambda x: abs(x[1]),
                    default=(None, 0)
                )[0]
                
                if weakest_symbol:
                    weakest_strength = abs(self.position_strengths.get(weakest_symbol, 0))
                    
                    # Only replace if new signal is significantly stronger
                    if signal_strength > weakest_strength * 1.2:  # 20% stronger
                        self.logger.info(
                            f"Replacing {weakest_symbol} (strength: {weakest_strength:.2f}) "
                            f"with {symbol} (strength: {signal_strength:.2f})"
                        )
                        return True
                        
                self.logger.debug(f"Max positions reached ({current_positions}/{max_positions})")
                return False
                
            # 5. Additional checks (optional)
            # Check if market is too volatile
            if signal.get('atr', 0) / signal.get('price', 1) > 0.05:  # 5% volatility
                self.logger.debug(f"High volatility detected for {symbol}")
                return False
                
            # Check if in cooldown period after last trade
            last_trade_time = self.last_trade_time.get(symbol, 0)
            cooldown = self.config['strategy'].get('trade_cooldown_sec', 60)  # Default 60s
            if time.time() - last_trade_time < cooldown:
                self.logger.debug(f"Symbol {symbol} in cooldown period")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error in can_trade for {symbol}: {str(e)}")
            return False
    

        
    async def update_trade_outcome(self, symbol, pnl, signal_strength=None):
        self.daily_pnl += pnl
        self.last_trade_time[symbol] = time.time()
        if signal_strength is not None:
            self.position_strengths[symbol] = signal_strength
        self.trade_history.append({
            'symbol': symbol,
            'time': datetime.utcnow(),
            'pnl': pnl,
            'strength': signal_strength
        })
            
    async def check_market_conditions(self, symbol, df):
        # Check for abnormal volume spikes
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        
        if current_volume > avg_volume * 3:
            await self.notifier.send_alert(
                f"⚠️ Volume spike detected for {symbol}\n"
                f"Current: {current_volume:.2f} vs Avg: {avg_volume:.2f}",
                "warning"
            )
            return False
            
        return True
        
    async def get_trade_score(self, signal):
        # Calculate composite score based on multiple factors
        volatility = signal.get('atr', 0) / signal.get('price', 1)
        strength = signal.get('strength', 0)
        rsi = signal.get('rsi', 50)
        
        # Normalize factors
        vol_score = 1 - min(volatility / 0.05, 1)  # 0-5% is ideal
        str_score = abs(strength)
        rsi_score = 1 - abs(rsi - 50) / 50  # Closer to 50 is better
        
        # Weighted score
        weights = {
            'volatility': 0.4,
            'strength': 0.4,
            'rsi': 0.2
        }
        
        score = (
            weights['volatility'] * vol_score +
            weights['strength'] * str_score +
            weights['rsi'] * rsi_score
        )
        
        return score