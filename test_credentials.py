import os
from dotenv import load_dotenv
from pathlib import Path

def test_credentials():
    # Load .env file
    env_path = Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    # Test Binance credentials
    binance_key = os.getenv("BINANCE_API_KEY")
    binance_secret = os.getenv("BINANCE_API_SECRET")
    
    print("\nBinance Credentials Test:")
    print(f"Key exists: {'YES' if binance_key else 'NO'}")
    print(f"Secret exists: {'YES' if binance_secret else 'NO'}")
    print(f"Key length: {len(binance_key) if binance_key else 0}")
    print(f"Secret length: {len(binance_secret) if binance_secret else 0}")
    
    # Test Telegram credentials
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")
    
    print("\nTelegram Credentials Test:")
    print(f"Token exists: {'YES' if tg_token else 'NO'}")
    print(f"Chat ID exists: {'YES' if tg_chat else 'NO'}")
    print(f"Token starts with: {tg_token[:10] if tg_token else 'N/A'}")
    print(f"Chat ID is numeric: {tg_chat.isdigit() if tg_chat else False}")

if __name__ == "__main__":
    test_credentials()