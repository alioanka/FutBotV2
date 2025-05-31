import aiohttp
import json
from datetime import datetime
from typing import Dict, Any
import ssl
import logging

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        # Debug input values immediately
        print(f"\nRaw Telegram Token Input: {bot_token}")
        print(f"Raw Chat ID Input: {chat_id}")
        
        # Verify credentials with proper validation
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError(f"Invalid Telegram bot token: type={type(bot_token)}, value={repr(bot_token)}")
        if len(bot_token) < 10:
            raise ValueError(f"Token too short: {len(bot_token)} chars")
        
        # Removed the check for token starting with 5 or 6 since modern tokens can start with other digits
        
        if not chat_id or not isinstance(chat_id, str):
            raise ValueError(f"Invalid chat ID: type={type(chat_id)}, value={repr(chat_id)}")
        if not chat_id.strip().isdigit():
            raise ValueError(f"Chat ID must be numeric: {chat_id}")

        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        
        print(f"\nVerified Telegram Credentials:")
        print(f"Token: {'*'*(len(self.bot_token)-4)}{self.bot_token[-4:]}")
        print(f"Chat ID: {self.chat_id}")
        
        # SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context)
        )
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        print(f"\nTelegram Notifier Initialized:")
        print(f"Bot Token: {'*' * 20}{self.bot_token[-5:]}")
        print(f"Chat ID: {self.chat_id}")

    async def send_message(self, text: str, parse_mode: str = "HTML") -> None:
        if not self.bot_token or not self.chat_id:
            self.logger.warning("Telegram credentials not configured")
            return
            
        try:
            # Verify credentials aren't just whitespace
            if not self.bot_token.strip() or not self.chat_id.strip():
                self.logger.warning("Telegram credentials are empty")
                return
                
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            async with self.session.post(url, json=payload, timeout=5) as response:
                if response.status != 200:
                    error = await response.json()
                    self.logger.error(f"Telegram API error: {error.get('description', str(error))}")
        except Exception as e:
            self.logger.error(f"Telegram send error: {str(e)}")

    async def send_alert(self, alert_type: str, message: str, data: Dict[str, Any] = None) -> None:
        emoji = self._get_emoji(alert_type)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        text = f"{emoji} <b>{alert_type.upper()} ALERT</b>\n"
        text += f"<pre>Time: {timestamp}</pre>\n"
        text += f"{message}\n"
        
        if data:
            text += "<pre>" + "\n".join(f"{k}: {v}" for k,v in data.items()) + "</pre>"
            
        await self.send_message(text)

    async def send_trade_alert(self, trade_data: Dict[str, Any]) -> None:
        try:
            side_emoji = "🟢" if trade_data['side'].upper() == 'BUY' else "🔴"
            text = f"{side_emoji} <b>TRADE EXECUTED</b> {side_emoji}\n"
            text += f"<pre>Symbol: {trade_data['symbol']}</pre>\n"
            text += f"<pre>Side: {trade_data['side']}</pre>\n"
            text += f"<pre>Price: {trade_data.get('price', 'N/A')}</pre>\n"
            text += f"<pre>Size: {trade_data.get('quantity', 'N/A')}</pre>\n"
            text += f"<pre>Leverage: {trade_data.get('leverage', 'N/A')}x</pre>"
            
            # Ensure we're using the correct send method
            await self.send_message(text)
        except Exception as e:
            self.logger.error(f"Error sending trade alert: {str(e)}")

    def _get_emoji(self, alert_type: str) -> str:
        emojis = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '❌',
            'success': '✅',
            'emergency': '🚨',
            'trade': '💰',
            'signal': '📈'
        }
        return emojis.get(alert_type.lower(), '🔔')

    async def close(self) -> None:
        await self.session.close()

    async def test_connection(self):
        """Test Telegram connection"""
        try:
            await self.send_message("🤖 FutBotV2 connection test successful!")
            return True
        except Exception as e:
            print(f"Telegram connection failed: {str(e)}")
            return False