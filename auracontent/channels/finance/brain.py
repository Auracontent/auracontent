"""Brain de la chaîne finance « Capital Simple » (les chiffres, sans jargon).

Même principe que mystery : sujet -> accroches notées (bandit) -> script contrôlé, régénéré tant qu'un
contrôle échoue. Différence : le sujet n'est pas une page Wikipédia mais un CONCEPT permanent (intérêts
composés, inflation...) avec des PARAMÈTRES (âges, taux, durées, montants). Les résultats chiffrés viennent
de calc.py : le LLM choisit parmi des sujets déjà calculés et n'écrit jamais un nombre absent des données
d'entrée ou des résultats de calc.py ; le résultat principal doit être dit dans la narration.
"""
from __future__ import annotations

import itertools
import os
import random
import re
import unicodedata
from pathlib import Path

from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import storyboard as fstory
from auracontent.channels.finance.spoken import SpokenError, display_text, spoken_text
from auracontent.core.brain.base_brain import BaseBrain
from auracontent.utils.topic_tracker import load_global_history, load_last_categories, load_used_values

TEMPLATES = tuple(fstory.VARIANTS)
PARAM_LABELS = {
    "early_age": "âge de départ de Léa", "late_age": "âge de départ de Hugo", "early_amount": "mise de Léa (€)",
    "late_amount": "mise de Hugo (€)", "rate": "rendement moyen (% par an)", "end_age": "âge d'arrivée",
    "amount": "montant de départ (€)", "inflation": "inflation (% par an)", "years": "durée (années)",
    "monthly": "versement mensuel (€)", "delay_years": "années d'attente avant de commencer",
    "horizon_years": "durée totale (années)", "fees": "frais (% par an)",
    "late_amount_factor": "Hugo met ce nombre de fois plus que Léa",
    "rate_b": "second taux d'exemple (% par an)",
}
RATE_KEYS = ("rate", "rate_b")                     # plafonnés par brain.max_rate
# Nature de chaque donnée d'entrée : « âge » et « ans » s'écrivent tous deux « ... ans » ; « €/mois » exige
# « par mois » dans la phrase.
PARAM_UNITS = {
    "early_age": "âge", "late_age": "âge", "end_age": "âge", "early_amount": "€", "late_amount": "€",
    "rate": "%", "amount": "€", "inflation": "%", "years": "ans", "monthly": "€/mois", "delay_years": "ans",
    "horizon_years": "ans", "fees": "%", "late_amount_factor": "fois", "rate_b": "%",
}
# unité écrite après un nombre (texte sans accents) -> natures compatibles de la table
_TEXT_UNITS = {
    "€": (re.compile(r"^(?:€|euros?\b)"), {"€", "€/mois"}),
    "%": (re.compile(r"^(?:%|pour ?cent\b)"), {"%"}),
    "ans": (re.compile(r"^(?:ans?\b|annees?\b)"), {"ans", "âge"}),
    "fois": (re.compile(r"^fois\b"), {"fois"}),
}
_PAR_FOIS_RE = re.compile(r"\bpar \d[\d ,]*\s*fois\b")                 # « multipliée par 24 fois »
_DISCLAIMER_RE = re.compile(r"exemple|simplifi|theori|illustr|hypothese|approximati|estimation")
_MONTHLY_RE = re.compile(r"\b(?:par mois|chaque mois|mensuel\w*|tous les mois)\b|/ ?mois")
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


def numbers_with_units(text: str) -> list[tuple[float, str, str]]:
    """(nombre, unité écrite juste après, suite de la phrase) pour chaque nombre en chiffres."""
    folded = _fold_keep(text)
    found = []
    for m in _NUMBER_RE.finditer(folded):
        value = float(re.sub(r"\s", "", m.group()).replace(",", "."))
        rest = folded[m.end():].lstrip()
        unit = next((u for u, (rx, _) in _TEXT_UNITS.items() if rx.match(rest)), "")
        found.append((value, unit, rest))
    return found


def _fold_keep(text: str) -> str:
    """Comme comparable(), sans retirer la ponctuation finale (positions des nombres conservées)."""
    text = unicodedata.normalize("NFD", normalize_title(text).casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _as_reasons(value, default: str) -> dict[str, str]:
    """Liste de termes (ancien format) ou dictionnaire terme -> raison."""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {str(t): default for t in value or []}


_ACCENTS = {"a": "aàâä", "e": "eéèêë", "i": "iîï", "o": "oôö", "u": "uùûü", "c": "cç", "y": "yÿ"}


def _accent_insensitive(term: str) -> re.Pattern:
    """Motif d'un terme en mots entiers, sans casse ni accents (« épargner » trouve « Epargner »)."""
    body = "".join(f"[{_ACCENTS[ch]}{_ACCENTS[ch].upper()}]" if ch in _ACCENTS else re.escape(ch)
                   for ch in unicodedata.normalize("NFD", term.lower()) if unicodedata.category(ch) != "Mn")
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.IGNORECASE)


def _folded_sub(pattern: str, repl: str, text: str) -> str:
    """Remplace les correspondances d'un motif écrit pour le texte sans accents, dans le texte d'origine."""
    folded = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    if len(folded) != len(text):                    # caractères composés : motif appliqué mot par mot
        return " ".join(repl if re.search(pattern, _fold_keep(w)) else w for w in text.split(" "))
    spans = [m.span() for m in re.finditer(pattern, folded.lower())]
    for start, end in reversed(spans):
        text = text[:start] + repl + text[end:]
    return text


def spoken_text_safe(text: str) -> str:
    try:
        return spoken_text(display_text(text))
    except SpokenError:
        return text


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
        cfg["banned_words"] = _as_reasons(cfg.get("banned_words"), "terme interdit")
        return cfg

    def forbidden_terms(self) -> dict[str, str]:
        """Mots interdits du texte (terme -> raison) : style.banned_words et banned_names."""
        return {**self.style_cfg()["banned_words"],
                **_as_reasons(self._brain().get("banned_names"), "nom de produit ou d'établissement")}

    def cta_terms(self) -> dict[str, str]:
        return _as_reasons(self._brain().get("cta_banned"), "invitation à agir")

    def all_forbidden(self) -> list[str]:
        """Tout ce qui ne doit JAMAIS apparaître dans une consigne ou une correction envoyée au LLM."""
        return [*self.forbidden_terms(), *self.cta_terms()]

    def mask_forbidden(self, text: str) -> str:
        """Correction renvoyée au LLM : chaque mot interdit ou terme exagéré devient « [terme interdit] »."""
        out = str(text)
        for term in sorted(self.all_forbidden(), key=len, reverse=True):
            out = _accent_insensitive(term).sub("[terme interdit]", out)
        for pattern in self.style_cfg().get("hype_patterns") or []:
            out = _folded_sub(pattern, "[terme exagéré]", out)
        return out

    def disclaimer_text(self) -> str:
        return clean_text(self._brain().get("disclaimer_text") or "")

    # ---------- Concepts et paramètres ----------
    @staticmethod
    def resolve_params(concept: str, raw: dict) -> dict | None:
        """Paramètres effectifs (dérivés compris), ou None si la combinaison n'a pas de sens."""
        params = dict(raw)
        if concept == "interets_composes":
            params["late_amount"] = params["early_amount"] * params["late_amount_factor"]
            if params["late_age"] - params["early_age"] < 15 or params["end_age"] - params["late_age"] < 15:
                return None
            # l'idée du concept (« commencer tôt pèse plus que la mise ») doit être vraie avec ces chiffres
            if fcalc.compute(concept, params)["gap"] <= 0:
                return None
        if concept == "cout_du_temps" and params["delay_years"] >= params["horizon_years"] / 2:
            return None
        if concept == "regle_72" and params["rate_b"] <= params["rate"]:   # deux taux, le second plus élevé
            return None
        return params

    @staticmethod
    def topic_key(concept: str, params: dict) -> str:
        """Clé de déduplication : concept + paramètres (ordre des clés indifférent)."""
        return concept + ":" + ",".join(f"{k}={_fmt(params[k])}" for k in sorted(params))

    def combinations(self, concept: str) -> list[dict]:
        """Combinaisons cohérentes ; tout taux de rendement au-dessus de brain.max_rate (8 %) est écarté."""
        spec = self._brain()["concepts"][concept].get("params", {})
        max_rate = float(self._brain().get("max_rate", 8))
        names = list(spec)
        combos = []
        for values in itertools.product(*(spec[n] for n in names)):
            raw = dict(zip(names, values, strict=True))
            if any(float(raw.get(k, 0)) > max_rate for k in RATE_KEYS):
                continue
            params = self.resolve_params(concept, raw)
            if params is not None:
                combos.append(params)
        return combos

    @staticmethod
    def describe(concept: str, p: dict) -> str:
        """Sujet lisible (sert de titre interne et d'entrée aux prompts)."""
        if concept == "interets_composes":
            return (f"Intérêts composés : {p['early_amount']} € mis de côté à {p['early_age']} ans contre "
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
            return (f"Règle des 72 : à {_fmt(p['rate'])} %/an puis à {_fmt(p['rate_b'])} %/an, en combien "
                    f"d'années ton argent double-t-il ?")
        raise KeyError(concept)

    @staticmethod
    def hypothesis(concept: str, p: dict) -> str:
        """Hypothèse affichée à l'écran (« 7 %/an · versement unique », « avant inflation »...)."""
        if concept == "interets_composes":
            return f"{_fmt(p['rate'])} %/an · versement unique · avant inflation"
        if concept == "inflation":
            return f"inflation de {_fmt(p['inflation'])} %/an · argent qui dort"
        if concept == "cout_du_temps":
            return f"{_fmt(p['rate'])} %/an · versements mensuels · avant inflation"
        if concept == "frais":
            return f"{_fmt(p['rate'])} %/an avant frais · versement unique · avant inflation"
        if concept == "regle_72":
            return f"{_fmt(p['rate'])} % et {_fmt(p['rate_b'])} %/an · gains réinvestis · approximation"
        raise KeyError(concept)

    def pick_topic(self) -> str:
        """Un candidat inédit par concept (hors concepts récents), puis le choix du LLM parmi eux."""
        candidates = self.topic_candidates()
        if not candidates:
            raise RuntimeError("Aucune combinaison concept + paramètres inédite.")
        concept, params = self.choose_candidate(candidates)
        self.last_pick = {"category": concept, "concept": concept, "topic_key": self.topic_key(concept, params),
                          "params": params}
        return self.describe(concept, params)

    def _first_unused(self, concept: str, used: set, used_titles: set) -> dict | None:
        combos = self.combinations(concept)
        random.shuffle(combos)
        for params in combos:
            if self.topic_key(concept, params) in used:
                continue
            topic = self.describe(concept, params)
            if comparable(topic) in used_titles:
                print(f"   ↻ Sujet écarté (titre déjà traité) : {topic}")
                continue
            return params
        print(f"   ↻ Concept épuisé : toutes les combinaisons de « {concept} » sont déjà traitées.")
        return None

    def topic_candidates(self) -> list[tuple[str, dict]]:
        """Concepts absents des dernières vidéos, chacun avec une combinaison jamais traitée (ordre aléatoire).
        Si tous ces concepts sont épuisés, les concepts récents servent de réserve."""
        b = self._brain()
        concepts = list(b.get("concepts") or {})
        if not concepts:
            raise RuntimeError("brain.concepts vide dans config/channels/finance.yaml")
        used = load_used_values("topic_key", channel=self.channel_name)
        used_titles = {comparable(t) for t in load_global_history(self.channel_name)}
        recent = set(load_last_categories(int(b.get("recent_concepts_window", 2)), channel=self.channel_name))
        random.shuffle(concepts)
        fresh = [c for c in concepts if c not in recent]
        for concept in concepts:
            if concept in recent and fresh:
                print(f"   ↻ Concept écarté : « {concept} » traité dans les {len(recent)} dernières vidéos.")
        for group in (fresh, [c for c in concepts if c in recent]):
            found = [(c, p) for c in group if (p := self._first_unused(c, used, used_titles)) is not None]
            if found:
                return found
        return []

    def choose_candidate(self, candidates: list[tuple[str, dict]]) -> tuple[str, dict]:
        """Le LLM choisit le sujet le plus parlant (il ne renvoie qu'un numéro, jamais un chiffre) ; au moindre
        problème, ou avec brain.concept_selection: random, le premier candidat (déjà tiré au hasard)."""
        if self._brain().get("concept_selection", "random") != "llm" or self.llm is None or len(candidates) == 1:
            return candidates[0]
        concepts = self._brain()["concepts"]
        lines = []
        for i, (concept, params) in enumerate(candidates, 1):
            result = fcalc.compute(concept, params).main
            lines.append(f"{i}. {self.describe(concept, params)} (idée : {concepts[concept].get('idea', '')}) "
                         f"-> résultat : {result.label} = {result.text}")
        sections = self.read_sections("select.md")
        values = {"candidates": "\n".join(lines), "count": len(candidates)}
        try:
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], **values)},
                 {"role": "user", "content": self.fill(sections["user"], **values)}],
                temperature=0.4, max_completion_tokens=800, **self.simple_routing())
            index = int(str(data.get("choice", "")).strip()) - 1
            if 0 <= index < len(candidates):
                print(f"🧭 Sujet choisi par le LLM parmi {len(candidates)} : {data.get('reason', '')}".rstrip(" :"))
                return candidates[index]
            print(f"⚠️ Choix du LLM hors liste ({data.get('choice')!r}) : tirage au hasard.")
        except Exception as e:                    # le choix est un confort : jamais bloquant
            print(f"⚠️ Choix du sujet par le LLM impossible ({e}) : tirage au hasard.")
        return candidates[0]

    def export_state(self) -> dict:
        return {"last_pick": self.last_pick}

    def restore_state(self, state: dict) -> None:
        """Reprise d'un sujet en attente ; ValueError s'il n'est plus valide avec le YAML actuel (concept
        retiré, taux au-dessus du plafond...) : le pipeline l'abandonne et choisit un nouveau sujet."""
        pick = dict((state or {}).get("last_pick") or {})
        concept, params = pick.get("concept"), pick.get("params")
        if concept not in (self._brain().get("concepts") or {}):
            raise ValueError(f"concept « {concept} » absent de la configuration")
        if params not in self.combinations(concept):
            raise ValueError(f"paramètres {params} hors des combinaisons autorisées")
        self.last_pick = pick

    def _pick(self) -> tuple[str, dict, dict]:
        if not self.last_pick:
            raise RuntimeError("Aucun concept choisi (pick_topic d'abord).")
        concept = self.last_pick["concept"]
        return concept, self.last_pick["params"], self._brain()["concepts"][concept]

    def calc(self) -> fcalc.Calc:
        concept, params, _ = self._pick()
        return fcalc.compute(concept, params)

    def allowed_numbers(self) -> set[float]:
        """Nombres que le texte peut citer : données d'entrée, constantes du concept et résultats de calc.py."""
        _, params, spec = self._pick()
        return {float(v) for v in [*params.values(), *(spec.get("constants") or [])]} | self.calc().numbers()

    def number_table(self) -> list[tuple[float, str, str]]:
        """(valeur, nature, libellé) de chaque chiffre citable : entrées, constantes, résultats de calc.py."""
        _, params, spec = self._pick()
        result = self.calc()
        table = [(float(v), PARAM_UNITS.get(k, ""), PARAM_LABELS.get(k, k)) for k, v in params.items()]
        table += [(float(c), "", "constante du concept") for c in [*(spec.get("constants") or []),
                                                                    *result.extra_numbers]]
        table += [(v.value, v.unit, v.label) for v in result.values.values()]
        return table

    def meaning_issues(self, text: str, what: str) -> list[str]:
        """Chaque nombre écrit avec une unité doit exister dans la table AVEC cette unité ; un versement mensuel
        s'écrit avec « par mois », et « par mois » ne s'accole jamais à un montant qui n'est pas mensuel."""
        issues, table = [], self.number_table()
        for sentence in sentences(text) or [text]:
            monthly_said = _MONTHLY_RE.search(_fold_keep(sentence)) is not None
            for value, unit, rest in numbers_with_units(sentence):
                matches = [(k, label) for v, k, label in table if v == value]
                if not matches:
                    continue                                    # nombre inconnu : signalé par text_issues
                if unit:
                    kinds = _TEXT_UNITS[unit][1]
                    fitting = [(k, label) for k, label in matches if k in kinds or k == ""]
                    if not fitting:
                        issues.append(f"{what} : « {_fmt(value)} {unit} » ne correspond à rien dans les calculs "
                                      f"({'; '.join(label for _, label in matches)})")
                        continue
                    matches = fitting
                if unit == "€" and all(k == "€/mois" for k, _ in matches) and not monthly_said:
                    issues.append(f"{what} : « {_fmt(value)} € » est un versement mensuel, écris « par mois »")
                after = rest[_TEXT_UNITS["€"][0].match(rest).end():].lstrip() if unit == "€" else ""
                if after and _MONTHLY_RE.match(after) and not any(k == "€/mois" for k, _ in matches):
                    issues.append(f"{what} : « {_fmt(value)} € par mois » est faux, ce montant n'est pas mensuel")
        return issues

    def hype_issues(self, text: str, what: str) -> list[str]:
        """Formulations absolues ou alarmistes (brain.style.hype_patterns, regex sur le texte sans accents)."""
        folded = _fold_keep(text)
        found = []
        for pattern in self.style_cfg().get("hype_patterns") or []:
            m = re.search(pattern, folded)
            if m:
                found.append(f"{what} exagère (terme absolu ou alarmiste) : reste factuel et mesuré")
        return found

    def numbers_block(self) -> str:
        """Liste lisible des chiffres autorisés, avec ce qu'ils désignent (entrées puis résultats)."""
        _, params, _ = self._pick()
        lines = [f"- {PARAM_LABELS.get(k, k)} : {_fmt(v)}" for k, v in params.items()]
        lines += [f"- {v.label} : {v.text}" for v in self.calc().values.values()]
        return "\n".join(lines)

    def hook_example(self) -> str:
        """Exemple d'accroche du concept (brain.concepts.<c>.hook_example, clés de calc.py entre accolades)."""
        _, _, spec = self._pick()
        example = spec.get("hook_example")
        if not example:
            return "Mettre moins d'argent… et finir avec plus."
        return example.format_map({k: v.text for k, v in self.calc().values.items()})

    def loss_issues(self, text: str, what: str) -> list[str]:
        """concepts.<c>.loss_needs (inflation : « pouvoir d'achat ») : une perte n'est vraie qu'avec ces mots."""
        _, _, spec = self._pick()
        needed = spec.get("loss_needs")
        if not needed:
            return []
        issues = []
        for sentence in sentences(text) or [text]:
            folded = _fold_keep(sentence)
            if re.search(r"\b(perd\w*|pert\w*)\b", folded) and _fold_keep(needed) not in folded:
                issues.append(f"{what} : « perdre » sans « {needed} » est faux (l'argent reste sur le compte, "
                              f"c'est le {needed} qui baisse)")
                break
        return issues

    def pending_hook_issues(self, text: str, topic: str) -> list[str]:
        """Accroche d'un sujet en attente, recontrôlée à la reprise (règles actuelles du code, puis LLM)."""
        issues = self.hook_issues(clean_text(text), topic)
        if not issues and not self.llm_hook_check([{"text": text}]):
            issues = ["refusée par la vérification du sens et de la grammaire"]
        return issues

    def llm_hook_check(self, hooks: list[dict]) -> list[dict]:
        """Avant la sélection : sens des chiffres (table de calc.py), vérité de l'affirmation et grammaire de
        chaque accroche, en un seul appel. Vérification impossible : les accroches restent (la scène 1, qui
        commence par l'accroche, passe ensuite le contrôle de sens du script)."""
        if not hooks or self._brain().get("meaning_check") != "llm" or self.llm is None:
            return hooks
        concept, params, spec = self._pick()
        table = [f"- {label} : {fcalc.fmt_number(v)} {unit}".rstrip() for v, unit, label in self.number_table()]
        sections = self.read_sections("hook_check.md")
        values = {"hypothesis": self.hypothesis(concept, params), "table": "\n".join(table),
                  "wording": spec.get("wording", ""),
                  "hooks": "\n".join(f"{i}. {h['text']}" for i, h in enumerate(hooks, 1))}
        try:
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], **values)},
                 {"role": "user", "content": self.fill(sections["user"], **values)}],
                temperature=0.0, max_completion_tokens=800, **self.simple_routing())
        except Exception as e:
            print(f"   ⚠️ Vérification des accroches impossible ({e}) : contrôle reporté sur le script.")
            return hooks
        rejected = {}
        for item in data.get("rejets") or []:
            try:
                rejected[int(item.get("numero"))] = str(item.get("motif") or "motif non fourni")
            except (TypeError, ValueError, AttributeError):
                continue
        kept = []
        for i, hook in enumerate(hooks, 1):
            if i in rejected:
                print(f"   ↻ Accroche rejetée (sens ou grammaire : {rejected[i]}) : « {hook['text']} »")
            else:
                kept.append(hook)
        return kept

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
                      wording=spec.get("wording", ""), max_hook_words=cfg["max_hook_words"],
                      numbers_block=self.numbers_block(), hook_example=self.hook_example())
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
            valid = self.llm_hook_check(valid)
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
            wording=spec.get("wording", ""),
            hypothesis=self.hypothesis(concept, params),
            params_block="\n".join(f"- {PARAM_LABELS.get(k, k)} : {_fmt(v)}" for k, v in params.items()),
            results_block="\n".join(f"- {v.label} : {v.text}" for v in self.calc().values.values()),
            main_result=f"{self.calc().main.label} : {self.calc().main.text}",
            chosen_hook=(chosen_hook or {}).get("text", ""), scene_count=scene_count,
            max_sentence_words=cfg["max_sentence_words"], storyboard=fstory.describe(concept),
            scene_words=self.scene_words_text(),
            bandeau_lengths=self.bandeau_lengths(), bandeau_rule=self.bandeau_rule_text(),
            scene_results="\n".join(
                f"- scène « {fstory.ROLES[role]} » : " + " ; ".join(
                    f"{self.calc().values[k].label} = {self.calc().values[k].text}" for k in keys)
                for role, keys in self.scene_keys().items()),
            must_say=", ".join(f"« {m} »" for m in fstory.must_say(concept)) or "rien de plus",
        )
        user = self.fill(sections["user"], **values)
        if correction_feedback:
            user += f"\n\n{self.mask_forbidden(correction_feedback)}"     # jamais un mot interdit vers le LLM
        return [{"role": "system", "content": self.fill(sections["system"], **values)},
                {"role": "user", "content": user}]

    def scene_keys(self) -> dict[str, tuple[str, ...]]:
        concept, _, _ = self._pick()
        return fstory.scene_keys(concept, self.calc().headline)

    def target_scene_count(self) -> int:
        """Le storyboard du concept fixe le nombre de scènes."""
        concept, _, _ = self._pick()
        return len(fstory.storyboard(concept))

    def validate_script_specifics(self, data, topic):
        """Comme _validate_structure, en journalisant le motif de chaque rejet (le script est alors régénéré)."""
        try:
            self._validate_structure(data)
        except ValueError as e:
            print(f"   ↻ Script (structure) : {e}")
            raise

    def _validate_structure(self, data):
        """Structure : bandeau en deux segments, hypothèse exacte, accroche en tête, storyboard imposé."""
        concept, params, _ = self._pick()
        title = clean_text(data.get("on_screen_title", ""))
        parts = [p.strip() for p in title.split("|")]
        if len(parts) != 2 or not all(parts):
            raise ValueError("on_screen_title doit avoir la forme « AFFIRMATION | PUNCHLINE ».")
        too_long = [p for p in parts if len(p) > 20]
        if too_long:
            raise ValueError(f"segment du bandeau de plus de 20 caractères : « {too_long[0]} ».")
        data["on_screen_title"] = self.checked_bandeau(" | ".join(parts))
        data["hypothesis"] = self.hypothesis(concept, params)          # jamais reformulée par le LLM
        data["calc"] = self.calc().to_dict()                           # chiffres et courbes des gabarits
        if not str(data.get("closing_cta", "")).strip():
            raise ValueError("closing_cta manquant.")
        expected = len(fstory.storyboard(concept))
        if len(data["scenes"]) != expected:
            raise ValueError(f"il faut exactement {expected} scènes, dans l'ordre du storyboard.")
        for note in fstory.apply(concept, data["scenes"]):           # rôles et gabarits fixés par le code
            print(f"   🧩 Storyboard : {note}")
        for scene in data["scenes"]:
            if scene["role"] == "disclaimer" and self.disclaimer_text():
                scene["text"], scene["fixed_text"] = self.disclaimer_text(), True    # jamais écrit par le LLM
            if scene["template"] == "carte_fin":
                scene["hide_watermark"] = True                       # le grand logo de la carte suffit
            # texte affiché (chiffres « 10 000 € ») et texte parlé (nombres en lettres), produits par le code
            scene["text"] = display_text(clean_text(scene["text"]))
            try:
                scene["spoken"] = spoken_text(scene["text"])
            except SpokenError as e:
                raise ValueError(f"scène {scene['id']} : {e} ; écris les chiffres sans autre symbole.") from e
            scene.setdefault("voice_type", "narrator")
        # l'accroche passe par le même formatage des nombres que la narration (« 1500 € » -> « 1 500 € ») :
        # sinon la comparaison échoue dès qu'un montant dépasse 999
        hook = display_text(clean_text(self.chosen_hook_text or "")).strip()
        if hook and not comparable(data["scenes"][0]["text"]).startswith(comparable(hook)):
            raise ValueError("la scène 1 doit commencer mot pour mot par l'accroche obligatoire.")

    chosen_hook_text: str | None = None

    def generate_script(self, topic, chosen_hook=None):
        self.chosen_hook_text = (chosen_hook or {}).get("text")
        return super().generate_script(topic, chosen_hook=chosen_hook)

    def text_issues(self, text: str, what: str) -> list[str]:
        """Contrôles de fond communs aux accroches, au bandeau et à la narration."""
        issues = []
        for term, reason in self.forbidden_terms().items():
            if contains_term(text, term):
                issues.append(f"{what} contient un terme interdit ({reason}) : « {self.mask_forbidden(text)} »")
                break
        for word in self._brain().get("style", {}).get("imperatives") or []:
            if any(_fold_keep(s).startswith(_fold_keep(word) + " ") for s in sentences(text) or [text]):
                issues.append(f"{what} donne un ordre au spectateur : décris le mécanisme, ne dis jamais quoi faire")
                break
        if re.search(r"\b(vous|votre|vos)\b", _fold(text)):
            issues.append(f"{what} vouvoie (tutoiement obligatoire)")
        allowed = self.allowed_numbers()
        extra = sorted({n for n in numbers_in(text) if n not in allowed})
        if extra:
            issues.append(f"{what} cite un nombre non autorisé : {', '.join(_fmt(n) for n in extra)}")
        issues += self.hype_issues(text, what)
        issues += self.loss_issues(text, what)
        m = _PAR_FOIS_RE.search(_fold_keep(text))
        if m:
            issues.append(f"{what} : « {m.group()} » ; écris « multipliée par N », sans « fois »")
        issues += self.meaning_issues(text, what)
        return issues

    def llm_meaning_issues(self, data: dict) -> list[str]:
        """brain.meaning_check: llm -> un appel reçoit la table des calculs et le script, répond oui/non avec
        motif. Un « non », ou une vérification impossible, fait régénérer le script : rien n'est publié sans."""
        if self._brain().get("meaning_check") != "llm" or self.llm is None:
            return []
        concept, params, _ = self._pick()
        # le rappel de fin (texte fixe du YAML) n'est pas envoyé : validé par construction
        lines = [f"Scène {s.get('id')} : {s.get('text', '')}" for s in data.get("scenes", []) if not s.get("fixed_text")]
        lines += [f"Bandeau : {data.get('on_screen_title', '')}", f"Titre : {data.get('title', '')}",
                  f"Question finale : {data.get('closing_cta', '')}"]
        table = [f"- {label} : {fcalc.fmt_number(v)} {unit}".rstrip() for v, unit, label in self.number_table()]
        sections = self.read_sections("meaning.md")
        values = {"hypothesis": self.hypothesis(concept, params), "table": "\n".join(table),
                  "script": "\n".join(lines)}
        try:
            verdict = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], **values)},
                 {"role": "user", "content": self.fill(sections["user"], **values)}],
                temperature=0.0, max_completion_tokens=1200, **self.simple_routing())
        except Exception as e:
            return [f"vérification du sens des chiffres impossible ({e})"]
        if verdict.get("ok") is True and not verdict.get("problems"):
            print("   ✔️ Sens des chiffres vérifié par le LLM.")
            return []
        problems = [p for p in verdict.get("problems") or [] if isinstance(p, dict)]
        if not problems:
            return ["vérification du sens des chiffres : réponse négative sans motif"]
        return [f"sens des chiffres, {p.get('ou') or p.get('scene') or '?'} : {p.get('motif') or p.get('reason')}"
                for p in problems]

    def checked_bandeau(self, bandeau: str) -> str:
        """Bandeau qui ne présente jamais un chiffre seul quand le concept en exige plusieurs (coût du temps :
        versements en plus ET résultat en plus) ; sinon bandeau construit par le code d'après calc.py."""
        concept, _, _ = self._pick()
        rule = fstory.bandeau_rule(concept)
        if not rule:
            return bandeau
        keys, template = rule
        values = self.calc().values
        said = set(numbers_in(bandeau))
        if all(values[k].value in said for k in keys):
            return bandeau
        built = template.format(**{k: values[k].text for k in keys}).upper()
        too_long = [part for part in built.split(" | ") if len(part.strip()) > 20]
        if too_long:
            raise ValueError(f"bandeau : il doit citer ensemble {', '.join(values[k].text for k in keys)} "
                             "en 20 caractères au plus par segment.")
        print(f"   🧩 Bandeau « {bandeau} » remplacé par « {built} » (les deux chiffres ensemble).")
        return built

    def bandeau_rule_text(self) -> str:
        concept, _, _ = self._pick()
        rule = fstory.bandeau_rule(concept)
        if not rule:
            return ""
        keys, template = rule
        values = self.calc().values
        example = template.format(**{k: values[k].text for k in keys}).upper()
        return (f"Ce bandeau cite ENSEMBLE {' et '.join(values[k].text for k in keys)}, jamais l'un sans l'autre "
                f"(ex : « {example} »).")

    def bandeau_lengths(self) -> str:
        """Longueur en caractères des montants qui peuvent aller dans le bandeau (20 au plus par segment)."""
        keys = [k for keys in self.scene_keys().values() for k in keys]
        texts = list(dict.fromkeys(self.calc().values[k].text for k in keys))
        return "; ".join(f"« {t} » = {len(t)} caractères" for t in texts)

    def scene_words_text(self) -> str:
        """Cibles de mots par scène pour le prompt (un montant en chiffres compte pour les mots prononcés)."""
        targets = self.scene_word_targets()
        if not targets:
            return "1 ou 2 phrases courtes par scène."
        return " ; ".join(f"scène {i} : environ {t} mots" for i, t in enumerate(targets, 1))

    def duration_target(self) -> float:
        """Durée visée (s) : VIDEO_DURATION (workflow) ou brain.target_duration."""
        try:
            return float(os.getenv("VIDEO_DURATION") or self._brain().get("target_duration", 45))
        except ValueError:
            return float(self._brain().get("target_duration", 45))

    def scene_word_targets(self) -> list[int]:
        """Mots PARLÉS visés par scène : (durée visée - question finale) x débit de la voix (brain.
        voice_words_per_second, mesuré : Rémy à -8 % = 2,6), accroche et fin courtes, le reste réparti.
        Liste vide si le débit n'est pas configuré (pas de contrôle de longueur)."""
        b = self._brain()
        wps = float(b.get("voice_words_per_second", 0) or 0)
        if wps <= 0:
            return []
        concept, _, _ = self._pick()
        n = len(fstory.storyboard(concept))
        total = round((self.duration_target() - float(b.get("cta_seconds", 3))) * wps)
        hook = int(b.get("hook_words", 10))
        end = count_words(spoken_text_safe(self.disclaimer_text())) if self.disclaimer_text() else int(b.get("end_words", 8))
        middle = max(8, round((total - hook - end) / max(n - 2, 1)))
        return [hook] + [middle] * (n - 2) + [end]

    @staticmethod
    def spoken_words(scene: dict) -> int:
        """Mots prononcés (montants en toutes lettres) : c'est ce qui fait la durée de la voix."""
        return count_words(scene.get("spoken") or spoken_text_safe(scene.get("text", "")))

    def storyboard_issues(self, data: dict) -> list[str]:
        """Chiffres exigés par rôle, expressions obligatoires, scène de fin sans chiffre, question sans chiffre."""
        concept, _, _ = self._pick()
        scenes, issues = data.get("scenes", []), []
        for role, keys in self.scene_keys().items():
            scene = next((s for s in scenes if s.get("role") == role), None)
            said = set(numbers_in(scene.get("text", ""))) if scene else set()
            for key in keys:
                value = self.calc().values[key]
                if value.value not in said:
                    issues.append(f"la scène « {fstory.ROLES[role]} » ne dit pas : {value.label} = {value.text}")
        narration = " ".join(comparable(s.get("text", "")) for s in scenes)
        for phrase in fstory.must_say(concept):
            if comparable(phrase) not in narration:
                issues.append(f"la narration doit nommer « {phrase} »")
        for scene in scenes:
            if scene.get("role") != "disclaimer" or scene.get("fixed_text"):
                continue
            if numbers_in(scene.get("text", "")):
                issues.append(f"scène {scene.get('id')} (fin) : aucun nouveau chiffre, seulement le rappel")
            if not _DISCLAIMER_RE.search(_fold_keep(scene.get("text", ""))):
                issues.append(f"scène {scene.get('id')} (fin) : doit rappeler que c'est un exemple simplifié")
        if numbers_in(data.get("closing_cta", "")):
            issues.append("la question finale ne contient aucun chiffre")
        cta = str(data.get("closing_cta", ""))
        if any(contains_term(cta, term) for term in self.cta_terms()):
            issues.append("la question finale invite à agir : pose une question sur le mécanisme (comment, pourquoi, "
                          "combien), jamais sur ce que le spectateur devrait faire de son argent")
        targets = self.scene_word_targets()
        if targets and len(targets) == len(scenes):
            said = [self.spoken_words(s) for s in scenes]
            wps = float(self._brain().get("voice_words_per_second"))
            if sum(said) < 0.9 * sum(targets):
                short = [f"scène {i} : {w} mots, vise {t} (+{t - w})"
                         for i, (w, t) in enumerate(zip(said, targets, strict=True), 1) if t - w >= 3]
                issues.append(f"script trop court : {sum(said)} mots prononcés (environ {sum(said) / wps:.0f} s), il "
                              f"en faut {sum(targets)} (environ {sum(targets) / wps:.0f} s) ; allonge : "
                              + " ; ".join(short))
        return issues

    def caption_issues(self, script: dict, caption: str) -> list[str]:
        """La légende (écrite par le prompt générique) passe les contrôles du script : exagération, mots et
        produits interdits, vouvoiement, chiffres absents de calc.py ou employés hors de leur sens."""
        pick = script.get("pick") or {}
        if pick.get("concept"):
            self.last_pick = dict(pick)
        footer = str((self.config.get("publish") or {}).get("caption_footer") or "")
        body = "\n".join(line for line in str(caption).splitlines()
                         if not line.strip().startswith("#") and (not footer or line.strip() != footer.strip()))
        # sans sujet (script incomplet) : seuls les contrôles qui n'ont pas besoin des chiffres de calc.py
        issues = self.text_issues(body, "la légende") if self.last_pick else self.hype_issues(body, "la légende")
        if re.search(r"[\U0001F600-\U0001F64F\U0001F910-\U0001F92F]", body):       # visages (😱, 🤯...)
            issues.append("la légende contient un émoji de visage (ton alarmiste)")
        return issues

    def safe_caption(self, script: dict, title: str, publish_cfg: dict) -> str:
        """Légende sans LLM : titre, hypothèse, question finale, hashtags et mention fixe."""
        from auracontent.services.publishing.caption import apply_caption_footer, apply_hashtag_rules

        parts = [title, f"Hypothèse : {script.get('hypothesis', '')}".strip(" :"), script.get("closing_cta", ""),
                 publish_cfg.get("fallback_hashtags", "")]
        caption = "\n\n".join(p for p in parts if p)
        return apply_hashtag_rules(apply_caption_footer(caption, publish_cfg.get("caption_footer")),
                                   publish_cfg.get("brand_hashtag"), publish_cfg.get("banned_hashtags", ()))

    def build_visuals(self, script: dict, scenes: list[dict], work_dir, video_cfg: dict) -> list:
        """Scènes dessinées (moteur linework, sprites de la vidéo test), une par scène, à la durée de la voix ;
        effets sonores calés sur l'action dans scene["sfx_cues"]. Mise en page refusée = vidéo non produite."""
        from auracontent.channels.finance import visuals

        cfg = dict((self.config.get("visuals") or {}).get("linework") or {})
        return visuals.render_scenes(script, scenes, work_dir, cfg)

    def check_script_logic(self, topic, data):
        """Style et fond : phrases courtes, aucun terme interdit, tutoiement, aucun nombre inventé."""
        cfg, issues = self.style_cfg(), []
        limit = int(cfg["max_sentence_words"])
        for scene in data.get("scenes", []):
            if scene.get("fixed_text"):                  # avertissement de fin : texte fixe du YAML
                continue
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
        issues += self.storyboard_issues(data)
        if not issues:
            issues += self.llm_meaning_issues(data)
        for issue in issues:
            print(f"   ↻ Script : {issue}")
        return issues
