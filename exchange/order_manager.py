import asyncio
from exchange.position_tracker import PositionTracker
from datetime import datetime
import numpy as np
import logging

class OrderManager:
    def __init__(self, client, config, logger, notifier):
        self.client = client
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier
        self.active_orders = {}
        self.position_tracker = PositionTracker(config, logger)

    async def place_order(self, signal):
        """Updated order placement with better error recovery"""
        symbol = signal["symbol"]
        
        try:
            # 1. Check existing position
            await self._check_existing_position(symbol)

            # 2. Execute main order
            order = await self._execute_market_order(
                symbol,
                signal["signal"],
                signal["size"]
            )
            
            # 3. Verify execution
            if not order or float(order.get('executedQty', 0)) <= 0:
                raise Exception("Order not filled")

            # 4. Get fill price with fallback
            avg_price = await self._calculate_avg_fill_price(order)
            if not avg_price:
                avg_price = float((await self.client.get_klines(symbol, "1m", limit=1))['close'].iloc[-1])

            # 5. Place SL/TP with flexible pricing
            await self._place_sl_tp_orders(
                symbol,
                signal["signal"],
                float(order['executedQty']),
                avg_price,
                signal["stop_loss"],
                signal["take_profits"]
            )

            # 6. Record and notify
            await self._record_position(signal, order, avg_price)
            await self._send_trade_alert(signal, avg_price)
            
            return order
            
        except Exception as e:
            if "Order would immediately trigger" in str(e):
                self.logger.warning(f"Price adjustment needed for {symbol}, will retry next cycle")
                return None
            await self._handle_failure(symbol, str(e))
            raise

    async def _check_existing_position(self, symbol):
        """Close any existing position for this symbol"""
        positions = await self.client.get_position_risk()
        existing = next((p for p in positions 
                       if p['symbol'] == symbol and float(p['positionAmt']) != 0), None)
        
        if existing:
            self.logger.warning(f"Closing existing {symbol} position")
            side = "SELL" if float(existing['positionAmt']) > 0 else "BUY"
            await self.client.create_order(
                symbol=symbol,
                side=side,
                quantity=str(abs(float(existing['positionAmt']))),
                order_type="MARKET",
                reduceOnly=True
            )
            await asyncio.sleep(1)  # Allow exchange to process

    async def _execute_market_order(self, symbol, side, quantity):
        """Execute market order with retries"""
        for attempt in range(3):
            try:
                order = await self.client.create_order(
                    symbol=symbol,
                    side=side,
                    quantity=str(quantity),
                    order_type="MARKET",
                    newOrderRespType="FULL"
                )
                
                if float(order.get('executedQty', 0)) > 0:
                    return order
                    
                # Verify through separate API call if needed
                await asyncio.sleep(1)
                verified = await self.client.get_order(
                    symbol=symbol,
                    orderId=order['orderId']
                )
                
                if float(verified.get('executedQty', 0)) > 0:
                    return verified
                    
                raise Exception("No execution confirmed")
                
            except Exception as e:
                if attempt == 2:
                    raise Exception(f"Order failed after retries: {str(e)}")
                await asyncio.sleep(1)

    def _calculate_avg_fill_price(self, order):
        """Calculate average fill price from order response"""
        fills = order.get('fills', [])
        if not fills:
            return None
            
        total_qty = sum(float(f['qty']) for f in fills)
        return sum(float(f['price'])*float(f['qty']) for f in fills) / total_qty

    async def _place_sl_tp_orders(self, symbol, side, quantity, entry_price, sl_price, take_profits):
        """Place SL/TP orders with verification"""
        # Place Stop Loss
        await self.client.create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            quantity=str(quantity),
            order_type="STOP_MARKET",
            stopPrice=str(sl_price),
            reduceOnly="true"
        )
        
        # Place Take Profits
        for tp in take_profits:
            await self.client.create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                quantity=str(quantity * (tp['percentage'] / 100)),
                order_type="TAKE_PROFIT_MARKET",
                stopPrice=str(tp['price']),
                reduceOnly="true"
            )
        
        # Verify orders were placed
        await asyncio.sleep(1)
        open_orders = await self.client._request(
            "GET",
            "/fapi/v1/openOrders",
            {'symbol': symbol},
            signed=True
        )
        
        if len(open_orders) < len(take_profits) + 1:
            raise Exception("Not all SL/TP orders were placed")

    async def _record_position(self, signal, order, avg_price):
        """Record position in tracker"""
        position = {
            'symbol': signal["symbol"],
            'side': signal["signal"],
            'quantity': float(order['executedQty']),
            'entry_price': avg_price,
            'entry_time': datetime.utcnow(),
            'stop_loss': float(signal["stop_loss"]),
            'take_profits': signal["take_profits"]
        }
        self.position_tracker.add_position(position)

    async def _send_trade_alert(self, signal, fill_price):
        """Send trade notification"""
        if not self.notifier:
            return
            
        message = (
            f"🚀 {signal['signal']} {signal['symbol']}\n"
            f"Entry: {fill_price:.2f}\n"
            f"Size: {signal['size']:.4f}\n"
            f"SL: {signal['stop_loss']:.2f}\n"
            f"TPs: {', '.join(f"{tp['price']:.2f} ({tp['percentage']}%)" for tp in signal['take_profits'])}"
        )
        await self.notifier.send_message(message)

    async def _handle_failure(self, symbol, error):
        """Handle order failure"""
        self.logger.error(f"Order failed for {symbol}: {error}")
        
        try:
            await self.client.cancel_all_orders(symbol)
            
            # Close any partial position
            positions = await self.client.get_position_risk()
            pos = next((p for p in positions 
                       if p['symbol'] == symbol and float(p['positionAmt']) != 0), None)
            
            if pos:
                side = "SELL" if float(pos['positionAmt']) > 0 else "BUY"
                await self.client.create_order(
                    symbol=symbol,
                    side=side,
                    quantity=str(abs(float(pos['positionAmt']))),
                    order_type="MARKET",
                    reduceOnly=True
                )
                
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")
            
        if self.notifier:
            await self.notifier.send_message(
                f"❌ Order failed for {symbol}\nError: {error}"
            )
        
    async def close_all_positions(self):
        """Close all open positions safely"""
        try:
            positions = await self.client.get_position_risk()
            results = []
            
            for position in positions:
                pos_amount = float(position['positionAmt'])
                if pos_amount == 0:
                    continue
                    
                symbol = position['symbol']
                try:
                    side = "SELL" if pos_amount > 0 else "BUY"
                    quantity = abs(pos_amount)
                    
                    # Close position
                    result = await self.client.create_order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        order_type="MARKET",
                        reduceOnly=True
                    )
                    results.append(result)
                    
                    # Cancel all orders for this symbol
                    await self.client.cancel_all_orders(symbol)
                    
                    # Update position tracker
                    if self.position_tracker.get_position(symbol):
                        self.position_tracker.close_position(
                            symbol,
                            exit_price=float(position['markPrice']),
                            exit_reason='shutdown',
                            pnl=float(position['unrealizedProfit'])
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error closing {symbol}: {str(e)}")
                    continue
                    
            return results
        except Exception as e:
            self.logger.error(f"Error closing all positions: {str(e)}")
            raise

    async def _calculate_avg_fill_price(self, order):
        """More robust fill price calculation"""
        try:
            # First try to get from fills
            if 'fills' in order and order['fills']:
                total_qty = sum(float(f['qty']) for f in order['fills'])
                if total_qty > 0:
                    return sum(float(f['price'])*float(f['qty']) for f in order['fills']) / total_qty
            
            # Fallback to average price if available
            if 'avgPrice' in order and float(order['avgPrice']) > 0:
                return float(order['avgPrice'])
            
            # Final fallback to entry price from position (requires await)
            positions = await self.client.get_position_risk()
            pos = next((p for p in positions if p['symbol'] == order['symbol']), None)
            if pos and float(pos['entryPrice']) > 0:
                return float(pos['entryPrice'])
            
            return None
        except Exception as e:
            self.logger.error(f"Error calculating fill price: {str(e)}")
            return None
    
    async def _place_sl_tp_orders(self, symbol, side, quantity, entry_price, sl_price, take_profits):
        """More flexible SL/TP placement with better price validation"""
        try:
            # Get current market data
            klines = await self.client.get_klines(symbol, "1m", limit=1)
            current_price = float(klines['close'].iloc[-1])
            price_precision = await self.client.get_precision(symbol)
            
            # Calculate minimum price differences
            if side == "BUY":
                # For long positions
                min_sl_diff = max(current_price * 0.0015, current_price * 0.0005)  # 0.15% min, 0.05% absolute
                min_tp_diff = max(current_price * 0.002, current_price * 0.0005)    # 0.2% min, 0.05% absolute
                
                # Adjust SL price
                sl_price = max(sl_price, current_price - min_sl_diff)
                
                # Adjust TP prices
                adjusted_tps = []
                for tp in take_profits:
                    tp_price = max(tp['price'], current_price + min_tp_diff)
                    adjusted_tps.append({
                        'price': round(tp_price, price_precision),
                        'percentage': tp['percentage']
                    })
            else:
                # For short positions
                min_sl_diff = max(current_price * 0.0015, current_price * 0.0005)  # 0.15% min, 0.05% absolute
                min_tp_diff = max(current_price * 0.002, current_price * 0.0005)    # 0.2% min, 0.05% absolute
                
                # Adjust SL price
                sl_price = min(sl_price, current_price + min_sl_diff)
                
                # Adjust TP prices
                adjusted_tps = []
                for tp in take_profits:
                    tp_price = min(tp['price'], current_price - min_tp_diff)
                    adjusted_tps.append({
                        'price': round(tp_price, price_precision),
                        'percentage': tp['percentage']
                    })

            # Place orders with retries
            await self._place_orders_with_retry(
                symbol,
                side,
                quantity,
                round(sl_price, price_precision),
                adjusted_tps,
                price_precision
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to place SL/TP for {symbol}: {str(e)}")
            raise

    async def _place_orders_with_retry(self, symbol, side, quantity, sl_price, take_profits, price_precision, max_retries=3):
        """Place orders with retry mechanism"""
        for attempt in range(max_retries):
            try:
                # Place Stop Loss
                await self.client.create_order(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=round(quantity, price_precision),
                    order_type="STOP_MARKET",
                    stopPrice=str(sl_price),
                    reduceOnly="true"
                )
                
                # Place Take Profits
                for tp in take_profits:
                    await self.client.create_order(
                        symbol=symbol,
                        side="SELL" if side == "BUY" else "BUY",
                        quantity=round(quantity * (tp['percentage'] / 100), price_precision),
                        order_type="TAKE_PROFIT_MARKET",
                        stopPrice=str(tp['price']),
                        reduceOnly="true"
                    )
                
                return True
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
                # Slightly adjust prices before retry
                adjustment_factor = 1.001 if side == "BUY" else 0.999
                sl_price = round(sl_price * adjustment_factor, price_precision)
                take_profits = [{
                    'price': round(tp['price'] * adjustment_factor, price_precision),
                    'percentage': tp['percentage']
                } for tp in take_profits]

    async def _place_validated_orders(self, symbol, side, quantity, sl_price, take_profits, price_precision):
        """Place orders with validated parameters"""
        # Place Stop Loss
        await self.client.create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            quantity=round(quantity, price_precision),
            order_type="STOP_MARKET",
            stopPrice=str(sl_price),
            reduceOnly="true"
        )
        
        # Place Take Profits
        for tp in take_profits:
            await self.client.create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                quantity=round(quantity * (tp['percentage'] / 100), price_precision),
                order_type="TAKE_PROFIT_MARKET",
                stopPrice=str(tp['price']),
                reduceOnly="true"
            )

    async def _place_sl_order(self, symbol, side, quantity, stop_price):
        """Place stop loss order with retries"""
        for attempt in range(3):
            try:
                return await self.client.create_order(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=str(quantity),
                    order_type="STOP_MARKET",
                    stopPrice=str(stop_price),
                    reduceOnly="true"
                )
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

    async def _place_tp_order(self, symbol, side, quantity, tp_price):
        """Place take profit order with retries"""
        for attempt in range(3):
            try:
                return await self.client.create_order(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=str(quantity),
                    order_type="TAKE_PROFIT_MARKET",
                    stopPrice=str(tp_price),
                    reduceOnly="true"
                )
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

    async def close_position(self, symbol, reason="manual"):
        try:
            position = self.position_tracker.get_position(symbol)
            if not position:
                return None
                
            # Get current price
            klines = await self.client.get_klines(symbol, limit=1)
            current_price = float(klines['close'].iloc[-1])
            
            # Calculate PnL
            pnl = self._calculate_pnl(position, current_price)
            
            # Close position
            side = "SELL" if position['side'] == "BUY" else "BUY"
            result = await self.client.create_order(
                symbol=symbol,
                side=side,
                quantity=position['quantity'],
                order_type="MARKET"
            )
            
            if result:

                if hasattr(self.risk_manager, 'position_strengths'):
                    if symbol in self.risk_manager.position_strengths:
                        del self.risk_manager.position_strengths[symbol]

                # Update position
                self.position_tracker.close_position(
                    symbol,
                    exit_price=current_price,
                    exit_reason=reason,
                    pnl=pnl
                )
                
                # Cancel any active orders
                if symbol in self.active_orders:
                    del self.active_orders[symbol]
                    
                # Send notification
                await self.notifier.send_alert(
                    f"✅ Position closed for {symbol}\n"
                    f"Reason: {reason}\n"
                    f"PnL: {pnl:.2f}",
                    "success"
                )
                
            return result
            
        except Exception as e:
            self.logger.error(f"Error closing position: {str(e)}")
            await self.notifier.send_alert(
                f"❌ Failed to close {symbol}\nError: {str(e)}",
                "error"
            )
            return None
        
    async def _cancel_all_orders(self, symbol):
        """Cancel all open orders for a symbol"""
        try:
            await self.client._request(
                "DELETE",
                "/fapi/v1/allOpenOrders",
                {'symbol': symbol},
                signed=True
            )
            self.logger.info(f"Cancelled all orders for {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to cancel orders for {symbol}: {str(e)}")
        
    async def check_positions(self):
        positions = self.order_manager.position_tracker.get_all_positions()
        for position in positions:
            symbol = position['symbol']
            try:
                # Update trailing stops
                await self.order_manager.order_management.update_trailing_stop(symbol, position)
                
                # Check if position was closed by exchange
                exchange_positions = await self.client.get_position_risk()
                pos_info = next((p for p in exchange_positions if p['symbol'] == symbol), None)
                
                if pos_info and float(pos_info['positionAmt']) == 0:
                    # Position was closed externally
                    await self.order_manager.order_management.cleanup_orders(symbol)
                    self.order_manager.position_tracker.close_position(
                        symbol,
                        exit_price=float(pos_info['entryPrice']),
                        exit_reason='external_close'
                    )
                    
            except Exception as e:
                self.logger.error(f"Position check error for {symbol}: {str(e)}")
        
    async def cancel_all_active_orders(self):
        """Cancel all active orders for all symbols"""
        for symbol in list(self.active_orders.keys()):
            try:
                await self.client._request(
                    "DELETE", 
                    "/fapi/v1/allOpenOrders",
                    {'symbol': symbol},
                    signed=True
                )
                del self.active_orders[symbol]
            except Exception as e:
                self.logger.error(f"Error cancelling orders for {symbol}: {e}")

    def _calculate_pnl(self, position, exit_price):
        if position['side'] == "BUY":
            return (exit_price - position['entry_price']) * position['quantity']
        else:
            return (position['entry_price'] - exit_price) * position['quantity']

    async def apply_trailing_stop(self, symbol, activation_percent, trail_percent):
        position = self.position_tracker.get_position(symbol)
        if not position:
            return
            
        klines = await self.client.get_klines(symbol, limit=1)
        current_price = float(klines['close'].iloc[-1])
        
        if position['side'] == "BUY":
            profit_pct = (current_price - position['entry_price']) / position['entry_price']
            if profit_pct >= activation_percent:
                new_stop = current_price * (1 - trail_percent)
                if new_stop > position['stop_loss']:
                    position['stop_loss'] = new_stop
        else:
            profit_pct = (position['entry_price'] - current_price) / position['entry_price']
            if profit_pct >= activation_percent:
                new_stop = current_price * (1 + trail_percent)
                if new_stop < position['stop_loss']:
                    position['stop_loss'] = new_stop