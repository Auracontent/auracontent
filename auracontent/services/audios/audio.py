import asyncio
import base64
import os
import re
import time
import wave
from pathlib import Path
import requests
from mutagen.mp3 import MP3
from constants import GEMINI_MODEL_VOICE
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

    # ---------- texte ----------
    def prepare_text(self, text: str) -> str:
        text = normalize_fr(text)
        for rx, repl in self.pron:
            text = rx.sub(repl, text)
        return text

    # ---------- moteurs ----------
    def _gemini(self, text, role, path):
        prof = self.cfg["gemini"][role]
        wait = self.GEMINI_MIN_INTERVAL - (time.time() - self._last_gemini_call)
        if wait > 0:
            time.sleep(wait)
        self._last_gemini_call = time.time()

        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL_VOICE}:generateContent")
        payload = {
            "contents": [{"parts": [{"text": f"{prof['style']}\nRead this French text naturally:\n{text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": prof["voice"]}}},
            },
        }
        r = requests.post(url, json=payload, timeout=90,
                          headers={"x-goog-api-key": self.gemini_key})   # clé en header, pas dans l'URL
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        parts = r.json()["candidates"][0]["content"]["parts"]
        inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
        if not inline:
            raise RuntimeError("Gemini: pas de données audio")
        pcm = base64.b64decode(inline["data"])
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
            wf.writeframes(pcm)

    async def _edge(self, text, role, path):
        if edge_tts is None:
            raise RuntimeError("edge_tts non installé")
        p = self.cfg["edge"][role]
        await edge_tts.Communicate(text, voice=p["voice"], rate=p.get("rate", "+0%"),
                                   pitch=p.get("pitch", "+0Hz")).save(str(path))

    # ---------- cascade ----------
    async def generate(self, text, name, role="narrator"):
        text = self.prepare_text(text)
        last_err = None
        for engine in list(self.engines):
            ext = "mp3" if engine == "edge" else "wav"
            path = self.out / f"{name}.{ext}"
            try:
                if engine == "gemini":
                    await asyncio.to_thread(self._gemini, text, role, path)
                else:
                    await self._edge(text, role, path)
                if audio_duration(str(path)) > 0:
                    return str(path), engine
            except Exception as e:
                last_err = e
                print(f"      ⚠️ {engine} a échoué : {e}")
                # Anti-rupture de voix : si Gemini tombe, on bascule TOUTE la fin
                # de la vidéo sur le moteur suivant au lieu d'alterner.
                if engine == "gemini":
                    self.engines.remove("gemini")
        raise RuntimeError(f"Aucun moteur TTS disponible : {last_err}")

    async def process_script(self, scenes: list[dict]) -> list[dict]:
        for scene in scenes:
            role = scene.get("voice_type", "narrator")
            role = role if role in ("narrator", "witness") else "narrator"
            path, engine = await self.generate(scene["text"], f"scene_{scene['id']}", role)
            scene.update(audio_path=path, tts_engine=engine,
                         duration=max(audio_duration(path), self.min_dur))
            print(f"     Scène {scene['id']} [{role}] via {engine} ({scene['duration']:.1f}s)")
        return scenes