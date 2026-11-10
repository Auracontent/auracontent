"""Génération d'images FLUX via Cloudflare Workers AI (allocation gratuite quotidienne, API stable).

Variables : CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN (jeton avec la permission « Workers AI »).
"""
from __future__ import annotations

import base64
import os

import requests

CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
MIN_IMAGE_BYTES = 5000


class CloudflareImageGenerator:
    name = "cloudflare"

    def __init__(self):
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        self.token = os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_R2_TOKEN")
        self.disabled = not (self.account_id and self.token)

    @property
    def url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{CLOUDFLARE_MODEL}"

    def generate_image(self, prompt: str, output_path: str, steps: int = 8) -> bool:
        if self.disabled:
            return False
        print("🎨 Génération Cloudflare FLUX...")
        try:
            r = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"prompt": prompt[:2048], "steps": steps},
                timeout=60,
            )
        except requests.RequestException as e:
            print(f"    ❌ Cloudflare : {e}")
            return False
        if r.status_code != 200:
            print(f"    ❌ Cloudflare HTTP {r.status_code} : {r.text[:150]}")
            if r.status_code in (401, 403, 429):  # jeton invalide ou allocation du jour épuisée
                self.disabled = True
            return False
        image_b64 = (r.json().get("result") or {}).get("image")
        if not image_b64:
            print("    ❌ Cloudflare : réponse sans image")
            return False
        data = base64.b64decode(image_b64)
        if len(data) < MIN_IMAGE_BYTES:
            return False
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)
        print(f"    ✅ Image sauvegardée (Cloudflare FLUX) : {output_path}")
        return True
