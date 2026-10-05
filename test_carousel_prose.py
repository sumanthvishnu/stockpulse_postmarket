"""Sector-key normalization and anti-filler checks for the carousel."""
import json
import os
import unittest
from datetime import date

import carousel
import compliance
import llm
import pipeline

ROOT = os.path.dirname(os.path.abspath(__file__))
PACK18 = os.path.join(ROOT, "data",
                      "stockpulse_datapack_2026-09-18_compiler.json")

CANNED = (
    "strongest sector",
    "second strongest",
    "biggest drag",
    "gainers closed firm",
    "losers stayed under pressure",
    "stay informed",
    "stay updated",
    "daily updates",
    "fresh global cues arrive",
    "global cues and corporate actions",
    "check back at the close",
    "full picture every evening",
    "was among the strongest sectors",
    "steady delivery",
    "26 aug 2026",
)


class SectorKeyTests(unittest.TestCase):
    def test_normalize_aliases_and_drop_unknown(self):
        raw = {
            "Nifty IT": "Weakest sector on the TCS drag",
            "nifty bank": "Banks held a bid",
            "Nifty Financial Services": "Financials joined the bid",
            "Nifty Healthcare Index": "Healthcare stayed firm",
            "Nifty Oil & Gas": "Oil held a bid",
            "IT": "Short key wins",
            "Nifty Midcap 150": "not a sector row",
            "Nifty INR": "not a sector",
            "Nifty Health": "do not guess healthcare",
            "  Nifty   Metal ": "Led the session as metals firmed",
        }
        got = carousel.normalize_sector_reasons(raw)
        self.assertEqual(got["IT"], "Short key wins")
        self.assertEqual(got["Bank"], "Banks held a bid")
        self.assertEqual(got["Financials"], "Financials joined the bid")
        self.assertEqual(got["Healthcare"], "Healthcare stayed firm")
        self.assertEqual(got["Oil & Gas"], "Oil held a bid")
        self.assertEqual(got["Metal"], "Led the session as metals firmed")
        for banned in ("Nifty Midcap 150", "Nifty INR", "Nifty Health",
                       "Midcap 150"):
            self.assertNotIn(banned, got)
        self.assertIsNone(carousel.normalize_sector_key("Nifty Health"))
        self.assertIsNone(carousel.normalize_sector_key("Nifty INR"))

    def test_build_renders_nifty_prefixed_reasons(self):
        with open(PACK18, encoding="utf-8") as fh:
            pack = json.load(fh)
        board = carousel.sector_board(pack, weekly=False)
        reasons = {}
        for full, short, _pct in board:
            reasons[full] = f"{short} note from the model"
        prose = {
            "headline": "Nifty rose while the *broader market ran ahead*",
            "sector_reasons": reasons,
        }
        html, leftover = carousel.build(pack, prose, weekly=False)
        self.assertEqual(leftover, [])
        self.assertIn("IT note from the model", html)
        self.assertIn("Metal note from the model", html)
        low = html.lower()
        self.assertNotIn("strongest sector", low)
        self.assertNotIn("biggest drag", low)
        self.assertIn("18 Sep 2026", html)
        self.assertNotIn("26 Aug 2026", html)
        self.assertIn("THE BROADER MARKET", html)

    def test_rank_stub_is_replaced_at_render(self):
        with open(PACK18, encoding="utf-8") as fh:
            pack = json.load(fh)
        prose = {"sector_reasons": {
            "IT": "strongest sector",
            "Nifty Metal": "Impact from global cues and FII outflows.",
            "Realty": "Weakest sector on the TCS drag",
        }}
        html, _leftover = carousel.build(pack, prose, weekly=False)
        low = html.lower()
        self.assertNotIn("strongest sector", low)
        self.assertNotIn("global cues", low)
        self.assertIn("Led the session", html)
        self.assertIn("Weakest sector on the TCS drag", html)

    def test_sep28_nifty_keys_do_not_render_rank_stubs(self):
        """The live 28 Sep carousel dropped every reason because keys were
        'Nifty IT' rather than 'IT', then painted rank stubs."""
        pack_path = os.path.join(
            ROOT, "data", "stockpulse_datapack_2026-09-28_compiler.json")
        prose_path = os.path.join(ROOT, "data", "prose_2026-09-28.json")
        with open(pack_path, encoding="utf-8") as fh:
            pack = json.load(fh)
        with open(prose_path, encoding="utf-8") as fh:
            prose = json.load(fh)
        self.assertTrue(any(str(k).startswith("Nifty ")
                            for k in prose["sector_reasons"]))
        html, leftover = carousel.build(pack, prose, weekly=False)
        self.assertEqual(leftover, [])
        low = html.lower()
        self.assertNotIn("strongest sector", low)
        self.assertNotIn("second strongest", low)
        self.assertNotIn("biggest drag", low)
        # The IT note was real prose under a "Nifty IT" key. It must render.
        self.assertIn("Minor impact from US market decline.", html)
        # Filler notes are replaced with a computed line for that sector.
        self.assertNotIn("impact from global cues", low)
        self.assertIn("Deepest loss", html)


class FallbackAndVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PACK18, encoding="utf-8") as fh:
            cls.pack = json.load(fh)

    def test_fallback_is_day_specific_and_locks(self):
        for weekly in (False, True):
            prose = carousel.fallback_prose(self.pack, weekly=weekly)
            flat = json.dumps(prose).lower()
            for phrase in CANNED:
                self.assertNotIn(phrase, flat, phrase)
            self.assertTrue(prose["sector_reasons"])
            for key in prose["sector_reasons"]:
                self.assertNotIn("nifty", key.lower())
            self.assertIn("while", prose["headline"].lower())
            self.assertIn("Monday", prose["cta_sub"])
            self.assertNotIn("tomorrow", flat)
            html, leftover = carousel.build(self.pack, prose, weekly=weekly)
            self.assertEqual(leftover, [])
            issues = []
            issues += carousel.budget_issues(prose)
            issues += compliance.number_lock(flat, self.pack)
            issues += compliance.calendar_lock(json.dumps(prose), self.pack)
            issues += carousel.validate(html, self.pack)
            self.assertEqual(issues, [], issues)
            voice = carousel.prose_quality_issues(
                prose, self.pack, weekly=weekly, memory=None)
            self.assertEqual(voice, [], voice)

    def test_omitted_fields_do_not_leak_canned_copy(self):
        html, _ = carousel.build(self.pack, {"headline": "Nifty rose while "
                                       "the *broader market ran ahead*"},
                                 weekly=False)
        low = html.lower()
        self.assertNotIn("gainers closed firm", low)
        self.assertNotIn("steady delivery", low)
        self.assertNotIn("stay informed", low)
        self.assertNotIn("muted session", low)
        self.assertIn("Adani", html)

    def test_quality_flags_restatement_filler_and_repeat(self):
        board = carousel.sector_board(self.pack, weekly=False)
        good = {full: f"{short} held a real bid"
                for full, short, _pct in board}
        clean = carousel.prose_quality_issues(
            {"headline": "Nifty rose while the *broader market ran ahead*",
             "sector_reasons": good,
             "why": [{"title": "Metals led the bid", "emoji": "🏭"}],
             "lessons": [
                 "Breadth backed the move. About 2 stocks rose for every 1 that fell.",
             ],
             "cta_headline": "A broad up day. *Save it for the open*.",
             "cta_sub": "Next bell is Monday."},
            self.pack, weekly=False)
        self.assertEqual(clean, [])

        bad = carousel.prose_quality_issues(
            {"headline": "Nifty 50 *plunges 1.56%* amid global cues",
             "sector_reasons": {"Nifty IT": "strongest sector",
                                "IT": "Pressure from volatile markets."},
             "why": [{"title": "Market Downturn", "emoji": "📉"}],
             "lessons": [
                 "Nifty 50 experienced a sharp drop of 1.56%.",
                 "Nifty 50 experienced a sharp drop of 0.40%.",
             ],
             "cta_headline": "Stay informed with *daily updates*",
             "movers_note_gainers": "Gainers closed firm into the close."},
            self.pack, weekly=False)
        joined = " ".join(bad).lower()
        self.assertIn("amid global cues", joined)
        self.assertIn("rank stub", joined)
        self.assertIn("filler", joined)
        self.assertIn("restates a percent", joined)
        self.assertIn("repeats the pattern", joined)
        self.assertIn("evergreen", joined)
        self.assertIn("canned filler", joined)
        self.assertIn("category label", joined)

        repeated = carousel.prose_quality_issues(
            {"headline": "A fresh contrast while breadth *ran ahead*",
             "sector_reasons": good,
             "lessons": ["Breadth backed the move in a new way today."],
             "cta_headline": "A broad up day.",
             "cta_sub": "Next bell is Monday."},
            self.pack, weekly=False,
            memory={"headlines": set(), "emojis": set(),
                    "lesson_skeletons": {
                        carousel.lesson_skeleton(
                            "Breadth backed the move in a new way today.")},
                    "movers": set(), "ctas": set(), "why_titles": set(),
                    "bonus_titles": set()})
        self.assertTrue(any("previous day's lesson pattern" in x
                            for x in repeated), repeated)


class CarouselModelTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("LLM_MODEL_CAROUSEL", None)
        os.environ.pop("LLM_MODEL", None)

    def test_carousel_model_override_and_blank_fallback(self):
        os.environ["LLM_MODEL"] = "gpt-4o"
        os.environ["LLM_MODEL_CAROUSEL"] = "anthropic/claude-sonnet-4.5"
        self.assertEqual(llm.resolved_carousel_model(),
                         "anthropic/claude-sonnet-4.5")
        os.environ["LLM_MODEL_CAROUSEL"] = "   "
        self.assertEqual(llm.resolved_carousel_model(), "gpt-4o")
        os.environ["LLM_MODEL_CAROUSEL"] = ""
        self.assertEqual(llm.resolved_carousel_model(), "gpt-4o")
        os.environ.pop("LLM_MODEL", None)
        self.assertEqual(llm.resolved_carousel_model(), "gpt-4o")


class Oct5GateTests(unittest.TestCase):
    """2026-10-05 shipped a whole-deck fallback after three live drafts failed
    soft voice checks. Those drafts should now ship, with only the failing
    fields replaced."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "data",
                            "stockpulse_datapack_2026-10-05_compiler.json")
        with open(path, encoding="utf-8") as fh:
            cls.pack = json.load(fh)
        _block, cls.memory = pipeline.recent_prose_memory(date(2026, 10, 5))

    def _kept(self):
        return {
            "headline": "FMCG carried the close while *breadth stayed soft*",
            "subline": "Staples did the lifting. The advance list did not.",
            "hero_text": "FMCG led the session while more names fell than rose.",
            "why": [
                {"emoji": "🧴", "title": "FMCG led the bid",
                 "desc": "Staples carried the close.", "badge": "FMCG"},
                {"emoji": "💸", "title": "Divergent flows",
                 "desc": "Foreign selling met domestic buying.", "badge": "Flows"},
                {"emoji": "🏗️", "title": "Infra held up",
                 "desc": "Construction stayed with the leaders.", "badge": "Infra"},
                {"emoji": "📉", "title": "Breadth was soft",
                 "desc": "More names fell than rose.", "badge": "A/D"},
            ],
            "sector_reasons": {
                "FMCG": "Staples led as the index held a bid.",
                "Consumer Durables": "Durables stayed firm with the leaders.",
                "Infra": "Infra held up beside the gainers.",
                "Healthcare": "Hospitals slipped as defensives lagged.",
                "Pharma": "Declined on global cues",
                "IT": "Software finished almost unchanged on the day.",
            },
            "bonus_title": "Breadth check",
            "bonus_text": "More stocks fell than rose.",
            "movers_note_gainers": "ITC and BSE set the pace on the way up.",
            "movers_note_losers": "A couple of large names weighed on the tape.",
            "lessons": [
                "Breadth lagged the index. The close looked better than the tape.",
                "FMCG led while Healthcare trailed.",
                "Flows were split. Foreign selling met domestic buying.",
                "IT barely moved while the leaders did the work.",
            ],
            "cta_headline": "A split tape. *Save the levels*.",
            "cta_sub": "Next bell is Tuesday.",
        }

    def test_attempt1_soft_failures_keep_the_draft(self):
        prose = self._kept()
        raw = carousel.prose_quality_issues(
            prose, self.pack, weekly=False, memory=self.memory)
        joined = " ".join(raw).lower()
        self.assertIn("pharma", joined)
        self.assertIn("breadth check", joined)
        self.assertIn("divergent flows", joined)

        resolved = carousel.resolve_carousel_draft(
            self.pack, prose, weekly=False, memory=self.memory)
        self.assertTrue(resolved["ship"], resolved["hard_issues"])
        self.assertIn("sector_reasons[Pharma]", resolved["field_fallbacks"])
        self.assertIn("bonus_title", resolved["field_fallbacks"])
        self.assertIn("why[2]", resolved["field_fallbacks"])
        html = resolved["html"]
        self.assertIn("breadth stayed soft", html)
        self.assertIn("Staples led as the index held a bid.", html)
        self.assertIn("FMCG led the bid", html)
        self.assertIn("Lagged the tape, closed -0.74%.", html)
        self.assertNotIn("Declined on global cues", html)
        self.assertNotIn("Divergent flows", html)
        self.assertNotIn("Nifty closed up on a", html)
        flat = json.dumps(resolved["prose"])
        self.assertEqual(compliance.number_lock(flat, self.pack), [])
        self.assertEqual(compliance.calendar_lock(flat, self.pack), [])

    def test_attempt2_robust_and_vague_sectors_are_field_fixes(self):
        prose = self._kept()
        prose["hero_text"] = "The close looked robust as FMCG led the tape."
        prose["sector_reasons"]["Healthcare"] = (
            "Pressured by broader market trends")
        prose["sector_reasons"]["Pharma"] = (
            "Declined on sector-specific headwinds")
        prose["sector_reasons"]["IT"] = "Flat as mixed global cues played"
        raw = " ".join(carousel.prose_quality_issues(
            prose, self.pack, weekly=False, memory=self.memory)).lower()
        self.assertIn("robust", raw)
        self.assertIn("healthcare", raw)
        self.assertIn("pharma", raw)
        self.assertIn("it", raw)

        resolved = carousel.resolve_carousel_draft(
            self.pack, prose, weekly=False, memory=self.memory)
        self.assertTrue(resolved["ship"], resolved["hard_issues"])
        self.assertTrue(any("robust" in x for x in resolved["auto_fixes"]))
        for key in ("Healthcare", "Pharma", "IT"):
            self.assertIn(f"sector_reasons[{key}]", resolved["field_fallbacks"])
        self.assertIn("The close looked firm as FMCG led the tape.",
                      resolved["html"])
        self.assertNotIn("robust", resolved["html"].lower())
        self.assertIn("Staples led as the index held a bid.", resolved["html"])
        self.assertIn("Deepest loss, closed -1.00%.", resolved["html"])
        self.assertIn("Nearly flat, closed -0.01%.", resolved["html"])
        self.assertNotIn("broader market trends", resolved["html"].lower())
        self.assertNotIn("sector-specific", resolved["html"].lower())
        self.assertNotIn("global cues", resolved["html"].lower())

    def test_attempt3_generic_title_and_repeat_do_not_drop_the_deck(self):
        prose = self._kept()
        prose["why"][2]["title"] = "Volatility rise"
        prose["sector_reasons"]["Pharma"] = "Declined on sector-specific selling"
        raw = " ".join(carousel.prose_quality_issues(
            prose, self.pack, weekly=False, memory=self.memory)).lower()
        self.assertIn("volatility rise", raw)
        self.assertIn("category label", raw)
        resolved = carousel.resolve_carousel_draft(
            self.pack, prose, weekly=False, memory=self.memory)
        self.assertTrue(resolved["ship"], resolved["hard_issues"])
        self.assertIn("why[3]", resolved["field_fallbacks"])
        self.assertIn("sector_reasons[Pharma]", resolved["field_fallbacks"])
        self.assertNotIn("Volatility rise", resolved["html"])
        self.assertIn("breadth stayed soft", resolved["html"])
        self.assertNotIn("sector-specific", resolved["html"].lower())

    def test_hard_rule_replaces_only_the_bad_field(self):
        prose = self._kept()
        prose["headline"] = ("Nifty secretly closed at 99999 while breadth "
                             "lagged")
        prose["bonus_text"] = "You should buy the open."
        self.assertTrue(carousel.field_hard_issues(
            prose["headline"], self.pack))
        self.assertTrue(carousel.field_hard_issues(
            prose["bonus_text"], self.pack))
        resolved = carousel.resolve_carousel_draft(
            self.pack, prose, weekly=False, memory=self.memory)
        self.assertTrue(resolved["ship"], resolved["hard_issues"])
        self.assertIn("headline", resolved["field_fallbacks"])
        self.assertIn("bonus_text", resolved["field_fallbacks"])
        flat = json.dumps(resolved["prose"]).lower()
        self.assertNotIn("99999", flat)
        self.assertNotIn("should buy", flat)
        self.assertIn("Staples did the lifting.", resolved["html"])
        self.assertEqual(compliance.number_lock(flat, self.pack), [])
        self.assertIn("Not investment advice.", resolved["html"])

    def test_telegram_names_unreachable_gate_and_fields(self):
        messages = []
        orig_log, orig_dry = pipeline.log, pipeline.DRY
        pipeline.log = messages.append
        pipeline.DRY = True
        try:
            common = dict(tdate=date(2026, 10, 5), pack=self.pack,
                          pdf_path="/tmp/none.pdf",
                          carousel_url="http://carousel",
                          pdf_url="http://pdf", issues=[])
            pipeline.notify(carousel_fallback=True, carousel_llm_reached=False,
                            **common)
            pipeline.notify(carousel_fallback=True, carousel_llm_reached=True,
                            **common)
            pipeline.notify(carousel_fallback=False, carousel_llm_reached=True,
                            carousel_field_fallbacks=["sector_reasons[Pharma]",
                                                      "bonus_title", "why[2]"],
                            carousel_auto_fixes=[
                                "rewrote banned wording 'robust' in hero_text"],
                            **common)
        finally:
            pipeline.log, pipeline.DRY = orig_log, orig_dry
        blob = "\n".join(messages)
        self.assertIn("LLM unreachable", blob)
        self.assertIn("rejected by the gate", blob)
        self.assertIn("sector_reasons[Pharma]", blob)
        self.assertIn("bonus_title", blob)
        self.assertIn("why[2]", blob)
        self.assertIn("robust", blob)
        self.assertIn("LLM draft kept", blob)


if __name__ == "__main__":
    unittest.main()
