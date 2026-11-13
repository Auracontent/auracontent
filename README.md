<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/shared/images/logo_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="assets/shared/images/logo_light.png">
    <img src="assets/shared/images/logo_light.png" alt="AuraContent" width="480">
  </picture>
</p>


<p align="center">
  From a channel config to a published YouTube Short / TikTok: script, voiceover, visuals, editing, storage and publishing — fully automated.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10–3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/uv-managed-DE5FE9?logo=uv&logoColor=white" alt="uv">
  <img src="https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/GitHub_Actions-automated-2088FF?logo=github-actions&logoColor=white" alt="GitHub Actions">
  <img src="https://img.shields.io/badge/Hugging_Face-storage-FFD21E?logo=huggingface&logoColor=black" alt="Hugging Face">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
</p>

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Pipeline](#-pipeline)
- [Project Structure](#-project-structure)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [GitHub Actions](#-github-actions)
- [Channel: C’est arrivé ici](#-channel-cest-arrivé-ici)
- [Adding a Channel](#-adding-a-channel)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🚀 Overview

**AuraContent** is a Python pipeline that produces and publishes short vertical videos (YouTube Shorts, TikTok) without a face on camera.

Each **channel** is described by a YAML file. The first one is [**C’est arrivé ici**](#-channel-cest-arrivé-ici) (internal name `mystery`): the hidden stories of French heritage. For every run, the pipeline:

1. picks a topic and writes a fact-checked script with an LLM (sources: Wikipedia);
2. generates the narration (Gemini TTS, with `edge-tts` as fallback);
3. gathers visuals from stock, archive and AI image providers;
4. edits everything with FFmpeg (subtitles, music, transitions);
5. uploads the video and its caption to a Hugging Face dataset;
6. publishes it to YouTube and TikTok through the Zernio API.

Everything can run in **GitHub Actions**: no server required.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **Multi-provider LLM** | 8 providers (Gemini, Groq, OpenRouter, DeepSeek, Cloudflare, GitHub Models, Z.ai, Qwen) with automatic fallback and rate-limit handling. Configure as many free tiers as you have. |
| 📚 **Fact-checked scripts** | Topics and facts are grounded on Wikipedia; locations are constrained per channel. |
| 🎣 **Hook optimisation** | A bandit tracker learns which hooks perform best using Zernio analytics. |
| 🗣️ **Voiceover** | Gemini TTS narration in a single request, split on silences; `edge-tts` fallback. |
| 🖼️ **Visuals** | Pexels, Pixabay, Wikimedia, Europeana, Internet Archive, Cloudflare FLUX and Pollinations, with local fallback images. |
| 🗺️ **Animated map** | "Where it happened" scene: France, zoom to the region, pulsing yellow dot and place name. Coordinates from the Wikipedia source page, else Nominatim. Settings in `visuals.map_scene`. |
| ✂️ **Automated editing** | FFmpeg composition with subtitles, background music, SFX and loudness check. |
| 🤗 **Shared state** | Videos, captions and history (used topics, hook stats) are synced to Hugging Face, so runs never repeat themselves. |
| 📱 **Publishing** | YouTube + TikTok via Zernio, with TikTok draft fallback. |
| 🩺 **Doctor** | A pre-flight command that really tests every key and fails fast in CI. |

---

## 🔄 Pipeline

```text
config/channels/<channel>.yaml
            │
            ▼
   Topic + script (LLM, Wikipedia)        auracontent/core/brain
            │
            ▼
   Voiceover (Gemini TTS / edge-tts)      auracontent/services/audios
            │
            ▼
   Visuals (stock / archives / AI)        auracontent/services/{scraping,visuals}
            │
            ▼
   Editing (FFmpeg)                       auracontent/services/video
            │
            ▼
   Upload video + caption (Hugging Face)  auracontent/services/publishing
            │
            ▼
   Publish (Zernio → YouTube, TikTok)     auracontent/cli/publish.py
```

---

## 🗂️ Project Structure

```text
auracontent_v2/
├── auracontent/
│   ├── cli/            # entry points: generate, publish, doctor
│   ├── core/           # pipeline + brain (LLM client, script generation)
│   ├── channels/       # one Brain per channel + registry
│   ├── services/       # audio, visuals, scraping, video, publishing
│   └── utils/          # subtitles, trackers, helpers
├── config/
│   ├── settings.py
│   └── channels/       # one YAML per channel (mystery, finance)
├── assets/             # fonts, music, SFX, fallback images (per channel + shared)
├── scripts/            # standalone helpers (e.g. render_scene.py)
├── tests/
├── .github/workflows/  # generation, publishing, tests, release
├── init.sh             # Onyxia service bootstrap
├── packages.txt        # system packages (ffmpeg, fonts)
└── pyproject.toml      # dependencies (uv dependency groups)
```

---

## 🧰 Prerequisites

- **Python 3.10 – 3.12** (CI uses 3.12)
- **[uv](https://docs.astral.sh/uv/)**
- **FFmpeg** on your `PATH` (and the fonts listed in `packages.txt`)
- At least **one LLM API key**; Hugging Face and Zernio accounts to upload and publish

---

## 📦 Installation

```bash
git clone https://github.com/SORADATA/auracontent_v2.git
cd auracontent_v2

# system packages (Debian/Ubuntu)
sudo apt-get install -y $(grep -vE '^\s*(#|$)' packages.txt)

# Python dependencies
uv sync --group default --group media          # add --group dev for tests/linters
```

On an **Onyxia** service, `bash init.sh` does all of the above.

> The `ai` and `ui` groups are v1 leftovers and are not needed by the v2 pipeline.

---

## 🔐 Configuration

```bash
cp .env.example .env
```

Then fill in the keys you have. [`.env.example`](.env.example) documents every variable; the essentials are:

| Variable | Needed for |
|---|---|
| one of `GEMINI_API_KEY`, `GROQ_API_KEY`, `GITHUB_TOKEN`, … | script generation (**required**) |
| `WIKIMEDIA_CONTACT` | Wikipedia/Wikimedia User-Agent (strongly recommended) |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `POLLINATIONS_TOKEN`, … | visuals (optional, more = better) |
| `HF_TOKEN` | upload + state sync (`--upload`, `--sync-state`) |
| `ZERNIO_API_KEY_<CHANNEL>`, `TIKTOK_ACCOUNT_ID_<CHANNEL>`, `YOUTUBE_ACCOUNT_ID_<CHANNEL>` | publishing (e.g. `_MYSTERY`; names set in the channel YAML) |

Channel behaviour (duration, voice, topic rules, publishing targets…) lives in `config/channels/<channel>.yaml`. The YAML only contains the **names** of environment variables, never their values.

Check your setup:

```bash
uv run python -m auracontent.cli.doctor
```

---

## ▶️ Usage

```bash
# generate a video for every registered channel
uv run python -m auracontent.cli.generate

# one channel
uv run python -m auracontent.cli.generate mystery

# script only (no audio/video), handy to iterate on prompts
uv run python -m auracontent.cli.generate mystery --script-only

# as in CI: upload to Hugging Face and sync history
uv run python -m auracontent.cli.generate mystery --upload --sync-state

# publish the latest uploaded video of a channel
uv run python -m auracontent.cli.publish mystery
```

Outputs are written to `output/` and `temp/` (both git-ignored).

---

## ⚙️ GitHub Actions

| Workflow | Trigger | What it does |
|---|---|---|
| `generator_video.yml` | manual, `repository_dispatch` (`trigger-videos`) | doctor → generate → upload to HF |
| `publisher.yml` | manual | publishes the latest video via Zernio |
| `tests.yml` | push / PR | ruff + pytest |
| `release.yml` | push to `main` / `pre-release` | semantic-release: version, `CHANGELOG.md`, GitHub release |
| `test_zernio_con.yml` | manual | Zernio API connectivity check |

Add the variables from `.env.example` as **repository secrets** (Settings → Secrets and variables → Actions). `GITHUB_TOKEN` is provided automatically; `RELEASE_TOKEN` is a personal access token used by the release workflow.

---

## 📍 Channel: C’est arrivé ici

French-language Shorts and TikToks. The channel was renamed in 2026 because more than forty channels used its previous name. **Internal name stays `mystery`**: the code folder, the Hugging Face folder `videos` and the `*_MYSTERY` secrets keep their names, so history and secrets keep working.

**Editorial line.** Every video starts from a real **place or object of French heritage** that can be named and shown (a lost treasure, a monument with a hidden story, a castle with an improbable fate, an absurd local law…), grounded on a Wikipedia page. Crime stories and general science are out. Overseas France is included.

**Visual identity.**

| Element | Rule |
|---|---|
| Accent colour | Yellow `#FFD400` only (`0xFFD400` in FFmpeg) |
| Font | Montserrat Bold (`assets/shared/fonts`) |
| On-screen text | Capitals, white with black outline |
| Headline | Permanent two-part banner « STATEMENT \| PUNCHLINE », punchline black on yellow |
| Subtitles | Capitals, cut at punctuation, numbers in yellow |
| Watermark | `cest_arrive_ici_watermark.png`, top left, 190 px, 85 % opacity |
| Safe zone (1080 × 1920) | Nothing important above y = 200, below y = 1440, or right of x = 930 |
| Hashtags | `#histoire #patrimoine #france #cestarriveici`; the old channel hashtag is stripped automatically |

**YAML options** (`config/channels/mystery.yaml`). Absent options keep the previous behaviour, so other channels are unaffected.

| Option | Lot | Effect |
|---|---|---|
| `video_composer.headline_*` | 0 | Permanent headline banner (position, size, accent colour) |
| `video_composer.subtitle_uppercase`, `subtitle_highlight_color` | 0 | Subtitle style |
| `visuals.map_scene.enabled`, `scene_index` | 1 | Animated "where it happened" map on scene 2 |
| `visuals.map_scene.zoom`, `overseas_view_km`, `overseas_zoom` | 1 | Map framing (mainland / overseas) |
| `visuals.map_scene.geocode_fallback`, `geocoder_url` | 1 | Nominatim fallback when the source page has no coordinates |
| `visuals.map_scene.tagline` | 10 | Optional brand line under the place name, e.g. `"C’EST ARRIVÉ ICI"` |
| `video_composer.source_credit_labels.map`, `.osm` | 1 | Map credits (Natural Earth, OpenStreetMap) |
| `video_composer.watermark_*` | 10 | Watermark file, width, opacity |
| `publish.fallback_hashtags`, `brand_hashtag`, `banned_hashtags` | 10 | Hashtags: fallback set, brand tag added if missing, old tags removed |

**Visual check offline:** `uv run python -m scripts.render_scene --map` renders the map scene with the headline, subtitles, credit and watermark, and saves frames to `output/map_preview/`.

---

## ➕ Adding a Channel

1. Create `config/channels/<name>.yaml` (start from `mystery.yaml`).
2. Create `auracontent/channels/<name>/brain.py` with a `BaseBrain` subclass.
3. Register it in `auracontent/channels/registry.py`.
4. Add its assets under `assets/<name>/`.

Currently registered: **`mystery`** and **`finance`** (« Capital Simple », in progress). `kids` is not ported to v2.

A channel can keep its own history files on Hugging Face (`meta/<channel>/`) with `state: {isolated: true}` in its YAML; channels without it keep the shared files.

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---|---|
| `Aucun fournisseur LLM configuré` | set at least one LLM key, then run the doctor |
| HTTP 429 from an LLM | normal on free tiers: the client waits and falls back; add more providers |
| HTTP 402 on AI images | set `POLLINATIONS_TOKEN` or Cloudflare credentials |
| Cloudflare 401/403 | the token needs the **Workers AI** permission (an R2 token is not enough) |
| Wikipedia 403 | set `WIKIMEDIA_CONTACT` to a real contact |
| `ffmpeg` not found | install it (`packages.txt`) and make sure it is on your `PATH` |

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Commits must follow [Conventional Commits](https://www.conventionalcommits.org/): releases are computed from them.

---

## 📄 License

[MIT](LICENSE)

**Third-party data**
- Map backgrounds (`assets/shared/maps/`) come from [Natural Earth](https://www.naturalearthdata.com/), which is in the **public domain**. "Made with Natural Earth."
- When the source page has no coordinates, the place is geocoded with [Nominatim](https://nominatim.org/) (© OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright)). The pipeline follows its [usage policy](https://operations.osmfoundation.org/policies/nominatim/): at most one request per second, an identifying User-Agent (`WIKIMEDIA_CONTACT`), cached results (`geocode_cache.json`, synced with the history) and on-screen attribution. The service can be swapped via `visuals.map_scene.geocoder_url`, or disabled with `geocode_fallback: false`.
