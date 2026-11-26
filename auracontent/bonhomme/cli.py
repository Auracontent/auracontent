"""Épisode « expliqué par un bonhomme » (Capital Simple), de plan.json à la vidéo finale.

    uv run python -m auracontent.bonhomme.cli episodes/bonhomme suite      # la suite promise par le dernier épisode
    uv run python -m auracontent.bonhomme.cli <épisode> check              # contrôle du plan, des repères, de la suite
    uv run python -m auracontent.bonhomme.cli <épisode> voice              # voix de Rémy (Edge TTS) -> voice/
    uv run python -m auracontent.bonhomme.cli <épisode> voice --preview    # minutage estimé, sans réseau (jamais publié)
    uv run python -m auracontent.bonhomme.cli <épisode> stills             # planche de contrôle -> stills.jpg
    uv run python -m auracontent.bonhomme.cli <épisode> render             # vidéo -> out/<slug>.mp4
    uv run python -m auracontent.bonhomme.cli <épisode> upload             # vidéo + légende -> Hugging Face (publisher)

<épisode> est un dossier qui contient plan.json (voir docs/finance_bonhomme.md et episodes/bonhomme/_exemple/).
La voix (auracontent.actu.voice), la musique (auracontent.actu.score) et la publication sont celles de Capital Simple.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from auracontent.actu import score, voice
from auracontent.archive.timeline import FPS, LEAD_IN, load

from . import plan as plan_mod
from .frames import Renderer, stills_times

END_CARD = 3.0


def _load_plan(ep: Path) -> dict:
    return json.loads((ep / "plan.json").read_text(encoding="utf-8"))


def _timeline(ep: Path):
    tl = load(ep)
    tl.plan.setdefault("end_card_seconds", END_CARD)
    return tl, Renderer(ep, tl)


def _in_series(ep: Path) -> bool:
    return ep.parent.name == "bonhomme" and ep.name != "_exemple"


def suite(root: Path) -> str:
    pending = plan_mod.pending_promise(root)
    if not pending:
        msg = "   aucune suite promise : sujet libre"
    else:
        msg = f"   suite promise par {pending[0]} : « {pending[1]} »  ->  \"suite_de\": \"{pending[0]}\""
    print(msg)
    return msg


def check(ep: Path) -> None:
    plan = _load_plan(ep)
    plan_mod.validate(plan)
    if _in_series(ep):
        errs = plan_mod.check_suite(plan, ep.parent, ep.name)
        if errs:
            raise plan_mod.PlanError("suite des épisodes :\n  - " + "\n  - ".join(errs))
    if (ep / "voice" / "timing.json").exists():
        tl, _r = _timeline(ep)
        errs = plan_mod.check_refs(plan, tl)
        if errs:
            raise plan_mod.PlanError("repères de temps introuvables :\n  - " + "\n  - ".join(errs))
    print("   plan valide")


def stills(ep: Path) -> Path:
    check(ep)
    _tl, r = _timeline(ep)
    ts = stills_times(r)
    vertical = r.H > r.W
    tw, th, per_row = (270, 480, 8) if vertical else (480, 270, 4)
    ims = [Image.fromarray(r.frame(int(t * FPS))).resize((tw, th)) for t in ts]
    sheet = Image.new("RGB", (tw * per_row, th * ((len(ims) + per_row - 1) // per_row)))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % per_row) * tw, (i // per_row) * th))
    out = ep / "stills.jpg"
    sheet.save(out, quality=82)
    (ep / "stills_times.json").write_text(json.dumps(ts))
    print(f"   planche : {out} ({len(ims)} images, temps dans stills_times.json)")
    return out


def _render_part(args):
    episode, a, b, path = args
    tl, r = _timeline(Path(episode))
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{r.W}x{r.H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "18", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for fi in range(a, min(b, tl.nframes)):
        p.stdin.write(r.frame(fi).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg a échoué sur {path}")
    return path


def cues(r: Renderer) -> list[tuple[float, str, float]]:
    """Bruitages : papier à chaque scène, pop sur chaque élément qui arrive, pièces sur les compteurs."""
    tl, out = r.tl, []
    for i, s in enumerate(r.scenes):
        if i:
            out.append((s["t0"], "paper.wav", 0.25))
        typ = s["type"]
        if typ == "accroche" and s.get("carte"):
            out.append((r.at(s, s.get("carte_at"), 1.2), "pop.wav", 0.3))
        elif typ == "compteur":
            out.append((r.at(s, s.get("count_at"), 0.4), "coins.wav", 0.3))
        elif typ in ("notifications", "liste"):
            ats = [tl.t(a) for a in s["at"]] if s.get("at") else \
                [s["t0"] + (0.6 + 0.7 * k if typ == "notifications" else 0.5 + 1.2 * k) for k in range(len(s["items"]))]
            out += [(a, "tap.wav" if typ == "notifications" else "pop.wav", 0.3) for a in ats]
        elif typ == "choix" and "pick" in s:
            out.append((r.at(s, s.get("pick_at"), 4.0), "draw.wav", 0.3))
        elif typ == "repartition":
            for k, p in enumerate(s["parts"]):
                a = r.at(s, p.get("at"), 0.8 + 1.4 * k)
                out.append((a, "pop.wav", 0.25))
                if p.get("bocal"):
                    out.append((a + 0.7, "fill.wav", 0.25))
        elif typ == "fin":
            out.append((s["t0"] + 0.9, "chime.wav", 0.35))
        for re_ in (s.get("bonhomme") or {}).get("reactions", []):
            if re_.get("hop"):
                out.append((tl.t(re_["at"]), "boing.wav", 0.2))
    return out


def render(ep: Path, workers: int | None = None) -> Path:
    check(ep)
    tl, r = _timeline(ep)
    work = ep / "build"
    work.mkdir(exist_ok=True)
    mix = score.build(ep, tl.dur, LEAD_IN, cues(r), tl.plan.get("mood", "calme"))
    workers = workers or max(1, min(4, os.cpu_count() or 2))
    n = tl.nframes
    q = (n + workers - 1) // workers
    jobs = [(str(ep), i * q, (i + 1) * q, str(work / f"part{i}.mp4")) for i in range(workers)]
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(_render_part, jobs))
    (work / "parts.txt").write_text("".join(f"file '{Path(p).name}'\n" for p in parts))
    slug = re.sub(r"[^\w-]+", "-", tl.plan.get("slug") or ep.name).strip("-")
    out = ep / "out"
    out.mkdir(exist_ok=True)
    final = out / f"{slug}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(work / "parts.txt"),
                    "-i", str(mix), "-map", "0:v", "-map", "1:a", "-t", f"{n / FPS:.3f}", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(final)], check=True)
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v", "-show_entries",
                             "stream=nb_read_packets", "-of", "csv=p=0", str(final)], capture_output=True,
                            text=True).stdout.strip()
    if not frames.isdigit() or abs(int(frames) - n) > 2:
        raise RuntimeError(f"vidéo incomplète : {frames} images sur {n}")
    for p in parts:
        Path(p).unlink(missing_ok=True)
    print(f"   vidéo : {final} ({tl.dur:.1f} s, {frames} images, {r.W}x{r.H})")
    return final


def caption(plan: dict, channel: str = "finance") -> str:
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.publishing.caption import apply_caption_footer, apply_hashtag_rules

    cfg = load_channel_config(channel).get("publish", {})
    text = plan["caption"]
    if plan.get("sources"):
        text += "\n\nSources : " + " ; ".join(s["name"] for s in plan["sources"].values())
    text = apply_caption_footer(text, cfg.get("caption_footer"))
    return apply_hashtag_rules(text, cfg.get("brand_hashtag"), cfg.get("banned_hashtags", ()))


def upload(ep: Path, channel: str = "finance") -> str:
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.publishing.hf_storage import upload_video

    plan = _load_plan(ep)
    plan_mod.validate(plan)
    timing = json.loads((ep / "voice" / "timing.json").read_text(encoding="utf-8"))
    if timing.get("source") == "estimée":
        raise RuntimeError("voix estimée (--preview) : relancer « voice » sans --preview avant de publier")
    videos = sorted((ep / "out").glob("*.mp4"))
    if not videos:
        raise RuntimeError("aucune vidéo dans out/ : lancer render d'abord")
    cfg = load_channel_config(channel).get("publish", {})
    return upload_video(str(videos[-1]), plan["title"], cfg["hf_repo"], cfg.get("hf_folder", channel),
                        caption(plan, channel))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", type=Path)
    ap.add_argument("step", choices=["suite", "check", "voice", "stills", "render", "upload"])
    ap.add_argument("--preview", action="store_true", help="voice : minutage estimé, sans réseau (jamais publié)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--channel", default="finance", help="chaîne dont la section publish sert à l'upload")
    a = ap.parse_args(argv)
    ep = a.episode.resolve()
    if a.step == "suite":
        suite(ep)
        return 0
    if not (ep / "plan.json").exists():
        print(f"plan.json introuvable dans {ep}", file=sys.stderr)
        return 2
    try:
        if a.step == "check":
            check(ep)
        elif a.step == "voice":
            plan_mod.validate(_load_plan(ep))
            voice.build(ep, preview=a.preview)
        elif a.step == "stills":
            stills(ep)
        elif a.step == "render":
            render(ep, a.workers)
        else:
            print("   déposé :", upload(ep, a.channel))
    except plan_mod.PlanError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
