"""Refonte V2 de Capital Simple : moteur de réalisation (finance uniquement)."""
from pathlib import Path

import pytest
from auracontent.channels.finance.v2 import captions, director, easing, props
from auracontent.channels.finance.v2.director import Shot


@pytest.mark.parametrize("name", list(easing.EASINGS))
def test_easing_bornes(name):
    assert easing.ease(name, 0) == pytest.approx(0, abs=1e-6)
    assert easing.ease(name, 1) == pytest.approx(1, abs=1e-6)


def test_easing_back_depasse_puis_revient():
    assert max(easing.back(x / 100) for x in range(101)) > 1.0


def test_easing_inconnu_retombe_sur_smooth():
    assert easing.ease("inconnu", 0.3) == pytest.approx(easing.smooth(0.3))


def test_key_state_respecte_la_courbe_de_la_cle_d_arrivee():
    layer = {"keys": [{"t": 0, "y": 0}, {"t": 1, "y": 100, "ease": "linear"}]}
    assert director.key_state(layer, 0.25)["y"] == pytest.approx(25)
    layer["keys"][1]["ease"] = "smooth"
    assert director.key_state(layer, 0.25)["y"] == pytest.approx(100 * easing.smooth(0.25))


def test_camera_fixe_sans_cle_et_interpolee_sinon():
    assert director.camera_at([], 1.0) == (1.0, 540.0, 960.0)
    zoom, cx, cy = director.camera_at([{"t": 0, "zoom": 1.0}, {"t": 2, "zoom": 1.2, "ease": "linear"}], 1.0)
    assert zoom == pytest.approx(1.1) and (cx, cy) == (540.0, 960.0)


def test_estimation_garde_les_montants_en_un_mot():
    words = captions.estimate("Et en cinq ans : 1 768 €.", 0.0, 3.0)
    assert "1 768" in [w.text for w in words]
    assert words[0].start == 0.0 and words[-1].end <= 3.0
    assert all(a.start < b.start for a, b in zip(words, words[1:], strict=False))


def test_minutage_edge_tts():
    words = captions.from_edge([{"offset": 5_000_000, "duration": 3_000_000, "text": "Hugo"}], offset=2.0)
    assert words[0].start == pytest.approx(2.5) and words[0].end == pytest.approx(2.8)


def test_find_cale_une_animation_sur_un_mot():
    words = captions.estimate("Sur un an, 354 € quittent son compte.", 0.0, 3.0)
    assert captions.find(words, "354") == next(w.start for w in words if w.text == "354")
    assert captions.find(words, "absent", 9.0) == 9.0


def test_groupes_coupes_a_la_ponctuation_et_a_trois_mots():
    words = captions.estimate("Hugo paie trois abonnements, presque plus.", 0.0, 3.0)
    for g in captions.groups(words):
        assert len(g) <= 3


def test_sous_titres_sans_chevauchement():
    words = captions.estimate("Trois abonnements oubliés : 1 768 € en cinq ans.", 0.0, 4.0)
    ass = captions.build_ass(words, bandeau=("HAUT", "BOITE"), total=4.0)
    events = [line for line in ass.splitlines() if line.startswith("Dialogue: 0,")]

    def sec(x):
        h, m, s = x.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    spans = sorted((sec(e.split(",")[1]), sec(e.split(",")[2])) for e in events)
    assert all(a[1] <= b[0] + 1e-6 for a, b in zip(spans, spans[1:], strict=False))
    assert "TopBox" in ass and "BOITE" in ass


def test_debut_des_plans_avec_transitions():
    shots = [Shot([], 3.0), Shot([], 2.0), Shot([], 4.0)]
    assert director.starts(shots, 0.5) == [0.0, 2.5, 4.0]


def test_objets_mis_en_cache(tmp_path: Path):
    p1 = props.ensure("coin", tmp_path)
    p2 = props.ensure("coin", tmp_path)
    assert p1 == p2 and Path(p1).exists()
    for name in props.BUILDERS:
        assert Path(props.ensure(name, tmp_path)).stat().st_size > 0


def test_rendu_d_un_plan_court(tmp_path: Path):
    from auracontent.channels.finance import visuals as fvis
    layer = {"type": "image", "id": "c", "path": props.ensure("coin", tmp_path), "x": 100, "y": 100, "w": 200,
             "keys": [{"t": 0, "y": 0}, {"t": 0.3, "y": 300, "ease": "bounce"}]}
    shot = Shot([layer], 0.4, camera=[{"t": 0, "zoom": 1.0}, {"t": 0.4, "zoom": 1.1}])
    kwargs = {"fonts": {k: str(v) for k, v in fvis.FONTS.items()}, "asset_dirs": []}
    out = director.render_shot(shot, kwargs, tmp_path / "plan.mp4")
    assert out.exists() and out.stat().st_size > 0


def test_le_moteur_partage_n_est_pas_modifie():
    """La V2 ne touche pas au moteur linework partagé : son interpolation reste le smoothstep."""
    from auracontent.services.visuals.linework import engine
    layer = {"keys": [{"t": 0, "y": 0}, {"t": 1, "y": 100, "ease": "linear"}]}
    assert engine.key_state(layer, 0.25)["y"] == pytest.approx(100 * easing.smooth(0.25))
