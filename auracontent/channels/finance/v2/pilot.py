"""Vidéo pilote de la refonte V2 : « Abonnements cumulés », en 3 directions artistiques.

A : style actuel (gabarits génériques existants), animé : caméra douce, fondus, sous-titres mot par mot.
B : narration par objets et personnages (appli, étiquettes de prix, calendrier, ticket de caisse), graphique minimal.
C : même histoire que B, réalisation dynamique : gros plans sur les chiffres, rebonds, transitions marquées.

Tous les chiffres viennent de calc.py. Sans voix (aperçu local) : minutage des mots estimé.
Usage : python -m auracontent.channels.finance.v2.pilot --out output/pilote_v2 [--versions A,B,C]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import visuals as fvis

from . import captions, director, props
from .director import Shot

S = 1280 / 1080                     # pixels de sortie -> plan de conception du moteur
WPS = 2.7                           # mots prononcés par seconde (Rémy, -8 %), pour l'estimation sans voix
INK, T, GOLD, GRAY = props.INK, props.TURQUOISE, props.GOLD, props.GRAY
PARAMS = {"sub_1": 13.49, "sub_2": 9.99, "sub_3": 5.99, "sub_4": 0, "years": 5}
HYPO = "prix mensuels constants · sans hausse de tarif"
GROUND_Y = 1180                      # sol des personnages (px de sortie), au-dessus des sous-titres


def d(px: float) -> float:
    return px * S


def img(iid, path, x, y, w, t0=0.0, t1=99.0, keys=None, **kw) -> dict:
    return {"type": "image", "id": iid, "path": path, "x": d(x), "y": d(y), "w": d(w), "from": t0, "to": t1,
            "keys": keys or [], **kw}


def txt(tid, text, x, y, size, color=INK, font="hand", w=900, t0=0.0, t1=99.0, keys=None, **kw) -> dict:
    return {"type": "text", "id": tid, "text": text, "x": d(x), "y": d(y), "size": d(size), "color": color,
            "font": font, "w": d(w), "from": t0, "to": t1, "keys": keys or [], **kw}


def pop(t, ease="back", dur=0.35, scale=True) -> list[dict]:
    k = [{"t": t, "alpha": 0}, {"t": t + dur * 0.5, "alpha": 1}]
    if scale:
        k += [{"t": t, "scaleX": 0.4, "scaleY": 0.4}, {"t": t + dur, "scaleX": 1, "scaleY": 1, "ease": ease}]
    return k


def drop(t, y0, y1, ease="bounce", dur=0.7) -> list[dict]:
    return [{"t": t, "y": d(y0), "alpha": 0}, {"t": t + 0.08, "alpha": 1}, {"t": t + dur, "y": d(y1), "ease": ease}]


def slide_x(t, x0, x1, ease="out", dur=0.45) -> list[dict]:
    return [{"t": t, "x": d(x0), "alpha": 0}, {"t": t + 0.1, "alpha": 1}, {"t": t + dur, "x": d(x1), "ease": ease}]


def character(name: str, cx: float, height: float, t0=0.0, keys=None) -> dict:
    path = fvis.resolve(name)
    from PIL import Image
    w0, h0 = Image.open(path).size
    w = height * w0 / h0
    return img(name + str(cx), str(path), cx - w / 2, GROUND_Y - height, w, t0=t0, keys=keys)


def ground() -> dict:
    """Sol tracé à la main (trait), sans aplat : la zone des sous-titres reste dégagée."""
    return {"type": "path", "id": "ground", "x": d(60), "y": d(GROUND_Y), "w": d(860), "color": INK, "lineWidth": 6,
            "points": [[0, 0], [d(300), 3], [d(600), -2], [d(860), 1]], "from": 0, "to": 99, "keys": [], "role": "decor"}


# ---------- Script (texte affiché, texte prononcé pour la durée) ----------
SCRIPT = [
    ("hook", "Trois abonnements oubliés : 1 768 € en cinq ans.",
     "Trois abonnements oubliés : mille sept cent soixante-huit euros en cinq ans."),
    ("situation", "Hugo paie trois abonnements qu'il n'utilise presque plus.", None),
    ("mechanism", "13,49 € + 9,99 € + 5,99 € : 29,47 € chaque mois.",
     "Treize euros quarante-neuf, plus neuf euros quatre-vingt-dix-neuf, plus cinq euros quatre-vingt-dix-neuf : "
     "vingt-neuf euros quarante-sept chaque mois."),
    ("year", "Sur un an, 354 € quittent son compte.",
     "Sur un an, trois cent cinquante-quatre euros quittent son compte."),
    ("reveal", "Et en cinq ans : 1 768 €.", "Et en cinq ans : mille sept cent soixante-huit euros."),
    ("end", "Et toi, combien d'abonnements tu paies sans les regarder ?", None),
]


def timed_script(pace: float = 1.0) -> list[dict]:
    out = []
    for role, shown, spoken in SCRIPT:
        n = len((spoken or shown).replace("-", " ").split())
        dur = n / (WPS * pace) + 0.55
        out.append({"role": role, "text": shown, "duration": round(dur, 2),
                    "words": captions.estimate(shown, 0.2, dur - 0.45)})
    return out


# ---------- Plans des versions B et C (objets et personnages) ----------
def shots_objects(sc: list[dict], pdir: Path, c: fcalc.Calc, dyn: bool) -> list[Shot]:
    v = c.values
    m, tot = fcalc.fmt_number(v["total_month"].value), \
        fcalc.fmt_number(v["over_years"].value)
    tiles = [props.ensure("app-play", pdir), props.ensure("app-note", pdir), props.ensure("app-gym", pdir)]
    big_ease = "back" if dyn else "out"
    shots = []

    # 1. Accroche : les 3 applis tombent, puis le gros chiffre éclate
    s = sc[0]
    t_num = 0.35                     # accroche : le résultat d'abord, avant même que la voix le dise
    L = [img("burst", props.ensure("burst", pdir), 190, 560, 620, t0=t_num - 0.1, keys=pop(t_num - 0.1, "back", 0.5))]
    for i, p in enumerate(tiles):
        L.append(img(f"tile{i}", p, 130 + i * 250, 500, 190, keys=drop(0.05 + i * 0.18, 180, 500 + (i % 2) * 30)))
    L.append(txt("big", f"{tot} €", 205, 720, 200, INK, "ui", w=700, t0=t_num, keys=pop(t_num, big_ease, 0.45)))
    L.append(txt("sub", "en 5 ans", 360, 960, 90, INK, t0=t_num + 0.5, keys=pop(t_num + 0.5, "out", 0.3, False)))
    cam = [{"t": 0, "zoom": 1.0}, {"t": t_num, "zoom": 1.0}, {"t": t_num + 0.45, "zoom": 1.1, "cy": 880, "ease": "back"}] \
        if dyn else [{"t": 0, "zoom": 1.0}, {"t": s["duration"], "zoom": 1.05, "ease": "linear"}]
    shots.append(Shot(L, s["duration"], cam, "slideup" if dyn else "fade",
                      [{"at": 0.05 + i * 0.18 + 0.5, "file": "pop.wav", "gain": 0.3} for i in range(3)]
                      + [{"at": t_num, "file": "reveal.mp3", "gain": 0.45}]))

    # 2. Situation : Hugo et son téléphone, les applis sortent du téléphone
    s = sc[1]
    L = [ground(), character("hugo-smug.png", 300, 560),
         img("phone", props.ensure("phone", pdir), 600, 760, 220, keys=slide_x(0.1, 960, 600))]
    for i, p in enumerate(tiles):
        t = captions.find(s["words"], "trois", 0.6) + i * 0.25
        L.append(img(f"tileB{i}", p, 560 + i * 120, 560, 130, t0=t,
                     keys=[{"t": t, "y": d(800), "alpha": 0}, {"t": t + 0.1, "alpha": 1},
                           {"t": t + 0.5, "y": d(560 - (i % 2) * 40), "ease": "back"}]))
    t_plus = captions.find(s["words"], "presque", s["duration"] - 1)
    L.append(txt("zz", "... presque plus", 110, 500, 70, GRAY, t0=t_plus, keys=pop(t_plus, "out", 0.3, False)))
    cam = [{"t": 0, "zoom": 1.0}, {"t": s["duration"], "zoom": 1.08 if dyn else 1.04, "cx": 520, "ease": "linear"}]
    shots.append(Shot(L, s["duration"], cam, "circleopen" if dyn else "fade",
                      [{"at": captions.find(s["words"], "trois", 0.6) + i * 0.25 + 0.3, "file": "tap.wav", "gain": 0.3}
                       for i in range(3)]))

    # 3. Mécanisme : trois étiquettes s'additionnent
    s = sc[2]
    prices = [PARAMS["sub_1"], PARAMS["sub_2"], PARAMS["sub_3"]]
    L, sfx = [], []
    for i, pv in enumerate(prices):
        label = f"{fcalc.fmt_number(pv)} €"
        t = captions.find(s["words"], label.split()[0], 0.3 + i * 0.9)
        tag = props.ensure(f"tag{i}", pdir, lambda lab=label, i=i: props.price_tag(lab, f"tag{i}"))
        L.append(img(f"tagimg{i}", tag, 130, 520 + i * 150, 380, t0=t,
                     keys=slide_x(t, -420, 130, "back" if dyn else "out")))
        L.append(img(f"tilec{i}", tiles[i], 540, 525 + i * 150, 110, t0=t + 0.15, keys=pop(t + 0.15, "back", 0.3)))
        sfx.append({"at": t, "file": "tap.wav", "gain": 0.3})
    t_tot = captions.find(s["words"], "29", s["duration"] - 1.6)
    L.append({"type": "underline", "id": "sum", "x": d(130), "y": d(990), "w": d(560), "color": INK, "lineWidth": 7,
              "from": t_tot - 0.2, "to": 99, "keys": [{"t": t_tot - 0.2, "progress": 0}, {"t": t_tot + 0.1, "progress": 1}]})
    L.append({"type": "marker", "id": "mk", "x": d(130), "y": d(1035), "w": d(560), "h": d(110), "color": GOLD,
              "from": t_tot, "to": 99, "keys": [{"t": t_tot, "progress": 0}, {"t": t_tot + 0.35, "progress": 1}]})
    L.append(txt("tot", f"{m} € / mois", 150, 1010, 110, INK, "hand", w=700, t0=t_tot, keys=pop(t_tot, big_ease, 0.4)))
    sfx.append({"at": t_tot, "file": "chime.wav", "gain": 0.35})
    cam = [{"t": 0, "zoom": 1.0}, {"t": t_tot, "zoom": 1.0}, {"t": t_tot + 0.4, "zoom": 1.1, "cy": 900, "ease": "back"}] \
        if dyn else []
    shots.append(Shot(L, s["duration"], cam, "wipeleft" if dyn else "fade", sfx))

    # 4. Un an : le calendrier défile, le compteur monte
    s = sc[3]
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    t_count0, t_count1 = 0.3, max(1.6, captions.find(s["words"], "354", s["duration"] - 1.2))
    step = (t_count1 - t_count0) / 12
    L = []
    for i, mo in enumerate(months):
        p = props.ensure(f"cal{i}", pdir, lambda mo=mo, i=i: props.calendar(mo, f"cal{i}"))
        t = t_count0 + i * step
        L.append(img(f"cal{i}", p, 120, 560, 280, t0=t, t1=(t + step + 0.05) if i < 11 else 99,
                     keys=[{"t": t, "angle": -0.12, "alpha": 0.6}, {"t": t + min(0.18, step), "angle": 0, "alpha": 1}]))
    L.append(txt("cnt", "", 470, 600, 150, INK, "ui", w=520,
                 count={"from": 0, "to": v["total_year"].value, "t0": t_count0, "t1": t_count1, "template": "{n} €"}))
    L.append(txt("per", "par an", 520, 790, 80, GRAY))
    L += [ground(), character("hugo-shock.png", 700, 330, t0=t_count1, keys=pop(t_count1, "back", 0.3, False))]
    sfx = [{"at": t_count0 + i * step, "file": "tick.wav", "gain": 0.18} for i in range(12)]
    sfx.append({"at": t_count1, "file": "coins.wav", "gain": 0.4})
    cam = [{"t": 0, "zoom": 1.0}, {"t": s["duration"], "zoom": 1.06, "ease": "linear"}]
    shots.append(Shot(L, s["duration"], cam, "zoomin" if dyn else "fade", sfx))

    # 5. Révélation : le ticket de caisse sur 60 mois
    s = sc[4]
    lines = [f"mois {k}   −{m} €" for k in (1, 2, 3)] + ["   ..."] + [f"mois 60   −{m} €"]
    rec = props.ensure("receipt", pdir, lambda: props.receipt(lines, f"{tot} €"))
    t_tot = captions.find(s["words"], "1", 1.0)
    L = [img("rec", rec, 110, 480, 470, keys=[{"t": 0, "y": d(1300), "alpha": 0}, {"t": 0.1, "alpha": 1},
                                               {"t": 0.9, "y": d(480), "ease": "out"}]),
         ground(), character("hugo-shock.png", 760, 420, t0=0.5)]
    L.append({"type": "marker", "id": "mk5", "x": d(355), "y": d(885), "w": d(205), "h": d(70),
              "color": GOLD, "from": t_tot, "to": 99, "keys": [{"t": t_tot, "progress": 0}, {"t": t_tot + 0.3, "progress": 1}]})
    cam = [{"t": 0, "zoom": 1.0}, {"t": t_tot, "zoom": 1.0},
           {"t": t_tot + 0.5, "zoom": 1.12 if dyn else 1.06, "cx": 420, "cy": 880, "ease": "back" if dyn else "out"}]
    shots.append(Shot(L, s["duration"], cam, "radial" if dyn else "fade",
                      [{"at": 0.1, "file": "paper.wav", "gain": 0.35}, {"at": t_tot, "file": "impact.mp3", "gain": 0.4}]))

    # 6. Fin : question + signature, retour visuel aux applis (boucle)
    s = sc[5]
    L = [txt("q", "Et toi, combien ?", 110, 560, 120, INK, "ui", w=820, keys=pop(0.1, "back", 0.4)),
         img("qs", tiles[0], 150, 820, 150, keys=pop(0.4, "back", 0.3)),
         img("qs2", tiles[1], 330, 820, 150, keys=pop(0.55, "back", 0.3)),
         img("qs3", tiles[2], 510, 820, 150, keys=pop(0.7, "back", 0.3)),
         txt("sig", "Capital Simple", 150, 1030, 70, T, w=700, t0=0.9, keys=pop(0.9, "out", 0.3, False)),
         txt("hyp", HYPO, 150, 1110, 46, GRAY, w=780, t0=1.1)]
    shots.append(Shot(L, s["duration"], [], "fade", [{"at": 0.1, "file": "boing.wav", "gain": 0.25}]))
    return shots


# ---------- Plans de la version A (gabarits actuels, animés) ----------
def shots_current(sc: list[dict], c: fcalc.Calc) -> list[Shot]:
    tot = fcalc.fmt_number(c.values["over_years"].value)
    gentle = lambda dur: [{"t": 0, "zoom": 1.0}, {"t": dur, "zoom": 1.05, "ease": "linear"}]  # noqa: E731
    shots = []
    s = sc[0]
    t_num = 0.35                     # accroche : le résultat d'abord, avant même que la voix le dise
    L = [{"type": "marker", "id": "mk", "x": d(170), "y": d(790), "w": d(640), "h": d(70), "color": GOLD,
          "from": t_num + 0.3, "to": 99, "keys": [{"t": t_num + 0.3, "progress": 0}, {"t": t_num + 0.7, "progress": 1}]},
         txt("big", f"{tot} €", 180, 640, 190, INK, "ui", w=760, t0=t_num, keys=pop(t_num, "out", 0.4, False)),
         txt("sub", "3 abonnements oubliés · 5 ans", 180, 900, 70, GRAY, w=760)]
    shots.append(Shot(L, s["duration"], gentle(s["duration"]), "fade", [{"at": t_num, "file": "reveal.mp3", "gain": 0.4}]))
    plan = [("situation", "personnages"), ("mechanism", "barres"), ("year", "deux_courbes"), ("reveal", "deux_arbres")]
    for (role, template), s in zip(plan, sc[1:5], strict=True):
        layers = fvis.scene_layers("abonnements", PARAMS, {"role": role, "template": template, "visual": ""},
                                   s["duration"], hypothesis=HYPO)
        shots.append(Shot(layers, s["duration"], gentle(s["duration"]), "fade"))
    s = sc[5]
    layers = fvis.scene_layers("abonnements", PARAMS, {"role": "cta", "template": "carte_fin"}, s["duration"],
                               question="Et toi, combien d'abonnements tu paies sans les regarder ?")
    shots.append(Shot(layers, s["duration"], [], "fade"))
    return shots


# ---------- Rendu ----------
def render_version(name: str, out: Path) -> dict:
    t_start = time.time()
    c = fcalc.compute("abonnements", PARAMS)
    pace = 1.08 if name == "C" else 1.0
    sc = timed_script(pace)
    pdir = out / "props"
    shots = shots_current(sc, c) if name == "A" else shots_objects(sc, pdir, c, dyn=(name == "C"))
    overlap = 0.35 if name != "C" else 0.3
    scene_kwargs = {"background": props.PAPER, "grid": True, "fonts": {k: str(v) for k, v in fvis.FONTS.items()},
                    "asset_dirs": [str(p) for p in fvis.ASSET_DIRS]}
    work = out / f"version_{name}"
    clips = [director.render_shot(sh, scene_kwargs, work / f"plan_{i + 1}.mp4") for i, sh in enumerate(shots)]
    t0 = director.starts(shots, overlap)
    words = [captions.Word(w.text, w.start + t0[i], w.end + t0[i]) for i, s in enumerate(sc) for w in s["words"]]
    total = t0[-1] + shots[-1].duration
    ass = work / "sous_titres.ass"
    ass.write_text(captions.build_ass(words, bandeau=("3 ABONNEMENTS OUBLIÉS", f"{fcalc.fmt_number(c.values['over_years'].value)} € EN 5 ANS"),
                                      total=total), encoding="utf-8")
    final = director.assemble(clips, shots, out / f"pilote_{name}.mp4", overlap=overlap, ass=ass)
    return {"version": name, "fichier": str(final), "duree_s": round(total, 1),
            "rendu_s": round(time.time() - t_start, 1), "taille_mo": round(final.stat().st_size / 1e6, 2),
            "plans": len(shots)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/pilote_v2")
    ap.add_argument("--versions", default="A,B,C")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = [render_version(v.strip(), out) for v in args.versions.split(",")]
    (out / "rapport.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in report:
        print(f"🎬 Version {r['version']} : {r['duree_s']} s, rendue en {r['rendu_s']} s, {r['taille_mo']} Mo -> {r['fichier']}")


if __name__ == "__main__":
    main()
