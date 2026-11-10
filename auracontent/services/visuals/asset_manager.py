"""Gestionnaire générique de récupération de médias visuels."""

from __future__ import annotations

from auracontent.services.scraping.archive_provider import ArchiveProvider
from auracontent.services.scraping.video_provider import VideoProvider
from auracontent.services.visuals.ai_image import AIImageGenerator
from auracontent.utils.scraping_helpers import load_history

# Direction artistique par défaut (surchargeable via channel_config)
DEFAULT_AI_COMPOSITION = "cinematic shot, well composed"
DEFAULT_AI_LIGHTING = "cinematic lighting"
DEFAULT_AI_TEXTURE = "detailed textures"
DEFAULT_AI_PALETTE = "cinematic color grading"
DEFAULT_AI_MOOD = "atmospheric"
DEFAULT_AI_SUFFIX = "photorealistic, 8k resolution, highly detailed"
DEFAULT_VIDEO_FALLBACK_QUERY = "cinematic background atmosphere"

AssetResult = tuple[bool, str]


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
        self.ai = AIImageGenerator()

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
        """Retourne (succès, source) avec source dans {wiki, openverse, ai, video, none}."""
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

        if self.ai.generate_image(ai_prompt, output_path):
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

        fallback_prompt = self._build_structured_prompt(
            query, event_context=event_context, image_prompt=image_prompt
        )
        print("🎨 Génération IA de secours (prompt structuré)...")
        if self.ai.generate_image(fallback_prompt, output_path):
            return True, "ai"

        return self._failure(query)