"""Compositeur vidéo vertical : scènes, sous-titres, mixage audio et watermark."""
from __future__ import annotations
import math
import os
import random
import shutil
import textwrap
import ffmpeg
from config.settings import (
    ASSETS_DIR,
    DEFAULT_FPS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    OUTPUT_DIR,
    TEMP_DIR,
)
from auracontent.utils.media_helpers import (
    cleanup_temp_files,
    ensure_pair,
    escape_drawtext,
    escape_path_for_filter,
    get_duration,
    is_video_file,
    pick_dominant_mood,
)
from constants import (
    AUDIO_FORMAT,
    DEFAULT_FONT_PATH,
    DEFAULT_SUBTITLE_STYLE,
    H264_AAC,
    LOUDNORM,
    MIN_SEGMENT_DURATION,
    SECOND_IMAGE_EXTRA_DURATION,
    VIDEO_CRF,
    ZOOM_IN_EXPR,
    ZOOM_OUT_EXPR,
)


# Helpers génériques
def _run(output_node) -> None:
    output_node.run(overwrite_output=True, quiet=True)


def _to_stereo_48k(audio):
    return audio.filter("aformat", **AUDIO_FORMAT)


def _safe_remove(path: str) -> None:
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


class Composer:
    """
    Compositeur vidéo vertical générique.
    Applique le pipeline visuel : scènes -> sous-titres -> watermark -> mixage audio.
    """

    def __init__(self, channel_config: dict | None = None, channel_name: str | None = None,
                 mascot: dict | None = None):
        # assets/<chaîne>/{music,images} propres à la chaîne, assets/shared/ pour le commun
        shared_dir = os.path.join(str(ASSETS_DIR), "shared")
        channel_dir = os.path.join(str(ASSETS_DIR), channel_name) if channel_name else shared_dir
        self.temp_dir = str(TEMP_DIR)
        self.final_dir = str(OUTPUT_DIR)
        self.music_dir = os.path.join(channel_dir, "music")
        self.images_dir = os.path.join(channel_dir, "images")
        self.sfx_dir = os.path.join(shared_dir, "sfx")

        for directory in (
            self.temp_dir,
            self.final_dir,
            self.music_dir,
            self.images_dir,
            self.sfx_dir,
        ):
            os.makedirs(directory, exist_ok=True)

        config = channel_config or {}

        # Vidéo
        self.video_width = config.get("video_width", DEFAULT_VIDEO_WIDTH)
        self.video_height = config.get("video_height", DEFAULT_VIDEO_HEIGHT)
        self.fps = config.get("fps", DEFAULT_FPS)
        self.transitions = config.get("transitions", ["fade", "fade", "fade", "fade"])

        # Audio et mixage
        self.current_bg_music_path = None
        self.music_exclude_patterns = config.get("music_exclude_patterns", [])
        self.voice_gain = config.get("voice_gain", 1.08)
        self.music_gain = config.get("music_gain", 0.085)
        self.music_fade_duration = config.get("music_fade_duration", 2.5)
        self.transition_duration = config.get("transition_duration", 0.38)

        # Effets sonores
        self.sfx_role_map = config.get("sfx_role_map", {})
        self.sfx_mood_map = config.get("sfx_mood_map", {})
        self.sfx_gain = config.get("sfx_gain", 0.55)
        self.sfx_fade_out = config.get("sfx_fade_out", 0.6)

        # Branding
        watermark_filename = config.get("watermark_filename")
        self.watermark_path = (
            os.path.join(self.images_dir, watermark_filename)
            if watermark_filename
            else None
        )
        self.watermark_width = config.get("watermark_width", 205)
        self.watermark_opacity = config.get("watermark_opacity", 0.72)
        self.watermark_x = config.get("watermark_x", 42)
        self.watermark_y = config.get("watermark_y", 48)

        # Textes
        self.subtitle_style = config.get("subtitle_style", DEFAULT_SUBTITLE_STYLE)
        self.watermark_font_path = config.get("font_path", DEFAULT_FONT_PATH)
        self.source_credit_y = config.get("source_credit_y", "h-520")
        self.source_credit_size = config.get("source_credit_size", 18)
        self.source_credit_alpha = config.get("source_credit_alpha", 0.52)
        self.source_credit_labels = config.get("source_credit_labels", {})

        # Cadrage des images fixes : plein écran (paysage recadré + panoramique lent) au lieu du fond flou
        self.image_full_screen = config.get("image_full_screen", False)
        self.pan_speed = config.get("pan_speed", 0.06)   # fraction de la largeur de l'écran par seconde

        # Titre accrocheur à l'écran (scène 1)
        self.overlay_duration = config.get("overlay_duration", 3.0)
        self.overlay_font_size = config.get("overlay_font_size", 72)
        self.overlay_chars_per_line = config.get("overlay_chars_per_line", 18)
        self.overlay_max_lines = config.get("overlay_max_lines", 3)
        self.overlay_y = config.get("overlay_y", 300)

        # Bandeau-titre permanent (signature visuelle + miniature lisible quelle que soit l'image retenue)
        self.fonts_dir = os.path.join(shared_dir, "fonts")
        headline_font = os.path.join(self.fonts_dir, config.get("headline_font", "Montserrat-Bold.ttf"))
        self.headline_font_path = headline_font if os.path.exists(headline_font) else self.watermark_font_path
        self.headline_persistent = config.get("headline_persistent", False)
        self.headline_font_size = config.get("headline_font_size", 96)
        self.headline_min_font_size = config.get("headline_min_font_size", 60)
        self.headline_chars_per_line = config.get("headline_chars_per_line", 18)
        self.headline_max_lines = config.get("headline_max_lines", 3)
        self.headline_y = config.get("headline_y", 230)
        self.headline_margin_x = config.get("headline_margin_x", 70)
        self.headline_accent_color = config.get("headline_accent_color", "0xFFD400")

        # Mascotte (section `mascot` du YAML) : petite épingle à gauche, sous le bandeau-titre
        from auracontent.services.visuals.mascot import mascot_files, mascot_settings

        self.mascot_cfg = mascot_settings(mascot)
        self.mascot_files = mascot_files(self.mascot_cfg, channel_name) if channel_name else {}

    def mascot_position(self) -> tuple[int, int]:
        """Coin gauche sous le bandeau-titre (3 lignes au plus), au-dessus des sous-titres et du crédit."""
        cfg = self.mascot_cfg
        if cfg.get("y") is not None:
            return int(cfg["x"]), int(cfg["y"])
        line_height = int(self.headline_font_size * 1.34)
        accent_pad = int(self.headline_font_size * 0.16)      # cartouche jaune de la chute
        bottom = self.headline_y + self.headline_max_lines * line_height + accent_pad
        return int(cfg["x"]), bottom + int(cfg["gap"])

    def _add_mascot(self, video_stream, expression: str | None, surprise: tuple[float, float] | None = None):
        """Mascotte du coin (sans ombre). `surprise` : (début, fin) de la phrase de la révélation, pendant
        laquelle « surpris » remplace l'expression de fond."""
        path = self.mascot_files.get(expression or "")
        if not path:
            return video_stream
        from auracontent.services.visuals.mascot import overlay_png

        out_dir = os.path.join(self.temp_dir, "mascot")
        height = int(self.mascot_cfg["height"])
        x, y = self.mascot_position()
        surprised = self.mascot_files.get("surpris") if surprise else None
        png = overlay_png(path, height, out_dir)
        sprite = ffmpeg.input(png, loop=1, framerate=self.fps).video.filter("format", "rgba")
        if not surprised:
            return ffmpeg.overlay(video_stream, sprite, x=x, y=y, shortest=1, eof_action="repeat")
        start, end = surprise
        during = f"between(t,{start:.2f},{end:.2f})"
        video_stream = ffmpeg.overlay(video_stream, sprite, x=x, y=y, shortest=1, eof_action="repeat",
                                      enable=f"not({during})")
        sprite2 = ffmpeg.input(overlay_png(surprised, height, out_dir), loop=1,
                               framerate=self.fps).video.filter("format", "rgba")
        return ffmpeg.overlay(video_stream, sprite2, x=x, y=y, shortest=1, eof_action="repeat", enable=during)

    # Musique et effets sonores
    def set_background_music(self, mood: str = "intriguing") -> None:
        self.current_bg_music_path = self._pick_music_track(mood)

    def _pick_music_track(self, mood: str) -> str | None:
        if not os.path.exists(self.music_dir):
            return None

        available = [
            name
            for name in os.listdir(self.music_dir)
            if name.lower().endswith(".mp3")
            and not any(p in name.lower() for p in self.music_exclude_patterns)
        ]
        if not available:
            return None

        matching = [name for name in available if mood.lower() in name.lower()]
        return os.path.join(self.music_dir, random.choice(matching or available))

    def _resolve_source_credit(self, path_a: str) -> str:
        file_name = str(path_a).lower()
        for token, label in self.source_credit_labels.items():
            if f"_{token}_" in file_name or file_name.startswith(f"{token}_"):
                return label
        return "Illustration"

    def _resolve_sfx_path(self, scene: dict) -> str | None:
        role = str(scene.get("role", "")).strip().lower()
        mood = str(scene.get("mood", "")).strip().lower()
        filename = self.sfx_role_map.get(role) or self.sfx_mood_map.get(mood)
        if not filename:
            return None
        path = os.path.join(self.sfx_dir, filename)
        return path if os.path.exists(path) else None

    def _build_scene_audio(self, audio_path: str, scene: dict, total_duration: float):
        voice_stream = ffmpeg.input(audio_path).audio

        sfx_path = self._resolve_sfx_path(scene)
        if not sfx_path:
            return voice_stream

        sfx_duration = get_duration(sfx_path)
        if sfx_duration <= 0:
            return voice_stream

        sfx_length = min(sfx_duration, total_duration)
        fade_start = max(sfx_length - self.sfx_fade_out, 0)

        sfx_audio = (
            _to_stereo_48k(ffmpeg.input(sfx_path).audio)
            .filter("volume", self.sfx_gain)
            .filter("atrim", duration=sfx_length)
            .filter(
                "afade", type="out", start_time=fade_start, duration=self.sfx_fade_out
            )
            .filter("apad")
        )
        return ffmpeg.filter(
            [_to_stereo_48k(voice_stream), sfx_audio],
            "amix",
            inputs=2,
            duration="first",
            dropout_transition=0,
            normalize=0,
        )

    # Rendu d'une scène
    def _loop_and_crop(self, path: str, duration: float, **input_kwargs):
        """Boucle une vidéo, la coupe à `duration` et la recadre au format cible."""
        return (
            ffmpeg.input(path, stream_loop=-1, **input_kwargs)
            .filter("trim", duration=duration)
            .filter(
                "scale",
                self.video_width,
                self.video_height,
                force_original_aspect_ratio="increase",
            )
            .filter("crop", self.video_width, self.video_height)
            .setpts("PTS-STARTPTS")
        )

    @staticmethod
    def _image_aspect(path: str) -> float:
        try:
            from PIL import Image

            with Image.open(path) as img:
                return img.width / img.height
        except Exception:
            return 9 / 16

    def _vertical_frame(self, stream, path: str):
        """Ramène l'image au format 9:16 SANS la déformer (zoompan étire sinon l'image à la taille de sortie).

        - image verticale : recadrage centré ;
        - image horizontale (photos d'archives) : image entière centrée sur un fond flouté d'elle-même.
        Marge de 15 % pour que le zoom Ken Burns ne montre jamais de bord.
        """
        w, h = int(self.video_width * 1.15) // 2 * 2, int(self.video_height * 1.15) // 2 * 2
        target = w / h
        if self._image_aspect(path) <= target * 1.25:  # déjà (presque) vertical : on recadre
            return (
                stream.filter("scale", w, h, force_original_aspect_ratio="increase")
                .filter("crop", w, h)
                .filter("setsar", 1)
            )
        split = stream.filter_multi_output("split", 2)
        background = (
            split[0]
            .filter("scale", w, h, force_original_aspect_ratio="increase")
            .filter("crop", w, h)
            .filter("boxblur", 30, 2)
            .filter("eq", brightness=-0.12)
        )
        foreground = split[1].filter("scale", w, -2)
        return ffmpeg.overlay(background, foreground, x="(W-w)/2", y="(H-h)/2").filter("setsar", 1)

    def _zoompan_clip(self, path: str, duration: float, zoom_expr: str):
        """Image fixe animée (effet Ken Burns) pendant `duration` secondes."""
        frames = max(int(duration * self.fps), 1)
        # UNE seule image en entrée : zoompan émet `d` frames PAR frame d'entrée.
        # (avec loop=1 l'image était répétée à 25 fps -> durée ~ au carré : 417 s pour une scène de 5 s)
        source = ffmpeg.input(path, loop=1, framerate=1, t=duration).filter("trim", end_frame=1)  # t distinct par segment
        return (
            self._vertical_frame(source, path)
            .filter(
                "zoompan",
                z=zoom_expr,
                x="iw/2-(iw/zoom/2)",
                y="ih/2-(ih/zoom/2)",
                d=frames,
                s=f"{self.video_width}x{self.video_height}",
                fps=self.fps,
            )
            .filter("trim", duration=duration)   # garde-fou sur la durée
            .setpts("PTS-STARTPTS")
        )

    def _is_landscape(self, path: str) -> bool:
        return self._image_aspect(path) > (self.video_width / self.video_height) * 1.25

    def _pan_clip(self, path: str, duration: float, reverse: bool = False):
        """Photo en paysage recadrée plein écran, avec un déplacement horizontal lent (jamais de fond flou)."""
        w, h = self.video_width, self.video_height
        scaled_h = int(h * 1.04) // 2 * 2                   # légère marge verticale : aucun bord visible
        scaled_w = int(self._image_aspect(path) * scaled_h) // 2 * 2
        travel = max(min(scaled_w - w, self.pan_speed * w * duration), 0)
        x0 = (scaled_w - w - travel) / 2                    # déplacement centré sur le milieu de l'image
        x = f"{x0 + travel:.2f}-{travel:.2f}*t/{duration:.3f}" if reverse else f"{x0:.2f}+{travel:.2f}*t/{duration:.3f}"
        return (
            ffmpeg.input(path, loop=1, framerate=self.fps, t=duration)
            .filter("scale", -2, scaled_h)
            .filter("crop", w, h, x=x, y="(ih-oh)/2")
            .filter("setsar", 1)
            .filter("trim", duration=duration)
            .setpts("PTS-STARTPTS")
        )

    def _still_clip(self, path: str, duration: float, motion: int = 0):
        """Image fixe en mouvement. Mouvements alternés : zoom avant, panoramique ou zoom arrière."""
        if not self.image_full_screen:
            return self._zoompan_clip(path, duration, ZOOM_IN_EXPR if motion % 2 == 0 else ZOOM_OUT_EXPR)
        if self._is_landscape(path):
            return self._pan_clip(path, duration, reverse=motion % 2 == 1)
        return self._zoompan_clip(path, duration, ZOOM_IN_EXPR if motion % 2 == 0 else ZOOM_OUT_EXPR)

    @staticmethod
    def shot_frames(total_duration: float, max_shot: float, fps: int) -> list[int]:
        """Images par plan : ceil(durée / max_shot) plans de longueurs égales à une image près."""
        total = max(math.ceil(total_duration * fps - 1e-6), 1)
        count = max(math.ceil(total_duration / max(max_shot, 0.1) - 1e-6), 1)
        base, extra = divmod(total, count)
        return [base + (1 if i < extra else 0) for i in range(count)]

    def _build_shots_video(self, scene_id, total_duration: float, shots: list[str], max_shot: float):
        """Plusieurs visuels de `max_shot` secondes au plus. Retourne (flux, [(début, fin, chemin)])."""
        frames = self.shot_frames(total_duration, max_shot, self.fps)
        if len(frames) > len(shots) > 0:
            print(f"  ⚠️ Scène {scene_id} : {len(frames)} plans pour {len(shots)} visuel(s), certains reviennent.")
        streams, windows, start = [], [], 0.0
        for j, n in enumerate(frames):
            path = shots[j % len(shots)]
            duration = n / self.fps + (SECOND_IMAGE_EXTRA_DURATION if j == len(frames) - 1 else 0.0)
            if is_video_file(path):
                offset = (j // len(shots)) * max_shot      # un clip repris montre un autre passage
                length = get_duration(path)
                streams.append(self._loop_and_crop(path, duration, ss=offset % length if length > 0 else 0))
            else:
                streams.append(self._still_clip(path, duration, motion=j))
            windows.append((start, start + duration, path))
            start += duration
        stream = streams[0] if len(streams) == 1 else ffmpeg.concat(*streams, v=1, a=0)
        return stream, windows

    def _build_scene_video(
        self,
        scene_id,
        total_duration: float,
        image_pair,
        bg_video_path: str | None,
        bg_offset: float,
    ):
        """Retourne (flux vidéo, chemin source principal ou None si fond vidéo)."""
        if bg_video_path and os.path.exists(bg_video_path):
            source_duration = get_duration(bg_video_path)
            start_offset = bg_offset % source_duration if source_duration > 0 else 0.0
            stream = self._loop_and_crop(bg_video_path, total_duration, ss=start_offset)
            return stream, None

        path_a, path_b = ensure_pair(image_pair)
        if not path_a:
            raise ValueError(f"Scene {scene_id}: aucune source dispo.")
        path_b = path_b or path_a

        if is_video_file(path_a):
            return self._loop_and_crop(path_a, total_duration), path_a

        duration_a = max(total_duration / 2, MIN_SEGMENT_DURATION)
        duration_b = max(
            (total_duration / 2) + SECOND_IMAGE_EXTRA_DURATION, MIN_SEGMENT_DURATION
        )
        stream_a = self._still_clip(path_a, duration_a, motion=0)
        stream_b = self._still_clip(path_b, duration_b, motion=1)
        return ffmpeg.concat(stream_a, stream_b, v=1, a=0), path_a

    def _add_overlay_title(self, video_stream, text: str, duration: float):
        """Titre en gros en haut de l'écran pendant les premières secondes (beaucoup regardent sans le son)."""
        lines = textwrap.wrap(str(text).upper(), width=self.overlay_chars_per_line)[: self.overlay_max_lines]
        size = self.overlay_font_size
        for i, line in enumerate(lines):
            video_stream = video_stream.filter(
                "drawtext",
                text=escape_drawtext(line),
                fontfile=self.watermark_font_path,
                fontcolor="white",
                fontsize=size,
                box=1,
                boxcolor="black@0.65",
                boxborderw=18,
                x="(w-text_w)/2",
                y=f"{self.overlay_y}+{i}*{int(size * 1.45)}",
                enable=f"lt(t,{min(duration, self.overlay_duration)})",
            )
        return video_stream

    def _headline_lines(self, text: str) -> tuple[list[str], int]:
        """Découpe « CONSTAT | CHUTE » en lignes ; retourne (lignes, nombre de lignes de chute en accent)."""
        parts = [p.strip() for p in str(text).upper().split("|") if p.strip()]
        wrapped = [
            textwrap.wrap(p, width=self.headline_chars_per_line, break_long_words=False, break_on_hyphens=False)
            for p in parts
        ]
        lines = [line for part in wrapped for line in part]
        if not lines:
            return [], 0
        # sans séparateur, seule la dernière ligne porte l'accent
        accent = len(wrapped[-1]) if len(wrapped) > 1 else 1
        if len(lines) > self.headline_max_lines:
            lines = lines[: self.headline_max_lines]
            accent = min(accent, 1)
        return lines, accent

    def _headline_font_size_for(self, lines: list[str]) -> int:
        """Plus grande taille (entre min et max) pour laquelle la ligne la plus longue tient dans l'écran."""
        size = self.headline_font_size
        try:
            from PIL import ImageFont

            max_width = self.video_width - 2 * self.headline_margin_x
            while size > self.headline_min_font_size:
                font = ImageFont.truetype(self.headline_font_path, size)
                if max(font.getlength(line) for line in lines) <= max_width:
                    break
                size -= 4
        except Exception:
            pass
        return size

    def _add_headline(self, video_stream, text: str):
        """Titre en deux temps, affiché pendant toute la vidéo : constat en blanc, chute sur fond jaune."""
        lines, accent = self._headline_lines(text)
        if not lines:
            return video_stream
        size = self._headline_font_size_for(lines)
        line_height = int(size * 1.34)
        for i, line in enumerate(lines):
            common = dict(
                text=escape_drawtext(line),
                fontfile=self.headline_font_path,
                fontsize=size,
                x="(w-text_w)/2",
                y=f"{self.headline_y}+{i * line_height}",
            )
            if i >= len(lines) - accent:
                video_stream = video_stream.filter(
                    "drawtext", fontcolor="black", box=1,
                    boxcolor=self.headline_accent_color, boxborderw=int(size * 0.16), **common,
                )
            else:
                video_stream = video_stream.filter(
                    "drawtext", fontcolor="white", borderw=max(int(size * 0.07), 4), bordercolor="black",
                    shadowcolor="black@0.6", shadowx=0, shadowy=int(size * 0.06), **common,
                )
        return video_stream

    def _add_source_credit(self, video_stream, text: str, enable: str | None = None):
        extra = {"enable": enable} if enable else {}
        return video_stream.filter(
            "drawtext",
            text=escape_drawtext(text),
            fontfile=self.watermark_font_path,
            fontcolor=f"white@{self.source_credit_alpha}",
            fontsize=self.source_credit_size,
            box=0,
            shadowcolor="black@0.75",
            shadowx=1,
            shadowy=1,
            x="30",
            y=self.source_credit_y,
            **extra,
        )

    def process_scene(
        self,
        scene: dict,
        image_pair,
        bg_video_path: str | None = None,
        bg_offset: float = 0.0,
    ) -> str | None:
        scene_id = scene["id"]
        audio_path = scene["audio_path"]
        total_duration = float(scene["duration"])
        output_path = os.path.join(self.temp_dir, f"scene_{scene_id}_rendered.mp4")

        try:
            scene_audio = self._build_scene_audio(audio_path, scene, total_duration)
            if not bg_video_path and isinstance(image_pair, dict) and image_pair.get("shots"):
                video_stream, windows = self._build_shots_video(
                    scene_id, total_duration, image_pair["shots"], float(image_pair.get("max_shot", 4.0))
                )
                for start, end, path in windows:   # crédit propre à chaque plan
                    label = self._resolve_source_credit(path)
                    video_stream = self._add_source_credit(video_stream, label, f"between(t,{start:.3f},{end:.3f})")
            else:
                video_stream, source_path = self._build_scene_video(
                    scene_id, total_duration, image_pair, bg_video_path, bg_offset
                )
                source_text = ""
                if not bg_video_path and source_path:
                    source_text = self._resolve_source_credit(source_path)
                if source_text:
                    video_stream = self._add_source_credit(video_stream, source_text)

            if scene.get("overlay_text"):
                video_stream = self._add_overlay_title(video_stream, scene["overlay_text"], total_duration)

            if scene.get("mascot"):
                video_stream = self._add_mascot(video_stream, scene["mascot"], scene.get("mascot_surprise"))

            srt_path = scene.get("srt_path")
            if srt_path and os.path.exists(srt_path):
                video_stream = video_stream.filter(
                    "subtitles",
                    filename=escape_path_for_filter(srt_path),
                    fontsdir=escape_path_for_filter(self.fonts_dir),
                    force_style=self.subtitle_style,
                )

            _run(
                ffmpeg.output(
                    video_stream,
                    scene_audio,
                    output_path,
                    r=self.fps,
                    crf=VIDEO_CRF,
                    **H264_AAC,
                )
            )
            return output_path

        except Exception as e:
            print(f"❌ Render Fail Scene {scene_id}: {e}")
            return None

    def render_all_scenes(
        self,
        script_data: list[dict],
        video_pairs: list,
        bg_video_path: str | None = None,
    ) -> list[str]:
        self.set_background_music(mood=pick_dominant_mood(script_data))
        rendered_paths = []
        bg_cursor = 0.0

        for i, scene in enumerate(script_data):
            pair = video_pairs[i] if i < len(video_pairs) else None
            output_path = self.process_scene(
                scene, pair, bg_video_path=bg_video_path, bg_offset=bg_cursor
            )
            bg_cursor += float(scene["duration"])
            if output_path:
                rendered_paths.append(output_path)
        return rendered_paths

    # Assemblage
    def _merge_two_clips(self, clip_a: str, clip_b: str, output_path: str):
        duration = self.transition_duration
        offset = max(get_duration(clip_a) - duration, 0)
        effect = random.choice(self.transitions)

        input_a = ffmpeg.input(clip_a)
        input_b = ffmpeg.input(clip_b)
        video = ffmpeg.filter(
            [input_a.video, input_b.video],
            "xfade",
            transition=effect,
            duration=duration,
            offset=offset,
        )
        audio = ffmpeg.filter([input_a.audio, input_b.audio], "acrossfade", d=duration)

        _run(ffmpeg.output(video, audio, output_path, crf=VIDEO_CRF, **H264_AAC))
        return effect, offset

    def _stitch_clips(self, video_paths: list[str], merge_step_files: list[str]):
        """Enchaîne les clips deux à deux. Retourne None si une fusion échoue."""
        if len(video_paths) == 1:
            return video_paths[0]

        merge_prefix = os.path.join(self.temp_dir, "merge_step_")
        current = video_paths[0]

        for i, next_clip in enumerate(video_paths[1:], start=1):
            merge_output = os.path.join(self.temp_dir, f"merge_step_{i}.mp4")
            try:
                self._merge_two_clips(current, next_clip, merge_output)
            except Exception:
                cleanup_temp_files(merge_step_files)
                return None

            if current.startswith(merge_prefix):
                merge_step_files.append(current)
            current = merge_output

        return current

    # Audio final
    def _normalize_audio_track(
        self, input_video_path: str, output_video_path: str
    ) -> bool:
        try:
            source = ffmpeg.input(input_video_path)
            audio = source.audio.filter("loudnorm", **LOUDNORM)
            _run(
                ffmpeg.output(
                    source.video,
                    audio,
                    output_video_path,
                    vcodec="copy",
                    acodec="aac",
                    ar=48000,
                    audio_bitrate=H264_AAC["audio_bitrate"],
                    movflags="faststart",
                )
            )
            return True
        except Exception:
            return False

    def _normalize_or_copy(self, stitched_path: str, destination: str) -> None:
        """Normalise l'audio sans musique ; à défaut, copie le fichier tel quel."""
        normalized = os.path.join(self.temp_dir, "normalized_no_music.mp4")
        if self._normalize_audio_track(stitched_path, normalized) and os.path.exists(
            normalized
        ):
            os.replace(normalized, destination)
        else:
            shutil.copy2(stitched_path, destination)

    @staticmethod
    def _prepare_track(audio, gain: float, duration: float):
        return (
            _to_stereo_48k(audio)
            .filter("volume", gain)
            .filter("atrim", duration=duration)
            .filter("asetpts", "PTS-STARTPTS")
        )

    def _mix_background_music(self, stitched_path: str, output_path: str) -> bool:
        try:
            video_duration = get_duration(stitched_path)
            if video_duration <= 0:
                return False

            fade_start = max(video_duration - self.music_fade_duration, 0)
            voice = ffmpeg.input(stitched_path)
            music = ffmpeg.input(self.current_bg_music_path, stream_loop=-1)

            voice_audio = self._prepare_track(
                voice.audio, self.voice_gain, video_duration
            )
            music_audio = (
                self._prepare_track(music.audio, self.music_gain, video_duration)
                .filter(
                    "afade", type="in", start_time=0, duration=min(1.2, video_duration)
                )
                .filter(
                    "afade",
                    type="out",
                    start_time=fade_start,
                    duration=self.music_fade_duration,
                )
            )

            voice_split = voice_audio.filter_multi_output("asplit", 2)
            music_split = music_audio.filter_multi_output("asplit", 2)

            ducked_music = ffmpeg.filter(
                [music_split[0], voice_split[0]],
                "sidechaincompress",
                threshold=0.035,
                ratio=5,
                attack=30,
                release=450,
                makeup=1,
            )
            mixed_audio = ffmpeg.filter(
                [voice_split[1], ducked_music],
                "amix",
                inputs=2,
                duration="first",
                dropout_transition=2,
                normalize=0,
            ).filter("loudnorm", **LOUDNORM)

            # loudnorm suréchantillonne (96-192 kHz) : on revient au 48 kHz standard des plateformes
            _run(ffmpeg.output(voice.video, mixed_audio, output_path, ar=48000, **H264_AAC))
            return True
        except Exception:
            return False

    # Habillage final : watermark + bandeau-titre, en un seul encodage
    def add_watermark(self, input_video_path: str, output_video_path: str, headline: str | None = None) -> bool:
        has_logo = bool(self.watermark_path and os.path.exists(self.watermark_path))
        if not has_logo and not headline:
            return False

        try:
            video = ffmpeg.input(input_video_path)
            stream = video.video
            if has_logo:
                logo = (
                    ffmpeg.input(self.watermark_path, loop=1, framerate=self.fps)
                    .video.filter(
                        "scale",
                        self.watermark_width,
                        -1,
                        force_original_aspect_ratio="decrease",
                    )
                    .filter("format", "rgba")
                    .filter("colorchannelmixer", aa=self.watermark_opacity)
                )
                stream = ffmpeg.overlay(
                    stream,
                    logo,
                    x=self.watermark_x,
                    y=self.watermark_y,
                    eof_action="repeat",
                    shortest=1,
                )
            if headline:
                stream = self._add_headline(stream, headline)
            _run(
                ffmpeg.output(
                    stream,
                    video.audio,
                    output_video_path,
                    r=self.fps,
                    crf=VIDEO_CRF,
                    shortest=None,
                    **H264_AAC,
                )
            )
            return True
        except Exception as e:
            print(f"⚠️ Habillage final échoué : {e}")
            return False

    # Pipeline final
    def concatenate_with_transitions(
        self, video_paths: list[str], output_filename: str = "final_video.mp4", headline: str | None = None
    ) -> str | None:
        raw_final_path = os.path.join(self.temp_dir, "raw_final_stitched.mp4")
        output_path = os.path.join(self.final_dir, output_filename)

        _safe_remove(output_path)

        if not video_paths:
            return None

        merge_step_files: list[str] = []
        stitched_path = self._stitch_clips(video_paths, merge_step_files)
        if stitched_path is None:
            return None

        has_music = bool(
            self.current_bg_music_path and os.path.exists(self.current_bg_music_path)
        )
        music_mixed = has_music and self._mix_background_music(
            stitched_path, raw_final_path
        )
        if not music_mixed:
            self._normalize_or_copy(stitched_path, raw_final_path)

        if not self.add_watermark(raw_final_path, output_path, headline=headline):
            shutil.copy2(raw_final_path, output_path)

        _safe_remove(raw_final_path)

        cleanup_temp_files(video_paths + merge_step_files, keep=output_path)
        if stitched_path not in video_paths and stitched_path != output_path:
            cleanup_temp_files([stitched_path], keep=output_path)

        return output_path
