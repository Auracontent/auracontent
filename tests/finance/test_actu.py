"""Format « L'éco du jour » (auracontent/actu) : contrôle du plan, voix, planche, synchronisation des courbes."""
from __future__ import annotations

import copy
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from auracontent.actu import cli, plan, voice
from auracontent.actu.frames import Renderer

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "episodes" / "finance" / "_exemple"


def _plan() -> dict:
    return json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))


@pytest.fixture
def episode(tmp_path: Path) -> Path:
    ep = tmp_path / "2026-11-25-dette"
    ep.mkdir()
    shutil.copy(EXAMPLE / "plan.json", ep / "plan.json")
    return ep


def test_exemple_valide():
    assert plan.check(_plan()) == []


def test_chiffre_sans_source_refuse():
    p = _plan()
    p["lines"][1].pop("source")
    assert any("phrase 1 : chiffre sans" in e for e in plan.check(p))


def test_calcul_accepte_comme_source():
    p = _plan()
    assert "calc" in p["lines"][11] and "source" not in p["lines"][11]
    assert not any("phrase 11" in e for e in plan.check(p))


def test_scene_de_donnees_sans_source_refusee():
    p = _plan()
    p["scenes"][1]["source"] = "inconnue"
    assert any("scène 1 (courbe)" in e for e in plan.check(p))


@pytest.mark.parametrize("phrase", ["Investis maintenant tant que les taux baissent.",
                                    "C'est un placement sûr pour toi."])
def test_conseil_et_promesse_refuses(phrase):
    p = _plan()
    p["lines"][5]["text"] = phrase
    assert any("phrase 5" in e for e in plan.check(p))


def test_voix_trop_longue_refusee():
    p = _plan()
    p["lines"] += copy.deepcopy(p["lines"][:6])
    assert any("mots prononcés" in e for e in plan.check(p))


def test_derniere_scene_est_la_carte_de_fin():
    p = _plan()
    p["scenes"] = p["scenes"][:-1]
    assert any("carte de fin" in e for e in plan.check(p))


def test_voix_estimee_planche_et_upload_refuse(episode: Path, monkeypatch):
    timing = voice.build(episode, preview=True)
    assert timing["source"] == "estimée" and len(timing["lines"]) == len(_plan()["lines"])
    assert 40 < timing["duration"] < 75
    sheet = cli.stills(episode)
    assert sheet.exists() and json.loads((episode / "stills_times.json").read_text())
    (episode / "out").mkdir()
    (episode / "out" / "x.mp4").write_bytes(b"0")
    monkeypatch.setattr("auracontent.services.publishing.hf_storage.upload_video", lambda *a, **k: "ne doit pas")
    with pytest.raises(RuntimeError, match="estimée"):
        cli.upload(episode)


def test_scenes_couvrent_toute_la_video(episode: Path):
    voice.build(episode, preview=True)
    tl, r = cli._timeline(episode)
    assert r.scenes[0]["t0"] == 0
    assert all(a["t1"] == b["t0"] for a, b in itertools.pairwise(r.scenes))
    assert r.scenes[-1]["t1"] == pytest.approx(tl.dur)
    assert r.frame(tl.nframes - 1).shape == (1920, 1080, 3)


def test_courbe_synchronisee_sur_la_voix(episode: Path):
    voice.build(episode, preview=True)
    tl, r = cli._timeline(episode)
    s = next(x for x in r.scenes if x["type"] == "courbe")
    xs = [float(p[0]) for p in s["points"]]
    for k in s["sync"]:
        lt = tl.t(k["at"]) - s["t0"]
        end, _ = r.curve_end(s, lt, xs)
        assert end == pytest.approx(float(k["x"]), abs=0.05)


def test_voix_edge_simulee(episode: Path, monkeypatch):
    """Edge TTS remplacé par un son de 1 s : une phrase = un fichier, minutage « edge » avec les pauses du plan."""
    async def fake(text, path, v):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1", str(path)], check=True)

    monkeypatch.setattr(voice, "_edge", fake)
    t = voice.build(episode)
    p = _plan()
    assert t["source"] == "edge" and (episode / "voice" / "voice.wav").exists()
    gap = t["lines"][1]["t0"] - t["lines"][0]["t1"]
    assert gap == pytest.approx(p["lines"][0]["pause"], abs=0.01)


def test_textes_tiennent_dans_leurs_zones(episode: Path):
    """Chaque scène se dessine sans « texte trop long » au début, au milieu et à la fin."""
    voice.build(episode, preview=True)
    _tl, r = cli._timeline(episode)
    for s in r.scenes:
        for t in (s["t0"] + 0.05, (s["t0"] + s["t1"]) / 2, s["t1"] - 0.05):
            r.frame(int(t * 30))


def test_workflow_tache_direct_finance():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "generator_video.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["direct_finance"]
    assert "FINANCE_MODE" in job["if"] and "finance_actu" in job["if"]
    prompt = next(s for s in job["steps"] if s.get("name") == "Claude réalise le short")["with"]["prompt"]
    assert "docs/finance_actu.md" in prompt and "WebSearch" in \
        next(s for s in job["steps"] if s.get("name") == "Claude réalise le short")["with"]["claude_args"]
    assert "finance_actu" in wf["jobs"]["generate"]["if"]


def test_renderer_refuse_une_scene_de_duree_nulle(episode: Path):
    voice.build(episode, preview=True)
    p = _plan()
    p["scenes"][2]["from"] = p["scenes"][1]["from"]
    (episode / "plan.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    from auracontent.archive.timeline import load
    with pytest.raises(ValueError, match="durée nulle"):
        Renderer(episode, load(episode))
