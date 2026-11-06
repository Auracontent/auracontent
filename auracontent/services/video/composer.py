"""Compositeur vidéo vertical : scènes, sous-titres, mixage audio et watermark."""
from __future__ import annotations
import os
import random
import shutil
import ffmpeg
from config.settings import (
    ASSETS_DIR,
    DEFAULT_FPS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    OUTPUT_DIR,
    TEMP_DIR,
)
from utils.media_helpers import (
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
    KEN_BURNS_SOURCE_WIDTH,
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

    def __init__(self, channel_config: dict | None = None):
        self.temp_dir = str(TEMP_DIR)
        self.final_dir = str(OUTPUT_DIR)
        self.music_dir = os.path.join(str(ASSETS_DIR), "music")
        self.images_dir = os.path.join(str(ASSETS_DIR), "images")
        self.sfx_dir = os.path.join(str(ASSETS_DIR), "sfx")

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

    def _zoompan_clip(self, path: str, duration: float, zoom_expr: str):
        """Image fixe animée (effet Ken Burns) pendant `duration` secondes."""
        frames = max(int(duration * self.fps), 1)
        return (
            ffmpeg.input(path, loop=1, t=duration)
            .filter("scale", KEN_BURNS_SOURCE_WIDTH, -1)
            .filter(
                "zoompan",
                z=zoom_expr,
                d=frames,
                s=f"{self.video_width}x{self.video_height}",
                fps=self.fps,
            )
            .setpts("PTS-STARTPTS")
        )

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
        stream_a = self._zoompan_clip(path_a, duration_a, ZOOM_IN_EXPR)
        stream_b = self._zoompan_clip(path_b, duration_b, ZOOM_OUT_EXPR)
        return ffmpeg.concat(stream_a, stream_b, v=1, a=0), path_a

    def _add_source_credit(self, video_stream, text: str):
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
            video_stream, source_path = self._build_scene_video(
                scene_id, total_duration, image_pair, bg_video_path, bg_offset
            )

            source_text = ""
            if not bg_video_path and source_path:
                source_text = self._resolve_source_credit(source_path)
            if source_text:
                video_stream = self._add_source_credit(video_stream, source_text)

            srt_path = scene.get("srt_path")
            if srt_path and os.path.exists(srt_path):
                video_stream = video_stream.filter(
                    "subtitles",
                    filename=escape_path_for_filter(srt_path),
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

            _run(ffmpeg.output(voice.video, mixed_audio, output_path, **H264_AAC))
            return True
        except Exception:
            return False

    # Watermark
    def add_watermark(self, input_video_path: str, output_video_path: str) -> bool:
        if not self.watermark_path or not os.path.exists(self.watermark_path):
            return False

        try:
            video = ffmpeg.input(input_video_path)
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
            watermarked = ffmpeg.overlay(
                video.video,
                logo,
                x=self.watermark_x,
                y=self.watermark_y,
                eof_action="repeat",
                shortest=1,
            )
            _run(
                ffmpeg.output(
                    watermarked,
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
            print(f"⚠️ Watermark failed: {e}")
            return False

    # Pipeline final
    def concatenate_with_transitions(
        self, video_paths: list[str], output_filename: str = "final_video.mp4"
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

        if not self.add_watermark(raw_final_path, output_path):
            shutil.copy2(raw_final_path, output_path)

        _safe_remove(raw_final_path)

        cleanup_temp_files(video_paths + merge_step_files, keep=output_path)
        if stitched_path not in video_paths and stitched_path != output_path:
            cleanup_temp_files([stitched_path], keep=output_path)

        return output_path
