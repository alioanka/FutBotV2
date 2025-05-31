import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
from strategies.core_strategy import CoreStrategy

class Backtester:
    def __init__(self, strategy: CoreStrategy, initial_balance: float = 10000):
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.results = []
        
    async def run(self, symbol: str, start_date: str, end_date: str) -> Dict:
        """Run backtest for a symbol between dates"""
        # Load historical data
        data = await self._load_historical_data(symbol, start_date, end_date)
        if data.empty:
            return {'error': 'No data loaded'}
            
        # Initialize tracking
        balance = self.initial_balance
        position = None
        trades = []
        
        # Simulate live trading
        for i in range(len(data)):
            current = data.iloc[i]
            
            # Get signal (using data up to current point)
            signal = await self.strategy.analyze_market(symbol, data[:i+1])
            
            if signal and not position:
                # Execute trade
                position = {
                    'symbol': symbol,
                    'side': signal['signal'],
                    'entry_price': current['close'],
                    'quantity': balance * 0.01 / current['close'],  # 1% risk
                    'entry_time': current.name,
                    'stop_loss': signal['stop_loss'],
                    'take_profits': signal['take_profits']
                }
                trades.append(position.copy())
                
            elif position:
                # Check exit conditions
                if self._check_stop_loss(current, position):
                    pnl = self._calculate_pnl(position, current['close'])
                    balance += pnl
                    position['exit_price'] = current['close']
                    position['exit_reason'] = 'stop_loss'
                    position['exit_time'] = current.name
                    position['pnl'] = pnl
                    position = None
                    
                elif self._check_take_profit(current, position):
                    pnl = self._calculate_pnl(position, current['close'])
                    balance += pnl
                    position['exit_price'] = current['close']
                    position['exit_reason'] = 'take_profit'
                    position['exit_time'] = current.name
                    position['pnl'] = pnl
                    position = None
                    
        # Prepare results
        stats = self._calculate_stats(trades, balance)
        return {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'final_balance': balance,
            'total_return': (balance - self.initial_balance) / self.initial_balance * 100,
            'stats': stats,
            'trades': trades
        }
        
    def _check_stop_loss(self, current, position) -> bool:
        if position['side'] == 'BUY':
            return current['low'] <= position['stop_loss']
        else:
            return current['high'] >= position['stop_loss']
            
    def _check_take_profit(self, current, position) -> bool:
        for tp in position['take_profits']:
            if position['side'] == 'BUY' and current['high'] >= tp['price']:
                return True
            elif position['side'] == 'SELL' and current['low'] <= tp['price']:
                return True
        return False
        
    def _calculate_pnl(self, position, exit_price) -> float:
        if position['side'] == 'BUY':
            return (exit_price - position['entry_price']) * position['quantity']
        else:
            return (position['entry_price'] - exit_price) * position['quantity']
            
    def _calculate_stats(self, trades, final_balance) -> Dict:
        closed_trades = [t for t in trades if 'exit_price' in t]
        winning_trades = [t for t in closed_trades if t['pnl'] > 0]
        
        return {
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(closed_trades) - len(winning_trades),
            'win_rate': len(winning_trades) / len(closed_trades) * 100 if closed_trades else 0,
            'avg_win': np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0,
            'avg_loss': np.mean([t['pnl'] for t in closed_trades if t['pnl'] <= 0]) if len(closed_trades) > len(winning_trades) else 0,
            'profit_factor': abs(sum(t['pnl'] for t in winning_trades) / sum(t['pnl'] for t in closed_trades if t['pnl'] <= 0)) if closed_trades and len(winning_trades) < len(closed_trades) else float('inf'),
            'max_drawdown': self._calculate_max_drawdown(closed_trades),
            'final_balance': final_balance,
            'total_return': (final_balance - self.initial_balance) / self.initial_balance * 100
        }
        
    def _calculate_max_drawdown(self, trades) -> float:
        if not trades:
            return 0
            
        equity = [self.initial_balance]
        for trade in trades:
            equity.append(equity[-1] + trade['pnl'])
            
        peak = equity[0]
        max_dd = 0
        
        for x in equity[1:]:
            if x > peak:
                peak = x
            dd = (peak - x) / peak * 100
            if dd > max_dd:
                max_dd = dd
                
        return max_dd