"""Brain de la chaîne finance « Capital Simple » (les chiffres, sans jargon).

Même principe que mystery : sujet -> accroches notées (bandit) -> script contrôlé, régénéré tant qu'un
contrôle échoue. Différence : le sujet n'est pas une page Wikipédia mais un CONCEPT permanent (intérêts
composés, inflation...) avec des PARAMÈTRES (âges, taux, durées, montants). Les résultats chiffrés viennent
de calc.py (phase 2) : le LLM n'écrit jamais un nombre absent des données d'entrée.
"""
from __future__ import annotations

import itertools
import random
import re
import unicodedata
from pathlib import Path

from auracontent.core.brain.base_brain import BaseBrain
from auracontent.utils.topic_tracker import load_global_history, load_last_categories, load_used_values

TEMPLATES = ("deux_arbres", "deux_courbes", "barres", "curseur_temps", "carte_fin")
PARAM_LABELS = {
    "early_age": "âge de départ de Léa", "late_age": "âge de départ de Hugo", "early_amount": "mise de Léa (€)",
    "late_amount": "mise de Hugo (€)", "rate": "rendement moyen (% par an)", "end_age": "âge d'arrivée",
    "amount": "montant de départ (€)", "inflation": "inflation (% par an)", "years": "durée (années)",
    "monthly": "versement mensuel (€)", "delay_years": "années d'attente avant de commencer",
    "horizon_years": "durée totale (années)", "fees": "frais (% par an)",
    "late_amount_factor": "Hugo met ce nombre de fois plus que Léa",
}
_WORD_RE = re.compile(r"[\wÀ-ÿ\u2019'-]+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?")
# fin de phrase : . ! ? (ou …) suivi d'une majuscule ; « … et finir » continue la même phrase
_SENTENCE_END_RE = re.compile(r"(?<=[.!?\u2026])\s+(?=[A-Z\u00c0-\u00dd\u00ab])")
_SPECIAL_CHARS = {"\u202f": " ", "\u00a0": " ", "\u2011": "-", "\u2010": "-"}


# ---------- Texte ----------
def clean_text(text: str) -> str:
    """Texte conservé : espaces fines/insécables -> espace, tirets insécables -> « - », espaces réduits."""
    text = str(text or "")
    for char, repl in _SPECIAL_CHARS.items():
        text = text.replace(char, repl)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(text: str) -> str:
    """Forme normalisée pour toute comparaison : NFKC, puis clean_text."""
    return clean_text(unicodedata.normalize("NFKC", str(text or "")))


def comparable(text: str) -> str:
    """Forme de comparaison : normalisée, minuscules, sans accents ni ponctuation finale."""
    text = unicodedata.normalize("NFD", normalize_title(text).casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.rstrip(" .!?")


def count_words(text: str) -> int:
    return len([w for w in _WORD_RE.findall(normalize_title(text)) if any(c.isalnum() for c in w)])


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END_RE.split(clean_text(text)) if count_words(s)]


def numbers_in(text: str) -> list[float]:
    """Nombres écrits en chiffres (« 1 630 », « 7 », « 0,5 »)."""
    found = []
    for raw in _NUMBER_RE.findall(normalize_title(text)):
        found.append(float(re.sub(r"\s", "", raw).replace(",", ".")))
    return found


def _fold(text: str) -> str:
    return comparable(text)


def contains_term(text: str, term: str) -> bool:
    """Terme interdit présent (mots entiers, sans casse ni accents)."""
    return re.search(rf"(?<![\w]){re.escape(_fold(term))}(?![\w])", _fold(text)) is not None


def _fmt(value) -> str:
    return f"{value:g}".replace(".", ",") if isinstance(value, float) else str(value)


# ---------- Brain ----------
class FinanceBrain(BaseBrain):
    last_pick: dict | None = None

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).parent / "prompts"

    def _brain(self) -> dict:
        return self.config.get("brain", {})

    def style_cfg(self) -> dict:
        cfg = dict(self._brain().get("style") or {})
        cfg.setdefault("max_sentence_words", 12)
        cfg.setdefault("max_hook_words", 12)
        cfg.setdefault("banned_words", [])
        return cfg

    # ---------- Concepts et paramètres ----------
    @staticmethod
    def resolve_params(concept: str, raw: dict) -> dict | None:
        """Paramètres effectifs (dérivés compris), ou None si la combinaison n'a pas de sens."""
        params = dict(raw)
        if concept == "interets_composes":
            params["late_amount"] = params["early_amount"] * params["late_amount_factor"]
            if params["late_age"] - params["early_age"] < 15 or params["end_age"] - params["late_age"] < 15:
                return None
        if concept == "cout_du_temps" and params["delay_years"] >= params["horizon_years"] / 2:
            return None
        return params

    @staticmethod
    def topic_key(concept: str, params: dict) -> str:
        """Clé de déduplication : concept + paramètres (ordre des clés indifférent)."""
        return concept + ":" + ",".join(f"{k}={_fmt(params[k])}" for k in sorted(params))

    def combinations(self, concept: str) -> list[dict]:
        spec = self._brain()["concepts"][concept].get("params", {})
        names = list(spec)
        combos = []
        for values in itertools.product(*(spec[n] for n in names)):
            params = self.resolve_params(concept, dict(zip(names, values, strict=True)))
            if params is not None:
                combos.append(params)
        return combos

    @staticmethod
    def describe(concept: str, p: dict) -> str:
        """Sujet lisible (sert de titre interne et d'entrée aux prompts)."""
        if concept == "interets_composes":
            return (f"Intérêts composés : {p['early_amount']} € placés à {p['early_age']} ans contre "
                    f"{p['late_amount']} € à {p['late_age']} ans, {_fmt(p['rate'])} %/an, jusqu'à {p['end_age']} ans")
        if concept == "inflation":
            return (f"Inflation : {p['amount']} € qui dorment pendant {p['years']} ans "
                    f"avec {_fmt(p['inflation'])} % d'inflation par an")
        if concept == "cout_du_temps":
            return (f"Coût du temps : {p['monthly']} € par mois sur {p['horizon_years']} ans à {_fmt(p['rate'])} %/an, "
                    f"en commençant tout de suite ou {p['delay_years']} ans plus tard")
        if concept == "frais":
            return (f"Frais : {p['amount']} € à {_fmt(p['rate'])} %/an pendant {p['years']} ans, "
                    f"avec ou sans {_fmt(p['fees'])} % de frais par an")
        if concept == "regle_72":
            return f"Règle des 72 : à {_fmt(p['rate'])} %/an, en combien d'années ton argent double-t-il ?"
        raise KeyError(concept)

    @staticmethod
    def hypothesis(concept: str, p: dict) -> str:
        """Hypothèse affichée à l'écran (« 7 %/an · versement unique », « avant inflation »...)."""
        if concept == "interets_composes":
            return f"{_fmt(p['rate'])} %/an · versement unique · avant inflation"
        if concept == "inflation":
            return f"inflation de {_fmt(p['inflation'])} %/an · argent non placé"
        if concept == "cout_du_temps":
            return f"{_fmt(p['rate'])} %/an · versements mensuels · avant inflation"
        if concept == "frais":
            return f"{_fmt(p['rate'])} %/an avant frais · versement unique · avant inflation"
        if concept == "regle_72":
            return f"{_fmt(p['rate'])} %/an · gains réinvestis · approximation"
        raise KeyError(concept)

    def pick_topic(self) -> str:
        """Concept absent des dernières vidéos, puis une combinaison de paramètres jamais traitée."""
        b = self._brain()
        concepts = list(b.get("concepts") or {})
        if not concepts:
            raise RuntimeError("brain.concepts vide dans config/channels/finance.yaml")
        used = load_used_values("topic_key", channel=self.channel_name)
        used_titles = {comparable(t) for t in load_global_history(self.channel_name)}
        recent = set(load_last_categories(int(b.get("recent_concepts_window", 2)), channel=self.channel_name))
        random.shuffle(concepts)
        ordered = [c for c in concepts if c not in recent] + [c for c in concepts if c in recent]
        for concept in ordered:
            if concept in recent and len(ordered) > len(recent):
                print(f"   ↻ Concept écarté : « {concept} » traité dans les {len(recent)} dernières vidéos.")
                continue
            combos = self.combinations(concept)
            random.shuffle(combos)
            for params in combos:
                key = self.topic_key(concept, params)
                topic = self.describe(concept, params)
                if key in used:
                    continue
                if comparable(topic) in used_titles:
                    print(f"   ↻ Sujet écarté (titre déjà traité) : {topic}")
                    continue
                self.last_pick = {"category": concept, "concept": concept, "topic_key": key, "params": params}
                return topic
            print(f"   ↻ Concept épuisé : toutes les combinaisons de « {concept} » sont déjà traitées.")
        raise RuntimeError("Aucune combinaison concept + paramètres inédite.")

    def export_state(self) -> dict:
        return {"last_pick": self.last_pick}

    def restore_state(self, state: dict) -> None:
        self.last_pick = dict((state or {}).get("last_pick") or {}) or None

    def _pick(self) -> tuple[str, dict, dict]:
        if not self.last_pick:
            raise RuntimeError("Aucun concept choisi (pick_topic d'abord).")
        concept = self.last_pick["concept"]
        return concept, self.last_pick["params"], self._brain()["concepts"][concept]

    def allowed_numbers(self) -> set[float]:
        """Nombres que le texte peut citer : les données d'entrée (phase 2 : + sorties de calc.py)."""
        _, params, spec = self._pick()
        return {float(v) for v in [*params.values(), *(spec.get("constants") or [])]}

    # ---------- Accroches ----------
    def hook_issues(self, text: str, topic: str) -> list[str]:
        cfg, issues = self.style_cfg(), []
        words = count_words(text)
        if not words:
            issues.append("accroche vide")
        if words > int(cfg["max_hook_words"]):
            issues.append(f"{words} mots (maximum {cfg['max_hook_words']})")
        if comparable(text) == comparable(topic):
            issues.append("identique au sujet")
        issues += self.text_issues(text, "l'accroche")
        return issues

    def generate_hook_variants(self, topic, n=5, previous_stats_list=None):
        concept, _, spec = self._pick()
        sections = self.read_sections("hook.md")
        cfg = self.style_cfg()
        values = dict(topic=topic, concept_label=spec.get("label", concept), idea=spec.get("idea", ""), n=n,
                      max_hook_words=cfg["max_hook_words"],
                      allowed_numbers=", ".join(_fmt(v) for v in sorted(self.allowed_numbers())))
        valid = []
        for attempt in range(2):
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], **values)},
                 {"role": "user", "content": self.fill(sections["user"], **values)}],
                temperature=1.0, max_completion_tokens=1500, **self.simple_routing())
            for hook in data.get("hooks", []):
                if not isinstance(hook, dict) or not str(hook.get("text", "")).strip():
                    continue
                hook["text"] = clean_text(hook["text"])
                issues = self.hook_issues(hook["text"], topic)
                if issues:
                    print(f"   ↻ Accroche rejetée ({'; '.join(issues)}) : « {hook['text']} »")
                    continue
                valid.append(hook)
            if valid:
                return valid[:n]
            print(f"   ↻ Aucune accroche valable (essai {attempt + 1}/2).")
        raise RuntimeError("Aucune accroche valable après 2 essais.")

    # ---------- Script ----------
    def build_script_prompt(self, topic, scene_count, chosen_hook, correction_feedback=""):
        concept, params, spec = self._pick()
        cfg = self.style_cfg()
        sections = self.read_sections("script.md")
        values = dict(
            topic=topic, concept_label=spec.get("label", concept), idea=spec.get("idea", ""),
            hypothesis=self.hypothesis(concept, params),
            params_block="\n".join(f"- {PARAM_LABELS.get(k, k)} : {_fmt(v)}" for k, v in params.items()),
            chosen_hook=(chosen_hook or {}).get("text", ""), scene_count=scene_count,
            max_sentence_words=cfg["max_sentence_words"], templates=", ".join(f'"{t}"' for t in TEMPLATES),
        )
        user = self.fill(sections["user"], **values)
        if correction_feedback:
            user += f"\n\n{correction_feedback}"
        return [{"role": "system", "content": self.fill(sections["system"], **values)},
                {"role": "user", "content": user}]

    def validate_script_specifics(self, data, topic):
        """Structure : bandeau en deux segments, hypothèse exacte, accroche en tête, gabarits connus."""
        concept, params, _ = self._pick()
        title = clean_text(data.get("on_screen_title", ""))
        parts = [p.strip() for p in title.split("|")]
        if len(parts) != 2 or not all(parts):
            raise ValueError("on_screen_title doit avoir la forme « AFFIRMATION | PUNCHLINE ».")
        too_long = [p for p in parts if len(p) > 20]
        if too_long:
            raise ValueError(f"segment du bandeau de plus de 20 caractères : « {too_long[0]} ».")
        data["on_screen_title"] = " | ".join(parts)
        data["hypothesis"] = self.hypothesis(concept, params)          # jamais reformulée par le LLM
        if not str(data.get("closing_cta", "")).strip():
            raise ValueError("closing_cta manquant.")
        for scene in data["scenes"]:
            scene["text"] = clean_text(scene["text"])
            if scene.get("template") not in TEMPLATES:
                raise ValueError(f"scène {scene.get('id')} : template inconnu « {scene.get('template')} ».")
            scene.setdefault("voice_type", "narrator")
        hook = (self.chosen_hook_text or "").strip()
        if hook and not comparable(data["scenes"][0]["text"]).startswith(comparable(hook)):
            raise ValueError("la scène 1 doit commencer mot pour mot par l'accroche obligatoire.")

    chosen_hook_text: str | None = None

    def generate_script(self, topic, chosen_hook=None):
        self.chosen_hook_text = (chosen_hook or {}).get("text")
        return super().generate_script(topic, chosen_hook=chosen_hook)

    def text_issues(self, text: str, what: str) -> list[str]:
        """Contrôles de fond communs aux accroches, au bandeau et à la narration."""
        b, cfg, issues = self._brain(), self.style_cfg(), []
        for term in [*cfg["banned_words"], *(b.get("banned_names") or [])]:
            if contains_term(text, term):
                issues.append(f"{what} contient « {term} » (interdit)")
        if re.search(r"\b(vous|votre|vos)\b", _fold(text)):
            issues.append(f"{what} vouvoie (tutoiement obligatoire)")
        allowed = self.allowed_numbers()
        extra = sorted({n for n in numbers_in(text) if n not in allowed})
        if extra:
            issues.append(f"{what} cite un nombre non autorisé : {', '.join(_fmt(n) for n in extra)}")
        return issues

    def check_script_logic(self, topic, data):
        """Style et fond : phrases courtes, aucun terme interdit, tutoiement, aucun nombre inventé."""
        cfg, issues = self.style_cfg(), []
        limit = int(cfg["max_sentence_words"])
        for scene in data.get("scenes", []):
            for sentence in sentences(scene.get("text", "")):
                if count_words(sentence) > limit:
                    issues.append(f"scène {scene.get('id')} : phrase de {count_words(sentence)} mots "
                                  f"(maximum {limit}) : « {sentence} »")
            issues += self.text_issues(scene.get("text", ""), f"la scène {scene.get('id')}")
        for key, what in (("on_screen_title", "le bandeau"), ("closing_cta", "la question finale"),
                          ("title", "le titre")):
            issues += self.text_issues(str(data.get(key, "")), what)
        if count_words(data.get("closing_cta", "")) > limit:
            issues.append(f"la question finale dépasse {limit} mots")
        for issue in issues:
            print(f"   ↻ Script : {issue}")
        return issues
