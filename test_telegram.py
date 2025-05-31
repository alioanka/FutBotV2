import asyncio
from utils.notifier import TelegramNotifier
from utils.config_loader import load_config

async def test_telegram():
    try:
        config = load_config()
        print("\nTesting Telegram Connection...")
        
        notifier = TelegramNotifier(
            config['telegram']['bot_token'],
            config['telegram']['chat_id']
        )
        
        await notifier.send_alert("🔔 Test message from FutBotV2", "info")
        print("SUCCESS: Telegram message sent!")
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_telegram())