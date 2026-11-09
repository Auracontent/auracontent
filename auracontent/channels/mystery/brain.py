"""Cerveau de la chaîne Mystery.

Flux : région + catégorie + format imposés par le code -> page Wikipédia réelle
-> titre écrit à partir de la page -> hooks -> script ancré sur la page -> fact-check.
"""
import random
from dataclasses import dataclass, field
from pathlib import Path

from auracontent.core.brain.base_brain import BaseBrain
from auracontent.services.scraping.wikipedia import find_candidates
from auracontent.utils.topic_tracker import (
    load_global_history,
    load_last_categories,
    load_last_regions,
    load_used_sources,
)

MOODS = {"ominous", "intriguing", "tense", "awe", "scientific", "investigation"}
ROLES = {"hook", "tension", "context", "value", "escalation", "reveal", "cta"}
TITLE_FORMATS = ["question provocante", "affirmation brute", "paradoxe frappant", "anecdote ciblée"]
MAX_WORDS_PER_SCENE = 45          # le prompt demande 20-30, on tolère jusqu'à 45


@dataclass
class MysteryBrain(BaseBrain):
    channel_name: str = "mystery"
    _source: dict | None = field(default=None, init=False, repr=False)      # page Wikipédia du sujet
    last_pick: dict = field(default_factory=dict, init=False, repr=False)   # région, catégorie, source

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).parent / "prompts"

    # ==========================================
    # SUJET
    # ==========================================
    def build_title_vars(self, used_topics, stats_text=""):
        b = self.config["brain"]

        # régions et catégories : {name, search} dans le YAML ; on compare sur 'name'
        last_regions = load_last_regions(n=b["region_lookback"], channel=self.channel_name)
        region = random.choice([r for r in b["regions"] if r["name"] not in last_regions] or b["regions"])

        last_cats = load_last_categories(n=2, channel=self.channel_name)
        category = random.choice(
            [c for c in b["theme_categories"] if c["name"] not in last_cats] or b["theme_categories"]
        )

        recent = " ".join(used_topics[-8:]).lower()
        ban_hits = sum(recent.count(w.lower()) for w in b["banned_if_recent"])
        ban_block = ""
        if ban_hits >= 2:
            ban_block = ("INTERDICTION TEMPORAIRE STRICTE : ces concepts ont été trop utilisés : "
                         + ", ".join(b["banned_if_recent"]) + ". N'utilise AUCUN de ces mots ni concepts.")

        used_block = ""
        if used_topics:
            used_block = ("SUJETS DÉJÀ TRAITÉS (propose un angle, un vocabulaire et un format "
                          "radicalement différents) :\n- " + "\n- ".join(used_topics[-30:]))

        return {
            "forced_region": region["name"],
            "forced_category": category["name"],
            "forced_format": random.choice(TITLE_FORMATS),   # tiré par le code : le LLM ne peut pas "alterner"
            "ban_block": ban_block,
            "stats_block": stats_text,
            "used_topics_block": used_block,
        }, region, category, ban_hits

    def pick_topic(self, max_attempts: int = 5, previous_stats_list=None) -> str:
        """Retourne le titre. La page source et la région sont gardées dans self._source / self.last_pick."""
        used = load_global_history()
        used_sources = load_used_sources()
        stats_text = self._stats_text(previous_stats_list)

        for attempt in range(1, max_attempts + 1):
            title_vars, region, category, _ = self.build_title_vars(used, stats_text)
            source = self._find_source(region, category, used_sources)
            if source is None:
                print(f"   ↻ Essai {attempt}/{max_attempts} : aucune page Wikipédia exploitable "
                      f"({category['name']} / {region['name']}).")
                continue

            title = self._write_title(title_vars, source)
            if not title:
                continue

            is_dup, matched = self.is_duplicate_topic_llm(title, used)
            if is_dup:
                print(f"   ↻ Doublon avec « {matched} », nouvel essai.")
                continue

            self._source = source
            self.last_pick = {"region": region["name"], "category": category["name"],
                              "source_title": source["title"], "source_url": source["url"]}
            return title

        raise RuntimeError(f"Aucun sujet valide trouvé après {max_attempts} tentatives.")

    def _find_source(self, region, category, used_sources):
        query = f'{random.choice(category["search"])} {random.choice(region["search"])}'
        print(f"   🔎 Wikipédia : « {query} »")
        candidates = find_candidates(query, limit=8, exclude=used_sources)
        return self._choose_source(candidates, region, category) if candidates else None

    def _choose_source(self, candidates, region, category):
        """Le LLM retient la page qui raconte un fait précis de la catégorie, dans la région (ou aucune)."""
        listing = "\n".join(f'{i}. {c["title"]} : {c["extract"][:400]}' for i, c in enumerate(candidates))
        prompt = (
            f"CATÉGORIE : {category['name']}\nRÉGION : {region['name']}\n\nPAGES WIKIPÉDIA :\n{listing}\n\n"
            "Choisis la page qui raconte un fait, un événement, un objet ou une personne PRÉCIS appartenant "
            "à cette catégorie et situé dans cette région, avec assez de matière pour une vidéo d'une minute. "
            "Exclus les articles généralistes (ville, département, région, biographie de personnalité connue). "
            'Si aucune ne convient, réponds -1. Réponds uniquement en JSON : {"index": <entier>}'
        )
        try:
            data = self.llm.call_json_with_retry([{"role": "user", "content": prompt}],
                                                 temperature=0, max_completion_tokens=100)
            idx = int(data.get("index", -1))
        except (RuntimeError, ValueError, TypeError) as e:
            print(f"⚠️ Choix de la source impossible : {e}")
            return None
        return candidates[idx] if 0 <= idx < len(candidates) else None

    def _write_title(self, title_vars, source):
        sections = self.read_sections("titles.md")
        source_block = f'SOURCE ({source["title"]}) :\n"""{source["extract"][:3000]}"""'
        user = self.fill(sections["user"], source_block=source_block, **title_vars)
        data = self.llm.call_json_with_retry(
            [{"role": "system", "content": sections["system"]}, {"role": "user", "content": user}],
            temperature=1.0, max_completion_tokens=200,
        )
        title = str(data.get("title", "")).strip().strip('"«» ')
        if not title or len(title.split()) > 18:
            print(f"   ↻ Titre rejeté : {title!r}")
            return None
        return title

    # ==========================================
    # HOOKS
    # ==========================================
    @staticmethod
    def _stats_text(previous_stats_list):
        if not previous_stats_list:
            return ""
        return ("STATS DES VIDÉOS PRÉCÉDENTES (inspire-toi de ce qui fonctionne) :\n"
                + "\n".join(f"- {s}" for s in previous_stats_list[:5]))

    def generate_hook_variants(self, topic, n=5, previous_stats_list=None):
        sections = self.read_sections("hook.md")
        user = self.fill(sections["user"], n=n, topic=topic, grounding_block=self._grounding(),
                         stats_block=self._stats_text(previous_stats_list))
        data = self.llm.call_json_with_retry(
            [{"role": "system", "content": self.fill(sections["system"], n=n)},
             {"role": "user", "content": user}],
            temperature=1.0, max_completion_tokens=1500,
        )
        # le LLM dépasse parfois la limite de 12 mots : on filtre
        hooks = [h for h in data.get("hooks", [])
                 if isinstance(h, dict) and h.get("text") and len(h["text"].split()) <= 14]
        return hooks[:n] or [{"text": str(topic), "pattern": "default", "raison": ""}]

    # ==========================================
    # SCRIPT
    # ==========================================
    def _grounding(self) -> str:
        if not self._source:
            return ("Aucune source fournie : n'avance ni date, ni chiffre, ni nom "
                    "que tu ne peux pas garantir.")
        return f'SOURCE VÉRIFIÉE ({self._source["title"]}) :\n"""{self._source["extract"][:6000]}"""'

    def build_script_prompt(self, topic, scene_count, chosen_hook, correction_feedback=""):
        hook = chosen_hook.get("text", "") if isinstance(chosen_hook, dict) else (chosen_hook or "")
        sections = self.read_sections("script.md")

        # {scene_count} est dans le prompt système : on le remplit aussi, et on y ajoute les règles de véracité
        system = self.fill(sections["system"], scene_count=scene_count)
        system += "\n\n" + self.read_prompt("veracity.md")

        user = self.fill(
            sections["user"],
            topic=topic, scene_count=scene_count, chosen_hook=hook,
            grounding_block=self._grounding(),
            rehook_scene=-(-scene_count // 3),      # tiers du script, arrondi au supérieur
        )
        if correction_feedback:
            user += "\n\n" + correction_feedback
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ==========================================
    # VALIDATION
    # ==========================================
    def validate_script_specifics(self, data, topic):
        if not str(data.get("closing_cta", "")).strip():
            raise ValueError("champ 'closing_cta' manquant.")

        for scene in data["scenes"]:
            sid = scene["id"]
            words = len(str(scene["text"]).split())
            if words > MAX_WORDS_PER_SCENE:
                raise ValueError(f"scène {sid} : {words} mots, maximum {MAX_WORDS_PER_SCENE} (vise 20 à 30).")
            if scene.get("location_name") and not str(scene.get("location_country", "")).strip():
                raise ValueError(f"scène {sid} : 'location_country' manquant pour '{scene['location_name']}'.")
            if scene.get("mood") not in MOODS:
                scene["mood"] = "intriguing"
            if scene.get("role") not in ROLES:
                scene["role"] = "context"

    def check_script_logic(self, topic, data):
        scenes = data["scenes"]
        return self._check_geo(scenes) + self._llm_factcheck(topic, scenes, data)

    def _check_geo(self, scenes):
        """Tous les lieux doivent être dans le pays attendu (brain.country dans le YAML)."""
        expected = str(self.config.get("brain", {}).get("country", "")).strip().lower()
        if not expected:
            return []
        issues = []
        for s in scenes:
            country = str(s.get("location_country") or "").strip().lower()
            if s.get("location_name") and country and country != expected:
                issues.append(f"scène {s['id']} : lieu « {s['location_name']} » en {s['location_country']}, "
                              f"attendu : {self.config['brain']['country']}.")
        return issues

    @staticmethod
    def _scenes_text(scenes):
        # texte intégral : résumer ferait disparaître les faits à vérifier
        return "\n".join(f"[scène {s['id']}] {s['text']}" for s in scenes)

    def _llm_factcheck(self, topic, scenes, data):
        text = self._scenes_text(scenes)
        grounded = bool(self._source and self._source.get("extract"))
        if grounded:
            sec = self.read_sections("factcheck_grounded.md")
            user = self.fill(sec["user"], source_title=self._source["title"],
                             source_extract=self._source["extract"][:6000], scenes_text=text)
        else:
            sec = self.read_sections("factcheck_ungrounded.md")
            user = self.fill(sec["user"], topic=topic, scenes_text=text)

        try:
            res = self.llm.call_json_with_retry(
                [{"role": "system", "content": sec["system"]}, {"role": "user", "content": user}],
                temperature=0, max_completion_tokens=500,
            )
        except Exception as e:
            print(f"⚠️ Fact-check indisponible : {e}")
            data["factcheck"] = "skipped"
            return []

        # sans source, un LLM ne repère que les contradictions internes : à traiter comme "non vérifié"
        data["factcheck"] = "grounded" if grounded else "ungrounded"
        # seule la liste 'issues' fait foi (is_consistent peut la contredire)
        return [str(i).strip() for i in res.get("issues", []) if str(i).strip()]