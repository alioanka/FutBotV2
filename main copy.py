import asyncio
import logging
import os
from utils.config_loader import load_config
from utils.logger import configure_logger
from utils.notifier import TelegramNotifier
from exchange.binance_client import BinanceClient
from exchange.order_manager import OrderManager
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
        self.liquidation_monitor = None
        self.performance_tracker = None
        self.running = False

    async def initialize(self):
        try:
            logger.info("Initializing FutBotV2...")
            
            # Initialize components
            self.notifier = TelegramNotifier(
                self.config['telegram']['bot_token'],
                self.config['telegram']['chat_id']
            )
            
            self.client = BinanceClient(
                api_key=self.config['binance']['api_key'],
                api_secret=self.config['binance']['api_secret'],
                testnet=self.config['binance']['testnet']
            )
            await self.client.initialize()
            
            self.strategy = CoreStrategy(self.client, self.config, logger)
            self.risk_manager = RiskManagement(self.config, logger, self.notifier)
            self.order_manager = OrderManager(self.client, self.config, logger, self.notifier)
            self.liquidation_monitor = LiquidationPredictor(self.client, self.config, logger, self.notifier)
            
            initial_balance = float(self.config.get('initial_balance', 128))
            self.performance_tracker = PerformanceTracker(initial_balance)
            
            # Send startup notification
            await self.notifier.send_alert(
                "🚀 FutBotV2 initialized successfully!",
                "success"
            )
            
            logger.info("FutBotV2 initialized successfully")
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            if self.notifier:
                await self.notifier.send_alert(
                    f"❌ FutBotV2 initialization failed: {e}",
                    "error"
                )
            raise

    async def start(self):
        self.running = True
        
        # Start liquidation monitor
        asyncio.create_task(self.liquidation_monitor.monitor_positions())
        
        # Main trading loop
        while self.running:
            try:
                await self._run_trading_cycle()
                await asyncio.sleep(10)  # Wait between cycles
                
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}")
                await self.notifier.send_alert(
                    f"⚠️ Trading cycle error: {e}",
                    "error"
                )
                await asyncio.sleep(30)

    async def _run_trading_cycle(self):
        """Execute one complete trading cycle for all symbols"""
        symbols = self.config['pairs']['tracked_pairs']
        
        for symbol in symbols:
            try:
                # Skip if we already have a position
                if (hasattr(self, 'position_tracker') and 
                    self.position_tracker.get_position(symbol)):
                    continue

                # Get market signal first
                signal = await self.strategy.analyze_market(symbol)
                if not signal:
                    continue

                                # Validate quantity precision
                signal['size'] = await self.client.validate_quantity(
                    symbol, 
                    signal['size']
                )
                    
                # Check if we can trade
                if not await self.risk_manager.can_trade(symbol, signal):
                    continue
                    
                # Evaluate signal quality (using get_trade_score instead of evaluate_risk)
                score = await self.risk_manager.get_trade_score(signal)
                if score < 0.5:  # Adjust threshold as needed
                    continue
                    
                # Execute trade
                trade_result = await self.order_manager.place_order(signal)
                if trade_result and hasattr(self, 'performance_tracker'):
                    self.performance_tracker.add_trade(trade_result)
                    
            except Exception as e:
                error_msg = f"Error processing {symbol}: {str(e)}"
                if hasattr(self, 'logger'):
                    self.logger.error(error_msg)
                try:
                    if hasattr(self, 'notifier') and self.notifier:
                        await self.notifier.send_alert(error_msg, "error")
                except Exception as e:
                    if hasattr(self, 'logger'):
                        self.logger.error(f"Failed to send Telegram alert: {e}")

    async def shutdown(self):
        self.running = False
        self.logger.info("Initiating graceful shutdown...")
        
        try:
            # 1. Cancel all orders
            if hasattr(self, 'order_manager'):
                await self.order_manager.cancel_all_active_orders()
                
            # 2. Close all positions
            if hasattr(self, 'client'):
                await self.client.close_all_positions()
                
            # 3. Send notification
            if hasattr(self, 'notifier'):
                await self._send_shutdown_notification()
                
        except Exception as e:
            self.logger.error(f"Shutdown error: {e}")
        finally:
            # Ensure all connections are closed
            if hasattr(self, 'notifier'):
                await self.notifier.close()
            if hasattr(self, 'client'):
                await self.client.close()

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
        """Close all network connections"""
        if hasattr(self, 'notifier') and self.notifier:
            await self.notifier.close()
        if hasattr(self, 'client') and self.client:
            await self.client.close()
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
    except Exception as e:
        bot.logger.error(f"Fatal error: {e}")
    finally:
        try:
            await bot.shutdown()
        except Exception as e:
            bot.logger.error(f"Shutdown error: {e}")
        finally:
            # Cleanup any remaining tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())