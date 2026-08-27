# StockPulse Post-Market Carousel — Builder Instructions

Build the StockPulse Instagram carousel (POST MARKET mode) as ONE
self-contained HTML file: 8 slides (1080x1080 px each), each with its own
"Download PNG" button, plus a CAPTIONS panel at the bottom with Caption A and
Caption B in copy boxes. Use ONLY real data from the datapack (the same locked
numbers as the report — never invent, never carry figures over).

## OUTPUT FORMAT

Return ONLY the HTML file content. No markdown fences, no commentary. All CSS
in one shared `<style>` block reused across slides.

## LAYOUT SYSTEM (non-negotiable — every slide shares ONE frame)

```
.frame { position:absolute; inset:7px 0 0 0; z-index:2;
         padding:56px 64px 60px; display:flex; flex-direction:column; }
.slide-header { display:flex; justify-content:space-between; align-items:center;
                margin-bottom:40px; flex-shrink:0; }
.body { flex:1; display:flex; flex-direction:column; min-height:0; }
```
- Header padding identical on ALL 8 slides. Never vary it.
- `.body` always flex:1 so content fills the full height. Use
  justify-content:space-between or flex ratios so no dead space at the bottom.
- Logo at the same left edge, slide counter at the same right edge, every slide.

## OVERFLOW CAPS (POST MARKET positions)

- Snapshot (slide 2): 3 index cards (Nifty, Sensex, Bank Nifty), one 2x2 stat
  grid, ONE full-width hero box. Never a 4th index card.
- Sector rows (slide 4): 6 rows + 1 bonus card. Never 7 rows.
- Why rows (slide 3): 4 event rows, NOT 5. Merge related points; never shrink
  fonts to fit a 5th.
- Top movers (slide 5): 4 per column (gainers + losers), one callout note per
  column. Never 5 per column.
- Levels (slide 6): dark price hero with 3 level badges + 2 level cards
  (Nifty, Bank Nifty) + 2 expert boxes (or one full-width "WHAT TO WATCH" box).
- Lessons (slide 7): 4 rows max. Bigger text beats more items.
- If anything still overflows, shorten descriptions. Never go below the font
  minimums.

FONT MINIMUMS: hero numbers 72px, section headings 50px, card titles 26px,
body text 20px, labels 18px, disclaimer 15px. Font weight 900 is BANNED; 800
is the max.

## DESIGN SYSTEM

- Font: Plus Jakarta Sans (Google Fonts), weights 400/500/700/800 only.
- Background dark #0F2744, light #FFFFFF, accent orange #F97316,
  success green #16A34A, danger red #EF4444, muted text #64748B.
- Top bar dark: solid #F97316, 7px. Top bar light: gradient #0F2744 to #F97316, 7px.
- html2canvas CDN 1.4.1 always (no iframes).
- Logo mark — use EXACTLY, never modify:
```
<svg width="34" height="34" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg">
  <rect width="36" height="36" rx="9" fill="#F97316"/>
  <path d="M8 24 L16 16 L22 20 L28 12" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M22 12 L28 12 L28 18" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```
- Wordmark (two spans, 22px weight 800):
  dark slide: `<span class="brand-name"><span style="color:#fff">Stock</span><span style="color:#F97316">Pulse</span></span>`
  light slide: `<span class="brand-name"><span style="color:#0F2744">Stock</span><span style="color:#F97316">Pulse</span></span>`
- Slide counter top-right, 18px, opacity 0.35.
- Ghost watermark on dark slides (1,3,5,7): ~300px, opacity 0.05, bottom-right.
  Post market words: 1 CLOSE · 3 WHY · 5 MOVE · 7 NEXT. Swap in an event word
  (RBI, FED, CPI, VIX, EXPIRY) when the day is defined by that event.
- Alternation: slides 1,3,5,7 dark navy; 2,4,6,8 white. Fixed to POSITION.

## SLIDE STRUCTURE — POST MARKET

1. **BANNER COVER (dark)** — full-width banner FIRST in body: WHITE banner
   (#FFFFFF), "POST MARKET ANALYSIS" in navy #0F2744, 72px weight 800; inside
   it a pill with the day + date (e.g. "FRIDAY · AUGUST 21, 2026"), orange
   #F97316 pill, white text, 27px weight 800. Below: headline (2 lines max,
   weight 800, key phrase in orange), one plain subline, and the stat pill
   (the day's most impactful stat; green = up day, red = down day, orange =
   mixed). Ghost watermark CLOSE.
2. **SNAPSHOT (white)** — 3 index cards (Nifty, Sensex, Bank Nifty; green top
   border if up, red if down), 2x2 stat grid (India VIX with direction,
   advance/decline breadth, FII net cash, DII net cash; substitute the next
   most prominent stat if one is missing, never leave a blank tile), full-width
   hero box for the day's biggest stat.
3. **WHY IT HAPPENED (dark)** — heading + 4 icon rows (emoji, title, plain
   description, data badge). Ghost watermark WHY.
4. **SECTOR SCORECARD (white)** — 6 sector rows (green/red/grey left bar) + one
   bonus card.
5. **TOP MOVERS (dark)** — gainers (green) and losers (red), 4 per column, one
   callout note per column. Ghost watermark MOVE.
6. **TECHNICAL LEVELS (white)** — dark price hero with 3 level badges, 2 level
   cards (Nifty, Bank Nifty: support from max Put OI strike, resistance from
   max Call OI strike), 2 expert quote boxes (max 15 words, name + firm, from
   the report only). If no attributed quotes exist, replace with one full-width
   "WHAT TO WATCH" box from the report's own outlook lines. Never invent a
   quote or attribution.
7. **KEY LESSONS (dark)** — 4 numbered lessons + alert box for the next event.
   Ghost watermark NEXT.
8. **CTA (white)** — bookmark emoji, headline tied to the day, subtext, 4-stat
   grid (Nifty close with percent, India VIX, FII net, DII net — these MUST
   match slide 2 exactly), next-session box, CTA pill ("Join early access, link
   in bio"), SwarmIQ row, @getstockpulse handle, SEBI disclaimer ending
   "Not investment advice."

Friday editions: frame as WEEKLY wrap (banner "WEEKLY MARKET WRAP", weekly
change data, "For Next Week" on slide 6, "This Week" lessons on slide 7).

## PNG DOWNLOAD MECHANISM (do not change)

Each slide previews at transform scale(0.4333) inside a 468x468 container with
overflow hidden; each has its own Download PNG button:
- html2canvas only. NEVER iframes.
- On click: detach the slide, render off-screen at 1080x1080 scale(1), capture
  at 2x, trigger download, then restore scale(0.4333) in place.
- Filename: stockpulse-postmarket-[DDMMM]-slide[N].png

## WRITING RULES

- Short sentences, 6-10 words. Past tense, settled ("Closed", "ended", "fell",
  "led the gains").
- NO em dashes. NO hyphens joining thoughts. Write "200 week" not "200-week".
- No AI-sounding words: worth noting, furthermore, moreover, in conclusion,
  delve, leverage, robust, pivotal, it is important to highlight.
- Numbers in plain form: 24,000 not "the 24K level". Use ONLY datapack data.
- Banned instruction words even if a source used them: buy, sell, long, short,
  target, stop loss, SL, invest, recommend. Levels and zones are fine;
  instructions are not.
- Green = up, red = down, orange = neutral.
- Currency "Rs", never the rupee glyph.

## CAPTIONS PANEL (after slide 8)

- Heading "CAPTIONS · TAP COPY"; two readonly `<textarea>` boxes labelled
  "Caption A" and "Caption B" (no spellcheck, styled to match, tall enough to
  show the full caption), each with a "Copy caption" button
  (navigator.clipboard.writeText + select-and-copy fallback, shows "Copied" for
  2s), and a live character count under each box (both under 500 chars
  including hashtags).
- Caption A opens with the most surprising fact. Caption B uses a different
  hook (flows or levels angle). 2-3 data points, one watch line, CTA line
  "Daily wrap every evening @getstockpulse", then "Not investment advice."
  Exactly 5 hashtags each, always including #Nifty and #IndianStockMarket plus
  3 relevant ones.

## SELF-CHECK BEFORE OUTPUT

All 8 slides share the identical .frame padding; header identical; body uses
flex:1; overflow caps met; dark/light alternation correct (1,3,5,7 dark);
slide 1 opens with the white POST MARKET ANALYSIS banner + correct day/date
pill; logo SVG exact on all slides; wordmark two spans; ghost watermark on
1,3,5,7 with correct words; every number matches the datapack exactly; the
slide-2 stat grid and slide-8 stat grid agree; no banned instruction words; no
em dashes or joining hyphens; no font weight 900; expert quotes only from the
report, under 15 words, attributed (or the fallback box used); html2canvas
1.4.1, no iframes, no localStorage, no `<form>` tags; captions inside the HTML
copy boxes (not chat text), both under 500 chars, exactly 5 hashtags each
including #Nifty and #IndianStockMarket.
