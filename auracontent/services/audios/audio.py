import asyncio
import base64
import os
import re
import time
import wave
from pathlib import Path
import requests
from mutagen.mp3 import MP3
from config.settings import GEMINI_CONFIG, GEMINI_TTS_MODELS
from .text_fr import normalize_fr

try:
    import edge_tts
except ImportError:
    edge_tts = None


def audio_duration(path: str) -> float:
    """Durée sans dépendre de soundfile/kokoro."""
    try:
        if path.endswith(".mp3"):
            return MP3(path).info.length
        with wave.open(path, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


class AudioEngine:
    GEMINI_MIN_INTERVAL = 12.0

    def __init__(self, audio_cfg: dict, output_dir="assets/audio_clips", min_scene_duration=3.0):
        self.cfg = audio_cfg
        self.engines = list(audio_cfg.get("engines", ["gemini", "edge"]))
        self.pron = [(re.compile(p, re.I), r) for p, r in audio_cfg.get("pronunciation", {}).items()]
        self.out = Path(output_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.min_dur = min_scene_duration
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        if "gemini" in self.engines and not self.gemini_key:
            self.engines.remove("gemini")
        self._last_gemini_call = 0.0
        self.gemini_models = list(audio_cfg.get("gemini_models") or GEMINI_TTS_MODELS)

    # ---------- texte ----------
    def prepare_text(self, text: str) -> str:
        text = normalize_fr(text)
        for rx, repl in self.pron:
            text = rx.sub(repl, text)
        return text

    # ---------- moteurs ----------
    # Direction de jeu selon le rôle narratif de la scène (s'ajoute au style de la voix)
    ROLE_DIRECTIONS = {
        "hook": "Opening line: grab attention immediately, intimate and gripping, slight urgency.",
        "tension": "Build tension, slightly lower and slower.",
        "escalation": "Rising intensity, tighter rhythm.",
        "reveal": "Slow down, dramatic pause before the key fact, then say it clearly.",
        "cta": "Warm, direct, conversational, like talking to one viewer.",
    }

    def _gemini_style(self, role, scene):
        style = self.cfg["gemini"][role]["style"]
        extras = [self.ROLE_DIRECTIONS.get(scene.get("role", "")), scene.get("voice_direction")]
        return " ".join([style] + [e for e in extras if e])

    @staticmethod
    def _retry_delay(body: str) -> float | None:
        """Délai conseillé par Google sur un 429 par minute ; None si quota journalier (inutile d'attendre)."""
        if "PerDay" in body or "per_day" in body.lower():
            return None
        m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', body)
        return min(float(m.group(1)) + 1, 65) if m else 30.0

    def _gemini(self, text, role, path, scene=None):
        style = self._gemini_style(role, scene or {})
        voice = self.cfg["gemini"][role]["voice"]
        last_error = None
        for model in list(self.gemini_models):
            for _ in range(3):
                wait = self.GEMINI_MIN_INTERVAL - (time.time() - self._last_gemini_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_gemini_call = time.time()
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                payload = {
                    "contents": [{"parts": [{"text": f"{style}\nRead this French text naturally:\n{text}"}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                    },
                }
                r = requests.post(url, json=payload, timeout=90, headers={"x-goog-api-key": self.gemini_key})
                if r.status_code == 200:
                    parts = r.json()["candidates"][0]["content"]["parts"]
                    inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
                    if not inline:
                        raise RuntimeError("Gemini : pas de données audio")
                    with wave.open(str(path), "wb") as wf:
                        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
                        wf.writeframes(base64.b64decode(inline["data"]))
                    return
                last_error = f"Gemini {model} HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code == 429:
                    delay = self._retry_delay(r.text)
                    if delay is None:  # quota journalier de ce modèle : on passe au modèle TTS suivant
                        print(f"      ⛔ Quota journalier atteint sur {model}, modèle TTS suivant.")
                        self.gemini_models.remove(model)
                        break
                    print(f"      ⏳ Limite par minute sur {model}, nouvel essai dans {delay:.0f}s...")
                    time.sleep(delay)
                    continue
                if r.status_code in (500, 503):
                    time.sleep(5)
                    continue
                if r.status_code == 404:
                    self.gemini_models.remove(model)
                break
        raise RuntimeError(last_error or "Gemini TTS indisponible")

    async def _edge(self, text, role, path):
        if edge_tts is None:
            raise RuntimeError("edge_tts non installé")
        p = self.cfg["edge"][role]
        await edge_tts.Communicate(text, voice=p["voice"], rate=p.get("rate", "+0%"),
                                   pitch=p.get("pitch", "+0Hz")).save(str(path))

    # ---------- cascade ----------
    async def generate(self, text, name, role="narrator", scene=None):
        text = self.prepare_text(text)
        last_err = None
        for engine in list(self.engines):
            ext = "mp3" if engine == "edge" else "wav"
            path = self.out / f"{name}.{ext}"
            try:
                if engine == "gemini":
                    await asyncio.to_thread(self._gemini, text, role, path, scene)
                else:
                    await self._edge(text, role, path)
                if audio_duration(str(path)) > 0:
                    return str(path), engine
            except Exception as e:
                last_err = e
                print(f"      ⚠️ {engine} a échoué : {e}")
                if engine == "gemini":
                    self.engines.remove("gemini")
        raise RuntimeError(f"Aucun moteur TTS disponible : {last_err}")

    async def _render(self, scene):
        role = scene.get("voice_type", "narrator")
        role = role if role in ("narrator", "witness") else "narrator"
        path, engine = await self.generate(scene["text"], f"scene_{scene['id']}", role, scene)
        scene.update(audio_path=path, tts_engine=engine, duration=max(audio_duration(path), self.min_dur))
        print(f"     Scène {scene['id']} [{role}] via {engine} ({scene['duration']:.1f}s)")

    async def process_script(self, scenes: list[dict]) -> list[dict]:
        for scene in scenes:
            await self._render(scene)
        # Une seule voix par vidéo : si le moteur a changé en cours de route, on refait tout avec le dernier
        engines = {s["tts_engine"] for s in scenes}
        if len(engines) > 1:
            print(f"     🔁 Voix mélangées ({', '.join(sorted(engines))}) : régénération complète pour une voix unique.")
            for scene in scenes:
                await self._render(scene)
        return scenes
