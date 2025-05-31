import asyncio
from datetime import datetime

class PositionMonitor:
    def __init__(self, client, order_manager, config, logger):
        self.client = client
        self.order_manager = order_manager
        self.config = config
        self.logger = logger
        self.running = False

    async def start(self):
        self.running = True
        while self.running:
            try:
                await self.check_positions()
                await asyncio.sleep(5)  # Check every 5 seconds
            except Exception as e:
                self.logger.error(f"Position monitor error: {e}")
                await asyncio.sleep(10)

    async def check_positions(self):
        positions = self.order_manager.position_tracker.get_all_positions()
        for position in positions:
            symbol = position['symbol']
            try:
                klines = await self.client.get_klines(symbol, limit=1)
                current_price = float(klines['close'].iloc[-1])
                
                # Check stop loss
                if ((position['side'] == 'BUY' and current_price <= position['stop_loss']) or 
                    (position['side'] == 'SELL' and current_price >= position['stop_loss'])):
                    await self.order_manager.close_position(symbol, "stop_loss")
                    continue
                    
                # Check take profits
                for tp in position['take_profits']:
                    if ((position['side'] == 'BUY' and current_price >= tp['price']) or 
                        (position['side'] == 'SELL' and current_price <= tp['price'])):
                        await self.order_manager.close_position(symbol, "take_profit")
                        break
                        
            except Exception as e:
                self.logger.error(f"Error monitoring {symbol}: {e}")