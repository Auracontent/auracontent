"""Chaîne finance : configuration, registre, choix du sujet, filtres et script (LLM factice)."""
import json

import pytest
from auracontent.channels.base_channel import BaseChannel, load_channel_config
from auracontent.channels.finance.brain import (
    FinanceBrain,
    clean_text,
    comparable,
    count_words,
    normalize_title,
    numbers_in,
    sentences,
)
from auracontent.channels.registry import CHANNEL_REGISTRY
from auracontent.services.publishing import state_sync


@pytest.fixture
def finance_state(monkeypatch, tmp_path):
    """Historiques dans un dossier temporaire ; finance isolée comme dans son YAML."""
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    return tmp_path


def _brain(llm=None) -> FinanceBrain:
    return BaseChannel("finance", FinanceBrain, llm).brain


# ---------- Configuration et registre ----------
def test_registry_and_config():
    assert CHANNEL_REGISTRY["mystery"].__name__ == "MysteryBrain"
    assert CHANNEL_REGISTRY["finance"] is FinanceBrain
    cfg = load_channel_config("finance")
    assert cfg["state"]["isolated"] is True
    assert set(cfg["brain"]["concepts"]) == {"interets_composes", "inflation", "cout_du_temps", "frais", "regle_72"}
    assert cfg["brain"]["rate_limit"] == "fallback" and cfg["brain"]["style_warnings"] == "reject"
    assert cfg["visuals"]["map_scene"]["enabled"] is False
    pub = cfg["publish"]
    assert pub["zernio_key_env"] == "ZERNIO_API_KEY_FINANCE"
    assert {p["account_env"] for p in pub["platforms"]} == {"TIKTOK_ACCOUNT_ID_FINANCE", "YOUTUBE_ACCOUNT_ID_FINANCE"}
    assert pub["brand_hashtag"] == "#capitalsimple" and pub["hf_folder"] == "finance"
    assert pub["caption_footer"] == "Contenu pédagogique, pas un conseil en investissement."
    assert "Montserrat" not in json.dumps(cfg["video_composer"])        # réservée à mystery


def test_finance_state_isolated_mystery_shared():
    state_sync.is_isolated.cache_clear()
    assert state_sync.is_isolated("finance") is True
    assert state_sync.is_isolated("mystery") is False


# ---------- Texte ----------
def test_normalize_title_unicode_spaces_and_dashes():
    raw = "100\u202f€\u00a0à\u00a020\u2011ans  !"
    assert normalize_title(raw) == "100 € à 20-ans !"
    assert normalize_title("plus\u2026") == "plus..."                       # NFKC : pour comparer seulement
    assert clean_text("plus\u2026\u00a0!") == "plus\u2026 !"                  # texte conservé tel quel
    assert comparable("Mettre MOINS d\u2019argent…") == comparable("mettre moins d\u2019argent")


def test_numbers_and_words():
    assert numbers_in("Hugo a 1\u202f630 € et 0,5 % de frais à 40 ans") == [1630, 0.5, 40]
    assert count_words("Mettre moins d'argent… et finir avec plus.") == 7
    assert sentences("Mettre moins d'argent… et finir avec plus. Pourquoi ? Le temps.") == [
        "Mettre moins d'argent… et finir avec plus.", "Pourquoi ?", "Le temps."]


# ---------- Sujet : concept + paramètres, déduplication ----------
def test_combinations_are_coherent():
    brain = _brain()
    for params in brain.combinations("interets_composes"):
        assert params["late_amount"] == params["early_amount"] * params["late_amount_factor"]
        assert params["late_age"] - params["early_age"] >= 15 and params["end_age"] - params["late_age"] >= 15
    assert all(p["delay_years"] < p["horizon_years"] / 2 for p in brain.combinations("cout_du_temps"))


def test_topic_key_ignores_param_order():
    assert FinanceBrain.topic_key("frais", {"rate": 7, "fees": 1}) == FinanceBrain.topic_key("frais", {"fees": 1, "rate": 7})


def test_pick_topic_dedups_concept_and_params(finance_state, capsys):
    from auracontent.utils.topic_tracker import save_global_history

    brain = _brain()
    brain.config["brain"]["concepts"] = {"regle_72": brain.config["brain"]["concepts"]["regle_72"]}
    brain.config["brain"]["recent_concepts_window"] = 0
    seen = set()
    for _ in range(5):                                     # 5 taux possibles (≤ 8 %), tous différents
        topic = brain.pick_topic()
        assert brain.last_pick["topic_key"] not in seen
        seen.add(brain.last_pick["topic_key"])
        save_global_history(topic, "finance", **brain.last_pick)
    with pytest.raises(RuntimeError, match="inédite"):
        brain.pick_topic()
    assert "Concept épuisé" in capsys.readouterr().out
    shared = finance_state / "global_history.json"
    assert not shared.exists()                             # rien dans le fichier partagé de mystery


def test_recent_concept_is_skipped_with_reason(finance_state, capsys):
    from auracontent.utils.topic_tracker import save_global_history

    brain = _brain()
    save_global_history("x", "finance", category="inflation", topic_key="inflation:x")
    save_global_history("y", "finance", category="frais", topic_key="frais:y")
    for _ in range(10):
        brain.pick_topic()
        assert brain.last_pick["concept"] not in {"inflation", "frais"}


# ---------- Filtres : accroches et script ----------
def _picked(concept="interets_composes", **params):
    brain = _brain()
    base = {"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount_factor": 3, "rate": 7, "end_age": 65}
    base.update(params)
    resolved = brain.resolve_params(concept, base)
    brain.last_pick = {"concept": concept, "params": resolved, "topic_key": brain.topic_key(concept, resolved)}
    return brain


def test_hook_filters_log_reasons():
    brain = _picked()
    topic = brain.describe("interets_composes", brain.last_pick["params"])
    assert brain.hook_issues("Mettre moins d'argent… et finir avec plus.", topic) == []
    assert any("mots" in i for i in brain.hook_issues("Un deux trois quatre cinq six sept huit neuf dix onze douze treize.", topic))
    assert brain.hook_issues("Léa finit avec 2 100 €.", topic) == []               # résultat de calc.py
    assert any("2500" in i or "2 500" in i for i in brain.hook_issues("Léa finit avec 2500 €.", topic))
    assert any("472" in i for i in brain.hook_issues("Léa a 472 € de plus.", topic))  # écart non arrondi
    assert any("vouvoie" in i for i in brain.hook_issues("Vous allez être surpris.", topic))
    assert any("livret A" in i for i in brain.hook_issues("Le livret A ne suffit pas.", topic))
    assert brain.hook_issues("100 € à 20 ans battent 300 € à 40 ans.", topic) == []


def test_regle_72_constant_allowed():
    brain = _picked("regle_72", rate=6)
    brain.last_pick["params"] = {"rate": 6}
    assert brain.text_issues("La règle des 72 marche à 6 % par an.", "x") == []


class _FakeLLM:
    """Accroches puis script ; le premier script est trop long (doit être régénéré)."""

    def __init__(self, scripts):
        self.scripts, self.calls, self.systems = list(scripts), [], []

    def call_json_with_retry(self, messages, **kw):
        self.calls.append(kw)
        self.systems.append(messages[0]["content"])
        if "vérifies les chiffres" in messages[0]["content"]:
            return {"ok": True, "problems": []}
        if "accroches" in messages[0]["content"]:
            return {"hooks": [{"text": "Mettre moins d'argent… et finir avec plus.", "pattern": "contradiction",
                               "score": 9},
                              {"text": "Vous allez découvrir le secret des riches investisseurs malins.",
                               "pattern": "question", "score": 7}]}
        return self.scripts.pop(0)

    def call_with_fallback(self, *a, **k):
        return ""


def _script(first_scene: str):
    scenes = [{"id": 1, "text": first_scene, "visual": "piles", "mood": "surprise", "pause_after_ms": 400}]
    scenes += [{"id": i, "text": "Les gains rapportent à leur tour des gains.", "visual": "arbres",
                "mood": "calm", "pause_after_ms": 400} for i in range(2, 8)]
    scenes[4]["text"] = "À 65 ans, Léa a 2 100 € et Hugo 1 630 €."      # scène 5 : « reveal » du storyboard
    return {"title": "Moins d'argent, plus à l'arrivée", "on_screen_title": "100 € À 20 ANS | BATTENT 300 € À 40",
            "hypothesis": "reformulée", "closing_cta": "Et toi, tu aurais parié sur qui ?", "scenes": scenes}


def test_run_channel_script_only_regenerates_and_saves(finance_state, monkeypatch):
    from auracontent.core.brain import global_brain

    long_first = ("Mettre moins d'argent… et finir avec plus, c'est exactement ce que cette petite histoire "
                  "va te montrer maintenant.")
    llm = _FakeLLM([_script(long_first), _script("Mettre moins d'argent… et finir avec plus.")])
    monkeypatch.setattr(global_brain.GlobalBrain, "_fetch_stats", staticmethod(lambda cfg: None))
    monkeypatch.setattr(global_brain.GlobalBrain, "output_dir", finance_state / "scripts")
    gb = global_brain.GlobalBrain(llm_client=llm)
    gb.output_dir = finance_state / "scripts"
    brain = gb.channels["finance"].brain
    brain.config["brain"]["concepts"] = {"interets_composes": brain.config["brain"]["concepts"]["interets_composes"]}
    brain.combinations = lambda concept: [brain.resolve_params(concept, {
        "early_age": 20, "late_age": 40, "early_amount": 100, "late_amount_factor": 3, "rate": 7, "end_age": 65})]

    path = gb.run_channel("finance")
    script = json.loads(path.read_text(encoding="utf-8"))
    assert script["scenes"][0]["text"] == "Mettre moins d'argent… et finir avec plus."
    assert script["hypothesis"] == "7 %/an · versement unique · avant inflation"
    assert "unresolved_issues" not in script
    assert script["calc"]["headline"] == "lea_final" and script["calc"]["values"]["lea_final"]["value"] == 2100
    assert [s["template"] for s in script["scenes"]] == ["deux_arbres", "curseur_temps", "barres", "deux_courbes",
                                                         "deux_arbres", "barres", "carte_fin"]
    assert script["scenes"][0]["visual"] == "piles" and script["scenes"][6]["visual"] == "logo"
    assert any("vérifies les chiffres" in c for c in llm.systems)              # vérification du sens faite
    assert all(call.get("rate_limit") == "fallback" for call in llm.calls)       # bascule au premier 429
    history = json.loads((finance_state / "finance" / "global_history.json").read_text(encoding="utf-8"))
    assert history[0]["concept"] == "interets_composes" and history[0]["channel"] == "finance"
    assert not (finance_state / "global_history.json").exists()


def test_script_with_style_warnings_is_never_returned(finance_state):
    long_first = ("Mettre moins d'argent… et finir avec plus, c'est exactement ce que cette petite histoire "
                  "va te montrer maintenant.")
    brain = _picked()
    brain.llm = _FakeLLM([_script(long_first)] * 12)
    brain.chosen_hook_text = None
    with pytest.raises(RuntimeError):
        brain.generate_script_with_target("sujet", scene_count=7)
