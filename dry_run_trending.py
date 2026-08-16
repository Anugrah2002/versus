"""
Dry-run script specifically testing live RSS ingestion from:
1. Hindustan Times Trending: https://www.hindustantimes.com/feeds/rss/trending/rssfeed.xml
2. NDTV Trending News: https://feeds.feedburner.com/ndtvnews-trending-news
"""

import asyncio
import json
from src.sources.rss_source import RSSFeedSource
from src.extractors.article_extractor import article_extractor
from src.clustering.clusterer import clusterer
from src.synthesis.llm_engine import synthesis_engine
from src.storage.state_manager import StateManager
from src.storage.models import FeedDefinition
from src.utils.logger import logger


async def test_live_trending_feeds():
    logger.info("=" * 70)
    logger.info("🔍 STARTING LIVE RSS DRY RUN FOR TRENDING FEEDS")
    logger.info("=" * 70)

    test_feeds = [
        FeedDefinition(
            name="Hindustan Times Trending",
            url="https://www.hindustantimes.com/feeds/rss/trending/rssfeed.xml",
            domain="hindustantimes.com",
            category="World Affairs",
            credibility=92,
            defaultBias="Trending News"
        ),
        FeedDefinition(
            name="NDTV Trending News",
            url="https://feeds.feedburner.com/ndtvnews-trending-news",
            domain="ndtv.com",
            category="World Affairs",
            credibility=93,
            defaultBias="Trending & Viral"
        )
    ]

    # Fresh state manager in memory for dry-run
    state_mgr = StateManager(local_path=".state_cache/dry_run_state.json")
    state_mgr.seen_url_hashes.clear()

    source = RSSFeedSource()
    source.feeds = test_feeds

    # 1. Fetch live RSS candidates
    logger.info(f"Fetching live candidate articles from {len(test_feeds)} feeds...")
    candidates = await source.fetch_candidates(state_mgr)
    logger.info(f"✅ Found {len(candidates)} live candidate articles across the two feeds.")

    for i, c in enumerate(candidates[:6], 1):
        logger.info(f"  [{i}] ({c.feed_name}) {c.title}")

    # 2. Extract full prose & images
    logger.info("\nExtracting and gatekeeping article content via Trafilatura / OpenGraph...")
    extracted = await article_extractor.extract_batch(candidates[:10], max_concurrent=5)
    logger.info(f"✅ {len(extracted)}/{min(len(candidates), 10)} articles passed extraction and quality gatekeeper.")

    # 3. Cluster articles locally
    logger.info("\nRunning Local Semantic Clustering & Active Story Matcher...")
    clusters = clusterer.cluster_articles(extracted, active_stories=[])
    logger.info(f"✅ Formed {len(clusters)} story clusters.")

    # 4. Synthesize top stories
    logger.info("\nSynthesizing Versus Dual-Perspective Stories...")
    synthesized_stories = []
    for i, c in enumerate(clusters[:3], 1):
        story = synthesis_engine.synthesize(c)
        if story:
            synthesized_stories.append(story)
            logger.info(f"\n--- [Synthesized Story #{i}] ---")
            logger.info(f"Title: {story.title}")
            logger.info(f"Category: {story.category} | Divergence: {story.divergenceScore}% | Consensus: {story.consensusScore}%")
            logger.info(f"Hero Image: {story.heroImageUrl}")
            logger.info(f"Perspectives Count: {len(story.perspectives)}")
            for p in story.perspectives:
                logger.info(f"  • [{p.label if hasattr(p, 'label') else p.type.upper()}] ({p.sourceName} | {p.biasTag})")
                logger.info(f"    Stance: {p.stanceTitle}")
                logger.info(f"    Summary: {p.summary[:140]}...")
                if p.keyPoints:
                    logger.info(f"    Key Points: {p.keyPoints}")

    logger.info("\n" + "=" * 70)
    logger.info(f"🎉 Live Dry Run Complete: Successfully processed live feeds and generated {len(synthesized_stories)} Versus stories.")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_live_trending_feeds())
