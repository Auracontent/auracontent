"""Script manuel : rend une scène à partir d'une vidéo pour juger le cadrage à l'œil.

    python -m scripts.render_scene            # utilise assets/shared/backgrounds/test_bg.mp4
    python -m scripts.render_scene clip.mp4    # ta propre vidéo
    python -m scripts.render_scene --map       # carte animée (Reims, Ajaccio, Saint-Denis de La Réunion)
    python -m scripts.render_scene --qualite   # ouverture en plans de 3 s, paysage plein écran, carte + repère

Tout est hors ligne (voix = bip, sous-titres factices). Le mode --map habille la scène comme la vidéo
finale (sous-titres, crédit, filigrane, bandeau-titre) et extrait trois images dans output/map_preview/.
"""
import glob
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
    ("reims", MapTarget(1, 49.2583, 4.0317, "Reims", "test")),           # avec l'accroche de marque
    ("ajaccio", MapTarget(1, 41.9192, 8.7386, "Ajaccio", "test")),
    ("saint_denis_reunion", MapTarget(1, -20.8789, 55.4481, "Saint-Denis", "test")),
]
MAP_DURATION = 6.2
MAP_PREVIEW_TIMES = (0.4, 3.0, 5.6)
MAP_HEADLINE = "EN 1825, UN TRÉSOR | DISPARAÎT ICI"
MAP_TAGLINE = "C’EST ARRIVÉ ICI"   # visuals.map_scene.tagline (facultatif) : montré sur le premier lieu

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


def check_watermark_clear_of_headline(composer: Composer) -> bool:
    """Le filigrane (en haut à gauche) doit finir au-dessus du bandeau-titre."""
    from PIL import Image

    if not (composer.watermark_path and os.path.exists(composer.watermark_path)):
        print("❌ filigrane introuvable")
        return False
    with Image.open(composer.watermark_path) as logo:
        height = composer.watermark_width * logo.height / logo.width
    bottom = composer.watermark_y + height
    ok = bottom < composer.headline_y
    print(f"{'✅' if ok else '❌'} filigrane {os.path.basename(composer.watermark_path)} : "
          f"y {composer.watermark_y} à {bottom:.0f}, bandeau à partir de y {composer.headline_y}")
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

    results = [check_watermark_clear_of_headline(composer)]
    for i, (name, target) in enumerate(MAP_TEST_PLACES):
        clip = os.path.join(composer.temp_dir, f"scene_map_{name}.mp4")
        cfg = map_settings(config.get("visuals"))
        if i == 0:
            cfg["tagline"] = MAP_TAGLINE
        if not render_map_scene(target, MAP_DURATION, clip, cfg=cfg, fps=fps):
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


QUALITY_HEADLINE = "EN 1791 | L'ABBAYE EST VENDUE"
QUALITY_OPENING = 7.0       # scène 1 : 3 plans de 2,33 s (3 s au plus)
# Lieu d'essai quelconque (aucune règle propre à un sujet) : abbaye de Fontenay, commune de Marmagne
QUALITY_MAP = MapTarget(1, 47.6392, 4.3889, "Abbaye de Fontenay", "test", sublabel="Marmagne")
QUALITY_MAP_DURATION = 6.0


def _landscape_from(path: str, out: str) -> str:
    """Bande paysage (16:9) découpée dans une image locale verticale : photo d'essai hors ligne."""
    from PIL import Image

    with Image.open(path) as img:
        w = img.width
        h = w * 9 // 16
        top = (img.height - h) // 2
        img.crop((0, top, w, top + h)).convert("RGB").save(out, quality=92)
    return out


def render_quality_previews() -> bool:
    """Ouverture (3 plans plein écran, panoramique sur les paysages) et carte avec repère, habillées comme
    la vidéo finale. Trois images dans output/quality_preview/ pour la pull request."""
    from PIL import Image

    config = load_channel_config("mystery")
    composer = Composer(config.get("video_composer"), channel_name="mystery")
    out_dir = os.path.join(str(OUTPUT_DIR), "quality_preview")
    os.makedirs(out_dir, exist_ok=True)
    images = sorted(glob.glob(os.path.join("assets", "shared", "images", "fallback_*.jpg")))
    shots = [_landscape_from(images[0], os.path.join(composer.temp_dir, "q_landscape_1.jpg")), images[1],
             _landscape_from(images[2], os.path.join(composer.temp_dir, "q_landscape_2.jpg"))]
    voice = os.path.join(composer.temp_dir, "q_voice.wav")
    srt = os.path.join(composer.temp_dir, "q_subs.srt")
    make_fake_voice(voice, QUALITY_OPENING)
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,300 --> 00:00:03,000\nEN 1791, LES MOINES PARTENT\n\n"
                "2\n00:00:03,000 --> 00:00:06,500\nL'ABBAYE EST VENDUE\n")
    results = []
    max_shot = float(config["video_composer"]["shots"]["first_scene_max_seconds"])
    frames = Composer.shot_frames(QUALITY_OPENING, max_shot, composer.fps)
    ok = max(frames) / composer.fps <= max_shot
    print(f"{'✅' if ok else '❌'} ouverture : {len(frames)} plans de {max(frames) / composer.fps:.2f} s au plus "
          f"(limite {max_shot} s)")
    results.append(ok)

    scene = {"id": "q_opening", "audio_path": voice, "duration": QUALITY_OPENING, "srt_path": srt, "mood": "tense"}
    rendered = composer.process_scene(scene, {"shots": shots, "max_shot": max_shot})
    dressed = os.path.join(composer.temp_dir, "q_opening_dressed.mp4")
    if not rendered or not composer.add_watermark(rendered, dressed, headline=QUALITY_HEADLINE):
        print("❌ ouverture : rendu impossible")
        return False
    duration = get_duration(dressed)
    results.append(abs(duration - QUALITY_OPENING) < 0.6)
    print(f"{'✅' if results[-1] else '❌'} ouverture : {duration:.2f} s pour {QUALITY_OPENING} s de voix")
    previews = []
    for name, t in (("1_ouverture_paysage_plein_ecran", 1.2), ("2_ouverture_plan_suivant", 3.6)):
        png = os.path.join(out_dir, f"{name}.png")
        ffmpeg.input(dressed, ss=t).output(png, vframes=1).run(overwrite_output=True, quiet=True)
        previews.append(png)

    # plein écran : la première et la dernière ligne de l'image ne sont pas le fond flou assombri
    with Image.open(previews[0]) as img:
        rgb = img.convert("RGB")
        edge = [rgb.getpixel((x, 1910)) for x in range(0, 1080, 60)]
        spread = max(max(c) - min(c) for c in zip(*edge))
    results.append(spread > 25)
    print(f"{'✅' if results[-1] else '❌'} paysage plein écran : détails jusqu'au bas de l'image (écart {spread})")

    map_clip = os.path.join(composer.temp_dir, "scene_map_qualite.mp4")   # nom du pipeline : crédit de la carte
    cfg = map_settings(config.get("visuals"))
    if not render_map_scene(QUALITY_MAP, QUALITY_MAP_DURATION, map_clip, cfg=cfg, fps=composer.fps):
        return False
    results.append(check_map_clip("qualite", map_clip, QUALITY_MAP_DURATION, composer.fps))
    make_fake_voice(voice, QUALITY_MAP_DURATION)
    map_scene_dict = {"id": "q_map", "audio_path": voice, "duration": QUALITY_MAP_DURATION, "mood": "tense"}
    rendered = composer.process_scene(map_scene_dict, (map_clip, map_clip))
    dressed = os.path.join(composer.temp_dir, "q_map_dressed.mp4")
    if not rendered or not composer.add_watermark(rendered, dressed, headline=QUALITY_HEADLINE):
        return False
    png = os.path.join(out_dir, "3_carte_etiquette_et_repere.png")
    ffmpeg.input(dressed, ss=QUALITY_MAP_DURATION - 0.4).output(png, vframes=1).run(overwrite_output=True, quiet=True)
    previews.append(png)
    for path in previews:
        print(f"    🖼️ {path}")
    return all(results)


if __name__ == "__main__":
    if "--map" in sys.argv[1:]:
        sys.exit(0 if render_map_previews() else 1)
    if "--qualite" in sys.argv[1:]:
        sys.exit(0 if render_quality_previews() else 1)

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
