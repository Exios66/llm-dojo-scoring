#!/usr/bin/env python3
"""Generate the README artwork for llm-dojo-scoring (constellation design v2).

    python3 docs/assets/readme/generate.py          # rewrite the SVGs beside this file
    python3 docs/assets/readme/generate.py --check  # read-only drift gate (exit 1 on drift)

`_art.py` is the shared kit (identical in every constellation repo); this file
owns only this repository's labels, scene and facts. Facts are backed by the
README and the source: `DEFAULT_PROFILES` (27), `BUILTIN_BUNDLES` (11), the
T0-T3 metric tiers in `registry.py`, the four console scripts in `pyproject.toml`,
and the Wilson interval for 2/3 at z = 1.96 computed below.
Standard library only, deterministic output.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _art as art  # noqa: E402  (shared kit lives beside this file)

HERO = {
    'title': 'LLM Dojo Scoring',
    'kicker': 'THE MAILROOM CONSTELLATION · THE SCORING ENGINE',
    'tagline': 'Score the extraction, not the vibes — field-aware metrics, honest intervals, failures explained.',
    'eyebrow': 'FIELD-TYPE-AWARE · DETERMINISTIC CORE · BOOTSTRAP + WILSON INTERVALS · FAILURE MODES',
    'caption': 'one engine for the pipeline and the sandbox · optional Langfuse and Phoenix sinks · no API key to score',
    'alt': 'Animated banner: expected and predicted document classes are compared pair by pair (two match, one '
           'does not) and the exact-match score of two thirds is shown with its Wilson confidence interval.',
    'tagline_lines': ['Score the extraction, not the vibes —', 'field-aware, honest, explained.'],
    'mobile_cards': [('Compare', 'typed fields + labels'), ('Measure', 'P · R · F1 · F2 + exact match'),
                     ('Quantify', 'bootstrap + Wilson'), ('Explain', 'failure modes + reports')],
    'mobile_note': 'deterministic core · no API key needed',
}
STATS = [('27', 'agent profiles', art.SKY), ('11', 'task bundles', art.VIOLET), ('T0–T3', 'metric tiers', art.LIME),
         ('4', 'command-line tools', art.PINK), ('CIs', 'bootstrap + Wilson', art.AMBER),
         ('Offline', 'core needs no API key', art.GREEN)]
STAGES = [('Task suite', 'get_suite(...)', 'per-agent contract'),
          ('Normalize', 'align fields or labels', 'date · money · id · name'),
          ('Compare', 'score_extraction', 'score_task'),
          ('Metrics', 'P · R · F1 · F2', 'exact match · per class'),
          ('Uncertainty', 'bootstrap_ci', 'Wilson · delta tests'),
          ('Explain', 'failure modes', 'dojo-analyze · -export')]
SIDE = [('Pipeline', 'imports the suites', 'llm-mailroom'),
        ('Sandbox', 'vendored snapshot', 'local-mailroom-sandbox'),
        ('Langfuse', 'LangfuseSink emitter', 'optional · inert if unset'),
        ('Phoenix', 'OTLP probe + reader', 'optional · local'),
        ('Workbooks', 'dojo-sync', 'live traces → workbook')]
TERMINAL = [('cmd', 'git clone https://github.com/Exios66/llm-dojo-scoring.git'),
            ('cmd', 'cd llm-dojo-scoring && pip install -e ".[dev]"'),
            ('note', '# core scoring is offline: no model, API key or tracing service'),
            ('cmd', 'dojo-version --check --offline --json'),
            ('note', '# which Dojo is loaded, and what is released'),
            ('cmd', 'dojo-analyze Sorter_Experiment_Results.xlsx --target 0.94 --min-n 100'),
            ('note', '# → a markdown report and PNG plots next to the workbook'),
            ('cmd', 'python -m pytest')]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval, computed here so the artwork cannot drift from the maths."""
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half

TUI_GAUGES = [('agent profiles', '27', None, art.SKY), ('task bundles', '11', None, art.VIOLET),
              ('metric tiers', 'T0 → T3', None, art.LIME), ('CLI tools', '4', None, art.PINK),
              ('core needs', 'no API key', None, art.GREEN)]
TUI_LOG = [('info', 'dojo-analyze --target 0.94 --min-n 100'), ('ok', 'score_task exact match 2 / 3'),
           ('info', 'Wilson 95% interval 0.21–0.94'), ('warn', 'n = 3: the interval is wide, trust it'),
           ('ok', 'report + plots beside the workbook')]
TUI_STATUS = 'deterministic core · offline · optional Langfuse and Phoenix sinks'


def scene() -> str:
    """Expected-vs-predicted pairs on the left; the score with its interval on the right."""
    rows = [('contract', 'contract', True), ('correspondence', 'contract', False),
            ('insurance_claim', 'insurance_claim', True)]
    out = [art.text(90, 244, 'EXPECTED', 11, '#8b9bb4', 700, spacing=2),
           art.text(310, 244, 'PREDICTED', 11, '#8b9bb4', 700, spacing=2)]
    for i, (exp, pred, ok) in enumerate(rows):
        y = 256 + i * 44
        out.append(art.chip(90, y, 200, 32, exp, art.SKY))
        out.append(art.chip(310, y, 200, 32, pred, art.GREEN if ok else '#fb7185'))
        out.append(art.check_mark(534, y + 17) if ok else art.cross_mark(534, y + 16))
    out.append('<rect class="motion" x="80" y="252" width="480" height="40" rx="10" fill="#ffffff" opacity="0">'
               '<animate attributeName="y" values="252;296;340;340" keyTimes="0;.33;.66;1" dur="4s" repeatCount="indefinite"/>'
               '<animate attributeName="opacity" values=".10;.10;.10;0" keyTimes="0;.33;.66;1" dur="4s" repeatCount="indefinite"/></rect>')
    out.append(art.arrow(572, 306, 640, 306, art.MUTED))
    out.append(art.text(606, 292, 'score_task', 12, art.MUTED, 600, 'middle', family=art.MONO))
    x0, x1, base = 680, 1130, 336
    lo, hi = wilson(2, 3)
    px = lambda v: x0 + (x1 - x0) * v  # noqa: E731
    out.append(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="#475569" stroke-width="3" stroke-linecap="round"/>')
    for v, lab in ((0, '0'), (0.5, '0.5'), (1, '1')):
        out.append(f'<line x1="{art.num(px(v))}" y1="{base - 6}" x2="{art.num(px(v))}" y2="{base + 6}" stroke="#64748b" stroke-width="2"/>')
        out.append(art.text(px(v), base + 26, lab, 12, art.DIM, anchor='middle'))
    out.append(f'<rect x="{art.num(px(lo))}" y="{base - 9}" width="{art.num(px(hi) - px(lo))}" height="18" rx="9" '
               f'fill="{art.AMBER}" opacity=".35"/>')
    out.append(f'<rect x="{art.num(px(lo))}" y="{base - 9}" width="{art.num(px(hi) - px(lo))}" height="18" rx="9" '
               f'fill="none" stroke="{art.AMBER}" stroke-width="2"/>')
    out.append(f'<circle cx="{art.num(px(2 / 3))}" cy="{base}" r="9" fill="{art.SKY}" stroke="#0b1220" stroke-width="3"/>')
    out.append(art.text(px(2 / 3), base - 30, 'exact match 2 / 3', 16, art.INK, 700, 'middle'))
    out.append(art.text((px(lo) + px(hi)) / 2, base + 50, f'Wilson 95% interval {lo:.2f}–{hi:.2f}', 13, '#fcd34d', 600, 'middle'))
    dots = ''.join(
        f'<circle cx="{art.num(px(v))}" cy="{base + dy}" r="3" fill="{art.AMBER}"><animate attributeName="opacity" '
        f'values="0;.9;0" dur="3s" begin="{art.num(i * 0.35)}s" repeatCount="indefinite"/></circle>'
        for i, (v, dy) in enumerate(((0.34, -22), (0.52, -18), (0.61, -24), (0.74, -16), (0.83, -23), (0.91, -17), (0.47, -25))))
    out.append(f'<g class="motion">{dots}</g>')
    return '\n'.join(out)


def build() -> dict[str, str]:
    """Return every generated asset keyed by file name."""
    flow_desc = ('Ground truth and predictions enter a task suite, are normalized and aligned, compared, turned into '
                 'metrics and intervals, then explained; the pipeline, sandbox and optional sinks plug into it.')
    return {
        'hero.svg': art.hero(HERO, scene),
        'hero-mobile.svg': art.hero(HERO, mobile=True),
        'stats.svg': art.stats(STATS, 'llm-dojo-scoring by the numbers'),
        'stats-mobile.svg': art.stats(STATS, 'llm-dojo-scoring by the numbers', mobile=True),
        'flow.svg': art.flow('From predictions to a verdict', STAGES, SIDE, 'Plug it in', desc=flow_desc, side_color=art.SKY),
        'flow-mobile.svg': art.flow('From predictions to a verdict', STAGES, SIDE, 'Plug it in', mobile=True,
                                    desc=flow_desc, side_color=art.SKY),
        'constellation.svg': art.constellation('llm-dojo-scoring'),
        'constellation-mobile.svg': art.constellation('llm-dojo-scoring', mobile=True),
        'tui.svg': art.tui('~/llm-dojo-scoring — dojo-analyze', TUI_GAUGES, TUI_LOG, TUI_STATUS,
                           'Dashboard: what the scoring engine ships (27 agent profiles, 11 task bundles, tiers T0 to T3, four command-line tools) and a sample run with its Wilson interval.', left='REGISTRY', right='SAMPLE RUN'),
        'terminal.svg': art.terminal('~/llm-dojo-scoring — zsh', TERMINAL,
                                     'Animated terminal: clone, install, check the Dojo version offline, analyze a '
                                     'workbook and run the tests.'),
    }


def main() -> None:
    """Write the assets, or compare them byte-for-byte with --check."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='fail on drift without writing')
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    drift = []
    for name, content in build().items():
        path = base / name
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                drift.append(name)
        else:
            path.write_text(content, encoding='utf-8')
    if drift:
        parser.exit(1, 'README asset drift: ' + ', '.join(drift) + '\n')
    print('README assets match' if args.check else 'README assets written')


if __name__ == '__main__':
    main()
