from datetime import datetime
from typing import Dict, List, Optional
import numpy as np

class PerformanceTracker:
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.trades: List[Dict] = []
        self.open_positions: Dict[str, Dict] = {}
        self.daily_stats = {
            'date': datetime.now().date(),
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'pnl': 0.0
        }

    def add_trade(self, trade: Dict) -> None:
        """Record a new trade"""
        trade['entry_time'] = datetime.now()
        self.open_positions[trade['symbol']] = trade
        self.trades.append(trade)

    def close_trade(self, symbol: str, exit_price: float, reason: str = 'manual') -> Optional[Dict]:
        """Close an open trade and calculate PnL"""
        if symbol not in self.open_positions:
            return None
            
        trade = self.open_positions.pop(symbol)
        trade.update({
            'exit_price': exit_price,
            'exit_time': datetime.now(),
            'exit_reason': reason
        })
        
        # Calculate PnL
        if trade['side'] == 'BUY':
            pnl = (exit_price - trade['entry_price']) * trade['quantity']
        else:
            pnl = (trade['entry_price'] - exit_price) * trade['quantity']
            
        trade['pnl'] = pnl
        trade['pnl_pct'] = (pnl / self.initial_balance) * 100
        self.current_balance += pnl
        
        # Update daily stats
        self._update_daily_stats(pnl > 0)
        
        return trade

    def _update_daily_stats(self, is_win: bool) -> None:
        today = datetime.now().date()
        if today != self.daily_stats['date']:
            self.daily_stats = {
                'date': today,
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'pnl': 0.0
            }
            
        self.daily_stats['trades'] += 1
        if is_win:
            self.daily_stats['wins'] += 1
        else:
            self.daily_stats['losses'] += 1

    def get_stats(self) -> Dict:
        """Return performance statistics"""
        closed_trades = [t for t in self.trades if 'exit_price' in t]
        
        stats = {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'total_pnl': self.current_balance - self.initial_balance,
            'total_pnl_pct': ((self.current_balance - self.initial_balance) / self.initial_balance) * 100,
            'total_trades': len(self.trades),
            'closed_trades': len(closed_trades),
            'open_trades': len(self.open_positions),
            'win_rate': (len([t for t in closed_trades if t['pnl'] > 0]) / len(closed_trades)) * 100 if closed_trades else 0,
            'daily_stats': self.daily_stats
        }
        
        return stats

    def get_open_position(self, symbol: str) -> Optional[Dict]:
        """Get an open position by symbol"""
        return self.open_positions.get(symbol)