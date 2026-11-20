"""Short d'archives, de plan.json à la vidéo finale.

    uv run python -m auracontent.archive.cli <épisode> fetch     # archives Commons -> img/
    uv run python -m auracontent.archive.cli <épisode> voice     # voix Gemini dirigée -> voice/
    uv run python -m auracontent.archive.cli <épisode> stills    # planche de contrôle -> stills.jpg
    uv run python -m auracontent.archive.cli <épisode> render    # vidéo -> out/<slug>.mp4
    uv run python -m auracontent.archive.cli <épisode> all       # fetch + voice + stills + render
    uv run python -m auracontent.archive.cli <épisode> upload    # vidéo + légende -> Hugging Face (publisher)

<épisode> est un dossier contenant plan.json (voir docs/archive_shorts.md et episodes/archive/_exemple/).
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

from . import commons, score, voice
from .frames import Renderer
from .timeline import FPS, H, W, load


def _render_part(args):
    episode, a, b, path = args
    tl = load(Path(episode)); r = Renderer(Path(episode), tl)
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                          "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for fi in range(a, min(b, tl.nframes)):
        p.stdin.write(r.frame(fi).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg a échoué sur {path}")
    return path


def stills(episode: Path) -> Path:
    tl = load(episode); r = Renderer(episode, tl)
    ts = [1.5] + [(s["t0"] + min(s["t1"], tl.dur)) / 2 for s in r.shots] + [x[1] + 0.3 for x in r.stamps] + [tl.dur - 1]
    ts = sorted(min(tl.dur - 0.05, x) for x in ts)
    ims = [Image.fromarray(r.frame(int(t * FPS))).resize((270, 480)) for t in ts]
    sheet = Image.new("RGB", (270 * 8, 480 * ((len(ims) + 7) // 8)))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % 8) * 270, (i // 8) * 480))
    out = episode / "stills.jpg"; sheet.save(out, quality=82)
    (episode / "stills_times.json").write_text(json.dumps([round(t, 2) for t in ts]))
    print(f"   planche : {out} ({len(ims)} images, temps dans stills_times.json)")
    return out


def render(episode: Path, workers: int | None = None) -> Path:
    tl = load(episode); r = Renderer(episode, tl)
    work = episode / "build"; work.mkdir(exist_ok=True)
    mix = score.build(episode, tl, [s["t0"] for s in r.shots], [x[1] for x in r.stamps])
    workers = workers or max(1, min(4, (os.cpu_count() or 2)))
    n = tl.nframes; q = (n + workers - 1) // workers
    jobs = [(str(episode), i * q, (i + 1) * q, str(work / f"part{i}.mp4")) for i in range(workers)]
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(_render_part, jobs))
    (work / "parts.txt").write_text("".join(f"file '{Path(p).name}'\n" for p in parts))
    slug = re.sub(r"[^\w-]+", "-", tl.plan.get("slug") or episode.name).strip("-")
    out = episode / "out"; out.mkdir(exist_ok=True); final = out / f"{slug}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(work / "parts.txt"), "-i", str(mix),
                    "-map", "0:v", "-map", "1:a", "-af", "apad", "-t", f"{n / FPS:.3f}", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)],
                   check=True)
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v", "-show_entries",
                             "stream=nb_read_packets", "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout.strip()
    if not frames.isdigit() or abs(int(frames) - n) > 2:
        raise RuntimeError(f"vidéo incomplète : {frames} images sur {n}")
    for p in parts:
        Path(p).unlink(missing_ok=True)
    print(f"   vidéo : {final} ({tl.dur:.1f} s, {frames} images)")
    return final


def upload(episode: Path, channel: str) -> str:
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.services.publishing.caption import apply_hashtag_rules
    from auracontent.services.publishing.hf_storage import upload_video

    plan = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    videos = sorted((episode / "out").glob("*.mp4"))
    if not videos:
        raise RuntimeError("aucune vidéo dans out/ : lancer render d'abord")
    cfg = load_channel_config(channel).get("publish", {})
    caption = plan.get("caption") or f"{plan.get('title', '')} {cfg.get('fallback_hashtags', '')}".strip()
    caption = apply_hashtag_rules(caption, cfg.get("brand_hashtag"), cfg.get("banned_hashtags", ()))
    return upload_video(str(videos[-1]), plan.get("title") or episode.name, cfg["hf_repo"], cfg.get("hf_folder", channel), caption)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("episode", type=Path)
    ap.add_argument("step", choices=["fetch", "voice", "stills", "render", "all", "upload"])
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--channel", default="mystery", help="chaîne dont la section publish sert à l'upload")
    a = ap.parse_args(argv)
    ep = a.episode.resolve()
    if not (ep / "plan.json").exists():
        print(f"plan.json introuvable dans {ep}", file=sys.stderr); return 2
    steps = ["fetch", "voice", "stills", "render"] if a.step == "all" else [a.step]
    for s in steps:
        print(f"▶ {s}")
        if s == "fetch":
            commons.fetch(ep)
        elif s == "voice":
            voice.build(ep)
        elif s == "stills":
            stills(ep)
        elif s == "upload":
            upload(ep, a.channel)
        else:
            render(ep, a.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
