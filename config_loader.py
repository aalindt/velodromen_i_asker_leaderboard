import yaml

def load_config(path: str = "config.yaml") -> dict:
    """Laster YAML-konfig og formaterer nødvendige felt."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    loc_id = cfg["location_id"]

    # Formatér URL-er med riktig location_id
    cfg["urls"]["activities"] = cfg["urls"]["activities"].format(location_id=loc_id)
    cfg["urls"]["sessions"] = cfg["urls"]["sessions"].format(activity_id="{activity_id}")

    return cfg
