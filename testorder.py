import asyncio
import logging
from exchange.binance_client import BinanceClient
from exchange.order_manager import OrderManager
from utils.logger import configure_logger
from utils.notifier import TelegramNotifier
from utils.config_loader import load_config

async def main():
    # Initialize components
    config = load_config()
    logger = configure_logger()
    
    notifier = TelegramNotifier(
        config['telegram']['bot_token'],
        config['telegram']['chat_id'],
        logger=logger
    )
    
    client = BinanceClient(
        api_key=config['binance']['api_key'],
        api_secret=config['binance']['api_secret'],
        testnet=True,
        logger=logger
    )
    await client.initialize()

    # Get current market data
    klines = await client.get_klines("BTCUSDT", "1m", limit=1)
    current_price = float(klines['close'].iloc[-1])
    
    # Create test signal with safe price levels
    test_signal = {
        "symbol": "BTCUSDT",
        "signal": "BUY",
        "size": 0.002,
        "stop_loss": round(current_price * 0.995, 2),  # 0.5% below
        "take_profits": [
            {"price": round(current_price * 1.005, 2), "percentage": 50},  # 0.5% above
            {"price": round(current_price * 1.01, 2), "percentage": 50}    # 1% above
        ]
    }
    # Execute test
    om = OrderManager(client, config, logger, notifier)
    try:
        print("Executing test order...")
        result = await om.place_order(test_signal)
        print("Order executed successfully!")
        print("Verify on Binance Testnet:")
        print("- Position should be open")
        print("- Stop loss order visible")
        print("- Two take profit orders visible")
    except Exception as e:
        print(f"Test failed: {str(e)}")
    finally:
        await client.close()
        await notifier.close()

if __name__ == "__main__":
    asyncio.run(main())