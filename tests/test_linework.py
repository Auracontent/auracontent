"""Scènes dessinées (linework) : moteur Pillow fidèle au moteur B1, contrôles de mise en page bloquants,
gabarit « deux montants », sprites de la vidéo test versionnés."""
import json
from pathlib import Path

import pytest
from auracontent.channels.finance import visuals
from auracontent.services.visuals.linework import templates as tpl
from auracontent.services.visuals.linework.engine import Painter, Scene, counter_text, key_state, render_mp4, wrap
from auracontent.services.visuals.linework.layout import LayoutError, Zones, check_layout, layout_issues

ROOT = Path(__file__).resolve().parents[1]
FONTS = {"hand": str(ROOT / "assets/finance/fonts/Caveat.ttf")}
DIRS = [str(ROOT / "assets/finance/characters"), str(ROOT / "assets/finance/props")]


def _scene(layers, duration=2.0):
    return Scene(layers=layers, duration=duration, fonts=FONTS, asset_dirs=DIRS, background="#F7F3EA")


# ---------- Moteur ----------
def test_key_state_smoothstep_like_b1_engine():
    layer = {"keys": [{"t": 0, "y": 0}, {"t": 1, "y": 100}]}
    assert key_state(layer, -1)["y"] == 0 and key_state(layer, 2)["y"] == 100
    assert key_state(layer, 0.5)["y"] == pytest.approx(50)
    assert key_state(layer, 0.25)["y"] == pytest.approx(100 * 0.25 * 0.25 * (3 - 0.5))


def test_counter_counts_up_to_the_exact_value():
    layer = {"count": {"from": 0, "to": 2100, "t0": 1, "t1": 2, "template": "Léa ≈ {n} €", "step": 10}}
    assert counter_text(layer, 0) == "Léa ≈ 0 €"
    assert counter_text(layer, 5) == "Léa ≈ 2 100 €"


def test_wrap_refuses_a_word_wider_than_its_zone():
    painter = Painter(_scene([]))
    font = painter.font({"bold": True}, 80)
    assert wrap(font, "deux mots", 2000) == ["deux mots"]
    with pytest.raises(ValueError, match="trop large"):
        wrap(font, "anticonstitutionnellement", 100)


def test_frame_renders_sprite_text_marker_and_stroke(tmp_path):
    layers = [{"type": "image", "path": "lea-joy.png", "x": 100, "y": 900, "w": 300, "role": "character"},
              {"type": "text", "text": "2 100 €", "x": 500, "y": 900, "size": 80},
              {"type": "marker", "x": 500, "y": 980, "w": 200, "h": 20, "progress": 0.5},
              {"type": "underline", "x": 100, "y": 1400, "w": 300, "keys": [{"t": 0, "progress": 0}, {"t": 1, "progress": 1}]}]
    img = Painter(_scene(layers)).frame(1.5)
    assert img.size == (1080, 1920) and img.getpixel((5, 1700)) != (0, 0, 0)
    out = render_mp4(_scene(layers, duration=0.2), tmp_path / "s.mp4")
    assert out.exists() and out.stat().st_size > 1000


def test_engine_reproduces_the_test_video_project():
    """Le project.json de la vidéo test se rend avec le moteur Pillow (même modèle de calques)."""
    ref = Path("/home/onyxia/work/videos/interets-composes-b1/project.json")
    if not ref.exists():
        pytest.skip("vidéo test absente de cette machine")
    shot = json.loads(ref.read_text())["shots"][4]
    scene = Scene(layers=shot["layers"], duration=6.7, fonts=FONTS, asset_dirs=[str(ref.parent)])
    assert Painter(scene).frame(6.4).getpixel((700, 1000)) != scene.background


# ---------- Contrôles de mise en page ----------
def test_text_outside_safe_zone_is_blocked():
    scene = _scene([{"type": "text", "text": "Résultat", "x": 1000, "y": 900, "size": 80, "role": "value"}])
    issues = layout_issues(scene)
    assert any("hors zone de sécurité" in i for i in issues)
    with pytest.raises(LayoutError):
        check_layout(scene)


def test_cut_text_is_blocked():
    scene = _scene([{"type": "text", "text": "anticonstitutionnellement", "x": 100, "y": 900, "size": 120, "w": 150}])
    assert any("texte coupé" in i for i in layout_issues(scene))


def test_text_over_character_and_reserved_zones_are_blocked():
    scene = _scene([{"type": "image", "path": "lea-joy.png", "x": 100, "y": 750, "w": 300, "role": "character"},
                    {"type": "text", "text": "2 100 €", "x": 150, "y": 900, "size": 80, "role": "value"},
                    {"type": "text", "text": "Sous le bandeau", "x": 100, "y": 300, "size": 60}])
    issues = layout_issues(scene)
    assert any("chevauchement texte/personnage" in i for i in issues)
    assert any("zone réservée « bandeau »" in i for i in issues)


def test_object_off_its_support_is_blocked():
    ground = {"type": "image", "id": "sol", "path": "ground.png", "x": 0, "y": 1200, "w": 1280, "role": "decor",
              "surface": 30}
    floating = {"type": "image", "path": "lea-joy.png", "x": 300, "y": 600, "w": 300, "role": "character",
                "rests_on": "sol"}
    assert any("hors de son support" in i for i in layout_issues(_scene([ground, floating])))


def test_issue_reported_once_not_per_instant():
    scene = _scene([{"type": "text", "text": "Résultat", "x": 1000, "y": 900, "size": 80, "role": "value"}], 5)
    assert len(layout_issues(scene)) == 1


def test_zones_from_yaml():
    z = Zones.from_config({"safe": [0, 210, 920, 1430], "reserved": {"bandeau": [0, 200, 1080, 450]}})
    assert z.safe == (0, 210, 920, 1430) and list(z.reserved) == ["bandeau"]


# ---------- Gabarit « deux montants », scène « deux arbres » ----------
PARAMS = {"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount": 300, "late_amount_factor": 3,
          "rate": 7, "end_age": 65}


def test_two_trees_scene_passes_layout_and_tells_the_story():
    scene = visuals.lea_hugo_trees(PARAMS)                       # contrôles bloquants passés
    ids = {lay.get("id"): lay for lay in scene.layers}
    assert ids["objet-gagnant"]["keys"][0]["t"] > ids["objet-perdant"]["keys"][-1]["t"]   # Hugo d'abord
    assert ids["perdant-reaction"]["path"] == "hugo-shock.png" and ids["gagnant"]["path"] == "lea-joy.png"
    assert counter_text(ids["montant-gagnant"], 99) == "Léa ≈ 2 100 €"                  # chiffre de calc.py
    assert counter_text(ids["montant-perdant"], 99) == "Hugo ≈ 1 630 €"
    assert all(lay.get("motion") for lay in scene.layers if lay.get("role") in ("prop",) or lay.get("id") == "gagnant")


def test_piles_variant_scales_with_the_amounts():
    side = dict(caption="", color=tpl.INK)
    layers = tpl.two_amounts(tpl.Side("A", 2000, "2 000 €", **side), tpl.Side("B", 1000, "1 000 €", **side),
                             resolve=visuals.resolve, variant="piles")
    big, small = (next(lay for lay in layers if lay.get("id") == i) for i in ("objet-gagnant", "objet-perdant"))
    assert small["h"] < big["h"]
    check_layout(visuals.make_scene(layers, 6.7))


def test_finance_sprites_are_versioned():
    for folder in ("characters", "props"):
        manifest = json.loads((ROOT / f"assets/finance/{folder}/sprites.json").read_text())
        assert manifest and all((ROOT / f"assets/finance/{folder}/{n}.png").exists() for n in manifest)
    for pose in ("lea-neutral", "lea-surprise", "lea-point", "hugo-neutral", "hugo-point"):
        assert (ROOT / f"assets/finance/characters/{pose}.png").exists()


def test_left_margin_of_60_px_is_enforced():
    """La carte de fin touchait le bord gauche (« Capital Simple », baseline, question) : 60 px au moins."""
    scene = _scene([{"type": "text", "text": "Capital Simple", "x": 30, "y": 900, "size": 80, "role": "text"}])
    assert any("hors zone de sécurité" in i for i in layout_issues(scene))
    assert Zones().safe[0] == 60
    card = visuals.build_scene("regle_72", {"rate": 4, "rate_b": 8}, {"role": "cta", "template": "carte_fin"}, 4.0,
                               question="Quel taux double ton argent le plus vite ?")
    texts = [lay for lay in card.layers if lay["type"] == "text"]
    assert all(lay["x"] * card.scale >= 60 for lay in texts)
