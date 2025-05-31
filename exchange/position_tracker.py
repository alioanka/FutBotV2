from datetime import datetime

class PositionTracker:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.positions = {}
        self.closed_positions = []
        
    async def sync_with_exchange(self, client):
        """Sync local positions with exchange"""
        try:
            exchange_positions = await client.get_position_risk()
            
            # Remove positions that no longer exist
            for symbol in list(self.positions.keys()):
                pos = next((p for p in exchange_positions if p['symbol'] == symbol), None)
                if not pos or float(pos['positionAmt']) == 0:
                    self.close_position(
                        symbol,
                        exit_price=float(pos['markPrice']) if pos else 0,
                        exit_reason='external_close',
                        pnl=float(pos['unrealizedProfit']) if pos else 0
                    )
                    
            # Add new positions from exchange
            for pos in exchange_positions:
                if float(pos['positionAmt']) != 0 and pos['symbol'] not in self.positions:
                    self.add_position({
                        'symbol': pos['symbol'],
                        'side': 'BUY' if float(pos['positionAmt']) > 0 else 'SELL',
                        'quantity': abs(float(pos['positionAmt'])),
                        'entry_price': float(pos['entryPrice']),
                        'leverage': int(pos['leverage']),
                        'entry_time': datetime.utcnow(),
                        'stop_loss': None,  # Will be updated
                        'take_profits': []  # Will be updated
                    })
        except Exception as e:
            self.logger.error(f"Error syncing positions: {str(e)}")
            raise
        
    def add_position(self, position):
        symbol = position['symbol']
        if symbol in self.positions:
            self.logger.warning(f"Position for {symbol} already exists")
            return
            
        self.positions[symbol] = position
        self.logger.info(f"New position added: {symbol} - Qty: {position['quantity']}")
        
    def get_position(self, symbol):
        return self.positions.get(symbol)
        
    def close_position(self, symbol, exit_price, exit_reason, pnl):
        if symbol not in self.positions:
            return
            
        position = self.positions[symbol]
        position.update({
            'exit_price': exit_price,
            'exit_time': datetime.utcnow(),
            'exit_reason': exit_reason,
            'pnl': pnl
        })
        
        self.closed_positions.append(position)
        del self.positions[symbol]
        
        self.logger.info(f"Position closed: {symbol} PnL: {pnl:.2f}")
        
    def get_all_positions(self):
        return list(self.positions.values())
        
    def get_closed_positions(self):
        return self.closed_positions
        
    def get_total_pnl(self):
        return sum(p['pnl'] for p in self.closed_positions)