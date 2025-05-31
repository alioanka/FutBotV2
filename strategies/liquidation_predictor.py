import asyncio
import numpy as np
from datetime import datetime, timedelta
import time

class LiquidationPredictor:
    def __init__(self, client, config, logger, notifier):
        self.client = client
        self.config = config
        self.logger = logger
        self.notifier = notifier
        self.position_risks = {}
        self.price_history = {}
        
    async def monitor_positions(self):
        while True:
            try:
                positions = await self.client.get_position_risk()
                for position in positions:
                    symbol = position['symbol']
                    if float(position['positionAmt']) == 0:
                        continue
                        
                    # Add timestamp for signed requests
                    params = {'timestamp': int(time.time() * 1000)}
                    klines = await self.client.get_klines(position['symbol'], limit=1)
                    # Update price history
                    if symbol not in self.price_history:
                        self.price_history[symbol] = []
                        
                    #klines = await self.client.get_klines(symbol, limit=1)
                    current_price = float(klines['close'].iloc[-1])
                    self.price_history[symbol].append(current_price)
                    
                    if len(self.price_history[symbol]) > 100:
                        self.price_history[symbol].pop(0)
                        
                    # Calculate risk
                    risk_score = self.calculate_liquidation_risk(position, current_price)
                    minutes_to_liq = self.predict_liquidation_time(symbol)
                    
                    # Send alerts if needed
                    if risk_score > 0.8 and minutes_to_liq < 10:
                        await self.notifier.send_alert(
                            f"🚨 LIQUIDATION IMMINENT: {symbol}\n"
                            f"Risk: {risk_score:.0%}\n"
                            f"Estimated time: {minutes_to_liq:.1f} minutes",
                            "emergency"
                        )
                    elif risk_score > 0.6:
                        await self.notifier.send_alert(
                            f"⚠️ High liquidation risk: {symbol}\n"
                            f"Risk: {risk_score:.0%}\n"
                            f"Estimated time: {minutes_to_liq:.1f} minutes",
                            "warning"
                        )
                        
                await asyncio.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Monitor error: {str(e)}")
                await asyncio.sleep(10)

    def calculate_liquidation_risk(self, position, current_price):
        entry_price = float(position['entryPrice'])
        leverage = float(position['leverage'])
        position_type = 'LONG' if float(position['positionAmt']) > 0 else 'SHORT'
        
        if position_type == 'LONG':
            liq_price = entry_price * (1 - 1/leverage)
            risk = (current_price - liq_price) / (entry_price - liq_price)
        else:
            liq_price = entry_price * (1 + 1/leverage)
            risk = (liq_price - current_price) / (liq_price - entry_price)
            
        return 1 - risk  # 0% (safe) to 100% (liquidated)
        
    def predict_liquidation_time(self, symbol):
        if symbol not in self.position_risks or len(self.price_history.get(symbol, [])) < 5:
            return float('inf')
            
        recent_prices = np.array(self.price_history[symbol][-5:])
        price_velocity = np.mean(np.diff(recent_prices))
        
        if price_velocity == 0:
            return float('inf')
            
        current_price = recent_prices[-1]
        liq_price = self.position_risks[symbol]['liq_price']
        
        if self.position_risks[symbol]['position_type'] == 'LONG':
            minutes = (current_price - liq_price) / price_velocity / 60
        else:
            minutes = (liq_price - current_price) / price_velocity / 60
            
        return max(0, minutes)