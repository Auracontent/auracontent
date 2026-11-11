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
from auracontent.services.visuals.map_scene import MapTarget, map_settings, pick_map_target, render_map_scene
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
    def _fetch_assets(self, scenes: list[dict], skip: set[int] | None = None) -> list[str | None]:
        """Un média par scène (vidéo .mp4 ou image .jpg). Image de secours partagée si tout échoue.

        `skip` : indices des scènes dont le visuel sera fabriqué plus tard (carte animée) ; leur place reste
        à None et `_fetch_scene_asset` sert de repli si la fabrication échoue.
        """
        self._asset_manager = AssetManager(self.channel.section("visuals"))
        self._query_counts: dict[str, int] = {}
        skip = skip or set()
        paths: list[str | None] = []

        for i, scene in enumerate(scenes):
            if scene.get("reuse_previous_asset") and paths:  # scène CTA : on garde le dernier visuel
                paths.append(paths[-1])
                continue
            if i in skip:
                self._count_location(scene)                    # le repli éventuel garde la même variété
                paths.append(None)
                continue
            paths.append(self._fetch_scene_asset(scene))
        return paths

    def _count_location(self, scene: dict) -> str:
        location = (scene.get("location_name") or "").strip().lower()
        if location:
            self._query_counts[location] = self._query_counts.get(location, 0) + 1
        return location

    def _fetch_scene_asset(self, scene: dict, counted: bool = False) -> str | None:
        assets_dir = self.work_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        sid = scene["id"]
        scene_type = scene.get("scene_type", "generic")
        location = (scene.get("location_name") or "").strip().lower()
        # Variété : un même lieu au-delà de 2 scènes -> plan d'ambiance (vidéo Pexels de préférence)
        seen = self._query_counts.get(location, 0) - (1 if counted else 0)
        if scene_type == "specific" and location and seen >= 2 and scene.get("stock_search"):
            print(f"  🔀 Scène {sid} : '{location}' déjà utilisé 2 fois, plan d'ambiance à la place.")
            scene_type = "generic"
        if not counted:
            self._count_location(scene)
        query = (scene.get("location_name") if scene_type == "specific" else scene.get("stock_search")) or ""
        query = query.strip() or scene.get("image_prompt", "") or self.channel.section("visuals").get(
            "video_fallback_query", "cinematic atmosphere"
        )
        print(f"  🎬 Scène {sid} [{scene_type}] : '{query}'")

        tmp_path = str(assets_dir / f"tmp_{sid}")
        ok, source = self._asset_manager.get_best_asset(
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
            return final
        fallbacks = sorted(glob.glob(SHARED_FALLBACK_IMAGES))
        if fallbacks:
            print(f"  ⚠️ Scène {sid} : aucun asset, image de secours.")
            return random.choice(fallbacks)
        return None

    # ---------- 1 bis. Carte animée (lot 1) ----------
    def _plan_map(self, script: dict, scenes: list[dict]) -> MapTarget | None:
        """Scène qui recevra la carte (visuals.map_scene dans le YAML), ou None."""
        cfg = map_settings(self.channel.section("visuals"))
        try:
            return pick_map_target(script, scenes, cfg)
        except Exception as e:   # la carte n'est jamais bloquante
            print(f"⚠️ Carte animée ignorée : {e}")
            return None

    def _render_map(self, target: MapTarget, scenes: list[dict], assets: list[str | None]) -> None:
        """Rend la carte à la durée réelle de la scène (connue après la voix) ; repli sur le visuel habituel."""
        scene = scenes[target.index]
        cfg = self.channel.section("video_composer")
        # « osm » dans le nom : le crédit affiché mentionne OpenStreetMap (lieu géocodé par Nominatim)
        tag = "map_osm" if target.source == "nominatim" else "map"
        out = self.work_dir / "assets" / f"scene_{tag}_{scene['id']}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        ok = render_map_scene(
            target, float(scene["duration"]), str(out), cfg=map_settings(self.channel.section("visuals")),
            width=cfg.get("video_width", 1080), height=cfg.get("video_height", 1920), fps=cfg.get("fps", 30),
        )
        if ok:
            assets[target.index] = str(out)
            scene["map"] = {"lat": target.lat, "lon": target.lon, "label": target.label, "source": target.source}
        else:
            print(f"  ↩️ Scène {scene['id']} : visuel habituel à la place de la carte.")
            assets[target.index] = self._fetch_scene_asset(scene, counted=True)
        # scène CTA juste après : elle reprend le visuel de la scène précédente, encore vide au moment du tri
        for i in range(target.index + 1, len(scenes)):
            if not scenes[i].get("reuse_previous_asset"):
                break
            assets[i] = assets[i - 1]

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

        map_target = self._plan_map(script, scenes)
        print("🔄 Recherche des assets...")
        assets = self._fetch_assets(scenes, skip={map_target.index} if map_target else None)

        print("📝 Légende...")
        caption = generate_caption(self.llm, title, scenes, self.publish_cfg.get("fallback_hashtags", ""),
                                   brand_hashtag=self.publish_cfg.get("brand_hashtag"),
                                   banned_hashtags=self.publish_cfg.get("banned_hashtags", ()))

        print("🎙️ Voix...")
        scenes = asyncio.run(self._voice(scenes))
        self._subtitles(scenes)
        if map_target:
            print("🗺️ Carte animée...")
            self._render_map(map_target, scenes, assets)

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

