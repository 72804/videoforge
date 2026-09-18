from __future__ import annotations

from pathlib import Path

from docprod.models.enums import AssetStrategy
from docprod.render.ffmpeg import escape_drawtext, escape_filter_path

STRATEGY_COLORS: dict[AssetStrategy, str] = {
    AssetStrategy.stock_video: "0x1a3d4d",
    AssetStrategy.archive_video: "0x2a3d22",
    AssetStrategy.stock_image: "0x1a3545",
    AssetStrategy.archive_image: "0x2a3520",
    AssetStrategy.ai_image: "0x3d2a22",
    AssetStrategy.ai_image_to_video: "0x4a2033",
    AssetStrategy.document: "0x3d3a28",
    AssetStrategy.map: "0x1a3328",
    AssetStrategy.generated_graphic: "0x2a2240",
    AssetStrategy.text_card: "0x222233",
    AssetStrategy.placeholder: "0x2a2a2e",
}


def placeholder_filter(
    *,
    strategy: AssetStrategy,
    scene_id: str,
    category: str,
    width: int,
    height: int,
    duration: float,
    fps: int,
    font: Path,
) -> str:
    color = STRATEGY_COLORS.get(strategy, "0x2a2a2e")
    fontfile = escape_filter_path(font)
    fs_id = max(12, height // 9)
    fs_meta = max(10, height // 12)
    label_id = escape_drawtext(scene_id)
    label_strat = escape_drawtext(strategy.value)
    label_cat = escape_drawtext((category or "generic").replace("_", " ")[:24])
    extras = ""
    if strategy is AssetStrategy.document:
        extras = (
            ",drawbox=x=iw*0.18:y=ih*0.22:w=iw*0.64:h=ih*0.58:color=white@0.20:t=fill"
            ",drawbox=x=iw*0.18:y=ih*0.22:w=iw*0.64:h=ih*0.58:color=white@0.55:t=2"
        )
    elif strategy is AssetStrategy.map:
        extras = (
            ",drawbox=x=iw*0.16:y=ih*0.45:w=iw*0.68:h=2:color=white@0.45:t=fill"
            ",drawbox=x=iw*0.48:y=ih*0.20:w=2:h=ih*0.58:color=white@0.35:t=fill"
        )
    elif strategy is AssetStrategy.ai_image_to_video:
        extras = ",drawbox=x=iw*0.12:y=ih*0.55:w=iw*0.28:h=ih*0.18:color=white@0.22:t=fill"
    elif strategy is AssetStrategy.generated_graphic:
        extras = ",drawbox=x=iw*0.10:y=ih*0.72:w=iw*0.80:h=ih*0.08:color=white@0.25:t=fill"
    return (
        f"color=c={color}:s={width}x{height}:d={duration:.4f}:r={fps},"
        f"drawgrid=w=iw/16:h=ih/9:t=1:c=white@0.14,"
        f"drawbox=x=iw*0.05:y=ih*0.07:w=iw*0.90:h=ih*0.86:color=white@0.40:t=3"
        f"{extras},"
        f"drawtext=fontfile={fontfile}:text='{label_id}':fontsize={fs_id}:"
        f"fontcolor=white:borderw=2:bordercolor=black:x=w*0.08:y=h*0.12,"
        f"drawtext=fontfile={fontfile}:text='{label_strat}':fontsize={fs_meta}:"
        f"fontcolor=white:borderw=2:bordercolor=black:x=w*0.08:y=h*0.28,"
        f"drawtext=fontfile={fontfile}:text='{label_cat}':fontsize={fs_meta}:"
        f"fontcolor=white:borderw=2:bordercolor=black:x=w*0.08:y=h*0.42"
    )
