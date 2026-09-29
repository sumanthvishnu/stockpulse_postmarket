"""Carousel prose: sector-key normalization and voice lint.

The live failure was twofold. sector_reasons arrived as "Nifty IT" while the
slide looks up "IT", so every reason was discarded. The model also keyed
sectors that were not on that day's board. These tests lock both fixes.
"""
import json
import os
import re
import unittest

import carousel
import llm

REPO = os.path.dirname(os.path.abspath(__file__))


def _reason(html, short):
    match = re.search(
        r'sec-name">%s</div><div class="sec-reason">([^<]*)</div>' % re.escape(short),
        html,
    )
    return match.group(1) if match else None


def _mini_pack():
    def ix(pct, close=100.0):
        return {"close": close, "pct_chg": pct, "pts_chg": pct}

    indices = {
        "Nifty 50": {"close": 23346.4, "pct_chg": 0.33, "pts_chg": 75.8},
        "Nifty Bank": {"close": 56358.7, "pct_chg": 0.54, "pts_chg": 302.95},
        "India VIX": {"close": 11.39, "pct_chg": -7.36, "pts_chg": -0.9},
        "Nifty Metal": ix(1.51),
        "Nifty Media": ix(1.34),
        "Nifty Realty": ix(1.19),
        "Nifty Energy": ix(1.05),
        "Nifty Auto": ix(-0.11),
        "Nifty IT": ix(-1.03),
    }
    return {
        "meta": {"trading_date": "2026-09-18"},
        "derived": {
            "indices": indices,
            "global_markets": {"markets": {"Sensex": {"level": 74294.96, "pct_chg": -0.03}}},
            "breadth": {"advances": 1775, "declines": 839},
            "fii_dii_cash_summary": {"fii_net_cr": 599.5, "dii_net_cr": 1019.7},
            "options_NIFTY": {
                "max_put_oi_strike": 23300,
                "max_call_oi_strike": 24000,
                "max_pain": 23350,
            },
            "options_BANKNIFTY": {"max_pain": 57200},
            "nifty50_movers": {"gainers": [], "losers": []},
            "vix": {"current": 11.39},
        },
    }


class SectorKeyTests(unittest.TestCase):
    def test_nifty_prefix_and_short_key_resolve_to_the_same_reason(self):
        note = "Weakest sector on the TCS drag"
        prefixed, unknown_prefixed = carousel.normalize_sector_reasons({"Nifty IT": note})
        short, unknown_short = carousel.normalize_sector_reasons({"IT": note})
        spaced, _unknown = carousel.normalize_sector_reasons({"  nifty it  ": note})
        self.assertEqual(unknown_prefixed, [])
        self.assertEqual(unknown_short, [])
        self.assertEqual(prefixed, {"IT": note})
        self.assertEqual(short, {"IT": note})
        self.assertEqual(spaced, {"IT": note})
        # The explicit short key wins when both forms are present.
        both_orders = [
            {"Nifty IT": "from prefix", "IT": "from short"},
            {"IT": "from short", "Nifty IT": "from prefix"},
        ]
        for raw in both_orders:
            norm, unknown = carousel.normalize_sector_reasons(raw)
            self.assertEqual(unknown, [])
            self.assertEqual(norm["IT"], "from short")

    def test_other_sector_aliases_map_to_renderer_shorts(self):
        raw = {
            "Nifty Financial Services": "banks and lenders",
            "Financial Services": "already bare",
            "Nifty Healthcare Index": "hospitals bid",
            "Nifty Oil & Gas": "crude eased",
            "Nifty PSU Bank": "state lenders lagged",
            "Nifty Consumer Durables": "durables slipped",
            "Nifty Infrastructure": "projects paused",
        }
        norm, unknown = carousel.normalize_sector_reasons(raw)
        self.assertEqual(unknown, [])
        self.assertEqual(norm["Financials"], "already bare")
        self.assertEqual(norm["Healthcare"], "hospitals bid")
        self.assertEqual(norm["Oil & Gas"], "crude eased")
        self.assertEqual(norm["PSU Bank"], "state lenders lagged")
        self.assertEqual(norm["Consumer Durables"], "durables slipped")
        self.assertEqual(norm["Infra"], "projects paused")

    def test_unknown_keys_are_dropped_not_guessed(self):
        norm, unknown = carousel.normalize_sector_reasons({
            "Nifty Midcap 150": "not a sector row",
            "Nifty INR": "not a sector",
            "Nifty Health": "not the healthcare index",
            "IT": "kept",
        })
        self.assertEqual(norm, {"IT": "kept"})
        self.assertCountEqual(unknown, ["Nifty Midcap 150", "Nifty INR", "Nifty Health"])

    def test_build_renders_prefixed_and_short_keys_on_the_it_row(self):
        pack = _mini_pack()
        note = "Weakest sector on the TCS drag"
        html_prefix, leftover_prefix = carousel.build(
            pack, {"sector_reasons": {"Nifty IT": note}})
        html_short, leftover_short = carousel.build(
            pack, {"sector_reasons": {"IT": note}})
        self.assertEqual(leftover_prefix, [])
        self.assertEqual(leftover_short, [])
        self.assertEqual(_reason(html_prefix, "IT"), note)
        self.assertEqual(_reason(html_short, "IT"), note)
        self.assertNotIn(">biggest drag<", html_prefix)
        self.assertNotIn(">biggest drag<", html_short)


class VoiceLintTests(unittest.TestCase):
    def test_lessons_that_only_restate_a_percent_are_flagged(self):
        self.assertTrue(carousel.lesson_restates_stat(
            "Nifty 50 experienced a sharp drop of 1.56%."))
        self.assertTrue(carousel.lesson_restates_stat(
            "Nifty moved -0.56% across the week's sessions."))
        self.assertTrue(carousel.lesson_restates_stat(
            "Volatility saw a notable increase with VIX rising 12.15%."))
        self.assertFalse(carousel.lesson_restates_stat(
            "Breadth backed the move. About 2 stocks rose for every 1 that fell."))
        self.assertFalse(carousel.lesson_restates_stat(
            "The broader market led. Midcaps and smallcaps beat the frontline."))
        self.assertFalse(carousel.lesson_restates_stat(
            "Fear fell fast. India VIX dropped 7.36 percent to 11.39."))
        self.assertFalse(carousel.lesson_restates_stat(
            "One cluster can cap an index. The Tata drag held the Sensex flat."))

    def test_missing_and_mismatched_sector_keys_are_reported(self):
        pack = _mini_pack()
        issues = carousel.prose_issues(
            {"sector_reasons": {
                "Nifty IT": "Weakest sector on the TCS drag",
                "Nifty INR": "not a sector",
            }},
            pack,
        )
        joined = " ".join(issues)
        self.assertIn("Nifty INR", joined)
        self.assertIn("Metal", joined)
        self.assertNotIn("missing cause notes for today's sector slide: IT", joined)
        # IT normalized, so it is not in the missing list.
        missing = next(item for item in issues if item.startswith("sector_reasons missing"))
        self.assertNotIn("IT", missing.split("Required keys")[0])

    def test_filler_headline_cta_and_category_titles(self):
        issues = carousel.prose_issues({
            "headline": "Nifty 50 *plunges 1.56%* amid global cues",
            "cta_headline": "Stay informed with *daily updates*",
            "cta_sub": "Follow us for concise market wraps.",
            "why": [{"title": "Market Downturn", "desc": "x", "badge": "y", "emoji": "📉"}],
            "sector_reasons": {"IT": "Impact from global cues and FII outflows."},
            "lessons": ["Nifty 50 experienced a sharp drop of 1.56%."],
        })
        joined = " ".join(issues)
        self.assertIn("amid global cues", joined)
        self.assertIn("stay informed", joined.lower())
        self.assertIn("follow us for", joined.lower())
        self.assertIn("category label", joined)
        self.assertIn("global cues", joined)
        self.assertIn("lessons[1]", joined)

    def test_rank_stub_reason_is_flagged_but_a_cause_is_not(self):
        stub = " ".join(carousel.prose_issues(
            {"sector_reasons": {"IT": "strongest sector"}}))
        cause = " ".join(carousel.prose_issues(
            {"sector_reasons": {"IT": "Weakest sector on the TCS drag"}}))
        self.assertIn("rank label", stub)
        self.assertNotIn("rank label", cause)
        self.assertNotIn("filler", cause)


class Sep18AndSep28Tests(unittest.TestCase):
    def test_voice_example_is_in_budget_and_is_not_a_percent_lesson(self):
        path = os.path.join(REPO, "skills", "carousel_voice_example.json")
        with open(path, encoding="utf-8") as fh:
            prose = json.load(fh)
        self.assertEqual(carousel.budget_issues(prose), [])
        self.assertEqual(carousel.prose_issues(prose), [])
        for lesson in prose["lessons"]:
            self.assertFalse(carousel.lesson_restates_stat(lesson))
        prompt = carousel.system_prompt()
        self.assertIn("broader market ran ahead", prompt)
        self.assertIn("SECTOR_SHORTS_TODAY", prompt)
        with open(path, encoding="utf-8") as fh:
            example = fh.read()
        self.assertNotIn("Vikram Kasat", example)
        self.assertNotIn("\U0001f5d3", example)
        self.assertNotIn("_meta", example)

    def test_sep18_daily_board_renders_gold_it_and_metal_notes(self):
        with open(os.path.join(
                REPO, "data", "stockpulse_datapack_2026-09-18_compiler.json"),
                encoding="utf-8") as fh:
            pack = json.load(fh)
        with open(os.path.join(
                REPO, "skills", "carousel_voice_example.json"),
                encoding="utf-8") as fh:
            prose = json.load(fh)
        # Claude's sample is the daily scorecard. The Friday pipeline ranks
        # the weekly board instead; this checks the daily lookup.
        self.assertEqual(
            carousel.sector_shorts_today(pack, weekly=False)[:3],
            ["Metal", "Media", "Realty"],
        )
        self.assertIn("IT", carousel.sector_shorts_today(pack, weekly=False))
        html, leftover = carousel.build(pack, prose, weekly=False)
        self.assertEqual(leftover, [])
        self.assertEqual(_reason(html, "IT"), "Weakest sector on the TCS drag")
        self.assertEqual(_reason(html, "Metal"), "Led the session as metals firmed")
        prefixed = {
            "sector_reasons": {
                "Nifty IT": prose["sector_reasons"]["IT"],
                "Nifty Metal": prose["sector_reasons"]["Metal"],
            }
        }
        html_prefixed, _leftover = carousel.build(pack, prefixed, weekly=False)
        self.assertEqual(_reason(html_prefixed, "IT"), "Weakest sector on the TCS drag")
        self.assertEqual(_reason(html_prefixed, "Metal"), "Led the session as metals firmed")

    def test_sep28_prefixed_keys_render_and_the_gap_is_linted(self):
        with open(os.path.join(
                REPO, "data", "stockpulse_datapack_2026-09-28_compiler.json"),
                encoding="utf-8") as fh:
            pack = json.load(fh)
        with open(os.path.join(REPO, "data", "prose_2026-09-28.json"),
                  encoding="utf-8") as fh:
            prose = json.load(fh)
        # Raw lookup misses every key. Normalization recovers the two sectors
        # that were actually on the board (IT, Realty). The other four keys
        # are the wrong sectors, which the lint must name.
        raw = prose["sector_reasons"]
        self.assertTrue(all(key.startswith("Nifty ") for key in raw))
        board = set(carousel.sector_shorts_today(pack, weekly=False))
        self.assertTrue(board.isdisjoint(raw.keys()))
        html, _leftover = carousel.build(pack, prose, weekly=False)
        self.assertEqual(
            _reason(html, "IT"), "Minor impact from US market decline.")
        self.assertEqual(
            _reason(html, "Realty"), "Affected by overall market sentiment.")
        issues = carousel.prose_issues(prose, pack, weekly=False)
        missing = next(item for item in issues if "missing cause notes" in item)
        for name in ("Consumer Durables", "Media", "PSU Bank", "Energy"):
            self.assertIn(name, missing)
        self.assertNotIn("Nifty INR", " ".join(issues))
        joined = " ".join(issues)
        self.assertIn("amid global cues", joined)
        self.assertIn("lessons[", joined)


class CarouselModelTests(unittest.TestCase):
    def test_blank_carousel_model_falls_through_to_llm_model(self):
        keys = ("LLM_MODEL_CAROUSEL", "LLM_MODEL")
        saved = {key: os.environ.get(key) for key in keys}
        try:
            os.environ.pop("LLM_MODEL_CAROUSEL", None)
            os.environ.pop("LLM_MODEL", None)
            self.assertEqual(llm.carousel_model(), "gpt-4o")
            os.environ["LLM_MODEL"] = "gpt-4o-mini"
            os.environ["LLM_MODEL_CAROUSEL"] = "   "
            self.assertEqual(llm.carousel_model(), "gpt-4o-mini")
            os.environ["LLM_MODEL_CAROUSEL"] = "claude-sonnet-test"
            self.assertEqual(llm.carousel_model(), "claude-sonnet-test")
            # Report calls pass no override, so they stay on LLM_MODEL.
            self.assertEqual(llm.resolve_model(None), "gpt-4o-mini")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
