# auracontent/channels/mystery/audio.py
from auracontent.services.audios.audio import AudioEngine

AUDIO_CONFIG = {
    "engines": ["gemini", "edge"],
    "gemini": {
        "narrator": {
            "voice": "Charon",
            "style": "Voix grave, lente et posée, ton de suspense, pauses marquées.",
        },
        "witness": {
            "voice": "Enceladus",
            "style": "Voix hésitante et essoufflée, comme un témoin encore sous le choc.",
        },
    },
    "edge": {
        "narrator": {"voice": "fr-FR-HenriNeural", "rate": "-8%", "pitch": "-4Hz"},
        "witness": {"voice": "fr-FR-RemyMultilingualNeural", "rate": "-3%"},
    },
    "pronunciation": {
        r"\bRoswell\b": "Rosse-ouel",
        r"\bLoch Ness\b": "Lok Nesse",
        r"\bOVNI\b": "ovni",
    },
}

def build_audio_engine() -> AudioEngine:
    return AudioEngine(AUDIO_CONFIG, output_dir="assets/audio_clips/mystery")