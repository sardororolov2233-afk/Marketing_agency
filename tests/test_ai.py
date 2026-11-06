import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

import httpx

from app.ai import GenerationError, generate_plan


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = patch.dict(os.environ, {"OPENROUTER_API_KEY": "example-secret", "OPENROUTER_MODEL": "provider/model"})
        self.config.start()
        self.addCleanup(self.config.stop)

    async def test_valid_structured_response_and_usage(self):
        draft = {"headline": "Sarlavha", "caption": "Matn", "cta": "Batafsil", "review_notes": []}
        payload = {"strategy": "Reja", "drafts": [draft] * 3, "missing_information": ["Narx"]}

        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["model"], "provider/model")
            self.assertEqual(body["max_tokens"], 2000)
            self.assertEqual(body["response_format"]["type"], "json_schema")
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost": 0.000123}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_plan("Ta'lim loyihasi", "Auditoriyani xabardor qilish", client=client)
        self.assertEqual(len(result.plan.drafts), 3)
        self.assertEqual((result.input_tokens, result.output_tokens), (10, 20))
        self.assertEqual(result.reported_cost_usd, Decimal("0.000123"))

    async def test_unknown_provider_cost_is_not_fabricated(self):
        draft = {"headline": "S", "caption": "M", "cta": "C", "review_notes": []}
        payload = {"strategy": "R", "drafts": [draft] * 3, "missing_information": []}
        for cost in (None, -1, True, "1.23"):
            response = {"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"cost": cost}}
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
                result = await generate_plan("brand", "goal", client=client)
            self.assertIsNone(result.reported_cost_usd)

    async def test_invalid_json_and_wrong_draft_count_fail_closed(self):
        response = {"choices": [{"message": {"content": '{"strategy":"test","drafts":[],"missing_information":[]}'}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
            with self.assertRaises(GenerationError):
                await generate_plan("brand", "goal", client=client)

    async def test_provider_errors_do_not_expose_response(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="example-secret"))) as client:
            with self.assertRaises(GenerationError) as error:
                await generate_plan("brand", "goal", client=client)
        self.assertNotIn("example-secret", str(error.exception))

    async def test_model_must_be_explicit(self):
        with patch.dict(os.environ, {"OPENROUTER_MODEL": ""}):
            with self.assertRaises(GenerationError):
                await generate_plan("brand", "goal")


if __name__ == "__main__":
    unittest.main()
