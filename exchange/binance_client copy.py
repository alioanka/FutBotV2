import hmac
import math
import asyncio
import hashlib
import time
import ssl
import aiohttp
import pandas as pd
import json
from urllib.parse import urlencode

class BinanceClient:
    def __init__(self, api_key, api_secret, testnet=False):

        print(f"BinanceClient received API key: {api_key}")
        print(f"BinanceClient received API secret: {api_secret}")
        if not api_key or not api_secret:
            raise ValueError("Binance API key and secret must be provided")
        
        # Clean the keys
        #self.api_key = ''.join(c for c in api_key.strip() if c.isalnum())
        #self.api_secret = ''.join(c for c in api_secret.strip() if c.isalnum())

        self.api_key = api_key
        self.api_secret = api_secret
        
        if len(self.api_key) < 30 or len(self.api_secret) < 30:
            raise ValueError("API keys appear to be invalid - too short after cleaning")
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = None
        self.symbol_info = {}
        self.last_api_call = 0
        self.rate_limit = 0.1
        self.headers = {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        }
        self.recv_window = 5000  # Binance's recommended value

    async def _request(self, method, endpoint, params=None, signed=False):
        url = f"{self.base_url}{endpoint}"
        
        if signed:
            params = params or {}
            params['timestamp'] = int(time.time() * 1000)
            query_string = urlencode(params)
            # Handle encoding here instead
            signature = hmac.new(
                self.api_secret.encode('utf-8'),  # Encode here
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params['signature'] = signature
        
        # Rate limiting
        elapsed = time.time() - self.last_api_call
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        
        async with self.session.request(method, url, params=params, headers=self.headers) as response:
            self.last_api_call = time.time()
            if response.status != 200:
                error = await response.text()
                raise Exception(f"API Error {response.status}: {error}")
            return await response.json()

    async def initialize(self):
        # Create custom SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context),
            headers={"X-MBX-APIKEY": self.api_key}
        )
        await self.load_symbol_info()
        
    async def load_symbol_info(self):
        data = await self._request("GET", "/fapi/v1/exchangeInfo")
        for symbol in data['symbols']:
            self.symbol_info[symbol['symbol']] = {
                'price_precision': symbol['pricePrecision'],
                'quantity_precision': symbol['quantityPrecision'],
                'filters': symbol['filters']
            }
    
    async def get_precision(self, symbol):
        if not self.symbol_info:
            await self.load_symbol_info()
        
        info = self.symbol_info.get(symbol, {})
        filters = info.get('filters', [])
        
        # Find LOT_SIZE filter
        for f in filters:
            if f['filterType'] == 'LOT_SIZE':
                step_size = f['stepSize']
                # Calculate precision from step size
                if '.' in step_size:
                    return len(step_size.split('.')[1].rstrip('0'))
                return 0
        return 8  # Default if not found
    
    async def validate_quantity(self, symbol, quantity):
        """Final robust quantity validation"""
        if not self.symbol_info:
            await self.load_symbol_info()
        
        info = self.symbol_info.get(symbol, {})
        filters = info.get('filters', [])
        
        for f in filters:
            if f['filterType'] == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                min_qty = float(f['minQty'])
                
                # Calculate exact precision from step size
                if step_size >= 1:
                    precision = 0
                else:
                    precision = len(f['stepSize'].split('.')[1].rstrip('0'))
                
                # Round to exact step size multiple
                quantity = float(quantity)
                quantity = round(quantity / step_size) * step_size
                quantity = round(quantity, precision)
                
                # Ensure meets minimum
                if quantity < min_qty:
                    quantity = min_qty
                    quantity = round(quantity / step_size) * step_size
                    quantity = round(quantity, precision)
                    
                return float(format(quantity, f".{precision}f"))  # Ensure exact string representation
        
        return round(float(quantity), 8)
    
    async def create_order(self, symbol, side, quantity, order_type="MARKET", 
                         stop_price=None, take_profit_price=None, stop_loss_price=None, **kwargs):
        # Verify quantity precision
        precision = await self.get_precision(symbol)
        quantity = round(float(quantity), precision)
        
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity,
            **kwargs
        }
        
        # Binance Futures requires timestamp
        params['timestamp'] = int(time.time() * 1000)
        
        if order_type == "STOP_MARKET":
            params['stopPrice'] = stop_price
        elif order_type == "TAKE_PROFIT_MARKET":
            params['stopPrice'] = take_profit_price
            
        return await self._request("POST", "/fapi/v1/order", params, signed=True)
    
    async def create_bracket_order(self, symbol, side, quantity, 
                                 take_profit_prices, stop_loss_price):
        # Create parent order
        parent_order = await self.create_order(symbol, side, quantity, "MARKET")
        
        if not parent_order:
            return None
            
        # Create OCO orders
        stop_order = await self.create_order(
            symbol,
            "SELL" if side == "BUY" else "BUY",
            quantity,
            "STOP_MARKET",
            stop_price=stop_loss_price
        )
        
        take_profit_orders = []
        for tp in take_profit_prices:
            tp_order = await self.create_order(
                symbol,
                "SELL" if side == "BUY" else "BUY",
                quantity * (tp['percentage'] / 100),
                "TAKE_PROFIT_MARKET",
                take_profit_price=tp['price']
            )
            take_profit_orders.append(tp_order)
            
        return {
            'parent_order': parent_order,
            'stop_order': stop_order,
            'take_profit_orders': take_profit_orders
        }
    
    async def get_account_balance(self):
        data = await self._request("GET", "/fapi/v2/account", signed=True)
        return {asset['asset']: float(asset['availableBalance']) 
                for asset in data['assets']}
    
    async def get_position_risk(self):
        return await self._request("GET", "/fapi/v2/positionRisk", signed=True)
    
    async def change_leverage(self, symbol, leverage):
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        return await self._request("POST", "/fapi/v1/leverage", params, signed=True)
    
    async def close_all_positions(self):
        positions = await self.get_position_risk()
        results = []
        for position in positions:
            if float(position['positionAmt']) != 0:
                side = "SELL" if float(position['positionAmt']) > 0 else "BUY"
                quantity = abs(float(position['positionAmt']))
                result = await self.create_order(
                    position['symbol'], 
                    side, 
                    quantity, 
                    "MARKET"
                )
                results.append(result)
        return results

    async def get_klines(self, symbol, interval="1m", limit=100):
        endpoint = "/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = await self._request("GET", endpoint, params)
        
        # Convert to DataFrame
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'count', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])
        
        # Convert to numeric
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)
        
        return df

    async def close(self):
        if self.session:
            await self.session.close()

    async def get_min_qty(self, symbol):
        """Get minimum order quantity for a symbol"""
        if not self.symbol_info:
            await self.load_symbol_info()
        
        info = self.symbol_info.get(symbol, {})
        filters = info.get('filters', [])
        
        # Find LOT_SIZE filter
        for f in filters:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['minQty'])
        
        return 0.001  # Default minimum if not found