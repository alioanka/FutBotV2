import asyncio
from typing import Dict, List
import time

class OrderManagement:
    def __init__(self, client, config, logger, notifier):
        self.client = client
        self.config = config
        self.logger = logger
        self.notifier = notifier
        self.active_orders = {}

    async def place_position_with_sltp(self, symbol: str, side: str, quantity: float, 
                                    entry_price: float, stop_loss: float, 
                                    take_profits: List[Dict]):
        """Place position with separate SL/TP orders"""
        try:
            self.logger.info(f"Attempting to place orders for {symbol}...")
            
            # Place main market order
            main_order = await self.client.create_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type="MARKET"
            )
            self.logger.info(f"Main order placed: {main_order}")
            
            # Brief delay for exchange to process
            await asyncio.sleep(1)
            
            # Place stop loss
            sl_order = await self.client.create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                quantity=quantity,
                order_type="STOP_MARKET",
                stop_price=stop_loss,
                reduce_only=True
            )
            self.logger.info(f"Stop loss placed: {sl_order}")
            
            # Place take profits
            tp_orders = []
            for tp in take_profits:
                tp_order = await self.client.create_order(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=tp['quantity'],
                    order_type="TAKE_PROFIT_MARKET",
                    stop_price=tp['price'],
                    reduce_only=True
                )
                tp_orders.append(tp_order)
                self.logger.info(f"Take profit placed: {tp_order}")
            
            # Verify orders in exchange
            open_orders = await self.client._request(
                "GET",
                "/fapi/v1/openOrders",
                {'symbol': symbol, 'timestamp': int(time.time() * 1000)},
                signed=True
            )
            self.logger.info(f"Open orders on exchange: {open_orders}")
            
            return main_order
            
        except Exception as e:
            self.logger.error(f"Order placement failed: {str(e)}")
            # Attempt to cancel any open orders
            try:
                await self.client._request(
                    "DELETE",
                    "/fapi/v1/allOpenOrders",
                    {'symbol': symbol, 'timestamp': int(time.time() * 1000)},
                    signed=True
                )
            except Exception as cancel_error:
                self.logger.error(f"Failed to cancel orders: {str(cancel_error)}")
            raise

    async def update_trailing_stop(self, symbol: str, position: Dict):
        """Update trailing stop based on current price"""
        try:
            klines = await self.client.get_klines(symbol, limit=1)
            current_price = float(klines['close'].iloc[-1])
            
            if position['side'] == 'BUY':
                new_stop = current_price * (1 - self.config['strategy']['trailing_stop_distance'])
                if new_stop > position['stop_loss']:
                    # Cancel old SL
                    await self.cancel_order(symbol, 'stop_loss')
                    # Place new SL
                    sl_order = await self.client.create_order(
                        symbol=symbol,
                        side="SELL",
                        quantity=position['quantity'],
                        order_type="STOP_MARKET",
                        stop_price=new_stop,
                        reduce_only=True
                    )
                    position['stop_loss'] = new_stop
                    self.active_orders[symbol]['stop_loss'] = sl_order
                    
            else:  # SELL position
                new_stop = current_price * (1 + self.config['strategy']['trailing_stop_distance'])
                if new_stop < position['stop_loss']:
                    # Cancel old SL
                    await self.cancel_order(symbol, 'stop_loss')
                    # Place new SL
                    sl_order = await self.client.create_order(
                        symbol=symbol,
                        side="BUY",
                        quantity=position['quantity'],
                        order_type="STOP_MARKET",
                        stop_price=new_stop,
                        reduce_only=True
                    )
                    position['stop_loss'] = new_stop
                    self.active_orders[symbol]['stop_loss'] = sl_order
                    
        except Exception as e:
            self.logger.error(f"Trailing stop update error for {symbol}: {str(e)}")

    async def cancel_order(self, symbol: str, order_type: str):
        """Cancel specific order type for a symbol"""
        if symbol in self.active_orders and order_type in self.active_orders[symbol]:
            try:
                order = self.active_orders[symbol][order_type]
                await self.client._request(
                    "DELETE",
                    "/fapi/v1/order",
                    {
                        'symbol': symbol,
                        'orderId': order['orderId'],
                        'timestamp': int(time.time() * 1000)
                    },
                    signed=True
                )
            except Exception as e:
                self.logger.error(f"Error cancelling {order_type} for {symbol}: {str(e)}")

    async def cleanup_orders(self, symbol: str):
        """Cancel all orders for a symbol"""
        try:
            await self.client._request(
                "DELETE",
                "/fapi/v1/allOpenOrders",
                {'symbol': symbol, 'timestamp': int(time.time() * 1000)},
                signed=True
            )
            if symbol in self.active_orders:
                del self.active_orders[symbol]
        except Exception as e:
            self.logger.error(f"Error cleaning up orders for {symbol}: {str(e)}")