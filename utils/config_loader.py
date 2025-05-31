import os
from dotenv import load_dotenv
import json
from pathlib import Path

import os
from dotenv import load_dotenv
import json
from pathlib import Path

def load_config():
    # Load .env from root directory
    env_path = Path(__file__).parent.parent / '.env'
    if not env_path.exists():
        raise FileNotFoundError(f".env file not found at {env_path}")
    
    load_dotenv(dotenv_path=env_path, override=True)
    
    # Strict validation function
    def get_required_env(name):
        value = os.getenv(name)
        if not value or not value.strip():
            raise ValueError(f"Missing or empty required environment variable: {name}")
        return value.strip()

    # Build config with proper validation
    config = {
        "binance": {
            "api_key": get_required_env("BINANCE_API_KEY"),
            "api_secret": get_required_env("BINANCE_API_SECRET"),
            "testnet": os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        },
        "telegram": {
            "bot_token": get_required_env("TELEGRAM_BOT_TOKEN"),
            "chat_id": get_required_env("TELEGRAM_CHAT_ID")
        }
    }

    # Debug output - show we have the values
    print("\nConfiguration Verification:")
    print(f"Binance API Key: {'*' * 20}{config['binance']['api_key'][-5:]}")
    print(f"Binance API Secret: {'*' * 20}{config['binance']['api_secret'][-5:]}")
    print(f"Telegram Token: {'*' * 20}{config['telegram']['bot_token'][-5:]}")
    print(f"Telegram Chat ID: {config['telegram']['chat_id']}")

    # Load additional config files
    config_dir = Path(__file__).parent.parent / 'config'
    try:
        # Load pairs.json
        with open(config_dir / 'pairs.json') as f:
            pairs_config = json.load(f)
            config['pairs'] = pairs_config
        
        # Load main config.json
        with open(config_dir / 'config.json') as f:
            main_config = json.load(f)
            
            # Merge strategy config
            if 'strategy' in main_config:
                config['strategy'] = main_config['strategy']
                
            # Merge trading config
            if 'trading' in main_config:
                config['trading'] = main_config['trading']
                
            # Merge risk config
            if 'risk' in main_config:
                config['risk'] = main_config['risk']
                
    except Exception as e:
        print(f"Warning: Could not load config files: {e}")

    # Final verification
    print("\nFinal Verified Values:")
    print(f"Telegram Token Length: {len(config['telegram']['bot_token'])}")
    print(f"Chat ID Length: {len(config['telegram']['chat_id'])}")
    
    return config

def validate_binance_key(key):
    """More lenient validation for Binance API keys"""
    if not key or len(key) < 30:  # Reduced minimum length requirement
        raise ValueError("Invalid Binance API key - too short or empty")
    
    # Remove any non-alphanumeric characters before checking
    clean_key = ''.join(c for c in key if c.isalnum())
    if len(clean_key) < 30:
        raise ValueError("Invalid Binance API key - contains too many special characters")