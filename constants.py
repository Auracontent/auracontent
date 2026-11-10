from types import MappingProxyType

# Default text
DEFAULT_SUBTITLE_STYLE = (
    "FontName=DejaVu Sans,FontSize=24,Bold=1,PrimaryColour=&H00FFFFFF"
)
DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Encodage vidéo et audio
H264_AAC = MappingProxyType(
    {
        "vcodec": "libx264",
        "acodec": "aac",
        "audio_bitrate": "192k",
        "pix_fmt": "yuv420p",
        "movflags": "faststart",
        "preset": "medium",
    }
)
VIDEO_CRF = 18
AUDIO_FORMAT = MappingProxyType(
    {
        "sample_fmts": "fltp",
        "sample_rates": 48000,
        "channel_layouts": "stereo",
    }
)
LOUDNORM = MappingProxyType({"I": -16, "TP": -1.5, "LRA": 9})

# Effet Ken Burns et durées
KEN_BURNS_SOURCE_WIDTH = 2200
ZOOM_IN_EXPR = "min(zoom+0.0009,1.14)"
ZOOM_OUT_EXPR = "if(eq(on,1),1.07,max(zoom-0.0008,1.0))"
SECOND_IMAGE_EXTRA_DURATION = 0.35
MIN_SEGMENT_DURATION = 0.1

WIKI_API_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API_URL = "https://fr.wikipedia.org/w/api.php"
