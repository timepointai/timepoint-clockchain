import json
import logging

import httpx

logger = logging.getLogger("clockchain.judge")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

JUDGE_PROMPT = """You are a content moderation system for a historical education platform.

Evaluate this query for a historical scene generation:
"{query}"

Classify as ONE of:
- "approve" — innocuous historical topic, safe to generate
- "sensitive" — involves violence, controversy, or mature themes but is historically significant and educational; approve with a disclaimer
- "reject" — harmful, hateful, exploitative, or not a genuine historical query

Return ONLY a JSON object: {{"verdict": "approve"|"sensitive"|"reject", "reason": "brief explanation"}}"""


class ContentJudge:
    def __init__(self, api_key: str, model: str = "google/gemini-2.0-flash-001"):
        self.api_key = api_key
        self.model = model

    async def screen(self, query: str) -> str:
        prompt = JUDGE_PROMPT.format(query=query)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        verdict = result.get("verdict", "reject")
        logger.info("Judge verdict for %r: %s (%s)", query, verdict, result.get("reason", ""))

        if verdict in ("approve", "sensitive"):
            return verdict
        return "reject"
