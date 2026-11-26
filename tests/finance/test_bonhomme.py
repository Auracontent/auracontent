"""Format « expliqué par un bonhomme » (auracontent/bonhomme) : contrôle du plan, repères, images, bruitages."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from auracontent.actu import voice
from auracontent.archive.timeline import load
from auracontent.bonhomme import cli, plan
from auracontent.bonhomme.frames import Renderer, stills_times

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "episodes" / "bonhomme" / "_exemple"


def _plan() -> dict:
    return json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))


@pytest.fixture
def episode(tmp_path: Path) -> Path:
    ep = tmp_path / "2026-11-26-decouvert"
    ep.mkdir()
    shutil.copy(EXAMPLE / "plan.json", ep / "plan.json")
    voice.build(ep, preview=True)
    return ep


def _renderer(ep: Path, fmt: str | None = None) -> Renderer:
    tl = load(ep)
    if fmt:
        tl.plan["format"] = fmt
    tl.plan.setdefault("end_card_seconds", cli.END_CARD)
    return Renderer(ep, tl)


def test_exemple_valide():
    assert plan.check(_plan()) == []


def test_chiffre_sans_source_ni_exemple_refuse():
    p = _plan()
    p["lines"][1].pop("exemple")
    assert any("phrase 1 : chiffre sans" in e for e in plan.check(p))


def test_chiffre_sans_say_refuse():
    p = _plan()
    p["lines"][6].pop("say")
    assert any("phrase 6 : chiffre sans « say »" in e for e in plan.check(p))


def test_ordre_d_investir_refuse():
    p = _plan()
    p["lines"][15]["text"] = "Investis tout en bourse."
    assert any("ordre d'investir" in e for e in plan.check(p))


def test_abonne_toi_refuse():
    p = _plan()
    p["scenes"][-1]["next"] = "Abonne-toi, une vidéo par jour"
    assert any("abonne" in e for e in plan.check(p))


def test_premiere_et_derniere_scene():
    p = _plan()
    p["scenes"] = p["scenes"][1:-1]
    p["scenes"][0]["from"] = 0
    errs = plan.check(p)
    assert any("accroche" in e for e in errs) and any("carte de fin" in e for e in errs)


def test_format_inconnu_et_longueur_paysage():
    p = _plan()
    p["format"] = "carre"
    assert any("format" in e for e in plan.check(p))
    p["format"] = "paysage"
    assert any("pour le format paysage" in e for e in plan.check(p))


def test_expression_inconnue_refusee():
    p = copy.deepcopy(_plan())
    p["scenes"][1]["bonhomme"]["reactions"][0]["expr"] = "furieux"
    assert any("expression 'furieux'" in e for e in plan.check(p))


def test_reperes_de_temps(episode: Path):
    tl = load(episode)
    assert plan.check_refs(tl.plan, tl) == []
    p = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    p["scenes"][2]["at"][0] = "w:introuvable@L4"
    assert any("mot introuvable" in e for e in plan.check_refs(p, tl))


@pytest.mark.parametrize(("fmt", "size"), [("vertical", (1920, 1080)), ("paysage", (1080, 1920))])
def test_images_des_deux_formats(episode: Path, fmt: str, size):
    r = _renderer(episode, fmt)
    for t in stills_times(r)[::3]:
        img = r.frame(int(t * 30))
        assert img.shape[:2] == size
        assert img.mean() > 3          # pas une image noire : bonhomme et textes dessinés


def test_scenes_couvrent_la_video(episode: Path):
    r = _renderer(episode)
    assert r.scenes[0]["t0"] == 0
    assert all(a["t0"] < b["t0"] for a, b in zip(r.scenes, r.scenes[1:], strict=False))
    assert r.scenes[-1]["t1"] == pytest.approx(r.tl.dur)


def test_bruitages(episode: Path):
    cues = cli.cues(_renderer(episode))
    names = [c[1] for c in cues]
    assert "coins.wav" in names and "chime.wav" in names and names.count("tap.wav") == 5
    assert all(0 <= at <= 80 for at, _n, _g in cues)


def test_legende_finance():
    txt = cli.caption(_plan())
    assert "Sources :" in txt and "#capitalsimple" in txt
    assert "pas un conseil" in txt


def test_upload_refuse_voix_estimee(episode: Path):
    with pytest.raises(RuntimeError, match="voix estimée"):
        cli.upload(episode)
