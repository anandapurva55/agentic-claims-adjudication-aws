"""Assemble recorded frames into GIFs. Usage: python docs/demo/make_gif.py <frames_dir> <out_dir> [colors] [fps] [width]

Scene a becomes guardrail_demo.gif, b human_in_the_loop.gif, c attack_lab.gif, d photo_evidence_and_signals.gif, and e observability.gif. Scene f only records stills (the architecture tab is static, so it is not a GIF). Pillow only, no ffmpeg needed.

Why they are sharp and small:
  * frames are lossless PNG at the size they are shown (no resizing), so text is never resampled
  * one shared palette per clip, built from frames spread across it, so colours do not drift between frames
  * frames that did not change are merged into the previous frame with a longer duration, so waiting costs nothing
  * Pillow stores only the pixels that changed between frames
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops

frames_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
COLORS = int(sys.argv[3]) if len(sys.argv) > 3 else 256
TARGET_FPS = float(sys.argv[4]) if len(sys.argv) > 4 else 6
WIDTH = int(sys.argv[5]) if len(sys.argv) > 5 else 0  # 0 keeps the recorded width


def load(p: Path) -> Image.Image:
    im = Image.open(p).convert("RGB")
    if WIDTH and im.width != WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    return im


def shared_palette(files: list[Path]) -> Image.Image:
    picks = [files[i] for i in range(0, len(files), max(1, len(files) // 16))][:16]
    tiles = [load(p) for p in picks]
    w, h = tiles[0].size
    cols = 4
    mosaic = Image.new("RGB", (w * cols, h * ((len(tiles) + cols - 1) // cols)))
    for i, t in enumerate(tiles):
        mosaic.paste(t, ((i % cols) * w, (i // cols) * h))
    return mosaic.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def build(scenes: str, name: str) -> None:
    files = sorted(p for p in frames_dir.glob("*.png") if p.name[0] in scenes)
    if not files:
        print("no frames for", name)
        return
    min_gap = 1.0 / TARGET_FPS
    kept: list[tuple[float, Image.Image]] = []
    prev = None
    for p in files:
        t = p.stat().st_mtime
        im = load(p)
        if prev is not None and ImageChops.difference(im, prev).getbbox() is None:
            continue  # nothing changed: the previous frame simply lasts longer
        if kept and t - kept[-1][0] < min_gap:
            continue  # cap the frame rate so a fast capture does not bloat the file
        kept.append((t, im))
        prev = im
    pal = shared_palette([files[i] for i in range(0, len(files), max(1, len(files) // 24))])
    # each frame lasts until the next one appeared, in real time
    durations = [min(3000, max(60, round((kept[i + 1][0] - kept[i][0]) * 1000))) for i in range(len(kept) - 1)] + [1800]
    frames = [im.quantize(palette=pal, dither=Image.Dither.NONE) for _, im in kept]
    out = out_dir / f"{name}.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False, disposal=1)
    print(f"{name}.gif: {len(files)} captured, {len(frames)} kept, {sum(durations) / 1000:.0f}s, {frames[0].width}px, {COLORS} colours, {out.stat().st_size / 1e6:.1f} MB")


out_dir.mkdir(parents=True, exist_ok=True)
build("a", "guardrail_demo")
build("b", "human_in_the_loop")
build("c", "attack_lab")
build("d", "photo_evidence_and_signals")
build("e", "observability")
build("g", "sign_in")
