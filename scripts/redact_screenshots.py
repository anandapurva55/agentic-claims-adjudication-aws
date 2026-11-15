"""Black out the AWS account id and the signed-in name in console screenshots before they go in a public README.

  python scripts/redact_screenshots.py <input_dir> <output_dir> <account_id> [name,name]

Two layers: a fixed block over the top-right corner where the console shows "Name (account id)", and OCR (tesseract) over the whole image to
find the account id inside ARNs and stack ids, wherever it appears. Prints how many boxes it drew per file. Always look at the output.
"""
import csv
import io
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def ocr_boxes(img: Image.Image, needles: list[str], tmp: Path, names: tuple[str, ...] = (), strip: bool = False) -> list[tuple[tuple[int, int, int, int], bool]]:
    img.save(tmp)
    out = subprocess.run(["tesseract", str(tmp), "stdout", "--psm", "11", "tsv"], capture_output=True).stdout.decode("utf-8", "ignore")
    boxes = []
    for row in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        header_name = word in names and (strip or (int(row["top"]) < img.size[1] * 0.06 and int(row["left"]) > img.size[0] * 0.6))
        account_like = bool(re.search(r"(?<!\d)\d{12}(?!\d)", word)) or word.lower().startswith("arn:") or ("claim" + "lens") in word.lower()
        if word and (any(n in word for n in needles) or account_like or header_name):
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            boxes.append(((x - 4, y - 4, x + w + 4, y + h + 4), any(n in word for n in needles) or account_like))
    return boxes


def header_boxes(img: Image.Image, needles: list[str], tmp: Path, names: tuple[str, ...] = ()) -> list[tuple[tuple[int, int, int, int], bool]]:
    """The console header is sometimes white text on a dark bar, which OCR misses. Invert the top strip, enlarge it and read it again."""
    w, h = img.size
    strip_h = int(h * 0.07)
    strip = ImageOps.invert(img.crop((int(w * 0.6), 0, w, strip_h)).convert("L")).resize((int(w * 0.4) * 2, strip_h * 2))
    boxes = ocr_boxes(strip.convert("RGB"), needles, tmp, names, strip=True)
    out = []
    for (x0, y0, x1, y1), acc in boxes:
        out.append(((int(w * 0.6) + x0 // 2 - 4, y0 // 2 - 4, int(w * 0.6) + x1 // 2 + 4, y1 // 2 + 4), acc))
    return out


def main(src: str, dst: str, account: str, names: str = "") -> None:
    Path(dst).mkdir(parents=True, exist_ok=True)
    needles = [account, account[:6], account[-5:], account[3:9]]
    for p in sorted(Path(src).glob("*.png")):
        img = Image.open(p).convert("RGB")
        w, h = img.size
        d = ImageDraw.Draw(img)
        tmp = Path(dst) / ".ocr_tmp.png"
        who = tuple(n for n in names.split(",") if n)
        boxes = ocr_boxes(img, needles, tmp, who) + header_boxes(img, needles, tmp, who)
        for b, _ in boxes:
            d.rectangle(b, fill="black")
        if not any(acc and b[1] < h * 0.06 and b[0] > w * 0.6 for b, acc in boxes):  # OCR never saw the id in the header: block the corner so nothing leaks
            d.rectangle([int(w * 0.88), 0, w, int(h * 0.055)], fill="black")
        img.save(Path(dst) / p.name)
        (Path(dst) / ".ocr_tmp.png").unlink(missing_ok=True)
        print(f"{p.name}: {len(boxes)} box(es)")


if __name__ == "__main__":
    main(*sys.argv[1:5])
