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


def test_aucun_son_de_mystery_ni_du_dossier_partage():
    assert all("finance" in str(p) for p in director.SFX_DIRS)


def test_pilote_avec_voix_simulee(tmp_path: Path, monkeypatch):
    """Chemin --voice : durée des plans = durée de la voix, voix posée au début de chaque plan."""
    import subprocess

    from auracontent.channels.finance.v2 import pilot

    async def fake_synth(text, path):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1.5", str(path)], check=True)
        return [{"offset": 1_000_000, "duration": 2_000_000, "text": "a"},
                {"offset": 12_000_000, "duration": 2_000_000, "text": "b"}]

    monkeypatch.setattr(pilot, "_synth", fake_synth)
    sc = pilot.timed_script(1.0, tmp_path / "voix")
    assert all(s["voice"].exists() for s in sc)
    assert sc[0]["duration"] == pytest.approx(pilot.LEAD + 1.4 + 0.5, abs=0.01)
    assert sc[0]["words"][0].start == pytest.approx(pilot.LEAD + 0.1)


# ---------- Branchement dans le pipeline (étape 3) ----------
def _params(concept):
    from auracontent.channels.finance import calc
    spec = calc.SPECS[concept]["params"]
    p = {}
    for name, (_label, _unit, lo, hi) in spec.items():
        v = lo + (hi - lo) * 0.3
        p[name] = round(v) if float(lo).is_integer() and float(hi).is_integer() else round(v, 2)
    fixed, msg = calc.check_params(concept, p)
    assert fixed, msg
    return fixed


def test_tous_les_calculs_ont_leurs_objets():
    from auracontent.channels.finance import calc
    assert set(calc.SPECS) <= set(props.CONCEPT_PROPS)


@pytest.mark.parametrize("concept", ["abonnements", "epargne_age", "credit_amortissable", "interets_composes",
                                     "inflation", "remises_successives", "forfait_appareil", "regle_72"])
def test_scenes_v2_passent_la_mise_en_page(concept, tmp_path):
    """Chaque scène V2 du storyboard passe le contrôle bloquant (sinon repli V1 : jamais de vidéo refusée)."""
    from auracontent.channels.finance import storyboard
    from auracontent.channels.finance.v2 import scenes
    from auracontent.services.visuals.linework.engine import Scene
    from auracontent.services.visuals.linework.layout import Zones, check_layout

    p = _params(concept)
    kw = scenes._scene_kwargs({})
    for i, (role, template) in enumerate(storyboard.storyboard(concept), 1):
        sc = {"id": i, "role": role, "template": template, "visual": "", "text": "Une phrase de test."}
        shot, engine = scenes.scene_shot(concept, p, sc, 6.0, hypothesis="hypothèse de test", question="Et toi ?",
                                         pdir=tmp_path)
        if engine == "v2":
            check_layout(Scene(layers=shot.layers, duration=6.0, **kw), Zones())


def test_accroche_barres_en_v2_et_courbe_en_v1(tmp_path):
    from auracontent.channels.finance.v2 import scenes
    p = _params("abonnements")
    hook = {"id": 1, "role": "hook", "template": "barres", "visual": "", "text": "x"}
    curve = {"id": 3, "role": "mechanism", "template": "deux_courbes", "visual": "", "text": "x"}
    assert scenes.scene_shot("abonnements", p, hook, 5.0, hypothesis="", question="", pdir=tmp_path)[1] == "v2"
    assert scenes.scene_shot("abonnements", p, curve, 5.0, hypothesis="", question="", pdir=tmp_path)[1] == "v1"


def test_texte_des_montants_garde_le_modele():
    from auracontent.channels.finance.v2 import scenes
    from auracontent.services.visuals.linework import templates as tpl
    assert scenes.value_text(tpl.Item("mise", 2.7, "2,7", count_template="× {n}")) == "× 2,7"
    assert scenes.value_text(tpl.Item("total", 4656, "4 656 €", count_template="{n} €")).endswith("€")


def test_render_scenes_v2_produit_un_clip_par_scene(tmp_path):
    from auracontent.channels.finance import storyboard
    from auracontent.channels.finance.v2 import scenes
    p = _params("abonnements")
    sb = storyboard.storyboard("abonnements")
    script = {"pick": {"concept": "abonnements", "params": p}, "hypothesis": "hypothèse", "closing_cta": "Et toi ?"}
    sc = [{"id": i, "role": r, "template": t, "visual": "", "text": "Phrase.", "duration": 0.6}
          for i, (r, t) in enumerate(sb, 1)]
    clips = scenes.render_scenes(script, sc, tmp_path)
    assert len(clips) == len(sc) and all(Path(c).exists() for c in clips)
    assert all("sfx_cues" in s for s in sc)


def test_option_v2_finance_seulement():
    import yaml
    root = Path(__file__).resolve().parents[1] / "config" / "channels"
    fin = yaml.safe_load((root / "finance.yaml").read_text(encoding="utf-8"))
    mys = yaml.safe_load((root / "mystery.yaml").read_text(encoding="utf-8"))
    assert fin["visuals"]["linework"]["engine"] == "v2"
    assert "engine" not in ((mys.get("visuals") or {}).get("linework") or {})
    assert mys["video_composer"].get("transitions") != fin["video_composer"]["transitions"]


def test_accroche_montre_le_resultat_principal_pas_l_idee_fausse(tmp_path):
    """Remises successives : le gros chiffre est la remise réelle (calc.headline), jamais la remise crue."""
    from auracontent.channels.finance import calc
    from auracontent.channels.finance.v2 import scenes
    p = _params("remises_successives")
    c = calc.compute("remises_successives", p)
    hook = {"id": 1, "role": "hook", "template": "barres", "visual": "", "text": "x"}
    shot, _ = scenes.scene_shot("remises_successives", p, hook, 5.0, hypothesis="", question="", pdir=tmp_path)
    big = next(lay for lay in shot.layers if lay.get("id") == "chiffre")
    assert c.values[c.headline].text.replace(" ", " ") in big["text"].replace(" ", " ")
