#!/usr/bin/env python3
"""export.py — three-format export orchestration + export report (contract §3/§4).

Owner: validate-export.  Writes nothing but the artefacts under ``out_dir`` and the
returned report dict; ``ar.py`` is the only writer of ``export_report.json``.

Public API (frozen, contract §4):
    export_all(scene, spec, fs, out_dir, formats=("svg","png","pdf")) -> dict

Returned dict keys (ar.py + result.json read these):
    artifacts      {name: {path, bytes, sha256}}
    page_mm        [w, h]                 (mm)
    dpi            int
    pdf            {pages, fonts_embedded, vector, ...}
    png            {px: [w, h], dpi, ...}
    determinism    {identical, hashes, identical_by_format}
    colorspace     "sRGB"

Also exposes the byte-level sniffers used by validate.py gate H so that the
measurement lives in exactly one place:
    sniff_png(path) -> dict
    sniff_pdf(path) -> dict

The backend modules (svg_backend / raster_backend, owned by render-core) are
imported lazily so this module stays importable (and testable with fixtures)
when the rendering half is not installed yet.  A missing backend is an explicit
error, never a silent skip.
"""
from __future__ import annotations
import sys as _sys
_sys.dont_write_bytecode = True

import hashlib
import importlib
import os
import re
import shutil
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import scene  # noqa: E402  (frozen shared model)

MM_PER_IN = 25.4
FORMAT_EXT = {"svg": "figure.svg", "png": "figure.png", "pdf": "figure.pdf"}
ARTIFACT_ORDER = ("figure.svg", "figure.png", "figure.pdf")


class ExportError(RuntimeError):
    """A backend is missing or failed; the caller must surface this, not ignore it."""


# --------------------------------------------------------------------------- #
# deterministic small helpers
# --------------------------------------------------------------------------- #
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def portable_path(path):
    """The file name in ``path``, with no directory part, on any host.

    ``os.path.basename`` alone is not enough: a ``C:\\a\\b\\figure.svg`` string
    seen on a POSIX host has no ``/`` in it, so basename would return the whole
    absolute path.  Normalising both separators first makes the result identical
    wherever the report is generated or read.
    """
    s = str(path or "").replace("\\", "/").rstrip("/")
    return s.rsplit("/", 1)[-1]


def _import_backend(name):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ExportError("backend module %r is not available: %s" % (name, exc))


def resolve_canvas(scene_obj, spec):
    """Page geometry: scene.canvas wins, then spec.meta.canvas, then defaults."""
    canvas = dict(scene.DEFAULT_CANVAS)
    meta_canvas = ((spec or {}).get("meta") or {}).get("canvas") or {}
    for k, v in meta_canvas.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            canvas[k] = float(v)
    sc = (scene_obj or {}).get("canvas") or {}
    for k, v in sc.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            canvas[k] = float(v)
    return canvas


# --------------------------------------------------------------------------- #
# byte-level sniffers (single source of truth for gate H)
# --------------------------------------------------------------------------- #
def _inflate_pdf_streams(raw):
    """Return the concatenation of every zlib-decodable PDF stream body."""
    parts = []
    idx = 0
    while True:
        s = raw.find(b"stream", idx)
        if s < 0:
            break
        e = raw.find(b"endstream", s)
        if e < 0:
            break
        body = raw[s + 6:e]
        if body.startswith(b"\r\n"):
            body = body[2:]
        elif body[:1] in (b"\n", b"\r"):
            body = body[1:]
        try:
            parts.append(zlib.decompress(body))
        except Exception:
            try:
                parts.append(zlib.decompressobj().decompress(body))
            except Exception:
                pass
        idx = e + 9
    return b"".join(parts)


def sniff_png(path):
    """Parse PNG chunks without third-party imports.

    Returns {"px":[w,h], "dpi":float|None, "dpi_x":..., "dpi_y":...,
             "has_phys":bool, "bit_depth":int|None, "color_type":int|None,
             "chunks":[names], "bytes":n}
    """
    out = {"px": None, "dpi": None, "dpi_x": None, "dpi_y": None, "has_phys": False,
           "bit_depth": None, "color_type": None, "chunks": [], "bytes": _size(path)}
    if not os.path.exists(path):
        out["error"] = "missing"
        return out
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        out["error"] = "not a PNG signature"
        return out
    pos = 8
    while pos + 12 <= len(raw):
        ln = int.from_bytes(raw[pos:pos + 4], "big")
        typ = raw[pos + 4:pos + 8].decode("latin-1")
        data = raw[pos + 8:pos + 8 + ln]
        out["chunks"].append(typ)
        if typ == "IHDR" and ln >= 13:
            out["px"] = [int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big")]
            out["bit_depth"] = data[8]
            out["color_type"] = data[9]
        elif typ == "pHYs" and ln >= 9:
            ppm_x = int.from_bytes(data[0:4], "big")
            ppm_y = int.from_bytes(data[4:8], "big")
            unit = data[8]
            if unit == 1:  # metres
                out["dpi_x"] = round(ppm_x * 0.0254, 4)
                out["dpi_y"] = round(ppm_y * 0.0254, 4)
                out["dpi"] = out["dpi_x"]
                out["has_phys"] = True
        elif typ in ("tEXt", "iTXt") and b"dpi" in data[:64].lower():
            m = re.search(rb"dpi\s*=\s*([0-9.]+)", data)
            if m and out["dpi"] is None:
                try:
                    out["dpi"] = float(m.group(1))
                except ValueError:
                    pass
        elif typ == "IEND":
            break
        pos += 12 + ln
    return out


def sniff_pdf(path):
    """Raw byte inspection of a PDF (works for uncompressed and Flate-streams).

    Returns {"pages":int, "mediabox_pt":[w,h]|None, "fonts_embedded":bool,
             "font_programs":n, "vector_text":bool, "text_ops":n,
             "image_objects":n, "bytes":n, "error":...}
    """
    out = {"pages": 0, "mediabox_pt": None, "fonts_embedded": False, "font_programs": 0,
           "vector_text": False, "text_ops": 0, "image_objects": 0, "bytes": _size(path),
           "header": None}
    if not os.path.exists(path):
        out["error"] = "missing"
        return out
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw.startswith(b"%PDF"):
        out["error"] = "not a PDF header"
        return out
    out["header"] = raw[:8].decode("latin-1", "replace")
    dec = _inflate_pdf_streams(raw)
    blob = raw + b"\n" + dec

    out["pages"] = len(re.findall(rb"/Type\s*/Page(?![sA-Za-z0-9])", blob))
    if out["pages"] == 0:
        m = re.search(rb"/Count\s+(\d+)", blob)
        if m:
            try:
                out["pages"] = int(m.group(1))
            except ValueError:
                out["pages"] = 0
    boxes = re.findall(
        rb"/MediaBox\s*\[\s*([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s*\]", blob)
    if boxes:
        x0, y0, x1, y1 = (float(v) for v in boxes[0])
        out["mediabox_pt"] = [round(abs(x1 - x0), 4), round(abs(y1 - y0), 4)]
    out["font_programs"] = len(re.findall(rb"/FontFile[23]?\b", blob))
    out["fonts_embedded"] = out["font_programs"] > 0
    out["text_ops"] = len(re.findall(rb"\bTj\b", blob)) + len(re.findall(rb"\bTJ\b", blob))
    out["vector_text"] = out["text_ops"] > 0
    out["image_objects"] = len(re.findall(rb"/Subtype\s*/Image", blob))
    return out


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _collect(name, path, extra=None):
    rec = {"path": os.path.basename(path), "bytes": _size(path), "sha256": sha256_file(path)}
    if extra:
        rec.update(extra)
    return rec


def _export_into(scene_obj, spec, fs, out_dir, formats, canvas):
    """Write the requested formats into out_dir; return (artifacts, per-format info, warnings)."""
    artifacts, info, warnings = {}, {}, []
    dpi = int(round(canvas["dpi"]))
    for fmt in formats:
        name = FORMAT_EXT.get(fmt)
        if name is None:
            warnings.append("unknown format %r ignored" % (fmt,))
            continue
        path = os.path.join(out_dir, name)
        if fmt == "svg":
            backend = _import_backend("svg_backend")
            fn = getattr(backend, "write_svg", None)
            if fn is None:
                raise ExportError("svg_backend has no write_svg(scene, path, fs, spec)")
            ret = fn(scene_obj, path, fs, spec) or {}
        elif fmt == "png":
            backend = _import_backend("raster_backend")
            fn = getattr(backend, "write_png", None)
            if fn is None:
                raise ExportError("raster_backend has no write_png(scene, path, fs, dpi)")
            ret = fn(scene_obj, path, fs, dpi) or {}
        else:  # pdf
            backend = _import_backend("raster_backend")
            fn = getattr(backend, "write_pdf", None)
            if fn is None:
                raise ExportError("raster_backend has no write_pdf(scene, path, fs)")
            ret = fn(scene_obj, path, fs) or {}
        if not os.path.exists(path):
            raise ExportError("%s backend reported success but %s does not exist" % (fmt, path))
        info[fmt] = ret
        artifacts[name] = _collect(name, path, {"format": fmt, "reported": {
            k: ret.get(k) for k in ("text_nodes", "groups", "px", "dpi", "pages", "page_mm",
                                    "fonts_embedded", "vector") if k in ret}})
    return artifacts, info, warnings


def export_all(scene_obj, spec, fs, out_dir, formats=("svg", "png", "pdf")):
    """Export the scene to SVG/PNG/PDF and return the contract §4 report dict."""
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    fmt_list = [str(f).strip().lower() for f in (formats or ()) if str(f).strip()]
    if not fmt_list:
        fmt_list = ["svg", "png", "pdf"]
    canvas = resolve_canvas(scene_obj, spec)
    dpi = int(round(canvas["dpi"]))

    artifacts, info, warnings = _export_into(scene_obj, spec, fs, out_dir, fmt_list, canvas)

    # ---- measured properties of the artefacts we just wrote -----------------
    png = {}
    png_path = os.path.join(out_dir, "figure.png")
    if os.path.exists(png_path):
        s = sniff_png(png_path)
        png = {"px": s.get("px"), "dpi": s.get("dpi"), "dpi_x": s.get("dpi_x"),
               "dpi_y": s.get("dpi_y"), "has_phys": s.get("has_phys"),
               "expected_px": [int(round(canvas["w_mm"] / MM_PER_IN * dpi)),
                               int(round(canvas["h_mm"] / MM_PER_IN * dpi))]}

    pdf = {}
    pdf_path = os.path.join(out_dir, "figure.pdf")
    if os.path.exists(pdf_path):
        p = sniff_pdf(pdf_path)
        pdf = {"pages": p.get("pages"), "fonts_embedded": p.get("fonts_embedded"),
               "vector": p.get("vector_text"), "font_programs": p.get("font_programs"),
               "text_ops": p.get("text_ops"), "mediabox_pt": p.get("mediabox_pt"),
               "image_objects": p.get("image_objects"),
               "expected_mediabox_pt": [round(canvas["w_mm"] * 72.0 / MM_PER_IN, 4),
                                        round(canvas["h_mm"] * 72.0 / MM_PER_IN, 4)]}

    svg_info = {}
    svg_path = os.path.join(out_dir, "figure.svg")
    if os.path.exists(svg_path):
        with open(svg_path, "r", encoding="utf-8", errors="replace") as fh:
            svg_txt = fh.read()
        svg_info = {"text_nodes": len(re.findall(r"<text\b", svg_txt)),
                    "groups": len(re.findall(r"<g\b", svg_txt)),
                    "named_groups": len(re.findall(r"<g\b[^>]*\bid=\"", svg_txt)),
                    "images": len(re.findall(r"<image\b", svg_txt)),
                    "bytes": len(svg_txt.encode("utf-8"))}

    # ---- determinism: re-export into a scratch dir and compare sha256 --------
    det_hashes, identical = {}, True
    det_tmp = os.path.join(out_dir, ".determinism_tmp")
    try:
        if os.path.isdir(det_tmp):
            shutil.rmtree(det_tmp, ignore_errors=True)
        os.makedirs(det_tmp)
        _export_into(scene_obj, spec, fs, det_tmp, fmt_list, canvas)
        for name in sorted(artifacts):
            p2 = os.path.join(det_tmp, name)
            h1 = artifacts[name]["sha256"]
            h2 = sha256_file(p2) if os.path.exists(p2) else None
            same = (h1 == h2)
            identical = identical and same
            det_hashes[name] = {"run1": h1, "run2": h2, "identical": same}
    except Exception as exc:  # determinism is a check, not a crash
        identical = False
        det_hashes["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        shutil.rmtree(det_tmp, ignore_errors=True)

    prims = (scene_obj or {}).get("primitives") or []
    types = {}
    for p in prims:
        t = (p or {}).get("type", "?")
        types[t] = types.get(t, 0) + 1

    report = {
        "artifacts": artifacts,
        "page_mm": [canvas["w_mm"], canvas["h_mm"]],
        "dpi": dpi,
        "margin_mm": canvas.get("margin_mm", 3.0),
        "formats": fmt_list,
        "pdf": pdf,
        "png": png,
        "svg": svg_info,
        "determinism": {"identical": bool(identical), "hashes": det_hashes,
                        "identical_by_format": {k: bool(v.get("identical")) for k, v in det_hashes.items()
                                                if isinstance(v, dict)}},
        "colorspace": "sRGB",
        "primitives": len(prims),
        "primitive_types": types,
        "warnings": warnings,
        # Relative file name only.  The backends report the *absolute* path they were
        # handed, and putting that in the report broke reproducibility two ways: the
        # report (and therefore result.json, which hashes it) changed whenever the
        # output directory changed, and it embedded an author-machine profile
        # directory in a delivered artefact.  Gate G compares only the three
        # figures, so it could not see this.  basename keeps the useful information
        # ("which file did each backend write") without either problem.
        "backends": {k: portable_path(v.get("path"))
                     for k, v in info.items()
                     if isinstance(v, dict) and v.get("path")},
    }
    # surface backend-reported determinism downgrades honestly
    for fmt, ret in info.items():
        if isinstance(ret, dict) and ret.get("degraded"):
            report["warnings"].append("%s backend degraded: %s" % (fmt, ret.get("degraded")))
    return report
