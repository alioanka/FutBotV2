import os
from dotenv import load_dotenv
from exchange.binance_client import BinanceClient
import asyncio

# Load environment variables
load_dotenv()

async def test_connection():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        print("Error: API keys not found in .env file")
        print(f"BINANCE_API_KEY exists: {api_key is not None}")
        print(f"BINANCE_API_SECRET exists: {api_secret is not None}")
        return

    print(f"Using API Key: {api_key[:5]}...{api_key[-5:]}")
    
    client = BinanceClient(
        api_key=api_key,
        api_secret=api_secret,
        testnet=True
    )
    
    try:
        await client.initialize()
        print("Testing connection...")
        ticker = await client._request("GET", "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        print("Success! Current BTC price:", ticker['price'])
    except Exception as e:
        print("Connection failed:", str(e))
    finally:
        await client.close()

asyncio.run(test_connection())