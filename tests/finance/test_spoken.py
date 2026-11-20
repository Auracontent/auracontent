"""Nombres en toutes lettres et texte parlé de la chaîne finance (produits par le code, jamais par le LLM)."""
import pytest
from auracontent.channels.finance.spoken import SpokenError, display_text, int_to_words, spoken_text


@pytest.mark.parametrize("n, words", [
    (0, "zéro"), (1, "un"), (16, "seize"), (21, "vingt et un"), (71, "soixante et onze"), (72, "soixante-douze"),
    (80, "quatre-vingts"), (81, "quatre-vingt-un"), (91, "quatre-vingt-onze"), (100, "cent"), (180, "cent quatre-vingts"),
    (200, "deux cents"), (201, "deux cent un"), (1000, "mille"), (1630, "mille six cent trente"),
    (23800, "vingt-trois mille huit cents"), (80000, "quatre-vingt mille"), (200000, "deux cent mille"),
    (1_000_000, "un million"), (2_500_000, "deux millions cinq cent mille"),
])
def test_int_to_words(n, words):
    assert int_to_words(n) == words


def test_display_text_formats_numbers():
    assert display_text("10000 € et 6.1 ans, 1630 €") == "10 000 € et 6,1 ans, 1 630 €"
    assert display_text("10 000 €") == "10 000 €"


@pytest.mark.parametrize("text, spoken", [
    ("72 divisé par 4 = 18 ans.", "soixante-douze divisé par quatre égale dix-huit ans."),
    ("Léa a 2 100 € et Hugo 1630 €.", "Léa a deux mille cent euros et Hugo mille six cent trente euros."),
    ("6 %/an pendant 6,1 ans", "six pour cent par an pendant six virgule un ans"),
    ("0,5 % de frais", "zéro virgule cinq pour cent de frais"),
    ("50 €/mois, 1 €.", "cinquante euros par mois, un euro."),
    ("2 000 000 €", "deux millions d'euros"),
])
def test_spoken_text(text, spoken):
    assert spoken_text(text) == spoken


def test_spoken_never_keeps_symbols():
    with pytest.raises(SpokenError):
        spoken_text("72 & 4")
