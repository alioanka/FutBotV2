import asyncio
import json
import logging
import os
import time
from utils.config_loader import load_config
from utils.logger import configure_logger
from utils.notifier import TelegramNotifier
from exchange.binance_client import BinanceClient
from exchange.order_manager import OrderManager
from exchange.position_monitor import PositionMonitor
from exchange.position_tracker import PositionTracker
from strategies.core_strategy import CoreStrategy
from strategies.risk_management import RiskManagement
from strategies.liquidation_predictor import LiquidationPredictor
from utils.performance_tracker import PerformanceTracker

logger = configure_logger()

class FutBotV2:
    def __init__(self):
        self.logger = configure_logger() 
        self.config = load_config()
        self.notifier = None
        self.client = None
        self.strategy = None
        self.order_manager = None
        self.risk_manager = None
        self.liquidation_monitor = None  # Explicitly initialize
        self.performance_tracker = None
        self.position_tracker = None
        self.position_monitor = None
        self.running = False

    async def initialize(self):
        try:
            print("\n" + "="*40)
            print("Initializing FutBotV2".center(40))
            print("="*40)
            
            # Step 1: Load configuration
            print("\n[1/4] Loading configuration...")
            self.config = load_config()
            
            # Step 2: Initialize Telegram
            print("\n[2/4] Initializing Telegram notifier...")
            try:
                self.notifier = TelegramNotifier(
                    self.config['telegram']['bot_token'],
                    self.config['telegram']['chat_id'],
                    logger=self.logger
                )
                await self.notifier.send_alert("🔧 FutBotV2 initialization started", "info")
            except Exception as e:
                raise ValueError(f"Telegram initialization failed: {str(e)}")
            
            # Step 3: Initialize Binance client
            print("\n[3/4] Initializing Binance client...")
            self.client = BinanceClient(
                api_key=self.config['binance']['api_key'],
                api_secret=self.config['binance']['api_secret'],
                testnet=self.config['binance']['testnet'],
                logger=self.logger
            )
            await self.client.initialize()
            
            # ... [previous initialization code until Binance client] ...

            # Step 4: Initialize trading components in correct order
            print("\n[4/4] Initializing trading components...")
            self.position_tracker = PositionTracker(self.config, self.logger)
            self.risk_manager = RiskManagement(self.client, self.config, self.logger, self.notifier)
            self.strategy = CoreStrategy(self.client, self.config, self.logger)
            self.order_manager = OrderManager(self.client, self.config, self.logger, self.notifier)
            
            # Initialize liquidation monitor only if configured
            if 'liquidation' in self.config:
                self.liquidation_monitor = LiquidationPredictor(
                    self.client, 
                    self.config, 
                    self.logger, 
                    self.notifier
                )
            
            # Initialize performance tracker
            initial_balance = float(self.config.get('initial_balance', 128))
            self.performance_tracker = PerformanceTracker(initial_balance)
            
            # Initialize position monitor
            self.position_monitor = PositionMonitor(
                self.client,
                self.order_manager,
                self.config,
                self.logger
            )
            
            # ... [rest of initialization] ...
            
            print("\n" + "="*40)
            print("Initialization complete!".center(40))
            print("="*40)
            
            await self.notifier.send_alert("🚀 FutBotV2 initialized successfully!", "success")
            logger.info("FutBotV2 initialized successfully")
            print("\n=== Initialization Complete ===")
            
        except Exception as e:
            error_msg = f"Initialization failed: {str(e)}"
            print(f"\n!!! {error_msg}")
            if hasattr(self, 'notifier') and self.notifier:
                await self.notifier.send_alert(f"❌ {error_msg}", "error")
            raise

    async def start(self):
        self.running = True
        
        try:
            # Start monitoring tasks only if components exist
            if self.position_monitor:
                asyncio.create_task(self.position_monitor.start())
            
            if self.liquidation_monitor:
                asyncio.create_task(self.liquidation_monitor.monitor_positions())
            
            # Main trading loop
            while self.running:
                try:
                    await self._run_trading_cycle()
                    await asyncio.sleep(10)
                except Exception as e:
                    self.logger.error(f"Trading cycle error: {e}")
                    await asyncio.sleep(30)
        except Exception as e:
            self.logger.error(f"Start error: {e}")
            raise

# Update your _monitor_positions method to:
    async def _monitor_positions(self):
        """Continuous position monitoring with SL/TP checks"""
        while self.running:
            try:
                if hasattr(self, 'order_manager'):
                    positions = await self.client.get_position_risk()
                    for pos in positions:
                        if float(pos['positionAmt']) != 0:
                            symbol = pos['symbol']
                            # Verify SL/TP orders exist
                            orders = await self.client._request(
                                "GET",
                                "/fapi/v1/openOrders",
                                {'symbol': symbol},
                                signed=True
                            )
                            if not any(o['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET'] for o in orders):
                                self.logger.warning(f"Missing SL/TP orders for {symbol}, recreating...")
                                await self.order_manager._place_sl_tp_orders(...)
                await asyncio.sleep(5)
            except Exception as e:
                self.logger.error(f"Position monitoring error: {e}")
                await asyncio.sleep(10)

    async def _run_trading_cycle(self):
        try:
            if 'pairs' not in self.config:
                raise ValueError("Missing 'pairs' configuration in config")
                
            # First sync positions with exchange
            if hasattr(self, 'position_tracker'):
                await self.position_tracker.sync_with_exchange(self.client)
                
            symbols = self.config['pairs'].get('tracked_pairs', [])
            
            for symbol in symbols:
                try:
                    signal = await self.strategy.analyze_market(symbol)
                    if not signal:
                        continue
                        
                    # Debug logging
                    positions = await self.client.get_position_risk()
                    current_pos = len([p for p in positions if float(p['positionAmt']) != 0])
                    
                    self.logger.info(f"""
    Trade Decision for {symbol}:
    - Signal: {signal.get('signal')} (Strength: {signal.get('strength', 0):.2f})
    - Current Positions: {current_pos}/{self.config['pairs']['max_concurrent_positions']}
    - Position Strengths: {self.risk_manager.position_strengths}
    """)

                    # Validate quantity
                    try:
                        signal['size'] = await self.client.validate_quantity(symbol, signal['size'])
                    except Exception as e:
                        self.logger.error(f"Quantity validation failed for {symbol}: {str(e)}")
                        continue

                    # Add this validation before processing the signal
                    if not all(k in signal for k in ['stop_loss', 'take_profits']):
                        self.logger.error(f"Incomplete signal for {symbol}: missing SL/TP parameters")
                        continue
                        
                    # Check if we can trade
                    if not await self.risk_manager.can_trade(symbol, signal):
                        continue
                        
                    # Execute trade
                    trade_result = await self.order_manager.place_order(signal)
                    
                except Exception as e:
                    self.logger.error(f"Error processing {symbol}: {str(e)}", exc_info=True)
                    await asyncio.sleep(5)  # Brief pause after error
                    
        except Exception as e:
            self.logger.error(f"Trading cycle error: {str(e)}", exc_info=True)
            await asyncio.sleep(30)  # Longer pause after major error

    async def shutdown(self):
        """More reliable shutdown sequence"""
        if not self.running:
            return
            
        self.running = False
        start_time = time.time()
        self.logger.info("Initiating graceful shutdown...")
        
        try:
            # 1. Cancel all orders first
            if hasattr(self, 'order_manager'):
                await self.order_manager.cancel_all_active_orders()
            
            # 2. Close positions with retries
            close_tasks = []
            try:
                positions = await self.client.get_position_risk()
                for pos in positions:
                    if float(pos['positionAmt']) != 0:
                        task = asyncio.create_task(
                            self._close_single_position(pos)
                        )
                        close_tasks.append(task)
                
                if close_tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*close_tasks),
                        timeout=30
                    )
            except Exception as e:
                self.logger.error(f"Position closing error: {str(e)}")
            
            # 3. Send final notification
            await self._send_shutdown_notification()
            
        except Exception as e:
            self.logger.error(f"Shutdown error: {str(e)}")
        finally:
            await self._close_connections()
            shutdown_time = time.time() - start_time
            self.logger.info(f"Shutdown completed in {shutdown_time:.1f}s")

    # Update your _close_single_position method to:
    async def _close_single_position(self, position):
        """Close a single position with SL/TP cleanup"""
        symbol = position['symbol']
        for attempt in range(3):
            try:
                # 1. Cancel all orders first
                await self.client.cancel_all_orders(symbol)
                
                # 2. Close position
                side = "SELL" if float(position['positionAmt']) > 0 else "BUY"
                await self.client.create_order(
                    symbol=symbol,
                    side=side,
                    quantity=abs(float(position['positionAmt'])),
                    order_type="MARKET",
                    reduceOnly=True
                )
                
                # 3. Verify closure
                await asyncio.sleep(1)
                pos = await self.client.get_position_risk()
                current_pos = next((p for p in pos if p['symbol'] == symbol), None)
                if current_pos and float(current_pos['positionAmt']) == 0:
                    return
                    
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(1)

    async def _send_shutdown_notification(self):
        if not hasattr(self, 'performance_tracker'):
            return
            
        stats = self.performance_tracker.get_stats()
        message = (
            "🔴 FutBotV2 Shutting Down\n"
            f"Final Balance: {stats.get('current_balance', 'N/A'):.2f}\n"
            f"Total PnL: {stats.get('total_pnl', 'N/A'):.2f}\n"
            f"Open Positions: {stats.get('open_trades', 0)}"
        )
        await self.notifier.send_alert(message, "info")

    async def _safe_execute(self, coro_func):
        try:
            return await coro_func()
        except Exception as e:
            self.logger.error(f"Shutdown task failed: {str(e)}")
            return None

    async def _close_connections(self):
        """Close all network connections safely"""
        try:
            if hasattr(self, 'notifier') and self.notifier:
                await self.notifier.close()
        except Exception as e:
            self.logger.error(f"Error closing notifier: {e}")
        
        try:
            if hasattr(self, 'client') and self.client:
                await self.client.close()
        except Exception as e:
            self.logger.error(f"Error closing client: {e}")
        
        # Give time for connections to close
        await asyncio.sleep(0.5)

async def main():
    print("Starting FutBotV2...")
    bot = FutBotV2()
    try:
        await bot.initialize()
        await bot.start()
    except KeyboardInterrupt:
        bot.logger.info("Received shutdown signal")
        await bot.shutdown()
        return  # Explicit return to prevent further errors
    except Exception as e:
        bot.logger.error(f"Fatal error: {e}")
        await bot.shutdown()
        raise
    finally:
        # Ensure all resources are closed
        if hasattr(bot, 'shutdown'):
            await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())