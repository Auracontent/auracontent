"""Tendances YouTube : service partagé, configuré par chaîne, sans effet sans clé."""
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from auracontent.services.trends import youtube

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """API simulée : 3 vidéos, dont une trop longue et une d'une grosse chaîne."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def get(self, url, params, timeout):
        self.calls.append((url.rsplit("/", 1)[-1], params))
        if self.fail:
            raise RuntimeError("quota dépassé")
        kind = url.rsplit("/", 1)[-1]
        if kind == "search":
            return FakeResponse({"items": [{"id": {"videoId": v}} for v in ("a", "b", "c")]})
        if kind == "videos":
            def vid(i, title, ch, views, dur):
                return {"id": i, "snippet": {"title": title, "channelId": ch, "channelTitle": ch.upper(),
                                             "publishedAt": "2026-11-10T00:00:00Z"},
                        "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": dur}}
            return FakeResponse({"items": [vid("a", "Le vrai prix du paiement en 4 fois", "petite", 200_000, "PT45S"),
                                           vid("b", "Mes abonnements oubliés", "grosse", 900_000, "PT50S"),
                                           vid("c", "Vlog de 10 minutes", "petite2", 500_000, "PT10M")]})
        return FakeResponse({"items": [{"id": "petite", "statistics": {"subscriberCount": "2000"}},
                                       {"id": "grosse", "statistics": {"subscriberCount": "3000000"}},
                                       {"id": "petite2", "statistics": {"subscriberCount": "100"}}]})


@pytest.fixture(autouse=True)
def _no_cache():
    youtube._CACHE.clear()
    yield
    youtube._CACHE.clear()


CFG = {"queries": ["astuce argent"], "min_views": 1000, "top": 5}


def test_sans_cle_ni_section_rien_ne_change(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    s = FakeSession()
    assert youtube.fetch(CFG, session=s) == [] and s.calls == []
    assert youtube.fetch(None, api_key="k", session=s) == []
    assert youtube.fetch({**CFG, "enabled": False}, api_key="k", session=s) == []
    assert youtube.trends_block(None) == ""


def test_classement_par_surperformance_et_shorts_seulement():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    vids = youtube.fetch(CFG, api_key="k", session=FakeSession(), now=now)
    assert [v.video_id for v in vids] == ["a", "b"]                  # « c » trop long (10 min) écarté
    assert vids[0].score == pytest.approx(100.0)                    # 200 000 vues / 2 000 abonnés
    assert vids[1].score < 1                                        # grosse chaîne : peu de surperformance


def test_une_seule_interrogation_par_run():
    s = FakeSession()
    youtube.fetch(CFG, api_key="k", session=s)
    n = len(s.calls)
    youtube.fetch(CFG, api_key="k", session=s)
    assert len(s.calls) == n


def test_erreur_api_jamais_bloquante():
    assert youtube.fetch(CFG, api_key="k", session=FakeSession(fail=True)) == []


def test_bloc_avec_consigne_de_la_chaine_et_interdiction_de_copier():
    vids = youtube.fetch(CFG, api_key="k", session=FakeSession())
    text = youtube.block(vids, {**CFG, "usage": "Consigne propre à la chaîne."})
    assert "ne copie jamais" in text and "Consigne propre à la chaîne." in text
    assert "Le vrai prix du paiement en 4 fois" in text
    assert youtube.block([], CFG) == ""


@pytest.mark.parametrize("channel", ["finance", "mystery"])
def test_chaque_chaine_a_sa_configuration(channel):
    cfg = yaml.safe_load((ROOT / "config" / "channels" / f"{channel}.yaml").read_text(encoding="utf-8"))
    t = cfg["trends"]
    assert t["queries"] and t["usage"] and t["language"] == "fr"
    assert len(t["queries"]) <= youtube.settings(t)["max_queries"]       # quota : au plus 6 x 100 unités


def test_prompts_contiennent_le_bloc_quand_il_existe(monkeypatch):
    """finance : {trends} dans le prompt des candidats ; mystery : ajouté au bloc d'informations des titres."""
    text = (ROOT / "auracontent" / "channels" / "finance" / "prompts" / "candidates.md").read_text(encoding="utf-8")
    assert "{trends}" in text
    src = (ROOT / "auracontent" / "channels" / "mystery" / "brain.py").read_text(encoding="utf-8")
    assert "youtube_trends.trends_block(self.config.get(\"trends\"))" in src
