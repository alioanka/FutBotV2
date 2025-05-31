import time
import hashlib
import hmac
from typing import Dict, Any
from datetime import datetime

def generate_signature(secret: str, data: str) -> str:
    """Generate HMAC SHA256 signature"""
    return hmac.new(
        secret.encode('utf-8'),
        data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def timestamp() -> int:
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)

def format_timestamp(ts: int) -> str:
    """Format timestamp to human-readable string"""
    return datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M:%S')

def calculate_pnl(entry_price: float, exit_price: float, quantity: float, is_long: bool) -> float:
    """Calculate profit/loss for a trade"""
    if is_long:
        return (exit_price - entry_price) * quantity
    else:
        return (entry_price - exit_price) * quantity

def filter_none_values(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from a dictionary"""
    return {k: v for k, v in data.items() if v is not None}