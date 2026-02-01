from __future__ import annotations

import io
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import matplotlib

from .uploader import upload_image_bytes

matplotlib.use("Agg")

from agno.tools.toolkit import Toolkit
from matplotlib import dates as mdates
from matplotlib import font_manager
from matplotlib import style as mpl_style
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

_FONT_FALLBACK = (
    "Noto Sans CJK SC, Noto Sans CJK, Source Han Sans SC, SimHei, "
    "PingFang SC, Heiti SC, Microsoft YaHei, Arial, sans-serif"
)
_FONT_DIRS = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    str(Path.home() / ".fonts"),
    "/System/Library/Fonts",
    "/Library/Fonts",
    "C:\\Windows\\Fonts",
)
_FONT_FILE_SUFFIXES = {".ttf", ".otf", ".ttc"}
_FONT_CANDIDATES: tuple[tuple[str, Iterable[str]], ...] = (
    ("Noto Sans CJK SC", ("notosanscjk", "noto-sans-cjk", "sourcehansans")),
    ("Source Han Sans SC", ("sourcehansans", "sourcehan")),
    ("SimHei", ("simhei",)),
    ("Microsoft YaHei", ("microsoftyahei", "msyh", "yahei")),
    ("PingFang SC", ("pingfang",)),
    ("Heiti SC", ("heiti", "stheiti")),
)


class MatplotlibRenderTools(Toolkit):
    def __init__(self, **kwargs):
        tools = [self.render_matplotlib_chart]
        instructions = (
            "Render a chart with Matplotlib and return a webp base64 image.\n"
            "Input: spec dict. Keys: title, x_label, y_label, grid, legend, "
            "x_format, x_scale, y_scale, x_lim, y_lim, style, traces, shapes, "
            "annotations.\n"
            "traces: list of {type: line|scatter|bar|area, x, y, label, color, "
            "linestyle, linewidth, marker, alpha}.\n"
            "shapes: list of {type: rect|vline|hline, x0,x1,y0,y1,x,y,color, "
            "alpha, linestyle, linewidth}.\n"
            "annotations: list of {x, y, text, arrow, dx, dy, fontsize, color}.\n"
            "Returns image_url for markdown embedding."
        )
        super().__init__(
            name="matplotlib_render_tools",
            tools=tools,
            instructions=instructions,
            **kwargs,
        )

    def render_matplotlib_chart(
        self,
        *,
        spec: dict[str, Any],
        format: str = "webp",
        width: int = 1280,
        height: int = 720,
        scale: float = 1.0,
        font_family: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(spec, dict) or not spec:
            return {"error": "invalid_spec"}

        scale = scale if scale > 0 else 1.0
        base_dpi = 100.0
        dpi = base_dpi * scale
        figsize = (width / base_dpi, height / base_dpi)
        render_width = int(round(width * scale))
        render_height = int(round(height * scale))

        _apply_style(spec.get("style"))
        _apply_font(font_family)

        fig = Figure(figsize=figsize, dpi=dpi)
        FigureCanvas(fig)
        ax = fig.add_subplot(1, 1, 1)

        title = spec.get("title")
        if title:
            ax.set_title(str(title))

        x_label = spec.get("x_label")
        if x_label:
            ax.set_xlabel(str(x_label))

        y_label = spec.get("y_label")
        if y_label:
            ax.set_ylabel(str(y_label))

        traces = _ensure_list(spec.get("traces"))
        x_type = _resolve_x_type(spec, traces)
        has_label = _draw_traces(ax, traces, x_type)

        shapes = _ensure_list(spec.get("shapes"))
        _draw_shapes(ax, shapes, x_type)

        annotations = _ensure_list(spec.get("annotations"))
        _draw_annotations(ax, annotations, x_type)

        if spec.get("grid", True):
            ax.grid(True, color="#E5E7EB", linestyle="-", alpha=0.6)

        if spec.get("legend", True) and has_label:
            ax.legend(loc="best")

        x_scale = spec.get("x_scale")
        if x_scale:
            ax.set_xscale(str(x_scale))

        y_scale = spec.get("y_scale")
        if y_scale:
            ax.set_yscale(str(y_scale))

        _apply_limits(ax, spec.get("x_lim"), spec.get("y_lim"), x_type)
        _apply_x_format(ax, spec.get("x_format"), x_type)

        fig.tight_layout()

        normalized_format = format.strip().lower() or "webp"
        buffer = io.BytesIO()
        try:
            fig.savefig(buffer, format=normalized_format, dpi=dpi)
        except Exception as exc:
            return {"error": "image_export_failed", "detail": str(exc)}

        upload_result = upload_image_bytes(
            buffer.getvalue(),
            expiration_sec=3 * 24 * 60 * 60,
        )

        return {
            "image_url": upload_result.url,
            "format": normalized_format,
            "width": render_width,
            "height": render_height,
            "scale": scale,
        }


def _apply_style(style: Any) -> None:
    if not style:
        return
    try:
        mpl_style.use(str(style))
    except Exception:
        return


def _apply_font(font_family: str | None) -> None:
    matplotlib.rcParams["axes.unicode_minus"] = False
    family = font_family or _resolve_font_family()
    if family:
        matplotlib.rcParams["font.family"] = [family]


def _resolve_x_type(spec: dict[str, Any], traces: list[dict[str, Any]]) -> str:
    x_type = spec.get("x_type")
    if isinstance(x_type, str) and x_type.lower() in {"datetime", "numeric"}:
        return x_type.lower()
    for trace in traces:
        values = trace.get("x")
        if _all_datetime(values):
            return "datetime"
    return "numeric"


def _draw_traces(ax, traces: list[dict[str, Any]], x_type: str) -> bool:
    has_label = False
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        trace_type = str(trace.get("type", "line")).lower()
        y = trace.get("y")
        if y is None:
            continue
        y_values = _ensure_list(y)
        if not y_values:
            continue
        x_values = trace.get("x")
        if x_values is None:
            x_values = list(range(len(y_values)))
        x_values = _normalize_x_values(x_values, x_type)

        label = trace.get("label")
        color = trace.get("color")
        linestyle = trace.get("linestyle")
        linewidth = _coerce_float(trace.get("linewidth"))
        marker = trace.get("marker")
        alpha = _coerce_float(trace.get("alpha"))

        label_value = str(label) if label else None

        if trace_type == "scatter":
            kwargs = {
                "label": label_value,
                "color": color,
                "alpha": alpha,
                "marker": marker,
            }
            if linewidth is not None:
                kwargs["linewidths"] = linewidth
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            ax.scatter(x_values, y_values, **kwargs)
        elif trace_type == "bar":
            kwargs = {
                "label": label_value,
                "color": color,
                "alpha": alpha,
                "linewidth": linewidth,
            }
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            ax.bar(x_values, y_values, **kwargs)
        elif trace_type == "area":
            kwargs = {
                "label": label_value,
                "color": color,
                "alpha": alpha,
            }
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            ax.fill_between(x_values, y_values, **kwargs)
        elif trace_type == "step":
            kwargs = {
                "label": label_value,
                "color": color,
                "linestyle": linestyle,
                "linewidth": linewidth,
                "marker": marker,
                "alpha": alpha,
            }
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            ax.step(x_values, y_values, **kwargs)
        else:
            kwargs = {
                "label": label_value,
                "color": color,
                "linestyle": linestyle,
                "linewidth": linewidth,
                "marker": marker,
                "alpha": alpha,
            }
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            ax.plot(x_values, y_values, **kwargs)

        if label_value:
            has_label = True
    return has_label


def _draw_shapes(ax, shapes: list[dict[str, Any]], x_type: str) -> None:
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        shape_type = str(shape.get("type", "")).lower()
        color = shape.get("color")
        facecolor = shape.get("facecolor")
        edgecolor = shape.get("edgecolor")
        linestyle = shape.get("linestyle")
        linewidth = _coerce_float(shape.get("linewidth")) or 1.0
        alpha = _coerce_float(shape.get("alpha"))

        if shape_type == "rect":
            x0 = _convert_x(shape.get("x0"), x_type)
            x1 = _convert_x(shape.get("x1"), x_type)
            y0 = _coerce_float(shape.get("y0"))
            y1 = _coerce_float(shape.get("y1"))
            if x0 is None or x1 is None or y0 is None or y1 is None:
                continue
            if x_type == "datetime":
                x0 = mdates.date2num(x0)
                x1 = mdates.date2num(x1)
            rect = Rectangle(
                (x0, y0),
                x1 - x0,
                y1 - y0,
                facecolor=facecolor or color or "#CBD5E1",
                edgecolor=edgecolor or color or "#CBD5E1",
                linewidth=linewidth,
                linestyle=linestyle or "-",
                alpha=alpha if alpha is not None else 0.2,
            )
            ax.add_patch(rect)
        elif shape_type == "vline":
            x = _convert_x(shape.get("x"), x_type)
            if x is None:
                continue
            ax.axvline(
                x=x,
                color=color or "#111111",
                linestyle=linestyle or "--",
                linewidth=linewidth,
                alpha=alpha,
            )
        elif shape_type == "hline":
            y = _coerce_float(shape.get("y"))
            if y is None:
                continue
            ax.axhline(
                y=y,
                color=color or "#111111",
                linestyle=linestyle or "--",
                linewidth=linewidth,
                alpha=alpha,
            )


def _draw_annotations(ax, annotations: list[dict[str, Any]], x_type: str) -> None:
    for note in annotations:
        if not isinstance(note, dict):
            continue
        x = _convert_x(note.get("x"), x_type)
        y = _coerce_float(note.get("y"))
        text = note.get("text")
        if x is None or y is None or not text:
            continue
        arrow = bool(note.get("arrow", True))
        dx = _coerce_float(note.get("dx"))
        dy = _coerce_float(note.get("dy"))
        fontsize = _coerce_float(note.get("fontsize"))
        color = note.get("color")

        annotate_kwargs = {
            "xy": (x, y),
            "text": str(text),
            "color": color or "#111111",
            "fontsize": fontsize or 12,
        }
        if dx is not None and dy is not None:
            annotate_kwargs.update({"xytext": (dx, dy), "textcoords": "offset points"})
        if arrow:
            annotate_kwargs["arrowprops"] = {
                "arrowstyle": "->",
                "color": color or "#111111",
            }
        ax.annotate(**annotate_kwargs)


def _apply_limits(ax, x_lim: Any, y_lim: Any, x_type: str) -> None:
    if isinstance(x_lim, (list, tuple)) and len(x_lim) == 2:
        x0 = _convert_x(x_lim[0], x_type)
        x1 = _convert_x(x_lim[1], x_type)
        if x0 is not None and x1 is not None:
            ax.set_xlim(x0, x1)
    if isinstance(y_lim, (list, tuple)) and len(y_lim) == 2:
        y0 = _coerce_float(y_lim[0])
        y1 = _coerce_float(y_lim[1])
        if y0 is not None and y1 is not None:
            ax.set_ylim(y0, y1)


def _apply_x_format(ax, x_format: Any, x_type: str) -> None:
    if x_type != "datetime":
        return
    ax.xaxis_date()
    if x_format:
        ax.xaxis.set_major_formatter(mdates.DateFormatter(str(x_format)))
    ax.figure.autofmt_xdate()


def _normalize_x_values(values: Any, x_type: str) -> list[Any]:
    items = _ensure_list(values)
    if x_type != "datetime":
        return items
    converted = []
    for value in items:
        dt_value = _coerce_datetime(value)
        if dt_value is None:
            return items
        converted.append(dt_value)
    return converted


def _convert_x(value: Any, x_type: str) -> Any:
    if x_type != "datetime":
        return value
    return _coerce_datetime(value)


def _all_datetime(values: Any) -> bool:
    items = _ensure_list(values)
    if not items:
        return False
    for item in items:
        if _coerce_datetime(item) is None:
            return False
    return True


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.utcfromtimestamp(seconds)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return None


@lru_cache(maxsize=1)
def _resolve_font_family() -> str:
    font_paths = font_manager.findSystemFonts(fontpaths=_FONT_DIRS)
    for font_path in font_paths:
        path = Path(font_path)
        if path.suffix.lower() not in _FONT_FILE_SUFFIXES:
            continue
        normalized = _normalize_font_token(path.stem)
        for family, tokens in _FONT_CANDIDATES:
            for token in tokens:
                if _normalize_font_token(token) in normalized:
                    try:
                        font_manager.fontManager.addfont(font_path)
                    except Exception:
                        pass
                    try:
                        return font_manager.FontProperties(fname=font_path).get_name()
                    except Exception:
                        return family
    return _FONT_FALLBACK


def _normalize_font_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())
