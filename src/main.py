"""
Versus Backend Ingestion Engine Entrypoint.
Orchestrates async RSS fetching, full-text extraction, local ONNX clustering,
multi-provider stance synthesis, and Firestore atomic sync.
"""

import sys
import os
import time
import argparse
import asyncio
from datetime import datetime, timezone
from typing import List, Tuple

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import settings
from src.utils.logger import logger
from src.storage.models import PipelineSummary, ArticleModel, StoryCluster, ClusterClassification
from src.storage.state_manager import state_manager
from src.storage.firestore_sync import firestore_sync
from src.sources.rss_source import RSSFeedSource
from src.sources.mock_source import MockFeedSource
from src.extractors.article_extractor import article_extractor
from src.clustering.clusterer import clusterer
from src.synthesis.llm_engine import synthesis_engine


async def run_pipeline(
    use_mock: bool = False,
    max_feeds: int = None,
    dry_run: bool = False
) -> PipelineSummary:
    start_time = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    logger.info("=" * 65)
    logger.info(f"🚀 Starting Versus Ingestion Pipeline at {now_iso}")
    logger.info("=" * 65)

    if dry_run:
        settings.DRY_RUN = True
        logger.info("[DRY RUN MODE ENABLED]")

    # Step 0: Initialize Firebase connection if available
    connected = firestore_sync.initialize()
    if connected:
        state_manager.set_firestore_client(firestore_sync.db)

    # Step 1: Ingest Feed Candidates
    source = MockFeedSource() if use_mock else RSSFeedSource()
    logger.info(f"Ingesting candidate articles from source: {source.name}...")
    candidates = await source.fetch_candidates(state_manager, max_feeds=max_feeds)

    # Edge Case: Fast Exit when 0 new articles found
    if not candidates:
        duration = time.time() - start_time
        logger.info(f"⚡ Zero new candidate articles found. Fast exit in {duration:.2f}s.")
        state_manager.save_local_state()
        state_manager.save_to_firestore()
        return PipelineSummary(
            run_timestamp=now_iso,
            feeds_checked=len(source.feeds) if hasattr(source, "feeds") else 0,
            feeds_with_304=getattr(source, "feeds_with_304", 0),
            candidate_urls_found=0,
            scraped_articles_passed=0,
            clusters_formed=0,
            new_debates=0,
            single_reports=0,
            upgraded_stories=0,
            firestore_writes_committed=0,
            ai_calls_made=0,
            ai_provider_used="none",
            duration_seconds=duration
        )

    # Step 2: Quality Gatekeeper & Full-Text Scraping
    logger.info(f"Extracting and gatekeeping {len(candidates)} candidate articles...")
    extracted_articles = await article_extractor.extract_batch(candidates)

    if not extracted_articles:
        duration = time.time() - start_time
        logger.info(f"All candidate articles were filtered by quality gatekeeper. Exit in {duration:.2f}s.")
        return PipelineSummary(
            run_timestamp=now_iso,
            feeds_checked=len(source.feeds) if hasattr(source, "feeds") else 0,
            feeds_with_304=getattr(source, "feeds_with_304", 0),
            candidate_urls_found=len(candidates),
            scraped_articles_passed=0,
            clusters_formed=0,
            new_debates=0,
            single_reports=0,
            upgraded_stories=0,
            firestore_writes_committed=0,
            ai_calls_made=0,
            ai_provider_used="none",
            duration_seconds=duration
        )

    # Mark extracted URLs as seen in state manager
    for art in extracted_articles:
        state_manager.mark_url_seen(art.url_hash)

    # Step 3: Local Semantic Clustering & Active Story Matching
    active_stories = state_manager.get_active_stories_list()
    clusters = clusterer.cluster_articles(extracted_articles, active_stories)

    # Step 4: AI Dual-Perspective Synthesis & Immediate Streaming Publication
    def on_story_completed(art: ArticleModel, cluster: StoryCluster):
        state_manager.register_active_story(art, cluster)

    synthesized_pairs = synthesis_engine.synthesize_batch(
        clusters,
        max_concurrent=8,
        on_published=on_story_completed
    )

    debates_count = sum(1 for _, c in synthesized_pairs if c.classification == ClusterClassification.NEW_DEBATE)
    upgrades_count = sum(1 for _, c in synthesized_pairs if c.classification == ClusterClassification.UPGRADE_STORY)
    singles_count = sum(1 for _, c in synthesized_pairs if c.classification == ClusterClassification.SINGLE_REPORT)

    # Step 5: Rolling 30-Day TTL Data Retention Cleanup
    firestore_sync.cleanup_expired_articles()

    # Step 6: Save Updated Pipeline State
    state_manager.save_local_state()
    state_manager.save_to_firestore()

    duration = time.time() - start_time
    logger.info("=" * 65)
    logger.info(
        f"✅ Ingestion Run Finished in {duration:.2f}s | "
        f"Committed {committed_count} stories ({debates_count} debates, {upgrades_count} upgrades, {singles_count} single updates) | "
        f"AI Provider: {synthesis_engine.last_provider_used}"
    )
    logger.info("=" * 65)

    return PipelineSummary(
        run_timestamp=now_iso,
        feeds_checked=len(source.feeds) if hasattr(source, "feeds") else 0,
        feeds_with_304=getattr(source, "feeds_with_304", 0),
        candidate_urls_found=len(candidates),
        scraped_articles_passed=len(extracted_articles),
        clusters_formed=len(clusters),
        new_debates=debates_count,
        single_reports=singles_count,
        upgraded_stories=upgrades_count,
        firestore_writes_committed=committed_count,
        ai_calls_made=synthesis_engine.total_ai_calls,
        ai_provider_used=synthesis_engine.last_provider_used,
        duration_seconds=duration
    )


def main():
    parser = argparse.ArgumentParser(description="Versus Backend Ingestion Engine")
    parser.add_argument("--mock", action="store_true", help="Run with synthetic mock data for offline testing")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to Firebase Firestore")
    parser.add_argument("--max-feeds", type=int, default=None, help="Limit number of RSS feeds to fetch")
    args = parser.parse_args()

    asyncio.run(
        run_pipeline(
            use_mock=args.mock,
            max_feeds=args.max_feeds,
            dry_run=args.dry_run
        )
    )


if __name__ == "__main__":
    main()
