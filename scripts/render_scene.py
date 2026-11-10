"""Script manuel : rend une scène à partir d'une vidéo pour juger le cadrage à l'œil.

    python -m scripts.render_scene            # utilise assets/shared/backgrounds/test_bg.mp4
    python -m scripts.render_scene clip.mp4    # ta propre vidéo
"""
import os
import sys

import ffmpeg

from auracontent.services.video.composer import Composer
from auracontent.utils.media_helpers import get_duration, is_video_file

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


if __name__ == "__main__":
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
