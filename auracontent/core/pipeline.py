"""Pipeline de production : script JSON -> assets -> légende -> voix -> sous-titres -> montage -> (upload HF).

Le script est produit en amont par GlobalBrain.run_channel (sujet, hooks, script, fact-check).
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path

from auracontent.channels.base_channel import BaseChannel
from auracontent.services.audios.audio import AudioEngine
from auracontent.services.publishing.caption import generate_caption
from auracontent.services.video.composer import Composer
from auracontent.services.visuals.asset_manager import AssetManager
from auracontent.utils.hook_tracker import record_hook_usage
from auracontent.utils.subtitles import generate_grouped_srt
from config.settings import ASSETS_DIR, TEMP_DIR

SHARED_FALLBACK_IMAGES = str(ASSETS_DIR / "shared" / "images" / "fallback_*.jpg")


class VideoPipeline:
    def __init__(self, channel: BaseChannel, llm):
        self.channel = channel
        self.name = channel.name
        self.llm = llm
        self.work_dir = TEMP_DIR / self.name
        self.publish_cfg = channel.section("publish")

    # ---------- 1. Assets ----------
    def _fetch_assets(self, scenes: list[dict]) -> list[str]:
        """Un média par scène (vidéo .mp4 ou image .jpg). Image de secours partagée si tout échoue."""
        manager = AssetManager(self.channel.section("visuals"))
        assets_dir = self.work_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        fallbacks = sorted(glob.glob(SHARED_FALLBACK_IMAGES))
        paths: list[str | None] = []
        query_counts: dict[str, int] = {}

        for scene in scenes:
            if scene.get("reuse_previous_asset") and paths:  # scène CTA : on garde le dernier visuel
                paths.append(paths[-1])
                continue
            sid = scene["id"]
            scene_type = scene.get("scene_type", "generic")
            location = (scene.get("location_name") or "").strip().lower()
            # Variété : un même lieu au-delà de 2 scènes -> plan d'ambiance (vidéo Pexels de préférence)
            if scene_type == "specific" and location and query_counts.get(location, 0) >= 2 and scene.get("stock_search"):
                print(f"  🔀 Scène {sid} : '{location}' déjà utilisé 2 fois, plan d'ambiance à la place.")
                scene_type = "generic"
            if location:
                query_counts[location] = query_counts.get(location, 0) + 1
            query = (scene.get("location_name") if scene_type == "specific" else scene.get("stock_search")) or ""
            query = query.strip() or scene.get("image_prompt", "") or self.channel.section("visuals").get(
                "video_fallback_query", "cinematic atmosphere"
            )
            print(f"  🎬 Scène {sid} [{scene_type}] : '{query}'")

            tmp_path = str(assets_dir / f"tmp_{sid}")
            ok, source = manager.get_best_asset(
                query=query,
                output_path=tmp_path,
                scene_type=scene_type,
                event_context=scene.get("event_context") or None,
                image_prompt=scene.get("image_prompt") or None,
            )
            if ok and os.path.exists(tmp_path):
                # Extension selon la source : le Composer anime les images (Ken Burns) et boucle les vidéos
                ext = ".mp4" if source == "video" else ".jpg"
                final = str(assets_dir / f"scene_{source}_{sid}{ext}")
                os.replace(tmp_path, final)
                paths.append(final)
            elif fallbacks:
                print(f"  ⚠️ Scène {sid} : aucun asset, image de secours.")
                paths.append(random.choice(fallbacks))
            else:
                paths.append(None)
        return paths

    # ---------- 2. Voix + sous-titres ----------
    async def _voice(self, scenes: list[dict]) -> list[dict]:
        engine = AudioEngine(self.channel.section("audio"), output_dir=str(self.work_dir / "audio"))
        return await engine.process_script(scenes)

    def _subtitles(self, scenes: list[dict]) -> None:
        cfg = self.channel.section("video_composer")
        for scene in scenes:
            scene["srt_path"] = generate_grouped_srt(
                text=scene["text"],
                duration=scene["duration"],
                output_path=str(self.work_dir / "subs" / f"scene_{scene['id']}.srt"),
                uppercase=cfg.get("subtitle_uppercase", False),
                highlight_color=cfg.get("subtitle_highlight_color"),
            )

    # ---------- Audience ----------
    def _enrich_for_audience(self, script: dict, scenes: list[dict], title: str) -> None:
        """Titre accrocheur à l'écran sur la scène 1 + CTA final lu par le narrateur."""
        # bandeau permanent : posé une seule fois sur la vidéo finale, pas sur la scène 1
        if scenes and not self.channel.section("video_composer").get("headline_persistent"):
            scenes[0]["overlay_text"] = str(script.get("on_screen_title") or title).replace("|", " ")
        cta = str(script.get("closing_cta") or "").strip()
        if cta and not any(s.get("role") == "cta" and cta in str(s.get("text", "")) for s in scenes):
            last = scenes[-1] if scenes else {}
            scenes.append({
                "id": len(scenes) + 1, "text": cta, "role": "cta", "mood": last.get("mood", "intriguing"),
                "voice_type": "narrator", "scene_type": last.get("scene_type", "generic"),
                "reuse_previous_asset": True,
            })

    # ---------- Orchestration ----------
    def run(self, script: dict, upload: bool = False) -> Path | None:
        scenes = script["scenes"]
        title = script.get("title") or script.get("topic") or self.name
        self._enrich_for_audience(script, scenes, title)
        shutil.rmtree(self.work_dir, ignore_errors=True)

        print("🔄 Recherche des assets...")
        assets = self._fetch_assets(scenes)

        print("📝 Légende...")
        caption = generate_caption(self.llm, title, scenes, self.publish_cfg.get("fallback_hashtags", ""))

        print("🎙️ Voix...")
        scenes = asyncio.run(self._voice(scenes))
        self._subtitles(scenes)

        print("🎞️ Montage...")
        composer = Composer(self.channel.section("video_composer"), channel_name=self.name)
        rendered = composer.render_all_scenes(scenes, assets)
        if not rendered:
            raise RuntimeError("aucune scène rendue.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        headline = (script.get("on_screen_title") or title) if composer.headline_persistent else None
        final = composer.concatenate_with_transitions(rendered, f"{self.name}_{stamp}.mp4", headline=headline)
        if not final:
            raise RuntimeError("assemblage final échoué.")

        final_path = Path(final)
        final_path.with_suffix(".txt").write_text(caption, encoding="utf-8")
        final_path.with_suffix(".json").write_text(
            json.dumps({"title": title, "caption": caption, "video": final_path.name}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Vidéo finale : {final_path}")
        hook = script.get("hook") if isinstance(script.get("hook"), dict) else {}
        record_hook_usage(title, hook.get("pattern"), self.name, caption)

        if upload:
            self._upload(final_path, title, caption)
        shutil.rmtree(self.work_dir, ignore_errors=True)
        return final_path

    def _upload(self, video: Path, title: str, caption: str) -> None:
        if not self.publish_cfg.get("hf_repo"):
            print(f"⏭️ Pas de `publish.hf_repo` pour {self.name} : upload ignoré.")
            return
        from auracontent.services.publishing.hf_storage import upload_video

        upload_video(str(video), title, self.publish_cfg["hf_repo"], self.publish_cfg.get("hf_folder", self.name), caption)


def produce_video(channel: BaseChannel, llm, script_path: Path, upload: bool = False) -> Path | None:
    script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    return VideoPipeline(channel, llm).run(script, upload=upload)

