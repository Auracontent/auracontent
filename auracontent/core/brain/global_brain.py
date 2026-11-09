# auracontent/core/brain/global_brain.py
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.registry import CHANNEL_REGISTRY
from auracontent.core.brain.llm_client import LLMClient
from auracontent.utils.topic_tracker import save_global_history
from config import settings


@dataclass
class GlobalBrain:
    llm_client: LLMClient
    output_dir: Path = settings.OUTPUT_DIR / "scripts"
    channels: dict[str, BaseChannel] = field(default_factory=dict, init=False)

    def __post_init__(self):
        """Instancie chaque chaîne du registre avec SA config YAML et le client LLM partagé."""
        self.channels = {
            name: BaseChannel(name, brain_cls, self.llm_client)
            for name, brain_cls in CHANNEL_REGISTRY.items()
        }
        print(f"🌍 GlobalBrain initialisé avec {len(self.channels)} chaîne(s) active(s).")

    # ==========================================
    # MÉTHODES D'ORCHESTRATION
    # ==========================================

    def run_channel(self, channel_name: str, previous_stats_list=None) -> Path:
        """Sujet -> hooks -> script pour une chaîne. Retourne le chemin du script JSON sauvegardé."""
        if channel_name not in self.channels:
            raise ValueError(f"Chaîne inconnue : {channel_name}. Vérifiez channels/registry.py.")
        brain = self.channels[channel_name].brain
        print(f"\n🚀 Démarrage de la chaîne : {channel_name.upper()}")

        # 1. Sujet (l'anti-doublon sur l'historique global est fait dans pick_topic)
        topic = brain.pick_topic()
        print(f"🎯 Sujet retenu : {topic}")

        # 2. Accroche
        hooks = brain.generate_hook_variants(topic, n=5, previous_stats_list=previous_stats_list)
        chosen_hook = hooks[0]
        print(f"🪝 Accroche : {chosen_hook.get('text')}")

        # 3. Script
        script = brain.generate_script(topic, chosen_hook=chosen_hook)
        pick = dict(getattr(brain, "last_pick", {}) or {})
        script.update({"topic": topic, "channel": channel_name, "hook": chosen_hook,
                       "hook_variants": hooks, "pick": pick})

        # 4. Sauvegarde du script puis de l'historique (seulement si tout a réussi)
        path = self._save_script(channel_name, script)
        save_global_history(topic, channel_name, script_path=str(path), **pick)
        print(f"✅ Script sauvegardé : {path}")
        return path

    def run_all(self) -> dict[str, Path | None]:
        """Lance séquentiellement toutes les chaînes actives."""
        print("\n🌍 Lancement de la production multi-chaînes")
        results = {}
        for name in self.channels:
            try:
                results[name] = self.run_channel(name)
            except Exception as e:
                print(f"❌ Échec critique sur la chaîne {name} : {e}")
                results[name] = None
        return results

    def _save_script(self, channel_name: str, script: dict) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"{channel_name}_{stamp}.json"
        path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
