"""Configuration handling utilities"""

import yaml
from typing import Dict, Any


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """
    Laster YAML-konfig og formaterer nødvendige felt.
    
    Args:
        path: Sti til YAML-konfigurasjonsfil
        
    Returns:
        dict: Formatert konfigurasjon
    """
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    loc_id = cfg["location_id"]

    # Formatér URL-er med riktig location_id
    cfg["urls"]["activities"] = cfg["urls"]["activities"].format(location_id=loc_id)
    cfg["urls"]["sessions"] = cfg["urls"]["sessions"].format(activity_id="{activity_id}")

    return cfg