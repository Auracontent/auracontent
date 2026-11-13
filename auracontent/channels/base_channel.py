from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHANNELS_CONFIG_DIR = ROOT / "config" / "channels"


def load_channel_config(name: str) -> dict:
    """Charge config/channels/<name>.yaml."""
    path = CHANNELS_CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def channel_enabled(name: str) -> bool:
    """`enabled: false` dans le YAML coupe la chaîne (generate et publish) ; clé absente = activée."""
    return load_channel_config(name).get("enabled", True) is not False


class BaseChannel:
    """Une chaîne = sa config YAML + son Brain."""

    def __init__(self, name: str, brain_cls, llm):
        self.name = name
        self.cfg = load_channel_config(name)
        self.brain = brain_cls(config=self.cfg, llm=llm, channel_name=name)

    def section(self, key: str) -> dict:
        return self.cfg.get(key, {})
