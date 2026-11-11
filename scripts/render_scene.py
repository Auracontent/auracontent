"""Script manuel : rend une scène à partir d'une vidéo pour juger le cadrage à l'œil.

    python -m scripts.render_scene            # utilise assets/shared/backgrounds/test_bg.mp4
    python -m scripts.render_scene clip.mp4    # ta propre vidéo
    python -m scripts.render_scene --map       # carte animée (Reims, Ajaccio, Saint-Denis de La Réunion)

Tout est hors ligne (voix = bip, sous-titres factices). Le mode --map habille la scène comme la vidéo
finale (sous-titres, crédit, filigrane, bandeau-titre) et extrait trois images dans output/map_preview/.
"""
import math
import os
import sys

import ffmpeg

from auracontent.channels.base_channel import load_channel_config
from auracontent.services.video.composer import Composer
from auracontent.services.visuals.map_scene import MapTarget, frame_count, map_settings, render_map_scene
from auracontent.utils.media_helpers import get_duration, is_video_file
from config.settings import OUTPUT_DIR

MAP_TEST_PLACES = [   # coordonnées fixes : aucun appel réseau
    ("reims", MapTarget(1, 49.2583, 4.0317, "Reims", "test")),
    ("ajaccio", MapTarget(1, 41.9192, 8.7386, "Ajaccio", "test")),
    ("saint_denis_reunion", MapTarget(1, -20.8789, 55.4481, "Saint-Denis", "test")),
]
MAP_DURATION = 6.2
MAP_PREVIEW_TIMES = (0.4, 3.0, 5.6)
MAP_HEADLINE = "EN 1825, UN TRÉSOR | DISPARAÎT ICI"

SCENE_DURATION = 6.0


def make_fake_voice(path: str, duration: float) -> None:
    """Génère une piste 'voix' (bip 440 Hz) pour ne pas dépendre du TTS."""
    (
        ffmpeg.input(f"sine=frequency=440:duration={duration}", f="lavfi")
        .output(path, ac=2, ar=48000)
        .run(overwrite_output=True, quiet=True)
    )


def make_fake_srt(path: str, duration: float) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"1\n00:00:00,000 --> 00:00:0{int(duration) - 1},000\nTest sous-titre vidéo\n")


def check(label: str, output: str | None) -> bool:
    if not output or not os.path.exists(output):
        print(f"❌ {label}: aucun fichier produit")
        return False
    probe = ffmpeg.probe(output)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    duration = get_duration(output)
    ok = (
        video["width"] == composer.video_width
        and video["height"] == composer.video_height
        and has_audio
        and abs(duration - SCENE_DURATION) < 0.5
    )
    print(
        f"{'✅' if ok else '⚠️ '} {label}: {output}\n"
        f"    {video['width']}x{video['height']}, {duration:.2f}s, audio={has_audio}"
    )
    return ok


def check_map_clip(label: str, path: str, duration: float, fps: int) -> bool:
    """Carte brute : 1080 x 1920, 30 i/s, durée de la scène à une image près, sans piste audio."""
    probe = ffmpeg.probe(path, count_frames=None)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    frames = int(video.get("nb_read_frames") or video.get("nb_frames") or 0)
    rate = eval(video["r_frame_rate"])   # « 30/1 »
    expected = frame_count(duration, fps)
    ok = (video["width"], video["height"]) == (1080, 1920) and abs(rate - fps) < 0.01 \
        and frames == expected and abs(frames / fps - duration) <= 1 / fps \
        and not any(s["codec_type"] == "audio" for s in probe["streams"])
    print(f"{'✅' if ok else '⚠️ '} carte {label}: {video['width']}x{video['height']}, {rate:g} i/s, "
          f"{frames} images ({frames / fps:.3f}s pour {duration}s)")
    return ok


def render_map_previews() -> bool:
    config = load_channel_config("mystery")
    composer = Composer(config.get("video_composer"), channel_name="mystery")
    fps = composer.fps
    preview_dir = os.path.join(str(OUTPUT_DIR), "map_preview")
    os.makedirs(preview_dir, exist_ok=True)
    voice = os.path.join(composer.temp_dir, "test_voice_map.wav")
    srt = os.path.join(composer.temp_dir, "test_subs_map.srt")
    make_fake_voice(voice, MAP_DURATION)
    with open(srt, "w", encoding="utf-8") as f:
        f.write(f"1\n00:00:00,500 --> 00:00:0{math.floor(MAP_DURATION) - 1},000\nTOUT COMMENCE ICI, EN 1825\n")

    results = []
    for name, target in MAP_TEST_PLACES:
        clip = os.path.join(composer.temp_dir, f"scene_map_{name}.mp4")
        if not render_map_scene(target, MAP_DURATION, clip, cfg=map_settings(config.get("visuals")), fps=fps):
            results.append(False)
            continue
        results.append(check_map_clip(name, clip, MAP_DURATION, fps))

        scene = {"id": f"map_{name}", "audio_path": voice, "duration": MAP_DURATION, "srt_path": srt,
                 "mood": "intriguing"}
        rendered = composer.process_scene(scene, (clip, clip))
        dressed = os.path.join(composer.temp_dir, f"map_{name}_dressed.mp4")
        if not rendered or not composer.add_watermark(rendered, dressed, headline=MAP_HEADLINE):
            print(f"❌ habillage {name} impossible")
            results.append(False)
            continue
        for t in MAP_PREVIEW_TIMES:
            png = os.path.join(preview_dir, f"{name}_{t:.1f}s.png")
            ffmpeg.input(dressed, ss=t).output(png, vframes=1).run(overwrite_output=True, quiet=True)
            print(f"    🖼️ {png}")
    return all(results)


if __name__ == "__main__":
    if "--map" in sys.argv[1:]:
        sys.exit(0 if render_map_previews() else 1)

    video_path = sys.argv[1] if len(sys.argv) > 1 else "assets/shared/backgrounds/test_bg.mp4"
    assert os.path.exists(video_path), f"Vidéo introuvable : {video_path}"
    assert is_video_file(video_path), f"Extension non reconnue comme vidéo : {video_path}"
    print(f"Source : {video_path} ({get_duration(video_path):.2f}s)")

    composer = Composer(channel_name="mystery")
    voice = os.path.join(composer.temp_dir, "test_voice.wav")
    srt = os.path.join(composer.temp_dir, "test_subs.srt")
    make_fake_voice(voice, SCENE_DURATION)
    make_fake_srt(srt, SCENE_DURATION)

    def scene(scene_id):
        return {"id": scene_id, "audio_path": voice, "duration": SCENE_DURATION,
                "srt_path": srt, "mood": "intriguing"}

    results = [
        # Cas 1 : la vidéo est la source de la scène (branche is_video_file)
        check("vidéo en source de scène",
              composer.process_scene(scene("video_src"), (video_path, video_path))),
        # Cas 2 : la vidéo est un fond continu (branche bg_video_path)
        check("vidéo en fond (bg_video_path)",
              composer.process_scene(scene("video_bg"), None,
                                     bg_video_path=video_path, bg_offset=3.0)),
    ]
    sys.exit(0 if all(results) else 1)
