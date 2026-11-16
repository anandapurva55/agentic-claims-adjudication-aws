"""Write the README's badges as local SVG files, so they load from the repository and never depend on an outside badge service.

  python scripts/make_badges.py

Each badge is a label on a grey ground and a value on a colour, in the flat style people expect. The CI and CodeQL badges are not made here: they show a live
pass or fail, so they come from GitHub itself. No counts of tests or checks are drawn into any picture, because a number in an image goes stale.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "images" / "badges"

# slug, label, value, colour of the value side
BADGES = [
    ("python", "Python", "3.12", "#3776AB"),
    ("aws", "AWS", "Bedrock | AgentCore | ECS | CDK", "#FF9900"),
    ("strands", "Strands", "Agents", "#7C3AED"),
    ("mcp", "MCP", "2 servers", "#0F766E"),
    ("rag", "RAG", "Bedrock Knowledge Bases", "#0EA5E9"),
    ("guardrails", "Bedrock", "Guardrails", "#DC2626"),
    ("react", "React", "19", "#149ECA"),
    ("typescript", "TypeScript", "7", "#3178C6"),
    ("fastapi", "FastAPI", "backend", "#009688"),
    ("cognito", "Cognito", "managed login", "#DD344C"),
    ("waf", "AWS WAF", "rate limits", "#C7131F"),
    ("cloudfront", "CloudFront", "VPC origin", "#8C4FFF"),
    ("dynamodb", "DynamoDB", "audit log", "#4053D6"),
    ("s3", "S3", "data and vectors", "#569A31"),
    ("secrets-manager", "Secrets Manager", "origin secret", "#DD344C"),
    ("uv", "uv", "locked environment", "#DE5FE9"),
    ("interactive-demo", "GitHub Pages", "interactive demo", "#222222"),
]

CHAR_W = 7.1  # average width of a character at 11 px in Verdana, which is what a viewer falls back to
PAD = 10


def width(text: str) -> int:
    return round(len(text) * CHAR_W + 2 * PAD)


def svg(label: str, value: str, colour: str) -> str:
    lw, vw = width(label), width(value)
    total = lw + vw
    text = 'font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11" fill="#fff" text-anchor="middle"'
    shadow = 'fill="#010101" fill-opacity=".3"'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{escape(label)}: {escape(value)}">
  <title>{escape(label)}: {escape(value)}</title>
  <clipPath id="r"><rect width="{total}" height="20" rx="3"/></clipPath>
  <g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{vw}" height="20" fill="{colour}"/></g>
  <g {text}>
    <text x="{lw / 2}" y="15" {shadow} textLength="{lw - 2 * PAD}" lengthAdjust="spacingAndGlyphs">{escape(label)}</text>
    <text x="{lw / 2}" y="14" textLength="{lw - 2 * PAD}" lengthAdjust="spacingAndGlyphs">{escape(label)}</text>
    <text x="{lw + vw / 2}" y="15" {shadow} textLength="{vw - 2 * PAD}" lengthAdjust="spacingAndGlyphs">{escape(value)}</text>
    <text x="{lw + vw / 2}" y="14" textLength="{vw - 2 * PAD}" lengthAdjust="spacingAndGlyphs">{escape(value)}</text>
  </g>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, label, value, colour in BADGES:
        (OUT / f"{slug}.svg").write_text(svg(label, value, colour))
    print(f"{len(BADGES)} badges written to {OUT.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
