"""
Prompt specifications and JSON schema templates for Versus Dual-Perspective Synthesis.
Enforces dense, journalistic 60-80 word summaries and multi-angle debate synthesis.
"""

import json
from typing import List
from ..storage.models import ExtractedArticle, ClusterClassification


SYSTEM_PROMPT_DEBATE = """You are the Senior Executive Editor for Versus News.
Your mission is to synthesize multi-source news reports covering a contested topic into an objective, deeply informative story presenting two distinct opposing viewpoints.

EDITORIAL STANDARDS (Dense, Informative Journalism):
1. Neutrality: Do not take a side. Present both angles with equal depth, intellectual rigor, and factual evidence.
2. Structure & Length Targets:
   - title: Clear, compelling journalistic headline (max 95 chars).
   - summary: Substantive 60-80 word editorial overview. Must answer:
       1) What happened (the central development)?
       2) Key background context & figures?
       3) Why it matters / the broader debate?
   - stanceTitle: Punchy, distinct angle headline for each perspective (60-85 chars).
   - biasTag: Editorial focus label, e.g., 'Economic Growth', 'Public Resource Cost', 'Policy Reform' (12-25 chars).
   - summary (per perspective): 55-75 word dense analysis explaining this specific viewpoint's primary arguments, evidence, and stakeholder perspective.
   - keyPoints: Exactly 2 distinct analytical takeaway bullets per perspective (60-90 chars each).
   - divergenceScore: Integer between 70 and 96 indicating level of opposing debate.
   - consensusScore: 100 - divergenceScore.
   - tags: Array of 3-5 relevant category and topic tags.

OUTPUT FORMAT:
Respond with ONLY valid raw JSON matching the required schema. No conversational preamble, markdown code blocks, or explanations.
"""

SYSTEM_PROMPT_SINGLE = """You are the Senior Executive Editor for Versus News.
Your mission is to synthesize a verified single-perspective news update (official mission, scientific discovery, corporate development, or public event) with depth and clarity.

EDITORIAL STANDARDS (Dense, Informative Journalism):
1. Factual Depth: Accurately explain the event, backstory, and broader significance.
2. Structure & Length Targets:
   - title: Clear, engaging headline (max 95 chars).
   - summary: Substantive 60-80 word comprehensive news summary covering:
       1) The core breaking event.
       2) Crucial data, names, locations, and background context.
       3) Ongoing investigations, implications, or future timeline.
   - stanceTitle: Sub-headline summarizing the primary outcome (60-85 chars).
   - biasTag: Perspective label, e.g., 'Official Update', 'Scientific Discovery', 'Court Ruling' (12-25 chars).
   - summary (inside perspective): 55-75 word detailed factual report.
   - keyPoints: Exactly 2 distinct factual takeaway bullets (60-90 chars each).
   - divergenceScore: MUST BE 0.
   - consensusScore: MUST BE 100.
   - perspective type: MUST BE 'directReport'.
   - tags: Array of 3-5 relevant tags.

OUTPUT FORMAT:
Respond with ONLY valid raw JSON matching the required schema. No conversational preamble or code blocks.
"""


def build_synthesis_prompt(
    articles: List[ExtractedArticle],
    category: str,
    classification: ClusterClassification
) -> str:
    articles_payload = []
    for i, a in enumerate(articles, 1):
        # Provide up to 400 words per source article for rich factual extraction
        snippet = " ".join(a.cleaned_body.split()[:400])
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

    perspectives_schema = [
        {
            "type": "viewpoint1" if is_debate else "directReport",
            "sourceName": articles[0].feed_name,
            "sourceDomain": articles[0].domain,
            "biasTag": articles[0].default_bias,
            "sourceCredibility": articles[0].credibility,
            "stanceTitle": "Angle headline summarizing viewpoint 1 (60-85 chars)",
            "summary": "55-75 words explaining this angle's arguments, data, and stakeholder position",
            "keyPoints": [
                "Takeaway bullet 1 with concrete fact or figure (60-90 chars)",
                "Takeaway bullet 2 with core argument or outcome (60-90 chars)"
            ],
            "quote": "",
            "quoteAuthor": ""
        }
    ]

    if is_debate:
        second_art = articles[1] if len(articles) > 1 else articles[0]
        perspectives_schema.append({
            "type": "viewpoint2",
            "sourceName": second_art.feed_name if len(articles) > 1 else "Counter Perspective",
            "sourceDomain": second_art.domain if len(articles) > 1 else second_art.domain,
            "biasTag": second_art.default_bias if len(articles) > 1 else "Counter View",
            "sourceCredibility": second_art.credibility if len(articles) > 1 else 90,
            "stanceTitle": "Angle headline summarizing opposing viewpoint 2 (60-85 chars)",
            "summary": "55-75 words explaining the counter-perspective arguments and concerns",
            "keyPoints": [
                "Counter takeaway bullet 1 with specific critique or risk (60-90 chars)",
                "Counter takeaway bullet 2 with alternative recommendation (60-90 chars)"
            ],
            "quote": "",
            "quoteAuthor": ""
        })

    schema_example = {
        "title": "Clear journalistic headline (60-95 chars)",
        "summary": "Substantive 60-80 word news story covering what happened, background context, and impact.",
        "category": category,
        "divergenceScore": 85 if is_debate else 0,
        "consensusScore": 15 if is_debate else 100,
        "tags": [category, "News", "Analysis"],
        "perspectives": perspectives_schema
    }

    prompt = (
        f"Category: {category}\n"
        f"Is Dual Perspective Debate: {is_debate}\n\n"
        f"Source Articles:\n"
        f"{json.dumps(articles_payload, indent=2)}\n\n"
        f"Write a dense, professional 60-80 word news story synthesized into the following JSON structure:\n"
        f"{json.dumps(schema_example, indent=2)}"
    )

    return prompt
