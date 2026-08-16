"""
Prompt specifications and JSON schema templates for Versus Dual-Perspective Synthesis.
Enforces character budget and editorial style matching the Flutter mobile client.
"""

import json
from typing import List
from ..storage.models import ExtractedArticle, ClusterClassification


SYSTEM_PROMPT_DEBATE = """You are the Lead Editorial AI for Versus News.
Your mission is to synthesize multi-source news articles covering a single controversial or debated topic into an objective, balanced story presenting two distinct opposing viewpoints.

EDITORIAL RULES:
1. Neutrality: Do not take a side. Present both angles with equal intellectual rigor and clarity.
2. Character Limits (Strict):
   - title: Balanced, engaging headline (max 90 chars).
   - summary: Objective 2-sentence background context (max 180 chars).
   - stanceTitle: Clear angle sub-headline (60-85 chars).
   - biasTag: Angle label, e.g., 'Innovation & Growth', 'Public Grid Strain' (12-25 chars).
   - keyPoints: Exactly 2 key takeaway bullets per perspective (50-75 chars each).
   - summary (per perspective): Concise editorial prose of this angle (55-75 words).
   - divergenceScore: Integer between 70 and 96 indicating level of conflicting debate.
   - consensusScore: 100 - divergenceScore.
   - tags: Array of 3-5 relevant short topic tags.

OUTPUT FORMAT:
Respond with ONLY valid, raw JSON matching the required schema. No conversational preamble, markdown code blocks, or explanations.
"""

SYSTEM_PROMPT_SINGLE = """You are the Lead Editorial AI for Versus News.
Your mission is to synthesize a single verified news report (scientific discovery, official announcement, or space mission) with 0 false controversy.

EDITORIAL RULES:
1. Factual & Clear: Accurately summarize the core event.
2. divergenceScore: MUST BE 0.
3. consensusScore: MUST BE 100.
4. perspective type: MUST BE 'directReport'.
5. Character Limits:
   - title: Clear, engaging headline (max 90 chars).
   - stanceTitle: Sub-headline summarizing the primary outcome (60-85 chars).
   - keyPoints: Exactly 2 key factual bullets (50-75 chars each).
   - summary: Concise verified update (55-75 words).
   - tags: Array of 3-5 tags.

OUTPUT FORMAT:
Respond with ONLY valid, raw JSON matching the required schema. No conversational preamble or code blocks.
"""


def build_synthesis_prompt(
    articles: List[ExtractedArticle],
    category: str,
    classification: ClusterClassification
) -> str:
    articles_payload = []
    for i, a in enumerate(articles, 1):
        # Truncate body to ~300 words to minimize tokens while keeping key context
        snippet = " ".join(a.cleaned_body.split()[:300])
        articles_payload.append({
            "source_index": i,
            "source_name": a.feed_name,
            "domain": a.domain,
            "credibility": a.credibility,
            "default_bias": a.default_bias,
            "title": a.title,
            "content_excerpt": snippet
        })

    is_debate = classification in (ClusterClassification.NEW_DEBATE, ClusterClassification.UPGRADE_STORY)

    prompt = f"""
Category: {category}
Is Dual Perspective Debate: {is_debate}
Source Articles:
{json.dumps(articles_payload, indent=2)}

Synthesize the above into the following JSON structure:
{{
  "title": "string",
  "summary": "string",
  "category": "{category}",
  "divergenceScore": {85 if is_debate else 0},
  "consensusScore": {15 if is_debate else 100},
  "tags": ["tag1", "tag2", "tag3"],
  "perspectives": [
    {{
      "type": "{"viewpoint1" if is_debate else "directReport"}",
      "sourceName": "string",
      "sourceDomain": "string",
      "biasTag": "string",
      "sourceCredibility": 95,
      "stanceTitle": "string (60-85 chars)",
      "summary": "string (55-75 words)",
      "keyPoints": ["bullet 1 (50-75 chars)", "bullet 2 (50-75 chars)"],
      "quote": "string (optional)",
      "quoteAuthor": "string (optional)"
    }}
    {"," if is_debate else ""}
    {'''{
      "type": "viewpoint2",
      "sourceName": "string",
      "sourceDomain": "string",
      "biasTag": "string",
      "sourceCredibility": 92,
      "stanceTitle": "string (60-85 chars)",
      "summary": "string (55-75 words)",
      "keyPoints": ["bullet 1 (50-75 chars)", "bullet 2 (50-75 chars)"],
      "quote": "string (optional)",
      "quoteAuthor": "string (optional)"
    }''' if is_debate else ''}
  ]
}}
"""
    return prompt
