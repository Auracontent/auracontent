"""Sujets libres ancrés dans le quotidien (Capital Simple, partie 3b).

À chaque run, le LLM propose des candidats NOUVEAUX : {situation, domaine, concept, calcul, question_spectateur}.
Chaque candidat est vérifié par le code, et chaque rejet est journalisé avec sa raison :
- situation concrète (une phrase, Léa ou Hugo), question présente ;
- calcul disponible dans calc.py, paramètres complets et réalistes (calc.check_params) ;
- aucun mot interdit (partie 1.1), aucune invitation à agir dans la question ;
- concept hors de la fenêtre concept_window, couple concept + situation hors de situation_window ;
- au plus brain.free_topics.max_from_examples candidat repris des exemples du YAML.
Deux situations sont comparées par mots-clés normalisés ; le LLM ne tranche qu'en cas de doute (un appel).
Le choix final (intérêt, clarté, différence avec les 10 derniers sujets) est fait par le LLM, sinon le premier.
"""
from __future__ import annotations

import os
import random
import re
import unicodedata

from auracontent.channels.finance import calc as fcalc

# Mots sans valeur pour reconnaître une scène de vie (articles, prépositions, verbes courants, prénoms)
STOPWORDS = frozenset("""
lea hugo les des une un le la de du au aux en et ou a avec sans sur sous pour par dans chez son sa ses leur leurs
ton ta tes mon ma mes ce cet cette ces qui que quoi dont il elle ils elles on se sa est sont etre avoir a ont fait
font prend prennent paie paye payer achete acheter met mettre va vont plus moins tres trop chaque tous toutes tout
toute apres avant pendant depuis quand alors puis mais donc car fois euro euros mois an ans annee annees semaine
semaines jours son pas ne plus peu bien deja encore
""".split())  # noqa: SIM905


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "").lower().replace("\u2019", "'").replace("'", " "))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def keywords(text: str, synonyms: dict[str, list[str]] | None = None) -> frozenset[str]:
    """Mots-clés normalisés d'une situation : sans accents, pluriels, mots vides ni chiffres ; synonymes ramenés
    à leur forme commune (« expresso », « petit noir » -> « cafe » ; « bureau » -> « travail »)."""
    t = f" {fold(text)} "
    for canon, words in (synonyms or {}).items():
        for word in sorted(words, key=len, reverse=True):
            t = re.sub(rf"(?<![a-z]){re.escape(fold(word))}(?![a-z])", f" {fold(canon)} ", t)
    out = set()
    for word in re.findall(r"[a-z]+", t):
        if len(word) < 3 or word in STOPWORDS:
            continue
        if len(word) > 4 and word[-1] in "sx":
            word = word[:-1]
        out.add(word)
    return frozenset(out)


def overlap(a: frozenset, b: frozenset) -> float:
    """Part commune : |A ∩ B| / min(|A|, |B|) (une situation courte incluse dans une longue = la même)."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


class FreeTopics:
    """Mélangé à FinanceBrain : utilise self.llm, self._brain(), self.read_sections, self.fill, les contrôles de
    mots interdits et l'historique (self.history_window)."""

    # ---------- Configuration ----------
    def free_cfg(self) -> dict:
        return dict(self._brain().get("free_topics") or {})

    def free_enabled(self) -> bool:
        return bool(self.free_cfg().get("enabled")) and self.llm is not None

    def run_rng(self) -> random.Random:
        """Hasard du run : FINANCE_SEED (tests, reproductibilité) sinon aléatoire."""
        seed = os.getenv("FINANCE_SEED")
        return random.Random(seed) if seed else random.Random()

    def draw_domains(self, rng: random.Random) -> list[str]:
        domains = list(self.free_cfg().get("domains") or [])
        n = min(len(domains), int(self.free_cfg().get("domains_per_run", 2)))
        return rng.sample(domains, n)

    def shown_examples(self, rng: random.Random) -> list[dict]:
        examples = list(self.free_cfg().get("examples") or [])
        return rng.sample(examples, min(len(examples), int(self.free_cfg().get("examples_shown", 3))))

    def synonyms(self) -> dict[str, list[str]]:
        return dict(self.free_cfg().get("synonyms") or {})

    def situation_keywords(self, text: str) -> frozenset[str]:
        return keywords(text, self.synonyms())

    def same_situation(self, a: frozenset, b: frozenset) -> bool | None:
        """True : même scène de vie ; False : différentes ; None : doute (le LLM tranche)."""
        sim = self.free_cfg().get("similarity") or {}
        score = overlap(a, b)
        if score >= float(sim.get("same", 0.75)):
            return True
        if score < float(sim.get("different", 0.4)):
            return False
        return None

    # ---------- Prompt ----------
    def calcs_block(self, only: str | None = None) -> str:
        lines = []
        for key, spec in fcalc.SPECS.items():
            if only and key != only:
                continue
            params = ", ".join(f"{name} ({label}, {fcalc.fmt_number(lo)} à {fcalc.fmt_number(hi)}"
                               f"{' ' + unit if unit else ''})" for name, (label, unit, lo, hi) in spec["params"].items())
            lines.append(f"- {key} : {spec['label']} ; paramètres : {params}")
        return "\n".join(lines)

    def recent_topics_text(self, n: int = 10) -> str:
        entries = self.history_window(n)
        lines = [f"- {e.get('situation') or e.get('topic', '')}" + (" (abandonné)" if e.get("status") == self.ABANDONED else "")
                 for e in entries]
        return "\n".join(lines) or "- aucun"

    def candidates_messages(self, rng: random.Random, forced: str | None = None) -> tuple[list[dict], list[str]]:
        cfg = self.free_cfg()
        drawn = self.draw_domains(rng)
        count = int(cfg.get("candidates", 8))
        examples = "\n".join(
            "- " + str({"situation": e["situation"], "calcul": e["calcul"], "question_spectateur": e["question_spectateur"]})
            for e in self.shown_examples(rng))
        forced_line = (f"\nSUJET IMPOSÉ : tous les sujets utilisent le calcul « {forced} ».\n" if forced else "")
        values = {"count": count, "half": (count + 1) // 2, "domains": ", ".join(cfg.get("domains") or []),
                  "drawn": ", ".join(drawn), "calcs": self.calcs_block(forced), "recent": self.recent_topics_text(10),
                  "forced": forced_line, "examples": examples, "max_examples": int(cfg.get("max_from_examples", 1))}
        sections = self.read_sections("candidates.md")
        # rien de ce qui part au LLM ne contient un mot interdit (historique ancien compris)
        return ([{"role": "system", "content": self.mask_forbidden(self.fill(sections["system"], **values))},
                 {"role": "user", "content": self.mask_forbidden(self.fill(sections["user"], **values))}], drawn)

    # ---------- Vérification d'un candidat ----------
    def wording_problem(self, text: str, what: str, cta: bool = False) -> str:
        checked = self.without_allowed_contexts(text)
        from auracontent.channels.finance.brain import contains_term

        terms = list(self.forbidden_terms()) + (list(self.cta_terms()) if cta else [])
        if any(contains_term(checked, t) for t in terms):
            return f"{what} contient un terme interdit (produit, établissement, promesse ou invitation à agir)"
        hype = self.hype_issues(text, what)
        return hype[0] if hype else ""

    def check_candidate(self, cand: dict, forced: str | None = None) -> tuple[dict | None, str]:
        """(pick, "") si le candidat est utilisable ; sinon (None, raison)."""
        if not isinstance(cand, dict):
            return None, "candidat illisible"
        situation = re.sub(r"\s+", " ", str(cand.get("situation") or "")).strip()
        question = str(cand.get("question_spectateur") or "").strip()
        if len(situation.split()) < 6 or not re.search(r"\b(Léa|Lea|Hugo)\b", situation):
            return None, "pas de situation concrète (une scène vécue par Léa ou Hugo, en une phrase)"
        if not question:
            return None, "pas de question du spectateur"
        calcul = cand.get("calcul") if isinstance(cand.get("calcul"), dict) else {}
        concept = str(calcul.get("type") or "").strip()
        if forced and concept != forced:
            return None, f"calcul « {concept} » au lieu du concept imposé « {forced} »"
        params, why = fcalc.check_params(concept, calcul.get("params") if isinstance(calcul.get("params"), dict) else {})
        if params is None:
            return None, f"non calculable : {why}"
        if concept in (self._brain().get("concepts") or {}):
            params = self.resolve_params(concept, params)
            if params is None:
                return None, "non calculable : combinaison sans intérêt pour ce concept"
        for text, what, cta in ((situation, "la situation", False), (question, "la question", True),
                                (str(cand.get("concept") or ""), "le concept", False)):
            problem = self.wording_problem(text, what, cta)
            if problem:
                return None, problem
        kw = self.situation_keywords(situation)
        if len(kw) < 2:
            return None, "situation trop vague pour être reconnue"
        return {"category": concept, "concept": concept, "params": params,
                "topic_key": self.topic_key(concept, params), "situation": situation,
                "situation_keywords": sorted(kw), "question": question,
                "domain": str(cand.get("domaine") or ""), "source": "libre"}, ""

    # ---------- Choix ----------
    def free_pick(self, forced: str | None = None) -> dict | None:
        """Génère, vérifie et choisit un sujet libre ; None si aucun candidat n'est utilisable."""
        cfg = self.free_cfg()
        rng = self.run_rng()
        messages, drawn = self.candidates_messages(rng, forced)
        print(f"🌱 Génération libre : {cfg.get('candidates', 8)} candidats demandés, domaines du run : "
              f"{', '.join(drawn)}" + (f" ; concept imposé : {forced}" if forced else ""))
        try:
            data = self.llm.call_json_with_retry(messages, temperature=0.9, max_completion_tokens=3500,
                                                 **self.simple_routing())
        except Exception as e:
            print(f"⚠️ Génération libre impossible ({e}) : repli sur les concepts du YAML.")
            return None
        raw = [c for c in (data.get("candidats") or data.get("candidates") or []) if isinstance(c, dict)]
        print(f"🧾 {len(raw)} candidat(s) reçu(s) :")
        recent_concepts = {} if forced else self.recent_subjects(self.concept_window())
        past = [e for e in self.history_window(self.situation_window()) if e.get("situation")]
        example_kws = [(self.situation_keywords(e["situation"]), e["calcul"]["type"])
                       for e in cfg.get("examples") or []]
        max_examples = int(cfg.get("max_from_examples", 1))
        valid, doubts, from_examples = [], [], 0
        for i, cand in enumerate(raw, 1):
            label = str(cand.get("situation") or "?")[:90]
            pick, why = self.check_candidate(cand, forced)
            if pick is None:
                print(f"   ✖ {i}. {label} : {why}")
                continue
            concept, kw = pick["concept"], frozenset(pick["situation_keywords"])
            if concept in recent_concepts:
                ago, status = recent_concepts[concept]
                print(f"   ✖ {i}. {label} : concept « {concept} » {'abandonné' if status == self.ABANDONED else 'traité'} "
                      f"il y a {ago} vidéo(s) (fenêtre de {self.concept_window()})")
                continue
            twin = next((v for v in valid if v["concept"] == concept and
                         self.same_situation(kw, frozenset(v["situation_keywords"]))), None)
            if twin:
                print(f"   ✖ {i}. {label} : même sujet qu'un autre candidat")
                continue
            verdicts = [(e, self.same_situation(kw, frozenset(e.get("situation_keywords") or
                                                             self.situation_keywords(e["situation"]))))
                        for e in past if (e.get("concept") or e.get("category")) == concept]
            same = next((e for e, v in verdicts if v is True), None)
            if same:
                print(f"   ✖ {i}. {label} : même situation et même concept que « {same['situation'][:60]} » "
                      f"(fenêtre de {self.situation_window()})")
                continue
            is_example = any(t == concept and self.same_situation(kw, ekw) for ekw, t in example_kws)
            if is_example and from_examples >= max_examples:
                print(f"   ✖ {i}. {label} : reprend un exemple de la liste (quota de {max_examples} atteint)")
                continue
            from_examples += is_example
            pick["from_example"] = bool(is_example)
            doubts += [(len(valid), pick["situation"], e["situation"]) for e, v in verdicts if v is None]
            valid.append(pick)
            print(f"   ✔ {i}. {label} -> {concept}" + (" (repris d'un exemple)" if is_example else ""))
        valid = self.drop_doubtful(valid, doubts)
        in_drawn = sum(1 for v in valid if v.get("domain") in drawn)
        print(f"   {len(valid)} candidat(s) valide(s), dont {in_drawn} dans les domaines du run.")
        if not valid:
            return None
        return self.choose_free(valid)

    def drop_doubtful(self, valid: list[dict], doubts: list[tuple[int, str, str]]) -> list[dict]:
        """Paires douteuses (même concept, mots-clés proches) : un seul appel au LLM ; « même scène » = écarté."""
        if not doubts:
            return valid
        pairs = "\n".join(f"{n}. « {a} » / « {b} »" for n, (_, a, b) in enumerate(doubts, 1))
        sections = self.read_sections("situation_check.md")
        try:
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"])},
                 {"role": "user", "content": self.mask_forbidden(self.fill(sections["user"], pairs=pairs))}],
                temperature=0.0, max_completion_tokens=400, **self.simple_routing())
            same = {int(n) for n in data.get("memes") or [] if str(n).isdigit()}
        except Exception as e:                       # doute non levé : prudence, le candidat est écarté
            print(f"⚠️ Vérification des situations impossible ({e}) : candidats douteux écartés.")
            same = set(range(1, len(doubts) + 1))
        dropped = {doubts[n - 1][0] for n in same if 1 <= n <= len(doubts)}
        for idx in sorted(dropped):
            print(f"   ✖ {valid[idx]['situation'][:90]} : même scène de vie qu'un sujet récent (vérifié par le LLM)")
        return [v for i, v in enumerate(valid) if i not in dropped]

    def choose_free(self, valid: list[dict]) -> dict:
        if len(valid) == 1:
            print(f"🧭 Sujet retenu : {valid[0]['situation']} (seul candidat valide)")
            return valid[0]
        lines = []
        for i, pick in enumerate(valid, 1):
            main = fcalc.compute(pick["concept"], pick["params"]).main
            lines.append(f"{i}. {pick['situation']} -> {pick['question']} (résultat : {main.label} = {main.text})")
        sections = self.read_sections("select_free.md")
        values = {"candidates": "\n".join(lines), "recent": self.recent_topics_text(10)}
        try:
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], **values)},
                 {"role": "user", "content": self.mask_forbidden(self.fill(sections["user"], **values))}],
                temperature=0.3, max_completion_tokens=500, **self.simple_routing())
            index = int(str(data.get("choice", "")).strip()) - 1
            if 0 <= index < len(valid):
                print(f"🧭 Sujet retenu par le LLM parmi {len(valid)} : {valid[index]['situation']} "
                      f"({data.get('reason', '')})")
                return valid[index]
        except Exception as e:
            print(f"⚠️ Choix du sujet par le LLM impossible ({e}) : premier candidat valide.")
        print(f"🧭 Sujet retenu : {valid[0]['situation']} (premier candidat valide)")
        return valid[0]
