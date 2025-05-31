from utils.config_loader import load_config
from utils.notifier import TelegramNotifier

def test_passthrough():
    print("Testing credential passthrough...")
    config = load_config()
    
    print("\nDirect from config:")
    print(f"Token type: {type(config['telegram']['bot_token'])}")
    print(f"Token length: {len(config['telegram']['bot_token'])}")
    
    try:
        print("\nAttempting to create notifier...")
        notifier = TelegramNotifier(
            config['telegram']['bot_token'],
            config['telegram']['chat_id']
        )
        print("SUCCESS: Notifier created!")
    except Exception as e:
        print(f"FAILED: {str(e)}")

if __name__ == "__main__":
    test_passthrough()