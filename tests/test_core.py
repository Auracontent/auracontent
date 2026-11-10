"""Tests rapides (< 30 s), sans clé API : lancés en CI à chaque push."""
import json
import random
import shutil

import pytest

from auracontent.core.brain.llm_client import _classify_error, _repair_json_text
from auracontent.services.audios.text_fr import normalize_fr
from auracontent.utils import hook_tracker
from auracontent.utils.subtitles import generate_grouped_srt


# ---------- Sous-titres ----------
def test_srt_covers_whole_duration(tmp_path):
    path = generate_grouped_srt("un deux trois quatre cinq six sept", 3.5, str(tmp_path / "a.srt"))
    blocks = open(path, encoding="utf-8").read().strip().split("\n\n")
    assert len(blocks) == 3  # groupes de 3 mots
    assert blocks[0].splitlines()[1].startswith("00:00:00,000")
    assert blocks[-1].splitlines()[1].endswith("00:00:03,500")


def test_srt_empty_text_returns_none(tmp_path):
    assert generate_grouped_srt("", 3, str(tmp_path / "a.srt")) is None


# ---------- Texte pour la voix ----------
@pytest.mark.parametrize("raw, expected", [
    ("Au XIVe siècle", "Au quatorzième siècle"),
    ("Louis XIV régna", "Louis quatorze régna"),
    ("Napoléon Ier", "Napoléon premier"),
    ("300 av. J.-C.", "300 avant Jésus-Christ"),
    ("à 12 km", "à 12 kilomètres"),
    ("« Le vol »", '"Le vol"'),
])
def test_normalize_fr(raw, expected):
    assert normalize_fr(raw) == expected


# ---------- LLM ----------
@pytest.mark.parametrize("message, kind", [
    ("Error code: 400 - Failed to validate JSON. See 'failed_generation'", "json_failed"),
    ("Error code: 400 - The model `x` has been decommissioned", "not_found"),
    ("Error code: 404 - This model is unavailable for free", "not_found"),
    ("Error code: 402 - This request requires more credits", "no_credit"),
    ("Error code: 429 - Rate limit reached", "rate_limit"),
])
def test_classify_llm_errors(message, kind):
    assert _classify_error(Exception(message), message) == kind


def test_repair_truncated_json():
    broken = '{"title":"x","scenes":[{"id":1,"text":"a"},"id":2,"text":"b'
    data = json.loads(_repair_json_text(broken))
    assert [s["id"] for s in data["scenes"]] == [1, 2]


def test_repair_strips_reasoning():
    assert json.loads(_repair_json_text('<think>hmm</think>{"ok": true}')) == {"ok": True}


# ---------- Bandit des hooks ----------
def test_bandit_exploits_best_pattern(tmp_path, monkeypatch):
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hooks.json")
    hook_tracker.record_hook_usage("Trésor perdu", "question", "mystery", "🔍 Trésor perdu... Qui l'a caché ?")
    hook_tracker.record_hook_usage("Cloche", "chiffre", "mystery", "🔔 En 1792, une cloche sonna seule")
    stats = [{"title": "🔍 Trésor perdu... Qui l'a caché ? #mystère", "views": 9000, "likes": 700},
             {"title": "🔔 En 1792, une cloche sonna seule", "views": 100, "likes": 2}]
    scores = hook_tracker.compute_pattern_scores(stats, hook_tracker.load_hook_history("mystery"))
    assert scores["question"] > scores["chiffre"]
    hooks = [{"text": "a", "pattern": "chiffre"}, {"text": "b", "pattern": "question"}]
    assert hook_tracker.select_hook(hooks, scores, epsilon=0.0)["pattern"] == "question"


def test_bandit_without_scores_still_picks():
    random.seed(0)
    assert hook_tracker.select_hook([{"text": "a", "pattern": "x"}], {}, epsilon=0.0)["text"] == "a"


# ---------- Montage (ffmpeg) ----------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_ken_burns_scene_has_expected_duration(tmp_path):
    """Régression : une scène image de 5 s sortait en 417 s (zoompan sur une image répétée à 25 fps)."""
    import ffmpeg
    from PIL import Image

    from auracontent.services.video.composer import Composer

    image = tmp_path / "img.jpg"
    Image.new("RGB", (1200, 800), (90, 60, 30)).save(image)
    voice = tmp_path / "voice.wav"
    ffmpeg.input("sine=frequency=440:duration=2", f="lavfi").output(str(voice), ac=2, ar=48000).run(quiet=True)

    composer = Composer({"video_width": 360, "video_height": 640, "fps": 15}, channel_name="mystery")
    composer.temp_dir = str(tmp_path)
    out = composer.process_scene({"id": "t", "audio_path": str(voice), "duration": 2.0}, str(image))

    assert out is not None
    duration = float(ffmpeg.probe(out)["format"]["duration"])
    assert 1.9 <= duration <= 2.6  # 2 s + SECOND_IMAGE_EXTRA_DURATION (0.35 s)


# ---------- Qualité / audience ----------
@pytest.mark.parametrize("duration, expected", [("45", 6), ("30", 5), ("90", 11), ("200", 11), ("abc", 6)])
def test_scene_count_follows_target_duration(monkeypatch, duration, expected):
    from auracontent.core.brain.base_brain import BaseBrain

    brain = BaseBrain.__new__(BaseBrain)
    brain.config = {"brain": {"scene_count": 11, "seconds_per_scene": 8}}
    monkeypatch.setenv("VIDEO_DURATION", duration)
    assert brain.target_scene_count() == expected


def test_best_scored_hook_wins_without_stats():
    hooks = [{"text": "a", "pattern": "x", "score": 6}, {"text": "b", "pattern": "y", "score": 9}]
    assert hook_tracker.select_hook(hooks, {}, epsilon=0.0)["text"] == "b"


@pytest.mark.parametrize("body, expected", [
    ('{"error": {"details": [{"retryDelay": "37s"}]}}', 38.0),
    ('{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}', None),
    ('{"error": "quota"}', 30.0),
])
def test_gemini_tts_retry_delay(body, expected):
    from auracontent.services.audios.audio import AudioEngine

    assert AudioEngine._retry_delay(body) == expected


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_landscape_image_is_not_distorted(tmp_path):
    """Régression : zoompan étirait les photos horizontales au format 9:16 (un cercle devenait une ellipse)."""
    import ffmpeg
    from PIL import Image, ImageDraw

    from auracontent.services.video.composer import Composer

    image = tmp_path / "circle.jpg"
    img = Image.new("RGB", (1600, 1000), (0, 0, 0))
    ImageDraw.Draw(img).ellipse((500, 200, 1100, 800), fill="white")
    img.save(image)
    voice = tmp_path / "voice.wav"
    ffmpeg.input("sine=duration=1", f="lavfi").output(str(voice), ac=2, ar=48000).run(quiet=True)

    composer = Composer({"video_width": 360, "video_height": 640, "fps": 10}, channel_name="mystery")
    composer.temp_dir = str(tmp_path)
    out = composer.process_scene({"id": "c", "audio_path": str(voice), "duration": 1.0}, str(image))
    frame = tmp_path / "frame.png"
    ffmpeg.input(out, ss=0.05).output(str(frame), vframes=1).run(quiet=True)

    px = Image.open(frame).convert("L")
    w, h = px.size
    bright = [(x, y) for x in range(w) for y in range(int(h * 0.3), int(h * 0.7)) if px.getpixel((x, y)) > 200]
    xs, ys = [p[0] for p in bright], [p[1] for p in bright]
    ratio = (max(xs) - min(xs)) / (max(ys) - min(ys))
    assert 0.85 <= ratio <= 1.15  # toujours un cercle
