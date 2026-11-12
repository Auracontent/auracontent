"""Gestionnaire générique de récupération de médias visuels."""

from __future__ import annotations

import hashlib
import os
from collections import Counter

from auracontent.services.scraping.archive_provider import ArchiveProvider
from auracontent.services.scraping.europeana_provider import EuropeanaProvider
from auracontent.services.scraping.gallica_provider import GallicaProvider
from auracontent.services.scraping.video_provider import VideoProvider
from auracontent.services.visuals.ai_image import AIImageGenerator
from auracontent.services.visuals.cloudflare_image import CloudflareImageGenerator
from auracontent.services.visuals.subject_images import (
    HEADERS as WIKIMEDIA_HEADERS,
)
from auracontent.services.visuals.subject_images import (
    SubjectImagePool,
    collect_subject_images,
    is_distinctive,
    mentions_place,
    name_matches,
    place_terms_of,
    subject_name,
)
from auracontent.utils.scraping_helpers import download_file, load_history

# Direction artistique par défaut (surchargeable via channel_config)
DEFAULT_AI_COMPOSITION = "cinematic shot, well composed"
DEFAULT_AI_LIGHTING = "cinematic lighting"
DEFAULT_AI_TEXTURE = "detailed textures"
DEFAULT_AI_PALETTE = "cinematic color grading"
DEFAULT_AI_MOOD = "atmospheric"
DEFAULT_AI_SUFFIX = "photorealistic, 8k resolution, highly detailed"
DEFAULT_VIDEO_FALLBACK_QUERY = "cinematic background atmosphere"
# Image générée (d) : l'époque et la région sont imposées, tout objet moderne est exclu
PERIOD_GUARD = ("period-accurate architecture, clothing and objects, no modern objects, no cars, "
                "no power lines, no street lights, no plastic, no tourists")

AssetResult = tuple[bool, str]
# Décompte de fin de génération : origine -> libellé du journal
TALLY_LABELS = {"object": "Wikipédia", "article": "Wikipédia", "commons": "Commons", "document": "Commons", "europeana": "Europeana",
                "gallica": "Gallica", "ai": "image générée", "video": "Pexels / Pixabay"}


def subject_settings(visuals_cfg: dict | None) -> dict:
    """Section visuals.subject_images du YAML ; désactivée si absente (autres chaînes : ordre historique)."""
    cfg = dict((visuals_cfg or {}).get("subject_images") or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("max_uses_per_file", 2)
    cfg.setdefault("documents", True)       # gravures et cartes postales anciennes de Commons
    cfg.setdefault("europeana", True)       # sans effet sans clé EUROPEANA_API_KEY
    cfg.setdefault("gallica", False)        # réutilisation commerciale payante : voir gallica_provider.py
    cfg.setdefault("stock_video", True)     # (e) dernier recours
    cfg.setdefault("document_shots", 0)     # plans réservés aux documents d'époque s'il en existe (variété)
    return cfg


def file_digest(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


class AssetManager:
    """
    Gestionnaire générique de récupération de médias visuels.
    La direction artistique (prompts IA, requêtes par défaut) est injectée
    via channel_config.
    """

    def __init__(self, channel_config: dict | None = None):
        self.config = channel_config or {}

        # Fournisseurs
        # Historique des assets déjà utilisés {source: [ids]} (anti-réutilisation)
        self.history = load_history()
        self.videos = VideoProvider(self.history)
        self.archives = ArchiveProvider(self.history)
        self.europeana = EuropeanaProvider(self.history)
        self.ai = AIImageGenerator()
        self.cloudflare = CloudflareImageGenerator()

        # Direction artistique (IA)
        self.ai_composition = self.config.get("ai_composition", DEFAULT_AI_COMPOSITION)
        self.ai_lighting = self.config.get("ai_lighting", DEFAULT_AI_LIGHTING)
        self.ai_texture = self.config.get("ai_texture", DEFAULT_AI_TEXTURE)
        self.ai_palette = self.config.get("ai_palette", DEFAULT_AI_PALETTE)
        self.ai_mood = self.config.get("ai_mood", DEFAULT_AI_MOOD)
        self.ai_suffix = self.config.get("ai_suffix", DEFAULT_AI_SUFFIX)

        # Secours (vidéo de stock)
        self.video_fallback_query = self.config.get(
            "video_fallback_query", DEFAULT_VIDEO_FALLBACK_QUERY
        )

        # Mode « sujet d'abord » (visuals.subject_images) : réserve d'images propre à la vidéo
        self.subject_cfg = subject_settings(self.config)
        self.gallica = GallicaProvider(self.history, enabled=bool(self.subject_cfg["gallica"]))
        self.max_uses = int(self.subject_cfg["max_uses_per_file"])
        self.pool = SubjectImagePool([], self.max_uses)
        self.subject: dict = {}
        self.file_uses: dict[str, int] = {}      # empreinte du fichier -> emplois dans la vidéo
        self.last_key: str | None = None         # visuel précédent : jamais deux fois de suite
        self.tally: Counter = Counter()          # plans par origine (journal de fin de génération)
        self.last_origin: str = ""
        self.document_scenes: set = set()        # scènes qui ont déjà reçu un document d'époque

    @property
    def subject_mode(self) -> bool:
        return bool(self.subject_cfg.get("enabled"))

    # ==========================================
    # MODE « SUJET D'ABORD »
    # ==========================================
    def prepare_subject(self, pick: dict | None, era: str | None = None, images=None) -> int:
        """Collecte une fois par vidéo les images (a), (b) et (c) du sujet. Retourne leur nombre.

        `pick` : script["pick"] (source_title, commons_category, commune, region). `images` : réserve
        déjà constituée (tests), sinon interrogation de Wikipédia et de Commons.
        """
        pick = pick or {}
        self.subject = {
            "name": subject_name(pick.get("source_title") or ""),
            "commune": str(pick.get("commune") or "").strip(),
            "department": str(pick.get("department") or "").strip(),
            "region": str(pick.get("region") or "").split("(")[0].strip(),
            "era": str(era or "").strip(),
            "place_terms": place_terms_of(pick),
            # objet précis de l'anecdote et son édifice (une statue dans une église) : leurs images d'abord
            "focus": [str(n) for n in pick.get("focus") or [] if str(n).strip()],
        }
        if images is None:
            focus = self.subject["focus"]
            print(f"🖼️ Images du sujet : « {' / '.join(focus) or pick.get('source_title') or '?'} »")
            images = collect_subject_images(pick.get("source_title"), pick.get("commons_category"), self.subject_cfg,
                                            place_terms=self.subject["place_terms"], focus=focus or None,
                                            focus_files=pick.get("focus_files") or None)
        self.pool = SubjectImagePool(images, self.max_uses)
        return len(self.pool)

    def _accept(self, path: str, origin: str) -> bool:
        """Limite par FICHIER (empreinte du contenu) : `max_uses` emplois au plus, jamais deux fois de suite."""
        digest = file_digest(path)
        if digest is None:
            return False
        if self.file_uses.get(digest, 0) >= self.max_uses or digest == self.last_key:
            print(f"   🔁 Fichier déjà montré ({self.file_uses.get(digest, 0)} fois) : écarté.")
            return False
        self.file_uses[digest] = self.file_uses.get(digest, 0) + 1
        self.last_key = digest
        self.tally[origin] += 1
        self.last_origin = origin
        return True

    def tally_report(self) -> str:
        """« 9 Wikipédia/Commons... » : plans par source, dans l'ordre de priorité."""
        totals: Counter = Counter()
        for origin, n in self.tally.items():
            totals[TALLY_LABELS.get(origin, origin)] += n
        order = list(dict.fromkeys(TALLY_LABELS.values()))
        parts = [f"{label} {totals[label]}" for label in order if totals[label]]
        parts += [f"{label} {n}" for label, n in totals.items() if label not in order]
        return ", ".join(parts) or "aucun"

    def _from_pool(self, output_path: str, first_use_only: bool, origins: set[str] | None = None) -> bool:
        for image in self.pool.candidates(avoid=self.last_key, first_use_only=first_use_only):
            if origins is not None and image.origin not in origins:
                continue
            if not download_file(image.url, output_path, headers=WIKIMEDIA_HEADERS, min_bytes=20_000):
                self.pool.discard(image.key)
                continue
            digest = file_digest(output_path)
            if digest == self.last_key or self.file_uses.get(digest, 0) >= self.max_uses:
                self.pool.discard(image.key)     # même contenu sous un autre nom
                continue
            self.pool.record(image.key)
            self.file_uses[digest] = self.file_uses.get(digest, 0) + 1
            self.last_key = digest
            self.tally[image.origin] += 1
            self.last_origin = image.origin
            print(f"   🏛️ {TALLY_LABELS[image.origin]} : {image.title} — {image.url} "
                  f"({self.pool.uses[image.key]}/{self.max_uses})")
            return True
        return False

    def archive_query(self, scene: dict) -> str:
        """Requête Europeana / Gallica : le lieu de la scène (scène « specific ») ou le sujet, suivi de la
        commune ou du département (homonymes). Le type de scène ne sert plus qu'à formuler la requête."""
        queries = self.archive_queries(scene)
        return queries[0] if queries else ""

    def archive_queries(self, scene: dict) -> list[str]:
        """Requêtes Europeana / Gallica, de la plus étroite à la plus large : « édifice commune », puis le nom
        de l'édifice seul (la commune exigée dans la notice écartait presque tout)."""
        place = self.subject.get("commune") or self.subject.get("department") or ""
        if scene.get("scene_type") == "specific" and scene.get("location_name"):
            base = str(scene["location_name"]).strip()
        else:
            base = (self.subject.get("focus") or [self.subject.get("name")])[-1] or \
                str(scene.get("location_name") or "").strip()
        if not base or not place:     # sans commune ni département, impossible d'écarter les homonymes
            return []
        narrow = base if place.lower() in base.lower() else f"{base} {place}"
        return list(dict.fromkeys([narrow, base]))

    def archive_notice_ok(self, text: str, base: str) -> bool:
        """La notice nomme la commune ou le département, ou l'édifice par un nom propre distinctif."""
        terms = self.subject.get("place_terms", [])
        return mentions_place(text, terms) or (is_distinctive(base, terms) and name_matches(text, base, terms))

    def _archive_ok(self, origin: str, path: str) -> bool:
        if not self._accept(path, origin):
            return False
        provider = self.europeana if origin == "europeana" else self.gallica
        print(f"   🏺 {origin} : {getattr(provider, 'last_url', '?')}")
        return True

    def _archives(self, scene: dict, output_path: str) -> AssetResult | None:
        for query in self.archive_queries(scene):
            base = self.archive_queries(scene)[-1]
            accept = lambda text, base=base: self.archive_notice_ok(text, base)   # noqa: E731
            if self.subject_cfg.get("europeana") and self.europeana.get_image(query, output_path, accept=accept) \
                    and self._archive_ok("europeana", output_path):
                return True, "europeana"
            if self.gallica.get_image(query, output_path, accept=accept) and self._archive_ok("gallica", output_path):
                return True, "gallica"
        return None

    def _document_slot(self, scene: dict) -> bool:
        """Variété : subject_images.document_shots plans réservés aux documents d'époque, un par scène au
        plus, jamais sur les deux premières scènes (ouverture et carte : le lieu réel)."""
        wanted = int(self.subject_cfg.get("document_shots") or 0)
        used = sum(self.tally[o] for o in ("document", "europeana", "gallica"))
        try:
            sid = int(str(scene.get("id", 0)))
        except ValueError:
            sid = 0
        return used < wanted and sid >= 3 and sid not in self.document_scenes

    def period_prompt(self, scene: dict) -> str:
        """Prompt (d) : sujet de la scène + époque + lieu + « no modern objects »."""
        subject = (scene.get("image_prompt") or scene.get("stock_search") or self.subject.get("name") or "").strip()
        place = ", ".join(x for x in (self.subject.get("commune"), self.subject.get("region"), "France") if x)
        era = self.subject.get("era") or "the historical period of the event"
        context = str(scene.get("event_context") or "").strip()
        parts = [subject, context, f"set in {era}", f"in {place}", PERIOD_GUARD]
        return ". ".join(p for p in parts if p) + ". " + ". ".join(
            [self.ai_composition, self.ai_lighting, self.ai_texture, self.ai_palette, self.ai_suffix])

    def get_scene_asset(self, scene: dict, output_path: str) -> AssetResult:
        """Ordre de priorité, pour toutes les scènes :

        (a) images de l'article Wikipédia source, (b) autres photos du lieu dans sa catégorie Commons,
        (c) gravures et documents d'époque (Commons, Europeana, Gallica), puis un second emploi des images
        (a)-(c), (d) image générée datée et située, sans objet moderne, (e) vidéo de banque d'images.
        Retourne (succès, source) : wiki, europeana, gallica, ai, video ou none.
        """
        if self._document_slot(scene):
            print("   📜 Plan réservé à un document d'époque (variété).")
            sid = int(str(scene.get("id", 0)))
            if self._from_pool(output_path, first_use_only=True, origins={"document"}):
                self.document_scenes.add(sid)
                return True, "wiki"
            found = self._archives(scene, output_path)
            if found:
                self.document_scenes.add(sid)
                return found
        if self._from_pool(output_path, first_use_only=True):
            return True, "wiki"
        found = self._archives(scene, output_path)
        if found:
            return found
        query = self.archive_query(scene)
        if self._from_pool(output_path, first_use_only=False):
            return True, "wiki"

        print("🧠 Plus d'image réelle du sujet : image générée (époque et région imposées).")
        prompt = self.period_prompt(scene)
        if self._generate_ai(prompt, output_path) and self._accept(output_path, "ai"):
            print(f"   🎨 Image générée — prompt : {prompt[:160]}…")
            return True, "ai"

        if self.subject_cfg.get("stock_video"):
            stock = (scene.get("stock_search") or self.video_fallback_query).strip()
            print(f"🎬 Dernier recours : vidéo de banque d'images ('{stock}').")
            if self.videos.fetch_background(stock, output_path) and self._accept(output_path, "video"):
                return True, "video"
        if os.path.exists(output_path):
            os.remove(output_path)
        return self._failure(scene.get("image_prompt") or query or "?")

    def _build_structured_prompt(
        self,
        query: str | None,
        event_context: str | None = None,
        image_prompt: str | None = None,
    ) -> str:
        """Construit un prompt structuré en anglais à partir de l'ADN de la chaîne."""
        clean_query = (query or "").strip()
        clean_image_prompt = (image_prompt or "").strip()

        if clean_image_prompt:
            subject = clean_image_prompt
            if clean_query and clean_query.lower() not in subject.lower():
                subject = f"{subject}, real location: {clean_query}"
        else:
            subject = clean_query

        if event_context:
            subject = f"{subject}, {event_context.strip()}"

        return ". ".join(
            [
                subject,
                self.ai_composition,
                self.ai_lighting,
                self.ai_texture,
                self.ai_palette,
                self.ai_mood,
                self.ai_suffix,
            ]
        )

    def _generate_ai(self, prompt: str, output_path: str) -> bool:
        """Cloudflare FLUX (stable) puis Pollinations en secours."""
        return self.cloudflare.generate_image(prompt, output_path) or self.ai.generate_image(prompt, output_path)

    @staticmethod
    def _failure(query: str) -> AssetResult:
        print(f"❌ Échec total de la récupération d'asset pour : '{query}'")
        return False, "none"

    def get_best_asset(
        self,
        query: str,
        output_path: str,
        scene_type: str = "generic",
        event_context: str | None = None,
        image_prompt: str | None = None,
    ) -> AssetResult:
        """Retourne (succès, source) : wiki, openverse, europeana, pexels_photo, ai, video ou none."""
        if scene_type == "specific":
            return self._get_specific_asset(
                query, output_path, event_context, image_prompt
            )
        return self._get_generic_asset(query, output_path, event_context, image_prompt)

    def _get_specific_asset(
        self,
        query: str,
        output_path: str,
        event_context: str | None,
        image_prompt: str | None,
    ) -> AssetResult:
        """Scènes spécifiques (lieux réels, personnages, objets) : archives d'abord."""
        print(f"🔍 Recherche de la vraie photo historique : '{query}'...")
        if self.archives.get_wikimedia(query, output_path):
            print("🏛️ Vraie archive trouvée !")
            return True, "wiki"

        print(f"🌍 Nouvelle tentative Openverse directe : '{query}'...")
        if self.archives.get_openverse(query, output_path):
            print("🏛️ Archive Openverse trouvée (tentative directe) !")
            return True, "openverse"

        if self.europeana.get_image(query, output_path):
            return True, "europeana"

        ai_prompt = self._build_structured_prompt(
            query, event_context=event_context, image_prompt=image_prompt
        )
        if event_context:
            print(
                "🧠 Archive introuvable. "
                "Tentative IA-First contextualisée (prompt structuré)."
            )
        else:
            print(
                f"🧠 Archive introuvable. "
                f"Tentative IA-First pour : '{query}' (prompt structuré)."
            )

        if self._generate_ai(ai_prompt, output_path):
            return True, "ai"

        print(f"🎬 IA échouée pour '{query}', tentative de secours vidéo générique...")
        if self.videos.fetch_background(self.video_fallback_query, output_path):
            return True, "video"

        return self._failure(query)

    def _get_generic_asset(
        self,
        query: str,
        output_path: str,
        event_context: str | None,
        image_prompt: str | None,
    ) -> AssetResult:
        """Scènes génériques (ambiance, paysages, émotions) : vidéo d'abord."""
        print(f"🔍 Recherche vidéo d'ambiance : '{query}'...")
        if self.videos.fetch_background(query, output_path):
            return True, "video"

        if self.videos.fetch_photo(query, output_path):
            return True, "pexels_photo"

        fallback_prompt = self._build_structured_prompt(
            query, event_context=event_context, image_prompt=image_prompt
        )
        print("🎨 Génération IA de secours (prompt structuré)...")
        if self._generate_ai(fallback_prompt, output_path):
            return True, "ai"

        return self._failure(query)
