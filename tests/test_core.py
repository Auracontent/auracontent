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


# ---------- Limites de débit ----------
class _FakeError(Exception):
    def __init__(self, msg, body=None):
        super().__init__(msg)
        self.body = body


def test_retry_after_groq_message():
    from auracontent.core.brain.llm_client import _retry_after

    msg = "Error code: 429 - Rate limit reached on tokens per minute (TPM): Limit 8000, Used 6844, Requested 2100. Please try again in 7.35s."
    assert _retry_after(_FakeError(msg), msg) == pytest.approx(7.35)


def test_retry_after_gemini_body():
    from auracontent.core.brain.llm_client import _is_daily_quota, _retry_after

    body = [{"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}]}}]
    e = _FakeError("Error code: 429", body)
    assert _retry_after(e, str(e)) == 23
    assert not _is_daily_quota(e, str(e))


def test_gemini_daily_quota_detected():
    from auracontent.core.brain.llm_client import _is_daily_quota

    body = [{"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}]
    e = _FakeError("Error code: 429", body)
    assert _is_daily_quota(e, str(e))


def test_groq_tpm_message_with_used_field():
    from auracontent.core.brain.llm_client import _RATE_LIMIT_NUMS_RE

    m = _RATE_LIMIT_NUMS_RE.search("Limit 8000, Used 4521, Requested 9100")
    assert (m.group(1), m.group(2)) == ("8000", "9100")


def test_duplicate_check_skips_llm_when_no_overlap():
    from auracontent.core.brain.base_brain import BaseBrain

    class NoCallLLM:
        def call_json_with_retry(self, *a, **k):
            raise AssertionError("le LLM ne doit pas être appelé")

    brain = BaseBrain.__new__(BaseBrain)
    brain.llm = NoCallLLM()
    history = ["Le trésor perdu de Rennes-le-Château", "La cloche fantôme de Bretagne"]
    assert brain.is_duplicate_topic_llm("Un médecin empoisonneur à Besançon", history) == (False, None)


def test_llm_registry_skips_providers_without_key(monkeypatch):
    from auracontent.core.brain import llm_client

    for spec in llm_client.PROVIDER_SPECS.values():
        for var in spec["key_env"]:
            monkeypatch.delenv(var, raising=False)
    for var in ("LLM_PROVIDERS",):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")  # sans CLOUDFLARE_ACCOUNT_ID -> ignoré
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    client = llm_client.LLMClient.create_default()
    assert {p["name"] for p in client.providers} == {"Mistral"}


# ---------- Narration Gemini en une seule requête ----------
AUDIO_CFG = {
    "engines": ["gemini", "edge"],
    "gemini": {"narrator": {"voice": "Charon", "style": "calm"}, "witness": {"voice": "Orus", "style": "tense"}},
    "edge": {"narrator": {"voice": "fr-FR-HenriNeural"}, "witness": {"voice": "fr-FR-HenriNeural"}},
}


def test_split_points_snap_to_paragraph_pauses():
    from auracontent.services.audios.audio import AudioEngine

    # 3 paragraphes (poids 1, 2, 1) sur 20 s ; pauses longues à 5.0 et 15.0, pause courte parasite à 9.0
    silences = [(4.5, 5.5), (8.9, 9.1), (14.6, 15.4)]
    assert AudioEngine.split_points(20.0, [1, 2, 1], silences) == [5.0, 15.0]


def test_split_points_gives_up_without_pauses():
    from auracontent.services.audios.audio import AudioEngine

    assert AudioEngine.split_points(20.0, [1, 1, 1], [(1.0, 1.4)]) is None


def test_batch_prompt_uses_two_voices_only_when_needed(monkeypatch, tmp_path):
    from auracontent.services.audios.audio import AudioEngine

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    engine = AudioEngine(AUDIO_CFG, output_dir=str(tmp_path))
    solo = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]
    _, speech = engine._batch_prompt(solo, ["a", "b"])
    assert speech["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Charon"

    duo = [{"id": 1, "text": "a"}, {"id": 2, "text": "b", "voice_type": "witness"}]
    prompt, speech = engine._batch_prompt(duo, ["a", "b"])
    voices = {c["speaker"]: c["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
              for c in speech["multiSpeakerVoiceConfig"]["speakerVoiceConfigs"]}
    assert voices == {"Narrateur": "Charon", "Temoin": "Orus"}
    assert "Temoin: b" in prompt


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_single_request_narration_is_split_per_scene(monkeypatch, tmp_path):
    import asyncio

    import ffmpeg

    from auracontent.services.audios.audio import AudioEngine, audio_duration

    # Fausse narration : 3 s de « voix », pause 1 s, 5 s (avec une micro-pause), pause 1 s, 3 s
    fake = tmp_path / "fake.wav"
    tone = "sine=frequency=300:sample_rate=24000:duration={d}"
    gap = "anullsrc=r=24000:cl=mono:d={d}"
    parts = [tone.format(d=3), gap.format(d=1), tone.format(d=2.4), gap.format(d=0.2), tone.format(d=2.4),
             gap.format(d=1), tone.format(d=3)]
    streams = [ffmpeg.input(p, f="lavfi") for p in parts]
    ffmpeg.concat(*streams, v=0, a=1).output(str(fake), ac=1, ar=24000, sample_fmt="s16").run(quiet=True)

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    engine = AudioEngine(AUDIO_CFG, output_dir=str(tmp_path / "out"), min_scene_duration=1.0)
    calls = []
    monkeypatch.setattr(engine, "_gemini_request", lambda prompt, speech, path: (calls.append(1), shutil.copy(fake, path)))

    scenes = [{"id": 1, "text": "x" * 30}, {"id": 2, "text": "x" * 50}, {"id": 3, "text": "x" * 30}]
    asyncio.run(engine.process_script(scenes))

    assert len(calls) == 1  # UNE seule requête TTS pour toute la vidéo
    durations = [audio_duration(s["audio_path"]) for s in scenes]
    assert durations[0] == pytest.approx(3.5, abs=0.3)
    assert durations[1] == pytest.approx(6.0, abs=0.4)
    assert durations[2] == pytest.approx(3.5, abs=0.3)
    assert {s["tts_engine"] for s in scenes} == {"gemini"}


def test_batch_failure_falls_back_to_per_scene(monkeypatch, tmp_path):
    import asyncio
    import wave

    from auracontent.services.audios.audio import AudioEngine

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    engine = AudioEngine(AUDIO_CFG, output_dir=str(tmp_path), min_scene_duration=1.0)

    def boom(scenes):
        raise RuntimeError("découpage aux silences impossible")

    def fake_scene(text, role, path, scene=None):
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000); wf.writeframes(b"\0\0" * 24000)

    monkeypatch.setattr(engine, "_gemini_batch", boom)
    monkeypatch.setattr(engine, "_gemini", fake_scene)
    scenes = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]
    asyncio.run(engine.process_script(scenes))
    assert all(s["tts_engine"] == "gemini" and s["audio_path"].endswith(".wav") for s in scenes)


# ---------- Direction artistique ----------
def test_srt_never_straddles_two_clauses(tmp_path):
    path = generate_grouped_srt("Ils restent divisés, et le trésor a disparu en 1875.", 5, str(tmp_path / "a.srt"),
                                uppercase=True, highlight_color="#FFD400")
    captions = [b.splitlines()[2] for b in open(path, encoding="utf-8").read().strip().split("\n\n")]
    assert captions[0] == "ILS RESTENT DIVISÉS"                      # coupe à la virgule, virgule masquée
    assert not any(c.endswith((" ET", " LE", " EN")) for c in captions)  # pas de mot-outil en fin de légende
    assert any('<font color="#FFD400">1875</font>' in c for c in captions)


def test_headline_splits_statement_and_punchline():
    from auracontent.services.video.composer import Composer

    composer = Composer({"headline_persistent": True}, channel_name="mystery")
    lines, accent = composer._headline_lines("Mont-Saint-Michel | 70 ans de prison")
    assert lines == ["MONT-SAINT-MICHEL", "70 ANS DE PRISON"] and accent == 1
    assert composer._headline_lines("") == ([], 0)


# ---------- Carte animée (lot 1) ----------
MAP_PLACES = [("Reims", 49.2583, 4.0317, "Grand Est", True),
              ("Ajaccio", 41.9192, 8.7386, "Corse", True),            # au fond du golfe : région la plus proche
              ("Saint-Denis", -20.8789, 55.4481, "Réunion", False)]


def test_wikipedia_page_keeps_primary_coordinates(monkeypatch):
    from auracontent.services.scraping import wikipedia

    page = {"title": "Trésor de Gourdon", "fullurl": "https://fr.wikipedia.org/wiki/T", "extract": "x" * 2000,
            "coordinates": [{"lat": 10.0, "lon": 20.0, "globe": "moon"}, {"lat": 46.64, "lon": 4.45, "globe": "earth"}]}
    monkeypatch.setattr(wikipedia, "_get", lambda params, retries=2: {"query": {"pages": [page]}})
    assert wikipedia._fetch_page("Trésor de Gourdon")["coordinates"] == {"lat": 46.64, "lon": 4.45}

    page.pop("coordinates")
    assert wikipedia._fetch_page("Trésor de Gourdon")["coordinates"] is None


@pytest.mark.parametrize("name, lat, lon, region, metro", MAP_PLACES)
def test_map_finds_region_and_framing(name, lat, lon, region, metro):
    from auracontent.services.visuals.map_scene import find_region, is_metropolitan

    assert find_region(lat, lon)["properties"]["name"] == region
    assert is_metropolitan(lat, lon) is metro


@pytest.mark.parametrize("name, lat, lon, region, metro", MAP_PLACES)
def test_map_point_lands_on_place(name, lat, lon, region, metro):
    """À la fin du zoom, le lieu est sous le point, dans la zone sûre (x < 930, 200 < y < 1440)."""
    from auracontent.services.visuals.map_scene import ACCENT, MapRenderer

    renderer = MapRenderer(lat, lon, name)
    x, y = renderer.to_screen(renderer.end, lon, lat)
    assert (round(x), round(y)) == renderer.ANCHOR
    assert x < 930 and 200 < y < 1440
    img = renderer.render_frame(5.9, 6.0)
    assert img.size == (1080, 1920)
    r, g, b = img.getpixel((round(x), round(y)))
    assert abs(r - ACCENT[0]) < 20 and abs(g - ACCENT[1]) < 20 and b < 60      # point jaune
    lx0, ly0, lx1, ly1 = renderer._label_box(renderer.label_below)
    assert lx1 <= 930 and ly0 > 610 and ly1 < 1200                            # entre bandeau et sous-titres


def test_map_target_disabled_by_default():
    from auracontent.services.visuals.map_scene import map_settings, pick_map_target

    script = {"pick": {"lat": 49.25, "lon": 4.03}}
    scenes = [{"id": 1, "location_name": "Reims"}, {"id": 2}]
    assert map_settings({})["enabled"] is False                  # finance, kids : pas de section map_scene
    assert pick_map_target(script, scenes, map_settings({})) is None


def test_map_target_prefers_wikipedia_then_geocodes():
    from auracontent.services.visuals.map_scene import map_settings, pick_map_target

    cfg = map_settings({"map_scene": {"enabled": True}})
    scenes = [{"id": 1, "location_name": "Cathédrale de Reims", "location_country": "France"},
              {"id": 2, "location_name": "Reims"}, {"id": 3, "role": "cta", "reuse_previous_asset": True}]
    calls = []

    def geocoder(query):
        calls.append(query)
        return 49.25, 4.03

    target = pick_map_target({"pick": {"lat": 48.85, "lon": 2.35}}, scenes, cfg, geocoder=geocoder)
    assert (target.index, target.lat, target.source, target.label) == (1, 48.85, "wikipedia", "Reims")
    assert calls == []                                              # coordonnées Wikipédia : pas de réseau

    target = pick_map_target({"pick": {}}, scenes, cfg, geocoder=geocoder)
    assert (target.lat, target.source) == (49.25, "nominatim")
    assert calls == ["Cathédrale de Reims, France"]                 # lieu de la scène 1

    assert pick_map_target({"pick": {}}, scenes, cfg, geocoder=lambda q: None) is None
    cta = map_settings({"map_scene": {"enabled": True, "scene_index": 2}})
    assert pick_map_target({"pick": {"lat": 48.85, "lon": 2.35}}, scenes, cta) is None   # jamais sur la scène CTA


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_map_clip_has_exact_duration_and_format(tmp_path):
    import ffmpeg

    from auracontent.services.visuals.map_scene import MapTarget, frame_count, render_map_scene

    out = tmp_path / "map.mp4"
    assert render_map_scene(MapTarget(1, 49.2583, 4.0317, "Reims", "test"), 0.5, str(out), fps=30)
    probe = ffmpeg.probe(str(out), count_frames=None)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1080, 1920, "30/1")
    assert int(video["nb_read_frames"]) == frame_count(0.5, 30) == 15
    assert not any(s["codec_type"] == "audio" for s in probe["streams"])


def test_map_render_failure_keeps_usual_visual(monkeypatch, tmp_path):
    """Carte impossible -> la scène reçoit son visuel habituel ; carte réussie -> le .mp4 de la carte."""
    from auracontent.core import pipeline as pl
    from auracontent.services.visuals.map_scene import MapTarget

    class FakeChannel:
        name = "mystery"

        def section(self, key):
            return {"visuals": {"map_scene": {"enabled": True}}}.get(key, {})

    vp = pl.VideoPipeline.__new__(pl.VideoPipeline)
    vp.channel, vp.name, vp.work_dir = FakeChannel(), "mystery", tmp_path
    fetched = []
    vp._fetch_scene_asset = lambda scene, counted=False: fetched.append(scene["id"]) or "usual.jpg"
    scenes = [{"id": 1, "duration": 3.0}, {"id": 2, "duration": 4.0}]
    target = MapTarget(1, 49.25, 4.03, "Reims", "wikipedia")

    monkeypatch.setattr(pl, "render_map_scene", lambda *a, **k: False)
    assets = ["a.jpg", None]
    vp._render_map(target, scenes, assets)
    assert assets == ["a.jpg", "usual.jpg"] and fetched == [2] and "map" not in scenes[1]

    durations = []
    monkeypatch.setattr(pl, "render_map_scene", lambda t, d, out, **k: durations.append(d) or True)
    assets = ["a.jpg", None]
    vp._render_map(target, scenes, assets)
    assert assets[1].endswith("scene_map_2.mp4") and durations == [4.0]   # durée réelle de la voix
    assert scenes[1]["map"]["source"] == "wikipedia"

    # la scène CTA qui suit reprend le visuel de la scène 2 (la carte), pas l'emplacement vide
    scenes.append({"id": 3, "duration": 2.0, "role": "cta", "reuse_previous_asset": True})
    assets = ["a.jpg", None, None]
    vp._render_map(target, scenes, assets)
    assert assets[2] == assets[1] and assets[1].endswith("scene_map_2.mp4")


def test_fetch_assets_leaves_map_scene_for_later(monkeypatch, tmp_path):
    from auracontent.core import pipeline as pl

    class FakeManager:
        def __init__(self, cfg):
            pass

    class FakeChannel:
        name = "mystery"

        def section(self, key):
            return {}

    monkeypatch.setattr(pl, "AssetManager", FakeManager)
    vp = pl.VideoPipeline.__new__(pl.VideoPipeline)
    vp.channel, vp.name, vp.work_dir = FakeChannel(), "mystery", tmp_path
    vp._fetch_scene_asset = lambda scene, counted=False: f"scene{scene['id']}.jpg"
    scenes = [{"id": 1}, {"id": 2, "location_name": "Reims"}, {"id": 3}]
    assert vp._fetch_assets(scenes, skip={1}) == ["scene1.jpg", None, "scene3.jpg"]
    assert vp._query_counts == {"reims": 1}          # le repli éventuel tient compte de ce lieu


def test_geocode_is_cached_and_never_repeated(monkeypatch, tmp_path):
    """Politique Nominatim : résultats en cache, la même requête n'est jamais renvoyée (même un échec)."""
    from auracontent.services.visuals import map_scene

    monkeypatch.setattr(map_scene, "GEOCODE_CACHE", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(map_scene, "NOMINATIM_MIN_INTERVAL", 0)
    calls = []

    class Resp:
        def __init__(self, hits):
            self.hits = hits

        def raise_for_status(self):
            pass

        def json(self):
            return self.hits

    def fake_get(url, params, headers, timeout):
        calls.append((params["q"], headers["User-Agent"]))
        return Resp([{"lat": "49.2536", "lon": "4.0339"}] if "Reims" in params["q"] else [])

    monkeypatch.setattr(map_scene.requests, "get", fake_get)
    assert map_scene.geocode_nominatim("Cathédrale de Reims", user_agent="test/1.0") == (49.2536, 4.0339)
    assert map_scene.geocode_nominatim("  cathédrale de  REIMS ", user_agent="test/1.0") == (49.2536, 4.0339)
    assert map_scene.geocode_nominatim("Lieu introuvable", user_agent="test/1.0") is None
    assert map_scene.geocode_nominatim("Lieu introuvable", user_agent="test/1.0") is None
    assert [q for q, _ in calls] == ["Cathédrale de Reims", "Lieu introuvable"]
    assert all(agent == "test/1.0" for _, agent in calls)


def test_map_credit_mentions_openstreetmap_only_when_geocoded():
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.video.composer import Composer

    composer = Composer(load_channel_config("mystery")["video_composer"], channel_name="mystery")
    assert composer._resolve_source_credit("temp/mystery/assets/scene_map_2.mp4") == "Carte : Natural Earth"
    assert "OpenStreetMap" in composer._resolve_source_credit("temp/mystery/assets/scene_map_osm_2.mp4")


# ---------- Nouveau nom « C’est arrivé ici » (lot 10) ----------
def test_caption_drops_old_name_and_adds_brand_hashtag():
    from auracontent.services.publishing.caption import apply_hashtag_rules

    banned = ["#minutemystere"]
    caption = "🧠 Un trésor perdu !\nVous le saviez ? #histoire #MinuteMystère #france"
    assert apply_hashtag_rules(caption, "#cestarriveici", banned) == (
        "🧠 Un trésor perdu !\nVous le saviez ? #histoire #france #cestarriveici")
    assert apply_hashtag_rules("Légende #CestArriveIci", "#cestarriveici", banned) == "Légende #CestArriveIci"
    assert apply_hashtag_rules("Légende #MinuteMystère", None, ()) == "Légende #MinuteMystère"   # autres chaînes


def test_caption_fallback_follows_brand_rules():
    from auracontent.services.publishing.caption import generate_caption

    class BrokenLLM:
        def call_with_fallback(self, *a, **k):
            raise RuntimeError("quota")

    caption = generate_caption(BrokenLLM(), "Le trésor de Gourdon", [], "#histoire #MinuteMystère",
                               brand_hashtag="#cestarriveici", banned_hashtags=["#minutemystere"])
    assert caption == "Le trésor de Gourdon #histoire #cestarriveici"


def test_mystery_branding_uses_new_name():
    from PIL import Image

    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.video.composer import Composer

    cfg = load_channel_config("mystery")
    composer = Composer(cfg["video_composer"], channel_name="mystery")
    assert composer.watermark_path.endswith("cest_arrive_ici_watermark.png")
    with Image.open(composer.watermark_path) as logo:
        assert logo.size == (541, 160) and logo.mode == "RGBA"
        bottom = composer.watermark_y + composer.watermark_width * logo.height / logo.width
    assert (composer.watermark_width, composer.watermark_opacity) == (190, 0.85)
    assert bottom < composer.headline_y                      # le filigrane ne touche pas le bandeau-titre
    publish = cfg["publish"]
    assert publish["fallback_hashtags"] == "#histoire #patrimoine #france #cestarriveici"
    assert publish["hf_folder"] == "videos" and publish["zernio_key_env"] == "ZERNIO_API_KEY_MYSTERY"


def test_no_old_channel_name_left():
    """Critère du lot 10 : l'ancien nom de la chaîne n'apparaît plus (hors historique git et CHANGELOG)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    old_name = "minute" + r"[\s_]" + "myst"           # écrit en morceaux : ce test ne doit pas se trouver lui-même
    pattern = re.compile(old_name + "|" + "mist" + "[eè]re", re.IGNORECASE)
    suffixes = {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".json", ".sh"}
    hits = []
    for folder in ("auracontent", "config", "scripts", "tests", ".github", "assets"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and (path.suffix in suffixes or path.suffix == ".png") and path != Path(__file__):
                if pattern.search(path.name) or (path.suffix in suffixes and path.stat().st_size < 3_000_000
                                                 and pattern.search(path.read_text(encoding="utf-8", errors="ignore"))):
                    hits.append(str(path.relative_to(root)))
    for name in ("README.md", "CONTRIBUTING.md", ".env.example", "pyproject.toml", "constants.py"):
        path = root / name
        if path.exists() and pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(name)
    assert hits == []


def test_map_tagline_is_optional_and_stays_in_safe_zone():
    from auracontent.services.visuals.map_scene import MapRenderer

    plain = MapRenderer(49.2583, 4.0317, "Reims")
    assert plain.tagline == "" and all(not accent for _, _, accent in plain._label_lines())
    for lat, lon, name in ((49.2583, 4.0317, "Reims"), (-20.8789, 55.4481, "Saint-Denis")):
        tagged = MapRenderer(lat, lon, name, {"tagline": "C’est arrivé ici"})
        assert tagged._label_lines()[-1][0] == "C’EST ARRIVÉ ICI" and tagged._label_lines()[-1][2]
        x0, y0, x1, y1 = tagged._label_box(tagged.label_below)
        assert x0 >= 40 and x1 <= 930 and y0 > 610 and y1 < 1200   # entre bandeau et sous-titres
