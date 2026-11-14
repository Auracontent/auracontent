"""Prévisualisation des scènes dessinées de Capital Simple (sans LLM, sans voix, sans réseau).

    python scripts/preview_finance.py arbres                       # 4 images + planche dans output/finance_preview
    python scripts/preview_finance.py arbres --mp4                 # + la scène en MP4
    python scripts/preview_finance.py arbres --compare <vidéo>     # planche côte à côte avec la vidéo test
    python scripts/preview_finance.py arbres --overlay             # bandeau et sous-titre simulés (Poppins)

Ne touche pas à scripts/render_scene.py (mystery). Les contrôles de mise en page sont bloquants : une scène
refusée affiche ses motifs et le script s'arrête.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from auracontent.channels.finance import visuals
from auracontent.services.visuals.linework.engine import Painter, render_mp4
from auracontent.services.visuals.linework.layout import LayoutError
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "finance_preview"
DEMO = {"arbres": dict(params={"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount": 300,
                               "late_amount_factor": 3, "rate": 7, "end_age": 65},
                       times=(0.65, 1.95, 4.35, 6.45), ref_start=16.95,
                       headline=("100 € À 20 ANS", "BATTENT 300 € À 40"),
                       subtitles=("Pourtant, à 65 ans,", "Hugo a environ 1 630 euros.", "Léa ? Environ 2 100.",
                                  "Léa ? Environ 2 100."))}


def overlay(img: Image.Image, headline: tuple[str, str], subtitle: str) -> Image.Image:
    """Simulation du bandeau (encre puis punchline noire sur or) et d'un sous-titre, comme le compositeur."""
    img = img.copy()
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(visuals.ASSETS / "fonts" / "Poppins-Bold.ttf"), 64)
    y = 230
    d.text((70, y), headline[0], font=font, fill="#1A1A1A")
    w = font.getlength(headline[1])
    d.rectangle([60, y + 92, 80 + w, y + 92 + 86], fill="#E0A526")
    d.text((70, y + 98), headline[1], font=font, fill="#1A1A1A")
    sub = ImageFont.truetype(str(visuals.ASSETS / "fonts" / "Poppins-Bold.ttf"), 54)
    tw = sub.getlength(subtitle)
    d.text(((img.width - tw) / 2, 1300), subtitle, font=sub, fill="#1A1A1A", stroke_width=4, stroke_fill="#F7F3EA")
    return img


def sheet(rows: list[list[Image.Image]], target: Path, labels: list[str]) -> Path:
    w, h = rows[0][0].size
    canvas = Image.new("RGB", (len(rows[0]) * (w + 20), len(rows) * (h + 90)), "white")
    d = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(visuals.ASSETS / "fonts" / "Poppins-Bold.ttf"), 60)
    for r, row in enumerate(rows):
        d.text((20, r * (h + 90) + 10), labels[r], font=font, fill="#1A1A1A")
        for i, im in enumerate(row):
            canvas.paste(im.convert("RGB"), (i * (w + 20), r * (h + 90) + 85))
    canvas.thumbnail((2400, 2400))
    canvas.save(target)
    return target


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", choices=sorted(DEMO))
    ap.add_argument("--mp4", action="store_true")
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--compare", type=Path)
    args = ap.parse_args(argv)
    demo = DEMO[args.scene]
    try:
        scene = visuals.lea_hugo_trees(demo["params"])
    except LayoutError as e:
        print(f"❌ {e}")
        return 1
    print(f"✅ Mise en page acceptée : {len(scene.layers)} calques, {scene.duration} s.")
    OUT.mkdir(parents=True, exist_ok=True)
    painter = Painter(scene)
    frames = []
    for t, sub in zip(demo["times"], demo["subtitles"], strict=True):
        im = painter.frame(t)
        if args.overlay:
            im = overlay(im, demo["headline"], sub)
        im.save(OUT / f"{args.scene}_{t:.2f}.png")
        frames.append(im)
    rows, labels = [frames], ["Capital Simple (Pillow)" + (" + bandeau et sous-titre simulés" if args.overlay else "")]
    if args.compare:
        with tempfile.TemporaryDirectory() as tmp:
            refs = []
            for t in demo["times"]:
                png = Path(tmp) / f"{t}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(demo["ref_start"] + t), "-i",
                                str(args.compare), "-frames:v", "1", str(png)], check=True)
                refs.append(Image.open(png).copy())
        rows.insert(0, refs)
        labels.insert(0, "Vidéo test (référence)")
    print(f"🖼️ Planche : {sheet(rows, OUT / f'{args.scene}_planche.png', labels)}")
    if args.mp4:
        print(f"🎬 {render_mp4(scene, OUT / f'{args.scene}.mp4')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
