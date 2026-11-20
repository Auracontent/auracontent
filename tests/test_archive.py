"""Shorts d'archives : références de temps, sous-titres, voix recomposée, validation du plan, rendu d'une image."""
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from auracontent.archive import timeline, voice

EXAMPLE = Path(__file__).resolve().parents[1] / "episodes" / "archive" / "_exemple" / "plan.json"


def _tl(plan=None, lines=((0.0, 2.0, "Paris. Le dix mai."), (2.5, 6.0, "Sauf que rien de tout cela n'est arrivé."))):
    tl = timeline.Timeline(plan=plan or {}, lines=[(a + timeline.LEAD_IN, b + timeline.LEAD_IN, t) for a, b, t in lines],
                           vo_end=timeline.LEAD_IN + lines[-1][1])
    tl.words = timeline.split_words(tl.lines)
    tl.chunks = timeline.caption_chunks(tl.words)
    return tl


def test_time_references():
    tl = _tl()
    assert tl.t(3) == 3.0 and tl.t("4.5") == 4.5
    assert tl.t("L1") == pytest.approx(2.75)
    assert tl.t("L1.end") == pytest.approx(6.25)
    assert tl.t("L1@0.5") == pytest.approx(4.5)
    assert tl.t("L1+0.4") == pytest.approx(3.15)
    assert tl.t("end") == pytest.approx(6.25) and tl.t("fin") == pytest.approx(6.25 + timeline.END_CARD)
    assert tl.t("w:rien") >= tl.t("L1") and tl.t("w:rien@L1-0.1") == pytest.approx(tl.t("w:rien") - 0.1)
    with pytest.raises(KeyError):
        tl.t("L9")
    with pytest.raises(KeyError):
        tl.t("w:introuvable")


def test_words_stay_inside_their_line_and_captions_are_short():
    tl = _tl()
    for a, b, w in tl.words:
        line = next(x for x in tl.lines if x[0] - 1e-6 <= a <= x[1] + 1e-6)
        assert b <= line[1] + 1e-6
    for a, b, words in tl.chunks:
        assert 1 <= len(words) <= 2 and a < b
    assert [w[2] for w in tl.chunks[0][2]] == ["Paris."]          # coupe à la ponctuation


def test_new_york_is_one_word():
    words = timeline.split_words([(0, 3, "Ils partent pour New York sans escale.")])
    assert any(w[2] == "New York" for w in words)


def test_trim_removes_silence():
    sr = voice.SR
    x = np.concatenate([np.zeros(sr), 0.3 * np.sin(np.linspace(0, 2000, sr)), np.zeros(sr)]).astype(np.float32)
    y = voice.trim(x)
    assert 0.9 * sr < len(y) < 1.3 * sr


def test_prompt_numbers_lines_and_keeps_directions():
    plan = {"voice": {"name": "Orus", "style": "Calm."},
            "lines": [{"text": "Un."}, {"text": "Deux.", "direction": "Whisper."}]}
    prompt, speech = voice.prompt_for(plan, ["Un.", "Deux."])
    assert "1. Un.\n2. Deux." in prompt and "Line 2: Whisper." in prompt and prompt.startswith("Calm.")
    assert speech["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Orus"


def _write_wav(path: Path, seconds: float, silence: float = 0.3):
    sr = voice.SR
    x = np.concatenate([np.zeros(int(silence * sr)), 0.3 * np.sin(np.linspace(0, 3000 * seconds, int(seconds * sr))),
                        np.zeros(int(silence * sr))])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((x * 32767).astype(np.int16).tobytes())


def test_manual_voice_is_recomposed_with_plan_pauses(tmp_path):
    plan = {"lines": [{"text": "Première phrase.", "pause": 1.0}, {"text": "Seconde."}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "voice" / "lines").mkdir(parents=True)
    _write_wav(tmp_path / "voice" / "lines" / "00.wav", 2.0)
    _write_wav(tmp_path / "voice" / "lines" / "01.wav", 1.0)
    timing = voice.build(tmp_path)
    l0, l1 = timing["lines"]
    assert l0["t1"] - l0["t0"] == pytest.approx(2.12, abs=0.05)      # blancs rognés (+ marge de 60 ms)
    assert l1["t0"] - l0["t1"] == pytest.approx(1.0, abs=0.01)       # pause du plan
    assert (tmp_path / "voice" / "voice.wav").exists()


def test_no_robotic_fallback_without_gemini_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "plan.json").write_text(json.dumps({"lines": [{"text": "Une phrase."}]}))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        voice.build(tmp_path)


def _episode(tmp_path, shots, n_lines=2):
    from PIL import Image
    plan = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    plan["lines"] = plan["lines"][:n_lines]
    plan.update(shots=shots, stamps=[{"text": "FAUX", "at": "L1"}], labels=[], music={},
                images={"a": "File:A.jpg"})
    (tmp_path / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
    (tmp_path / "img").mkdir(exist_ok=True); Image.new("RGB", (1600, 1200), (120, 100, 80)).save(tmp_path / "img" / "a.jpg")
    (tmp_path / "voice").mkdir(exist_ok=True)
    (tmp_path / "voice" / "timing.json").write_text(json.dumps(
        {"duration": 5.0, "lines": [{"t0": 0, "t1": 2, "text": "Paris. Le dix mai."}, {"t0": 2.5, "t1": 5, "text": "Sauf que rien."}]}))
    return tmp_path


def test_plan_must_cover_the_whole_video(tmp_path):
    from auracontent.archive.frames import Renderer
    ep = _episode(tmp_path, [{"from": 0, "to": "L1", "image": "a", "keys": [[0, .5, .5, 1]]}])
    with pytest.raises(ValueError, match="fin"):
        Renderer(ep, timeline.load(ep))
    ep = _episode(tmp_path, [{"from": 0, "to": "L1", "image": "a", "keys": [[0, .5, .5, 1]]},
                             {"from": "L1+0.5", "to": "fin", "type": "fog"}])
    with pytest.raises(ValueError, match="trou"):
        Renderer(ep, timeline.load(ep))
    ep = _episode(tmp_path, [{"from": 0, "to": "fin", "image": "absente", "keys": [[0, .5, .5, 1]]}])
    with pytest.raises(ValueError, match="absente"):
        Renderer(ep, timeline.load(ep))


def test_renders_frames_of_every_kind(tmp_path):
    from auracontent.archive.frames import Renderer
    from auracontent.archive.timeline import FPS, H, W
    ep = _episode(tmp_path, [
        {"from": 0, "to": "L0@0.5", "image": "a", "keys": [[0, .5, .5, 1], [1, .4, .4, .5]], "fx": {"shake": 1}},
        {"from": "L0@0.5", "to": "L1", "type": "split", "top": {"image": "a", "keys": [[0, .5, .5, .6]]},
         "bottom": {"image": "a", "keys": [[0, .5, .5, .6]]}, "labels": ["HAUT", "BAS"]},
        {"from": "L1", "to": "L1@0.5", "type": "sign", "lines": ["RUE", "NUNGESSER-ET-COLI", "« inscription »"], "background": "a"},
        {"from": "L1@0.5", "to": "end", "type": "card", "title": "9 MAI 1927", "sub": "TERRE-NEUVE"},
        {"from": "end", "to": "fin", "type": "fog"}])
    tl = timeline.load(ep); r = Renderer(ep, tl)
    for t in (0.5, 1.8, 3.0, 4.5, tl.dur - 0.5):
        fr = r.frame(int(t * FPS))
        assert fr.shape == (H, W, 3) and fr.dtype == np.uint8 and fr.std() > 3


def test_example_plan_is_complete():
    plan = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for key in ("slug", "title", "caption", "sources", "voice", "lines", "hook", "images", "shots"):
        assert plan.get(key), key
    assert all(v.startswith("File:") for v in plan["images"].values())
    assert len(plan["hook"]) <= 3 and all(len(line) <= 24 for line in plan["hook"])
