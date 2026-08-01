#!/usr/bin/env python3
import os
import unittest

from scripts import radar


class StrictRadarFilterTests(unittest.TestCase):
    def assertCandidate(self, subject, sender, body=""):
        accepted, score, reason = radar.radar_signal(subject, sender, body)
        self.assertTrue(accepted, msg=f"expected candidate: score={score} {reason}")
        return score

    def assertRejected(self, subject, sender, body=""):
        accepted, score, reason = radar.radar_signal(subject, sender, body)
        self.assertFalse(accepted, msg=f"expected rejection: score={score} {reason}")

    def test_new_model_release(self):
        self.assertCandidate(
            "Kimi K3 is here",
            "Moonshot AI <news@moonshot.ai>",
            "We released Kimi K3 today with a new mixture-of-experts architecture.",
        )

    def test_open_weights_release(self):
        self.assertCandidate(
            "Qwen 4 open weights are now available",
            "Qwen Team <news@example.com>",
            "Model weights and checkpoints have been released for builders.",
        )

    def test_capacity_constrained_availability(self):
        score = self.assertCandidate(
            "Kimi K3 now available on Ollama Cloud",
            "Ollama <hello@ollama.com>",
            "Demand exceeds capacity, so we are not accepting Max plan signups right now.",
        )
        self.assertGreaterEqual(score, 8)

    def test_major_government_blocking_before_aggregators(self):
        score = self.assertCandidate(
            "Fable blocked by the U.S. government",
            "Industry source <alerts@example.net>",
            "The government blocked access to Fable's AI language model and coding agent runtime.",
        )
        self.assertGreaterEqual(score, 8)

    def test_sender_allowlist_is_not_automatic(self):
        self.assertRejected(
            "Your July account summary",
            "OpenAI <noreply@openai.com>",
            "Here is your account activity.",
        )

    def test_generic_ai_webinar_is_rejected(self):
        self.assertRejected(
            "Register now: transform your business with AI",
            "Marketing <events@vendor.example>",
            "Save your seat for our webinar and book a demo.",
        )

    def test_vendor_newsletter_without_event_is_rejected(self):
        self.assertRejected(
            "Five tips for better Claude prompts",
            "Anthropic <news@anthropic.com>",
            "Our monthly roundup of tutorials and customer stories.",
        )

    def test_promotional_model_offer_is_rejected(self):
        self.assertRejected(
            "Mistral free trial available now — save 20%",
            "Mistral <sales@mistral.ai>",
            "Limited time discount. Upgrade today.",
        )

    def test_generic_agent_and_rag_terms_are_rejected(self):
        self.assertRejected(
            "How agents and RAG can improve your workflow",
            "Newsletter <digest@example.com>",
            "Download our ebook and customer case study.",
        )

    def test_json_array_extraction(self):
        parsed = radar._extract_json_array('```json\n[{"id": 0, "score": 90, "post": true}]\n```')
        self.assertEqual(parsed[0]["score"], 90)

    def test_deterministic_fallback_is_strict(self):
        old = os.environ.get("RADAR_TRIAGE_LLM")
        os.environ["RADAR_TRIAGE_LLM"] = "0"
        try:
            weak = {"subject": "Kimi K3 is here", "radar_score": 7}
            strong = {"subject": "Kimi K3 capacity blocked", "radar_score": 10}
            ranked = radar.rank_newsworthy_candidates([weak, strong])
            self.assertEqual([item["subject"] for item in ranked], ["Kimi K3 capacity blocked"])
        finally:
            if old is None:
                os.environ.pop("RADAR_TRIAGE_LLM", None)
            else:
                os.environ["RADAR_TRIAGE_LLM"] = old


if __name__ == "__main__":
    unittest.main()
