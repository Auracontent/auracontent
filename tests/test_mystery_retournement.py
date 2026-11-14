"""mystery : contrôle « retournement » assoupli pour les anecdotes « Le saviez-vous ? » (la surprise est-elle
gardée ?), critère d'origine pour les sujets par mots-clés ; titre nettoyé de son numéro de liste."""
import pytest
from auracontent.channels.base_channel import load_channel_config
from auracontent.channels.mystery.brain import MysteryBrain


class _Judge:
    def __init__(self, answer):
        self.answer, self.messages = answer, []

    def call_json_with_retry(self, messages, **kw):
        self.messages.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _mystery(llm) -> MysteryBrain:
    return MysteryBrain(config=load_channel_config("mystery"), llm=llm)


ANECDOTE = {"title": "Poissons (Haute-Marne)", "extract": "Commune de la Haute-Marne.",
            "anecdote": "La ville de Poissons, dans la Haute-Marne, est jumelée à celle d'Avril."}
QUESTION = "Pourquoi Poissons est-il jumelé à Avril ?"


def test_anecdote_uses_surprise_criterion():
    judge = _Judge({"garde_surprise": True, "raison": "le jumelage Poissons-Avril est annoncé"})
    ok, reason = _mystery(judge).has_reversal(QUESTION, ANECDOTE)
    assert ok and "jumelage" in reason
    system, user = judge.messages[0][0]["content"], judge.messages[0][1]["content"]
    assert ANECDOTE["anecdote"] in user and QUESTION in user
    assert "n'est PAS un motif de rejet" in user and "En cas de doute, réponds false" not in system + user


def test_anecdote_title_losing_the_surprise_is_rejected():
    judge = _Judge({"garde_surprise": False, "raison": "parle d'un autre fait"})
    assert _mystery(judge).has_reversal("En 1153, le village s'appelait autrement", ANECDOTE) == (
        False, "parle d'un autre fait")


def test_old_key_is_not_accepted_for_anecdotes():
    """Une réponse au format de l'ancien critère ne vaut pas acceptation (jamais accepté par défaut)."""
    assert _mystery(_Judge({"retournement": True})).has_reversal(QUESTION, ANECDOTE)[0] is False


def test_keyword_topics_keep_the_original_criterion():
    judge = _Judge({"retournement": True, "raison": "abbaye devenue prison"})
    source = {"title": "Abbaye de Clairvaux", "extract": "Abbaye devenue prison."}
    assert _mystery(judge).has_reversal("L'abbaye devenue prison", source)[0]
    assert "RETOURNEMENT" in judge.messages[0][1]["content"]


def test_judge_failure_still_rejects():
    ok, reason = _mystery(_Judge(RuntimeError("quota"))).has_reversal(QUESTION, ANECDOTE)
    assert not ok and "contrôle impossible" in reason


@pytest.mark.parametrize("raw, clean", [
    ("1. Le chien Robòt a mené Georges Ravidat à la grotte de Lascaux",
     "Le chien Robòt a mené Georges Ravidat à la grotte de Lascaux"),
    ("2) Pourquoi Poissons est jumelé à Avril ?", "Pourquoi Poissons est jumelé à Avril ?"),
    ("1864 : La barre des Écrins", "1864 : La barre des Écrins"),          # une date n'est pas un numéro
    ("11 novembre 1918 : Stenay", "11 novembre 1918 : Stenay"),
])
def test_list_number_is_stripped_from_title(raw, clean):
    brain = _mystery(_Judge({"title": raw}))
    title_vars = {k: "" for k in ("forced_region", "forced_category", "forced_format")}
    assert brain._write_title(title_vars, {"title": "X", "extract": "y"}) == clean


def test_eval_script_covers_the_ten_titles_of_the_run(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    from auracontent.core.brain import llm_client

    spec = importlib.util.spec_from_file_location("eval_reversal", Path("scripts/eval_reversal.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.CASES) == 10
    monkeypatch.setattr(llm_client.LLMClient, "create_default",
                        classmethod(lambda cls: _Judge({"garde_surprise": True, "raison": "ok"})))
    assert module.main([]) == 0
    assert "10/10 titre(s) passent le critère nouveau" in capsys.readouterr().out
