"""Cerveau de la chaîne Mystery.

Flux : région + catégorie + format imposés par le code -> page Wikipédia réelle
-> titre écrit à partir de la page -> hooks -> script ancré sur la page -> fact-check.
"""
import math
import random
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from auracontent.core.brain.base_brain import BaseBrain
from auracontent.services.scraping.anecdotes import collect_french_anecdotes
from auracontent.services.scraping.wikipedia import fetch_page, find_candidates, place_details
from auracontent.services.visuals.asset_manager import subject_settings
from auracontent.services.visuals.subject_images import collect_subject_images, place_terms_of
from auracontent.utils.topic_tracker import (
    load_global_history,
    load_last_categories,
    load_last_regions,
    load_used_sources,
    load_used_values,
)

MOODS = {"ominous", "intriguing", "tense", "awe", "scientific", "investigation"}
ROLES = {"hook", "tension", "context", "value", "escalation", "reveal", "cta"}
SCENE_TYPES = {"specific", "generic"}
TITLE_FORMATS = [
    "fait daté (commence par l'année ou la date)",
    "lieu en tête, suivi de deux-points puis du fait",
    "paradoxe en une phrase affirmative",
    "chiffre précis en tête",
]
MAX_TITLE_CHARS = 80              # au-delà, YouTube coupe le titre bien avant la fin
BANNED_TITLE_WORDS = ("le plus ", "la plus ", "les plus ", "incroyable", "hallucinant", "bizarre")
MAX_WORDS_PER_SCENE = 32          # le prompt demande deux phrases de 12 mots au plus, on tolère jusqu'à 32
DEFAULT_TOPIC_ATTEMPTS = 10
ANECDOTE_CATEGORY = {"name": "anecdote « Le saviez-vous ? » de Wikipédia", "search": []}
DEFAULT_ANECDOTE_YEARS = (2010, 2025)
DEFAULT_MIN_SOURCE_IMAGES = 5
HOOK_ROUNDS = 3                   # générations d'accroches avant d'abandonner (jamais d'accroche par défaut)
MAX_HOOK_WORDS = 12               # l'accroche ouvre la scène 1 : même limite que les phrases du script
NUMBER_WORDS = {"deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
                "treize", "quatorze", "quinze", "seize", "vingt", "trente", "quarante", "cinquante",
                "soixante", "cent", "cents", "mille", "million", "millions", "milliard", "milliards"}
STOPWORDS = {"le", "la", "les", "l", "de", "du", "des", "d", "et", "en", "au", "aux", "a", "à", "un", "une",
             "sur", "sous", "dans", "par", "pour", "ce", "cet", "cette", "son", "sa", "ses", "sans"}


def fold(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : comparaisons robustes (titres, accroches, lieux)."""
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?…])\s+|[;:]\s+", str(text)) if p.strip()]


def count_words(sentence: str) -> int:
    """Mots prononcés : « l'abbaye » compte pour un mot, la ponctuation seule pour aucun."""
    return len([w for w in re.split(r"\s+", sentence) if re.search(r"\w", w)])


# Articles généralistes : la première phrase définit une entité administrative, pas un fait
GENERALIST = re.compile(r"\best (une|un|l une des|l un des) (commune|ville|region|province|departement|localite|"
                        r"agglomeration|metropole|collectivite|canton|arrondissement|pays|intercommunalite)\b")


def prefilter_candidates(candidates: list[dict], region: dict) -> list[dict]:
    """Filtre sans modèle avant le choix par LLM : écarte les articles généralistes (commune, département...)
    et les pages qui ne nomment ni la région visée ni l'un de ses lieux de recherche."""
    places = [fold(x) for x in [region.get("name", "").split("(")[0], *region.get("search", [])] if fold(x)]
    kept = []
    for c in candidates:
        head = fold(c.get("extract", "")[:300])
        if GENERALIST.search(head):
            continue
        text = f" {fold(c.get('title', ''))} {fold(c.get('extract', '')[:4000])} "
        if places and not any(f" {p} " in text for p in places):
            continue
        kept.append(c)
    return kept


def banned_word_pattern(words) -> re.Pattern | None:
    """« escarpé » attrape aussi « escarpée », « escarpés », « escarpées »."""
    stems = [re.escape(w.strip().lower()) for w in words or [] if str(w).strip()]
    if not stems:
        return None
    return re.compile(r"\b(" + "|".join(stems) + r")(e|s|es|x)?\b", re.IGNORECASE)


@dataclass
class MysteryBrain(BaseBrain):
    channel_name: str = "mystery"
    _source: dict | None = field(default=None, init=False, repr=False)      # page Wikipédia du sujet
    _anecdotes: list | None = field(default=None, init=False, repr=False)   # réserve « Le saviez-vous ? »
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

    def pick_topic(self, max_attempts: int | None = None, previous_stats_list=None) -> str:
        """Retourne le titre. La page source et la région sont gardées dans self._source / self.last_pick.

        Chaque essai : page Wikipédia -> nombre d'images exploitables du lieu (seuil brain.min_source_images)
        -> titre -> retournement validé par le LLM -> anti-doublon. Si aucun essai ne passe, on retient le
        sujet testé qui a le plus d'images plutôt que d'échouer.
        """
        b = self.config["brain"]
        max_attempts = int(max_attempts or b.get("topic_attempts", DEFAULT_TOPIC_ATTEMPTS))
        min_images = int(b.get("min_source_images", DEFAULT_MIN_SOURCE_IMAGES))
        used = load_global_history()
        used_sources = load_used_sources()
        stats_text = self._stats_text(previous_stats_list)
        tested: dict[str, dict] = {}          # titre de la page -> essai (pour le repli)

        sources = [str(x) for x in b.get("topic_sources") or ["keywords"]]
        for attempt in range(1, max_attempts + 1):
            title_vars, region, category, _ = self.build_title_vars(used, stats_text)
            source, region, category = self._next_source(sources, region, category, used_sources | set(tested))
            if source is None:
                print(f"   ↻ Essai {attempt}/{max_attempts} : aucune page Wikipédia exploitable "
                      f"({category['name']} / {region['name']}).")
                continue
            title_vars.update(forced_region=region["name"], forced_category=category["name"])

            trial = {"source": source, "region": region, "category": category, "title_vars": title_vars}
            trial["details"] = place_details(source.get("wikibase_item"))
            trial["images"] = self.count_source_images(source, trial["details"])
            tested[source["title"].lower()] = trial
            print(f"   🖼️ Essai {attempt}/{max_attempts} « {source['title']} » : {trial['images']} image(s) "
                  f"exploitable(s) (minimum {min_images})")
            if trial["images"] < min_images:
                print("   ↻ Sujet trop peu illustré, sujet suivant.")
                continue

            title = self._accept_title(trial, used)
            if title:
                return self._retain(trial, title)

        if tested:
            print(f"⚠️ Aucun sujet ne passe tous les contrôles en {max_attempts} essais : "
                  "repli sur le sujet testé le mieux illustré.")
            for trial in sorted(tested.values(), key=lambda t: -t["images"])[:3]:
                print(f"   ↪ « {trial['source']['title']} » ({trial['images']} image(s))")
                title = self._accept_title(trial, used)
                if title:
                    return self._retain(trial, title)
        raise RuntimeError(f"Aucun sujet valide trouvé après {max_attempts} tentatives.")

    # ==========================================
    # REPRISE (sujet validé, script en échec)
    # ==========================================
    def export_state(self) -> dict:
        return {"source": self._source, "last_pick": dict(self.last_pick)}

    def restore_state(self, state: dict) -> None:
        self._source = state.get("source")
        self.last_pick = dict(state.get("last_pick") or {})

    def count_source_images(self, source: dict, details: dict) -> int:
        """Images exploitables du lieu : article Wikipédia source + sa catégorie Commons (licence libre,
        1000 px de large au moins, ni logo, ni carte, ni blason, ni pictogramme). 0 si Wikimedia échoue."""
        cfg = subject_settings(self.config.get("visuals"))
        try:
            images = collect_subject_images(source["title"], details.get("commons_category"), cfg,
                                            place_terms=place_terms_of(details), documents=False)
        except Exception as e:   # jamais bloquant : le sujet est simplement considéré comme non illustré
            print(f"⚠️ Comptage des images impossible : {e}")
            return 0
        return len(images)

    def _accept_title(self, trial: dict, used) -> str | None:
        """Titre écrit d'après la source, avec retournement et sans doublon ; None sinon."""
        title = self._write_title(trial["title_vars"], trial["source"])
        if not title:
            return None
        ok, reason = self.has_reversal(title, trial["source"])
        if not ok:
            print(f"   ↻ Titre sans retournement rejeté : « {title} » ({reason})")
            return None
        is_dup, matched = self.is_duplicate_topic_llm(title, used)
        if is_dup:
            print(f"   ↻ Doublon avec « {matched} », nouvel essai.")
            return None
        return title

    def _retain(self, trial: dict, title: str) -> str:
        source, region, category = trial["source"], trial["region"], trial["category"]
        self._source = source
        self.last_pick = {"region": region["name"], "category": category["name"],
                          "source_title": source["title"], "source_url": source["url"],
                          "source_images": trial["images"],
                          "topic_source": "le_saviez_vous" if source.get("anecdote") else "keywords"}
        if source.get("anecdote"):
            self.last_pick.update(anecdote=source["anecdote"], anecdote_id=source.get("anecdote_id"))
        if source.get("coordinates"):   # pour la carte animée (lot 1)
            self.last_pick.update(lat=source["coordinates"]["lat"], lon=source["coordinates"]["lon"])
        # commune (étiquette de la carte, homonymes), département, catégorie Commons (photos du lieu)
        self.last_pick.update(trial.get("details") or {})
        return title

    def has_reversal(self, title: str, source: dict) -> tuple[bool, str]:
        """Le LLM valide que le titre contient un retournement (ce qui s'est passé contredit ce qu'on
        attendrait). Une simple fondation, naissance ou construction est rejetée. En cas d'erreur du LLM,
        le titre est rejeté (jamais accepté par défaut)."""
        sections = self.read_sections("title_check.md")
        user = self.fill(sections["user"], title=title, source_title=source.get("title", ""),
                         source_extract=str(source.get("extract", ""))[:1500])
        try:
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": sections["system"]}, {"role": "user", "content": user}],
                temperature=0, max_completion_tokens=200, **self.simple_routing(),
            )
        except (RuntimeError, ValueError) as e:
            return False, f"contrôle impossible : {e}"
        return data.get("retournement") is True, str(data.get("raison", "")).strip()

    # ==========================================
    # SOURCES DE SUJETS (brain.topic_sources)
    # ==========================================
    def _next_source(self, sources, region, category, excluded):
        """(page, région, catégorie) : chaque source de brain.topic_sources dans l'ordre, la suivante si
        elle ne donne rien. « le_saviez_vous » : anecdotes de Wikipédia ; « keywords » : recherche aléatoire."""
        for name in sources:
            if name == "le_saviez_vous":
                page = self._next_anecdote(excluded)
                if page:
                    return page, self.region_of(page), ANECDOTE_CATEGORY
            elif name == "keywords":
                page = self._find_source(region, category, excluded)
                if page:
                    return page, region, category
                return None, region, category
            else:
                print(f"⚠️ Source de sujets inconnue dans brain.topic_sources : {name}")
        return None, region, category

    def _next_anecdote(self, excluded) -> dict | None:
        """Prochaine anecdote inédite dont l'article est exploitable ; aucun appel LLM."""
        cfg = dict(self.config.get("brain", {}).get("le_saviez_vous") or {})
        if self._anecdotes is None:
            first, last = cfg.get("years", DEFAULT_ANECDOTE_YEARS)
            try:
                self._anecdotes = collect_french_anecdotes(
                    list(range(int(first), int(last) + 1)), archives=int(cfg.get("archives_per_run", 2)),
                    include_home=bool(cfg.get("include_home", True)), sample=int(cfg.get("sample", 200)),
                    exclude_ids=load_used_values("anecdote_id"), exclude_titles=set(excluded))
            except Exception as e:      # jamais bloquant : la recherche par mots-clés prend le relais
                print(f"⚠️ « Le saviez-vous ? » indisponible : {e}")
                self._anecdotes = []
        while self._anecdotes:
            anecdote = self._anecdotes.pop(0)
            if anecdote["target"].lower() in excluded:
                continue
            page = fetch_page(anecdote["target"])
            if not page:
                print(f"   ↻ Anecdote écartée (article trop court ou trop général) : {anecdote['target']}")
                continue
            print(f"   💡 Anecdote : {anecdote['text'][:140]}")
            return {**page, "anecdote": anecdote["text"], "anecdote_id": anecdote["id"],
                    "wikibase_item": page.get("wikibase_item") or anecdote.get("wikibase_item"),
                    # coordonnées Wikidata si la page n'en a pas (région, carte animée)
                    "coordinates": page.get("coordinates") or anecdote.get("coordinates")}
        return None

    def region_of(self, page: dict) -> dict:
        """Région du YAML qui contient le lieu (coordonnées de la page), pour la rotation des régions."""
        from auracontent.services.visuals.map_scene import find_region, is_metropolitan

        regions = self.config["brain"]["regions"]
        coords = page.get("coordinates") or {}
        if not coords:
            return {"name": "France", "search": []}
        lat, lon = coords["lat"], coords["lon"]
        if not is_metropolitan(lat, lon):
            return next((r for r in regions if "outre" in fold(r["name"])), {"name": "Outre-mer", "search": []})
        feature = find_region(lat, lon)
        name = fold((feature or {}).get("properties", {}).get("name", ""))
        if name == "ile de france" and 48.815 <= lat <= 48.902 and 2.224 <= lon <= 2.470:
            return next((r for r in regions if fold(r["name"]).startswith("paris")), {"name": "Paris", "search": []})
        for r in regions:
            if name and fold(r["name"]).startswith(name):
                return r
        return {"name": (feature or {}).get("properties", {}).get("name", "France"), "search": []}

    def _find_source(self, region, category, used_sources):
        query = f'{random.choice(category["search"])} {random.choice(region["search"])}'
        print(f"   🔎 Wikipédia : « {query} »")
        candidates = find_candidates(query, limit=8, exclude=used_sources)
        kept = prefilter_candidates(candidates, region)
        if len(kept) < len(candidates):
            print(f"   🧹 Filtre sans modèle : {len(candidates) - len(kept)} page(s) écartée(s) sur {len(candidates)}.")
        if not kept:
            return None                       # rien d'utilisable : aucun appel LLM
        return self._choose_source(kept, region, category)

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
                                                 temperature=0, max_completion_tokens=100, **self.simple_routing())
            idx = int(data.get("index", -1))
        except (RuntimeError, ValueError, TypeError) as e:
            print(f"⚠️ Choix de la source impossible : {e}")
            return None
        return candidates[idx] if 0 <= idx < len(candidates) else None

    def _write_title(self, title_vars, source):
        sections = self.read_sections("titles.md")
        source_block = f'SOURCE ({source["title"]}) :\n"""{source["extract"][:3000]}"""'
        if source.get("anecdote"):   # fait déjà repéré et sourcé par les contributeurs de Wikipédia
            source_block = (f"ANGLE À RETENIR (rubrique « Le saviez-vous ? » de Wikipédia) : « {source['anecdote']} »\n"
                            "Le titre raconte CE fait, avec les détails exacts de la source.\n\n" + source_block)
        user = self.fill(sections["user"], source_block=source_block, **title_vars)
        data = self.llm.call_json_with_retry(
            [{"role": "system", "content": sections["system"]}, {"role": "user", "content": user}],
            temperature=1.0, max_completion_tokens=200, **self.simple_routing(),
        )
        title = str(data.get("title", "")).strip().strip('"«» ')
        low = title.lower()
        if (not title or len(title) > MAX_TITLE_CHARS or len(title.split()) > 14
                or any(w in low for w in BANNED_TITLE_WORDS)):
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

    @staticmethod
    def _hook_score(hook: dict) -> float | None:
        try:
            return float(hook.get("score"))
        except (TypeError, ValueError):
            return None

    def valid_hooks(self, hooks, topic) -> list[dict]:
        """Rejette les accroches notées 0/10, identiques au titre ou trop longues."""
        title = fold(topic)
        kept = []
        for h in hooks:
            if not isinstance(h, dict) or not str(h.get("text", "")).strip():
                continue
            text = fold(h["text"])
            if self._hook_score(h) == 0:
                print(f"   ↻ Accroche notée 0/10 rejetée : « {h['text']} »")
            elif text == title or (len(title) > 10 and title in text):
                print(f"   ↻ Accroche identique au titre rejetée : « {h['text']} »")
            elif count_words(h["text"]) > MAX_HOOK_WORDS:
                print(f"   ↻ Accroche de plus de {MAX_HOOK_WORDS} mots rejetée : « {h['text']} »")
            else:
                kept.append(h)
        return kept

    def generate_hook_variants(self, topic, n=5, previous_stats_list=None):
        """Accroches valables uniquement : une liste vide est régénérée (HOOK_ROUNDS fois), jamais
        remplacée par le titre."""
        sections = self.read_sections("hook.md")
        user = self.fill(sections["user"], n=n, topic=topic, grounding_block=self._grounding(),
                         stats_block=self._stats_text(previous_stats_list))
        for round_ in range(1, HOOK_ROUNDS + 1):
            data = self.llm.call_json_with_retry(
                [{"role": "system", "content": self.fill(sections["system"], n=n)},
                 {"role": "user", "content": user}],
                temperature=1.0, max_completion_tokens=1500, **self.simple_routing(),
            )
            hooks = self.valid_hooks(data.get("hooks", []), topic)
            if hooks:
                return hooks[:n]
            print(f"   ↻ Aucune accroche valable ({round_}/{HOOK_ROUNDS}), nouvelle génération.")
            user += ("\n\nCORRECTION : tes accroches précédentes étaient notées 0, identiques au titre ou trop "
                     "longues. Écris des accroches neuves, différentes du titre.")
        raise RuntimeError("aucune accroche valable après plusieurs générations.")

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
            min_specific=self.min_specific(scene_count),
            max_sentence_words=self.style_cfg()["max_sentence_words"],
            banned_words=", ".join(f"« {w} »" for w in self.style_cfg()["banned_words"]) or "aucun",
        )
        if correction_feedback:
            user += "\n\n" + correction_feedback
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def style_cfg(self) -> dict:
        """brain.style (YAML) : longueur des phrases et adjectifs décoratifs interdits."""
        cfg = dict(self.config.get("brain", {}).get("style") or {})
        cfg.setdefault("max_sentence_words", 12)
        cfg.setdefault("banned_words", [])
        return cfg

    def min_specific(self, scene_count: int) -> int:
        """Scènes 'specific' exigées : brain.min_specific_ratio (2/3 par défaut, soit 4 sur 6)."""
        ratio = float(self.config.get("brain", {}).get("min_specific_ratio", 2 / 3))
        return min(scene_count, math.ceil(scene_count * ratio - 1e-9))

    # ==========================================
    # VALIDATION
    # ==========================================
    def check_style(self, scenes) -> list[str]:
        """Phrases trop longues et adjectifs décoratifs : renvoyés au LLM comme corrections."""
        cfg = self.style_cfg()
        limit = int(cfg["max_sentence_words"])
        banned = banned_word_pattern(cfg["banned_words"])
        issues = []
        for scene in scenes:
            for sentence in sentences(scene.get("text", "")):
                n = count_words(sentence)
                if n > limit:
                    issues.append(f"scène {scene['id']} : phrase de {n} mots (maximum {limit}) : « {sentence} ». "
                                  "Coupe-la en deux phrases courtes, comme à l'oral.")
            hits = sorted({m.group(0).lower() for m in banned.finditer(scene.get("text", ""))}) if banned else []
            if hits:
                issues.append(f"scène {scene['id']} : adjectif(s) décoratif(s) interdit(s) {', '.join(hits)}. "
                              "Supprime-les ou remplace-les par un fait précis.")
        return issues

    def check_specific_count(self, scenes) -> list[str]:
        scored = [s for s in scenes if s.get("role") != "cta"]
        need = self.min_specific(len(scored))
        have = sum(1 for s in scored if s.get("scene_type") == "specific")
        if have < need:
            return [f"{have} scène(s) 'specific' sur {len(scored)}, il en faut au moins {need} : montre le lieu "
                    "réel (bâtiment, salle, objet, détail) plutôt qu'une ambiance."]
        return []

    def validate_headline(self, data) -> None:
        """Bandeau rejeté s'il n'a ni verbe ni chiffre, ou s'il n'aligne que des noms de lieux."""
        headline = str(data.get("on_screen_title") or "").strip()
        if not headline:
            raise ValueError("champ 'on_screen_title' manquant.")
        words = [w for w in fold(headline.replace("|", " ")).split() if w not in STOPWORDS]
        places = set()
        for name in [s.get("location_name") for s in data.get("scenes", [])] + [
                self.last_pick.get(k) for k in ("source_title", "commune", "department", "region")]:
            places.update(fold(re.sub(r"\([^)]*\)", " ", str(name or ""))).split())
        if words and all(w in places for w in words):
            raise ValueError(f"on_screen_title « {headline} » : seulement des noms de lieux. Le bandeau doit dire "
                             "ce qui s'est passé (un verbe ou un chiffre), pas seulement où.")
        if any(ch.isdigit() for ch in headline) or any(w in NUMBER_WORDS for w in words):
            return
        if not self._headline_has_verb(headline):
            raise ValueError(f"on_screen_title « {headline} » : ni verbe ni chiffre. Le bandeau doit contenir un "
                             "verbe conjugué ou un participe (« VENDUE », « DISPARAÎT ») ou un chiffre.")

    def _headline_has_verb(self, headline: str) -> bool:
        """Le LLM dit si le bandeau contient un verbe (conjugué, participe ou infinitif). En cas d'erreur
        du LLM, le bandeau est rejeté (le script est alors régénéré)."""
        prompt = (f"Bandeau : « {headline} »\nCe texte contient-il au moins un verbe (forme conjuguée, participe "
                  "passé ou présent, ou infinitif) ? Un nom (« construction », « vente ») n'est pas un verbe. "
                  'Réponds uniquement en JSON : {"verbe": true|false, "mot": "..."}')
        try:
            data = self.llm.call_json_with_retry([{"role": "user", "content": prompt}],
                                                 temperature=0, max_completion_tokens=100, **self.simple_routing())
        except (RuntimeError, ValueError) as e:
            print(f"⚠️ Contrôle du bandeau impossible : {e}")
            return False
        return data.get("verbe") is True

    def validate_script_specifics(self, data, topic):
        if not str(data.get("closing_cta", "")).strip():
            raise ValueError("champ 'closing_cta' manquant.")
        self.validate_headline(data)

        for scene in data["scenes"]:
            sid = scene["id"]
            words = len(str(scene["text"]).split())
            if words > MAX_WORDS_PER_SCENE:
                raise ValueError(f"scène {sid} : {words} mots, maximum {MAX_WORDS_PER_SCENE} "
                                 "(deux phrases courtes).")
            if scene.get("location_name") and not str(scene.get("location_country", "")).strip():
                raise ValueError(f"scène {sid} : 'location_country' manquant pour '{scene['location_name']}'.")
            # Le LLM confond parfois scene_type et role ("intro", "hook"...) : on le recalcule
            if scene.get("scene_type") not in SCENE_TYPES:
                scene["scene_type"] = "specific" if scene.get("location_name") else "generic"
            if scene.get("mood") not in MOODS:
                scene["mood"] = "intriguing"
            if scene.get("role") not in ROLES:
                scene["role"] = "context"

    def check_script_logic(self, topic, data):
        """Lieux, style, scènes 'specific' puis fact-check : le fact-check tourne toujours (véracité)."""
        scenes = data["scenes"]
        writing = self.check_style(scenes) + self.check_specific_count(scenes)
        return self._check_geo(scenes) + writing + self._llm_factcheck(topic, scenes, data)

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
                temperature=0, max_completion_tokens=500, **self.script_routing(),   # véracité : gros modèles
            )
        except Exception as e:
            print(f"⚠️ Fact-check indisponible : {e}")
            data["factcheck"] = "skipped"
            return []

        # sans source, un LLM ne repère que les contradictions internes : à traiter comme "non vérifié"
        data["factcheck"] = "grounded" if grounded else "ungrounded"
        # seule la liste 'issues' fait foi (is_consistent peut la contredire)
        return [str(i).strip() for i in res.get("issues", []) if str(i).strip()]