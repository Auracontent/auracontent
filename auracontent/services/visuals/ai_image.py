"""Génération d'images IA via Pollinations, avec reprises et modèle de secours."""

from __future__ import annotations
import hashlib
import os
import time
import urllib.parse
from typing import NamedTuple
import requests
from config.settings import (
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    WIKIMEDIA_CONTACT,
)

POLLINATIONS_PROMPT_URL = "https://image.pollinations.ai/prompt/"
MIN_IMAGE_BYTES = 5000
DEFAULT_TIMEOUT = 45
LONG_TIMEOUT = 60

DEFAULT_BASE_STYLE = "photorealistic, 8k resolution, highly detailed"
DEFAULT_NEGATIVE_PROMPT = (
    "text, logo, watermark, subtitles, borders, split screen, multiple frames, "
    "deformed hands, extra fingers, duplicate people, cropped head, "
    "blurry face, cartoon, anime"
)
DEFAULT_PRIMARY_MODEL = "flux"
DEFAULT_FALLBACK_MODEL = "turbo"

VARIANT_HINTS = {
    "a": (
        "wider establishing composition, environment clearly visible, "
        "stable cinematic framing"
    ),
    "b": (
        "closer cinematic framing, more subject detail, "
        "same scene continuity, same visual world"
    ),
}


class GenerationAttempt(NamedTuple):
    model: str
    seed: int
    timeout: int


class AIImageGenerator:
    """Génère des images via Pollinations avec reprises et modèle de secours."""

    def __init__(self, channel_config: dict | None = None):
        config = channel_config or {}

        # Dimensions vidéo : config de la chaîne, sinon réglages globaux
        self.width = config.get("video_width", DEFAULT_VIDEO_WIDTH)
        self.height = config.get("video_height", DEFAULT_VIDEO_HEIGHT)

        # Style visuel et prompt négatif, propres à la chaîne
        self.base_style = config.get("ai_base_style", DEFAULT_BASE_STYLE)
        self.negative_prompt = config.get(
            "ai_negative_prompt", DEFAULT_NEGATIVE_PROMPT
        )

        # Modèles
        self.primary_model = config.get("ai_primary_model", DEFAULT_PRIMARY_MODEL)
        self.fallback_model = config.get("ai_fallback_model", DEFAULT_FALLBACK_MODEL)

        self.headers = {"User-Agent": f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT})"}
        self.quota_exhausted = False
        # Sans jeton, Pollinations bascule vite en 402 (quota anonyme) : on s'authentifie si possible
        token = os.getenv("POLLINATIONS_TOKEN")
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        else:
            print("ℹ️ POLLINATIONS_TOKEN absent : quota anonyme Pollinations (erreurs 402 probables).")
        print("🤖 Initialisation du générateur d'images IA (Pollinations)")

    # Prompt et URL
    @staticmethod
    def _stable_seed(
        prompt_text: str, visual_identity: str | None = None, variant: str = "base"
    ) -> int:
        """Seed déterministe : un même prompt donne toujours la même image."""
        raw = f"{prompt_text}|{visual_identity or ''}|{variant}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 999999 + 1

    def _build_prompt(
        self,
        prompt_text: str,
        visual_identity: str | None = None,
        variant: str | None = None,
    ) -> str:
        parts = [prompt_text.strip().rstrip(",."), self.base_style]

        if visual_identity:
            parts.append(f"visual continuity: {visual_identity.strip().rstrip(',.')}")

        variant_hint = VARIANT_HINTS.get(variant)
        if variant_hint:
            parts.append(variant_hint)

        parts.append(f"avoid: {self.negative_prompt}")
        return ", ".join(parts)

    def _build_url(self, enhanced_prompt: str, seed: int, model: str) -> str:
        encoded_prompt = urllib.parse.quote(enhanced_prompt, safe="")
        return (
            f"{POLLINATIONS_PROMPT_URL}{encoded_prompt}"
            f"?width={self.width}&height={self.height}"
            f"&seed={seed}"
            f"&model={model}"
            f"&nologo=true&enhance=true"
        )

    # Fichiers et réponses
    @staticmethod
    def _file_is_valid(output_path: str, min_bytes: int = MIN_IMAGE_BYTES) -> bool:
        return os.path.exists(output_path) and os.path.getsize(output_path) >= min_bytes

    @staticmethod
    def _is_valid_image(response: requests.Response, content_type: str) -> bool:
        return (
            response.status_code == 200
            and content_type.startswith("image/")
            and len(response.content) > MIN_IMAGE_BYTES
        )

    @staticmethod
    def _save_image(content: bytes, output_path: str) -> None:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as file:
            file.write(content)

    # Génération
    def _try_pollinations(
        self,
        prompt_text: str,
        output_path: str,
        visual_identity: str | None = None,
        seed: int | None = None,
        variant: str | None = None,
        model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> bool:
        enhanced_prompt = self._build_prompt(
            prompt_text, visual_identity=visual_identity, variant=variant
        )
        if seed is None:
            seed = self._stable_seed(
                prompt_text, visual_identity=visual_identity, variant=variant or "base"
            )

        model = model or self.primary_model
        api_url = self._build_url(enhanced_prompt, seed, model)

        try:
            response = requests.get(api_url, timeout=timeout, headers=self.headers)
            content_type = response.headers.get("Content-Type", "")

            if self._is_valid_image(response, content_type):
                self._save_image(response.content, output_path)
                return True

            if response.status_code == 429:
                print("    ⚠️ Limite de requêtes atteinte sur Pollinations.")
            else:
                print(
                    f"    ❌ Erreur Pollinations ({model}) : "
                    f"{response.status_code}, type={content_type} {response.text[:150] if 'json' in content_type else ''}"
                )
                if response.status_code == 402:
                    self.quota_exhausted = True  # inutile de retenter ce run
            return False

        except requests.RequestException as error:
            print(f"    ❌ Erreur réseau Pollinations ({model}) : {error}")
            return False

    def _build_attempts(self, base_seed: int, retries: int) -> list[GenerationAttempt]:
        """Modèle principal, puis secours, puis principal avec une autre seed."""
        attempts = [
            GenerationAttempt(self.primary_model, base_seed, DEFAULT_TIMEOUT),
            GenerationAttempt(self.fallback_model, base_seed, DEFAULT_TIMEOUT),
            GenerationAttempt(self.primary_model, base_seed + 1, LONG_TIMEOUT),
        ]
        return attempts[: retries + 1]

    def generate_image(
        self,
        prompt_text: str,
        output_path: str,
        visual_identity: str | None = None,
        retries: int = 2,
        seed: int | None = None,
        variant: str | None = None,
    ) -> bool:
        if self.quota_exhausted:
            print("    ⏭️ Quota Pollinations épuisé (402) : génération IA ignorée pour ce run.")
            return False
        print(f"🎨 Génération d'une image IA pour : '{prompt_text}'")

        if self._file_is_valid(output_path):
            print(f"    ♻️ Image déjà présente : {output_path}")
            return True

        base_seed = seed or self._stable_seed(
            prompt_text, visual_identity=visual_identity, variant=variant or "base"
        )
        attempts = self._build_attempts(base_seed, retries)

        for index, attempt in enumerate(attempts):
            if index > 0:
                backoff = 2 * index
                print(
                    f"    🔄 Tentative {index + 1}/{len(attempts)} "
                    f"(modèle={attempt.model}, pause {backoff}s)..."
                )
                time.sleep(backoff)

            success = self._try_pollinations(
                prompt_text=prompt_text,
                output_path=output_path,
                visual_identity=visual_identity,
                seed=attempt.seed,
                variant=variant,
                model=attempt.model,
                timeout=attempt.timeout,
            )

            if success and self._file_is_valid(output_path):
                print(
                    f"    ✅ Image sauvegardée (Pollinations/{attempt.model}, "
                    f"seed={attempt.seed}) : {output_path}"
                )
                return True
            if self.quota_exhausted:
                break

        print(f"    ❌ Échec définitif pour la génération de l'image : {output_path}")
        return False
