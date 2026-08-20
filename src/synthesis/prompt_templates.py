"""
Prompt specifications and JSON schema templates for Versus Dual-Perspective Synthesis.
Enforces rich, journalistic 90-120 word substantive editorial summaries and multi-angle debate synthesis.
"""

import json
from typing import List
from ..storage.models import ExtractedArticle, ClusterClassification


SYSTEM_PROMPT_DEBATE = """You are the Senior Executive Editor for Versus News.
Your mission is to transform multi-source reporting on a major news event into a deeply engaging, balanced dual-perspective story presenting TWO DISTINCT, CONTRASTING EDITORIAL ANGLES.

CORE EDITORIAL PRINCIPLES:
1. ANGLE CONTRAST RULE (MANDATORY):
   - Perspective 1 MUST focus on the PRO-CASE / STRATEGIC IMPACT / INNOVATION / ECONOMIC BENEFITS / OFFICIAL GOALS.
     * Stance Title format: "[Focus Tag]: [Bold, punchy angle headline]" (e.g. "Commercial Milestone: Tesla Secures Crucial Autonomous Foothold in Nevada")
     * Bias Tag: e.g. "Autonomous Growth", "Economic Impact", "Industry Push"
   - Perspective 2 MUST focus on the COUNTER-CASE / REGULATORY SCRUTINY / SAFETY RISKS / CRITICISMS / RESTRICTIONS.
     * Stance Title format: "[Focus Tag]: [Bold, punchy counter-headline]" (e.g. "Regulatory Safeguards: Nevada Imposes Tight 10-Car Fleet Cap Under 45mph Limit")
     * Bias Tag: e.g. "Safety Oversight", "Public Caution", "Regulatory Scrutiny"
   - STRICT PROHIBITION: Never duplicate the same perspective or rewrite the same sentence. Both angles must explore distinct, contrasting dimensions of the story.

2. WRITING STYLE (Inshorts Style - High Impact, Zero Fluff):
   - title: Sharp, compelling headline capturing the core event (max 90 chars).
   - summary: 45-55 words giving an urgent, crystal-clear overview of what happened and why it matters.
   - summary (per perspective): 45-55 words of polished, substantive editorial prose highlighting specific arguments, numbers, and stakeholder stakes.
   - keyPoints: Exactly 2 sharp takeaway bullets with concrete numbers, data, or facts (max 85 chars each).
   - divergenceScore: Integer between 75 and 92.
   - consensusScore: 100 - divergenceScore.
   - tags: Array of 3-5 relevant topic tags.

3. REAL SOURCE ATTRIBUTION:
   - Ground all details strictly in the real source text. Preserve real sourceName and sourceDomain.

OUTPUT FORMAT:
Respond with ONLY valid raw JSON matching the required schema. No preamble or markdown code blocks.
"""

SYSTEM_PROMPT_SINGLE = """You are the Senior Executive Editor for Versus News.
Your mission is to synthesize a verified single-perspective news update (official mission, scientific discovery, corporate development, or public event) with maximum brevity and clarity.

EDITORIAL STANDARDS (Concise, High-Impact Short-Form Journalism):
1. Factual Precision: Accurately explain the event, immediate facts, and key outcome.
2. Structure & Length Targets (Strict Inshorts Style):
   - title: Clear, engaging headline (max 95 chars).
   - summary: Concise 45-60 word news summary (strictly 2-3 sentences covering who/what/why).
   - stanceTitle: Sub-headline summarizing the primary outcome (max 120 chars).
   - biasTag: Perspective label, e.g., 'Official Update', 'Scientific Discovery', 'Court Ruling', 'Public Briefing' (12-25 chars).
   - summary (inside perspective): Strictly 45-60 words of clear factual report.
   - keyPoints: Exactly 2 distinct factual takeaway bullets (max 85 chars each).
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
        # Provide up to 600 words per source article for rich factual extraction
        snippet = " ".join(a.cleaned_body.split()[:600])
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
            "stanceTitle": "Angle headline summarizing viewpoint 1 (60-90 chars)",
            "summary": "80-110 words explaining this angle's arguments, data, and stakeholder position in full sentences",
            "keyPoints": [
                "Takeaway bullet 1 with concrete fact, number, or quote (75-110 chars)",
                "Takeaway bullet 2 with core argument or outcome (75-110 chars)"
            ],
            "quote": "",
            "quoteAuthor": ""
        }
    ]

    if is_debate:
        second_art = articles[1] if len(articles) > 1 else articles[0]
        perspectives_schema.append({
            "type": "viewpoint2",
            "sourceName": second_art.feed_name,
            "sourceDomain": second_art.domain,
            "biasTag": second_art.default_bias,
            "sourceCredibility": second_art.credibility,
            "stanceTitle": "Angle headline summarizing viewpoint 2 (60-90 chars)",
            "summary": "80-110 words explaining this counter-viewpoint's arguments, risks, or contrasting evidence",
            "keyPoints": [
                "Counter-takeaway bullet 1 with specific evidence or constraint (75-110 chars)",
                "Counter-takeaway bullet 2 with contrasting stakeholder concern (75-110 chars)"
            ],
            "quote": "",
            "quoteAuthor": ""
        })

    output_schema_example = {
        "title": "Clear, informative headline covering the story (max 95 chars)",
        "summary": "Substantive 90-120 word comprehensive editorial overview detailing what happened, background context, and societal significance.",
        "category": category,
        "divergenceScore": 85 if is_debate else 0,
        "consensusScore": 15 if is_debate else 100,
        "perspectives": perspectives_schema,
        "tags": [category, "Analysis", "Key Topic"]
    }

    instructions = (
        f"Synthesize the following {len(articles)} source articles into a {'dual-perspective debate story' if is_debate else 'verified single-perspective news brief'}.\n"
        f"Primary Category: {category}\n\n"
        f"SOURCE ARTICLES DATA:\n"
        f"{json.dumps(articles_payload, indent=2)}\n\n"
        f"TARGET JSON OUTPUT STRUCTURE (Follow this exact schema):\n"
        f"{json.dumps(output_schema_example, indent=2)}\n\n"
        f"CRITICAL REQUIREMENT: Return ONLY raw, valid JSON starting with '{{' and ending with '}}'. Produce 90-120 words for the main summary and 80-110 words per perspective summary."
    )

    return instructions
