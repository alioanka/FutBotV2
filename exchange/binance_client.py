import hmac
import math
import asyncio
import hashlib
import time
import logging
import ssl
import aiohttp
import pandas as pd
import json
from urllib.parse import urlencode

class BinanceClient:
    def __init__(self, api_key, api_secret, testnet=False, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Verify credentials are present
        if not api_key or not isinstance(api_key, str) or len(api_key) < 30:
            raise ValueError("Invalid Binance API key format")
        if not api_secret or not isinstance(api_secret, str) or len(api_secret) < 30:
            raise ValueError("Invalid Binance API secret format")
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        
        print(f"\nBinance Client Initialized:")
        print(f"Endpoint: {self.base_url}")
        print(f"API Key: {'*' * 20}{self.api_key[-5:]}")       
        print(f"BinanceClient initialized with key: {'*'*len(api_key)}")
        print(f"Using {'TESTNET' if testnet else 'LIVE'} environment")
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
            params['timestamp'] = int(time.time() * 1000)  # Add timestamp first
            query_string = urlencode(params)
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params['signature'] = signature
        
        # Rate limiting
        elapsed = time.time() - self.last_api_call
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        
        try:
            async with self.session.request(
                method, 
                url, 
                params=params, 
                headers=self.headers
            ) as response:
                self.last_api_call = time.time()
                
                if response.status != 200:
                    error = await response.json()
                    raise Exception(f"API Error {response.status}: {error}")
                    
                return await response.json()
                
        except Exception as e:
            self.logger.error(f"Request failed to {url}: {str(e)}")
            raise

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

    async def get_symbol_info(self, symbol):
        """Get detailed symbol information"""
        if not self.symbol_info:
            await self.load_symbol_info()
        return self.symbol_info.get(symbol, {})
    
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
        """Final robust quantity validation with proper rounding"""
        if not self.symbol_info:
            await self.load_symbol_info()
        
        info = self.symbol_info.get(symbol, {})
        filters = info.get('filters', [])
        
        for f in filters:
            if f['filterType'] == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                min_qty = float(f['minQty'])
                
                # Calculate precision from step size
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
                    
                return float(format(quantity, f".{precision}f"))
        
        return round(float(quantity), 8)
    
    async def create_order(self, symbol, side, quantity, order_type="MARKET", **kwargs):
        """Robust order creation with precision handling"""
        # Get symbol precision info
        if not self.symbol_info:
            await self.load_symbol_info()
        
        symbol_data = self.symbol_info.get(symbol, {})
        price_precision = symbol_data.get('price_precision', 2)
        quantity_precision = symbol_data.get('quantity_precision', 3)

        # Format quantities and prices
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': f"{float(quantity):.{quantity_precision}f}",
            'timestamp': str(int(time.time() * 1000)),
            'newOrderRespType': 'FULL',
            'workingType': 'MARK_PRICE',
            'priceProtect': 'true'
        }

        # Format price-related parameters
        for price_param in ['price', 'stopPrice', 'takeProfitPrice']:
            if price_param in kwargs:
                kwargs[price_param] = f"{float(kwargs[price_param]):.{price_precision}f}"

        params.update({k: str(v) for k, v in kwargs.items() if v is not None})

        try:
            return await self._request("POST", "/fapi/v1/order", params, signed=True)
        except Exception as e:
            self.logger.error(f"Order failed for {symbol}: {str(e)}")
            raise
    
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

    async def get_order(self, symbol, orderId):
        """Get order status by order ID"""
        params = {
            'symbol': symbol,
            'orderId': orderId,
            'timestamp': int(time.time() * 1000)
        }
        return await self._request("GET", "/fapi/v1/order", params, signed=True)

    async def cancel_all_orders(self, symbol):
        """Cancel all open orders for a symbol"""
        params = {
            'symbol': symbol,
            'timestamp': int(time.time() * 1000)
        }
        return await self._request("DELETE", "/fapi/v1/allOpenOrders", params, signed=True)

    async def cancel_order(self, symbol, orderId):
        """Cancel specific order"""
        params = {
            'symbol': symbol,
            'orderId': orderId,
            'timestamp': int(time.time() * 1000)
        }
        return await self._request("DELETE", "/fapi/v1/order", params, signed=True)