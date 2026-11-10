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
        paths = []

        for scene in scenes:
            sid = scene["id"]
            scene_type = scene.get("scene_type", "generic")
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
        for scene in scenes:
            scene["srt_path"] = generate_grouped_srt(
                text=scene["text"],
                duration=scene["duration"],
                output_path=str(self.work_dir / "subs" / f"scene_{scene['id']}.srt"),
            )

    # ---------- Orchestration ----------
    def run(self, script: dict, upload: bool = False) -> Path | None:
        scenes = script["scenes"]
        title = script.get("title") or script.get("topic") or self.name
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
        final = composer.concatenate_with_transitions(rendered, f"{self.name}_{stamp}.mp4")
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

