"""
Inspects and displays the synthesized dual-perspective debate stories
generated during the pipeline dry-run.
"""

import json
from pathlib import Path
from src.storage.state_manager import state_manager
from src.storage.models import ClusterClassification
from src.sources.mock_source import MockFeedSource
from src.extractors.article_extractor import article_extractor
from src.clustering.clusterer import clusterer
from src.synthesis.llm_engine import synthesis_engine
import asyncio


async def show_dual_perspectives():
    print("=" * 80)
    print("🌟 VERSUS DUAL-PERSPECTIVE SYNTHESIS INSPECTOR")
    print("=" * 80)

    # Run on multi-source candidates with fresh in-memory state
    from src.storage.state_manager import StateManager
    fresh_state = StateManager(local_path=".state_cache/temp_inspect_state.json")
    fresh_state.seen_url_hashes.clear()

    source = MockFeedSource()
    candidates = await source.fetch_candidates(fresh_state)
    extracted = await article_extractor.extract_batch(candidates)
    clusters = clusterer.cluster_articles(extracted, active_stories=[])

    debates = [c for c in clusters if c.classification == ClusterClassification.NEW_DEBATE]
    print(f"\nFound {len(debates)} Multi-Source Debate Clusters.\n")

    for idx, cluster in enumerate(debates, 1):
        story = synthesis_engine.synthesize(cluster)
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"🔥 DEBATE STORY #{idx}: {story.title}")
        print(f"📁 Category: {story.category} | ⚡ Divergence Score: {story.divergenceScore}% (Consensus: {story.consensusScore}%)")
        print(f"🖼️ Hero Image: {story.heroImageUrl}")
        print(f"📝 Editorial Summary: {story.summary}\n")

        for p in story.perspectives:
            color_tag = "🔵 CYAN (VIEWPOINT 1)" if p.type == "viewpoint1" else "🟣 MAGENTA (VIEWPOINT 2)"
            print(f"  {color_tag}:")
            print(f"    • Source: {p.sourceName} ({p.sourceDomain}) | Credibility: {p.sourceCredibility}/100")
            print(f"    • Bias / Angle Tag: [{p.biasTag}]")
            print(f"    • Stance Headline: \"{p.stanceTitle}\"")
            print(f"    • Angle Summary: {p.summary}")
            if p.keyPoints:
                print(f"    • Takeaways:")
                for k in p.keyPoints:
                    print(f"        - {k}")
            print()

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


if __name__ == "__main__":
    asyncio.run(show_dual_perspectives())
