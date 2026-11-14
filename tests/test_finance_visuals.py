"""Capital Simple : chaque scène de chaque storyboard se dessine sans faute de mise en page, avec les chiffres de
calc.py, des effets sonores calés sur l'action, et build_visuals rend un clip par scène."""
import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import storyboard, visuals
from auracontent.channels.finance.brain import FinanceBrain
from auracontent.services.visuals.linework import templates as tpl
from auracontent.services.visuals.linework.engine import counter_text

PARAMS = {
    "interets_composes": {"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount": 300,
                          "late_amount_factor": 3, "rate": 7, "end_age": 65},
    "inflation": {"amount": 10000, "inflation": 3, "years": 20},
    "cout_du_temps": {"monthly": 100, "rate": 5, "delay_years": 10, "horizon_years": 40},
    "frais": {"amount": 5000, "rate": 6, "fees": 2, "years": 20},
    "regle_72": {"rate": 4, "rate_b": 8},
}
CASES = [(concept, role, template, variant)
         for concept in PARAMS
         for role, template in [*storyboard.storyboard(concept), ("cta", "carte_fin")]
         for variant in storyboard.VARIANTS[template]]


@pytest.mark.parametrize("concept, role, template, variant", CASES)
@pytest.mark.parametrize("duration", [3.0, 7.0])
def test_every_scene_passes_layout(concept, role, template, variant, duration):
    scene = {"role": role, "template": template, "visual": variant}
    built = visuals.build_scene(concept, PARAMS[concept], scene, duration,
                                hypothesis=FinanceBrain.hypothesis(concept, PARAMS[concept]), question="Et toi ?")
    animated = [lay for lay in built.layers if lay.get("keys") and lay.get("role") in ("prop", "character", "value")]
    assert animated, "au moins une animation liée au propos"


def _texts(layers):
    return [counter_text(lay, 999) for lay in layers if lay["type"] == "text"]


def test_numbers_on_screen_come_from_calc():
    p = PARAMS["cout_du_temps"]
    c = fcalc.compute("cout_du_temps", p)
    layers = visuals.scene_layers("cout_du_temps", p, {"role": "reveal", "template": "deux_courbes", "visual": "ecart"},
                                  6.0, hypothesis="h")
    shown = " ".join(_texts(layers))
    for key in ("final_now", "final_late", "cost"):
        assert c.values[key].text in shown


def test_decimal_values_keep_their_template():
    p = PARAMS["interets_composes"]
    layers = visuals.scene_layers("interets_composes", p, {"role": "takeaway", "template": "barres", "visual": "barres"},
                                  6.0)
    shown = _texts(layers)
    assert "\u00d7 21" in shown and "\u00d7 5,4" in shown


def test_sound_cues_are_sorted_and_inside_the_scene():
    p = PARAMS["interets_composes"]
    layers = visuals.scene_layers("interets_composes", p, {"role": "reveal", "template": "deux_arbres", "visual": "arbres"},
                                  6.7)
    cues = tpl.cues(layers, 6.7)
    times = [c["time"] for c in cues]
    assert times == sorted(times) and all(0 <= t < 6.7 for t in times)
    assert {"grow.wav", "boing.wav", "chime.wav"} <= {c["file"] for c in cues}
    for c in cues:
        assert (visuals.ASSETS / "sfx" / c["file"]).exists()


def test_build_visuals_renders_one_clip_per_scene(tmp_path):
    brain = BaseChannel("finance", FinanceBrain, None).brain
    script = {"pick": {"concept": "regle_72", "params": PARAMS["regle_72"]}, "hypothesis": "4 % et 8 %/an",
              "closing_cta": "Et toi ?"}
    scenes = [{"id": i, "role": r, "template": t, "visual": next(iter(storyboard.VARIANTS[t])), "duration": 0.3}
              for i, (r, t) in enumerate(storyboard.storyboard("regle_72"), 1)]
    scenes.append({"id": len(scenes) + 1, "role": "cta", "duration": 0.3, "text": "Et toi ?"})
    clips = brain.build_visuals(script, scenes, tmp_path, {})
    assert len(clips) == len(scenes) and all(tmp_path.joinpath("visuals").exists() for _ in clips)
    assert all("sfx_cues" in s for s in scenes)


def test_mystery_keeps_its_visual_search():
    from auracontent.channels.mystery.brain import MysteryBrain

    brain = MysteryBrain(config=BaseChannel("mystery", MysteryBrain, None).cfg, llm=None)
    assert brain.build_visuals({}, [], ".", {}) is None


def test_voice_role_directions_opt_out():
    from auracontent.services.audios.audio import AudioEngine

    on = AudioEngine({"engines": [], "gemini": {"narrator": {"style": ""}}}, output_dir="/tmp/aura_test_audio")
    off = AudioEngine({"engines": [], "role_directions": False, "gemini": {"narrator": {"style": ""}}},
                      output_dir="/tmp/aura_test_audio")
    scene = {"role": "reveal"}
    assert on._directions(scene) and off._directions(scene) == []          # mystery : consignes inchangées


def test_finance_yaml_subtitles_and_layout():
    cfg = BaseChannel("finance", FinanceBrain, None).cfg
    assert "MarginV=72" in cfg["video_composer"]["subtitle_style"]
    assert cfg["audio"]["role_directions"] is False
    assert cfg["visuals"]["linework"]["layout"]["reserved"]["sous-titres"] == [0, 1240, 1080, 1440]


def test_every_storyboard_template_has_a_drawing():
    used = {t for concept in PARAMS for _, t in storyboard.storyboard(concept)}
    assert used <= set(storyboard.VARIANTS)
    assert set(storyboard.VARIANTS) == {"deux_arbres", "deux_courbes", "barres", "curseur_temps", "carte_fin",
                                        "personnages"}


@pytest.mark.parametrize("delay, horizon", [(5, 40), (5, 30), (10, 30)])
@pytest.mark.parametrize("variant", ["frise", "sablier"])
def test_close_timeline_steps_do_not_overlap(delay, horizon, variant):
    """Run du 14/11 : 5 ans d'attente sur 40, les libellés « début » et « on attend » se chevauchaient."""
    params = {"monthly": 200, "rate": 5, "delay_years": delay, "horizon_years": horizon}
    for role in ("context", "mechanism"):
        visuals.build_scene("cout_du_temps", params, {"role": role, "template": "curseur_temps", "visual": variant},
                            4.0, hypothesis="5 %/an")


def _yaml_sample(every: int = 25):
    brain = BaseChannel("finance", FinanceBrain, None).brain
    for concept in brain.config["brain"]["concepts"]:
        combos = brain.combinations(concept)
        for params in combos[::every] + combos[-1:]:
            yield concept, params


@pytest.mark.parametrize("concept, params", list(_yaml_sample()))
def test_yaml_combinations_pass_layout(concept, params):
    """Échantillon des combinaisons du YAML (une sur 25, plus la dernière), contrôles bloquants appliqués à
    chaque scène et variante. Le balayage complet se lance hors tests (toutes les combinaisons)."""
    hyp = FinanceBrain.hypothesis(concept, params)
    for role, template in [*storyboard.storyboard(concept), ("cta", "carte_fin")]:
        for variant in storyboard.VARIANTS[template]:
            visuals.build_scene(concept, params, {"role": role, "template": template, "visual": variant}, 4.0,
                                hypothesis=hyp, question="Quand as-tu prévu de commencer ?")


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg absent")
def test_repeated_sound_cue_mixes(tmp_path):
    """Run du 14/11 : le même effet deux fois dans une scène faisait échouer FFmpeg (scène sautée)."""
    import subprocess

    import ffmpeg
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.video.composer import Composer

    voice = tmp_path / "v.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=3", "-ar", "48000", str(voice)],
                   check=True)
    composer = Composer(load_channel_config("finance")["video_composer"], channel_name="finance")
    scene = {"sfx_cues": [{"time": 0.2, "file": "tick.wav", "gain": 0.3}, {"time": 1.0, "file": "tick.wav", "gain": 0.3},
                          {"time": 1.5, "file": "chime.wav", "gain": 0.3}]}
    out = tmp_path / "mix.wav"
    ffmpeg.output(composer._build_scene_audio(str(voice), scene, 3.0), str(out)).overwrite_output().run(quiet=True)
    assert out.stat().st_size > 100_000


def test_incomplete_video_is_refused(monkeypatch, tmp_path):
    """finance (require_all_scenes) : une scène non rendue = vidéo refusée, jamais une vidéo tronquée."""
    from auracontent.core import pipeline

    brain = BaseChannel("finance", FinanceBrain, None)
    assert brain.section("video_composer")["require_all_scenes"] is True
    assert not BaseChannel("mystery", __import__("auracontent.channels.mystery.brain", fromlist=["MysteryBrain"])
                           .MysteryBrain, None).section("video_composer").get("require_all_scenes")

    class FakeComposer:
        headline_persistent = False

        def __init__(self, *a, **k):
            pass

        def render_all_scenes(self, scenes, assets):
            return ["a.mp4"]                                       # une seule scène sur deux

    monkeypatch.setattr(pipeline, "Composer", FakeComposer)
    monkeypatch.setattr(pipeline, "generate_caption", lambda *a, **k: "légende")
    monkeypatch.setattr(pipeline.VideoPipeline, "_voice", lambda self, scenes: _coro(scenes))
    monkeypatch.setattr(pipeline.VideoPipeline, "_subtitles", lambda self, scenes: None)
    monkeypatch.setattr(FinanceBrain, "build_visuals", lambda self, *a: ["a.mp4", "b.mp4", "c.mp4"])
    vp = pipeline.VideoPipeline(brain, None)
    vp.work_dir = tmp_path
    script = {"title": "t", "scenes": [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}], "closing_cta": "Et toi ?"}
    with pytest.raises(RuntimeError, match="vidéo incomplète refusée"):
        vp.run(script)


async def _coro(value):
    return value
