"""Common utility functions"""

import math
import random
from typing import Optional, Dict, Any


def to_float(x: Any) -> Optional[float]:
    """Konverter til float, returner None hvis konvertering feiler."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def floor2(x: float) -> float:
    """Avrund et tall ned til 2 desimaler."""
    return math.floor(x * 100) / 100


def get_headers() -> Dict[str, str]:
    """Generer standard headers med random User-Agent."""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.88 Safari/537.36"
    ]
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": random.choice(user_agents),
        "Referer": "https://sporthive.com/",
        "Origin": "https://sporthive.com",
    }