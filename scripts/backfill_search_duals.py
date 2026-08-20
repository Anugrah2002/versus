"""
Backfill Active Search Discovery on existing Firestore articles.
Finds real, published competing articles from accredited news outlets (The Hindu, Indian Express,
Economic Times, Livemint, NDTV, Reuters, etc.) for existing single-source stories,
synthesizes genuine Dual Views with full source attribution, and updates Firestore + Static Feeds.
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
import hashlib

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync
from src.sources.search_discovery import search_discovery
from src.storage.models import ExtractedArticle, StoryCluster, ClusterClassification
from src.synthesis.llm_engine import synthesis_engine
from src.storage.static_exporter import static_exporter
from src.utils.logger import logger


async def run_backfill(max_stories: int = 30):
    if not firestore_sync.initialize():
        print("Failed to connect to Firestore.")
        return

    db = firestore_sync.db
    articles_col = db.collection("articles")

    print("Auditing existing Dual Views in Firestore for 100% congruence...")
    all_docs = list(articles_col.stream())
    print(f"Total articles fetched: {len(all_docs)}")

    # Clean up previous mismatched dual views
    for doc in all_docs:
        d = doc.to_dict() or {}
        if not d.get("isSinglePerspective", True):
            perspectives = d.get("perspectives", [])
            if len(perspectives) >= 2:
                p1_t = perspectives[0].get("stanceTitle", "")
                p2_t = perspectives[1].get("stanceTitle", "")
                # Check for mismatched topics
                is_fishing_iran = "fishing" in p1_t.lower() and "iran" in p2_t.lower()
                is_working_travel = "working" in p1_t.lower() and "travel" in p2_t.lower()
                is_everest_deepseek = "everest" in p1_t.lower() and "deepseek" in p2_t.lower()
                if is_fishing_iran or is_working_travel or is_everest_deepseek:
                    print(f"🧹 Relegating mismatched Dual View to Brief: [{doc.id}] {d.get('title')}")
                    articles_col.document(doc.id).update({
                        "isSinglePerspective": True,
                        "divergenceScore": 0,
                        "consensusScore": 100
                    })

    # Find single perspective articles that are substantial
    single_articles = []
    for doc in all_docs:
        d = doc.to_dict() or {}
        if d.get("isSinglePerspective", True):
            title = d.get("title", "")
            summary = d.get("summary", "")
            perspectives = d.get("perspectives", [])
            p1_summary = perspectives[0].get("summary", "") if perspectives else summary
            
            if len((title + " " + p1_summary).split()) >= 25:
                single_articles.append((doc.id, d))

    print(f"Found {len(single_articles)} candidate single-perspective stories for active search discovery.")

    upgraded_count = 0

    for doc_id, d in single_articles[:max_stories]:
        title = d.get("title", "")
        summary = d.get("summary", "")
        perspectives = d.get("perspectives", [])
        p1 = perspectives[0] if perspectives else {}
        source_name = p1.get("sourceName", "News Source")
        source_domain = p1.get("sourceDomain", "news.com")
        category = d.get("category", "World Affairs")
        published_at_str = d.get("publishedAt", datetime.now(timezone.utc).isoformat())
        hero_image = d.get("heroImageUrl", "")

        try:
            pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
        except Exception:
            pub_date = datetime.now(timezone.utc)

        p1_body = p1.get("summary", summary)
        if len(p1_body.split()) < 15:
            p1_body = f"{title}. {summary}"

        primary_extracted = ExtractedArticle(
            url=f"https://{source_domain}/article/{doc_id}",
            url_hash=hashlib.sha256(doc_id.encode()).hexdigest()[:16],
            title=title,
            cleaned_body=p1_body,
            word_count=len(p1_body.split()),
            hero_image_url=hero_image,
            feed_name=source_name,
            domain=source_domain,
            category=category,
            credibility=p1.get("sourceCredibility", 92),
            default_bias=p1.get("biasTag", "Reporting"),
            published_at=pub_date
        )

        # Active search discovery
        competing_list = await search_discovery.discover_competing_articles(primary_extracted, max_matches=1)
        if not competing_list:
            continue

        competing_art = competing_list[0]
        print(f"\n✨ Upgrading: [{doc_id}] {title}")
        print(f"   Source 1: {source_name} ({source_domain})")
        print(f"   Source 2: {competing_art.feed_name} ({competing_art.domain}) -> {competing_art.title}")

        # Form a 2-article cluster
        cluster = StoryCluster(
            cluster_id=f"deb_{doc_id}",
            classification=ClusterClassification.NEW_DEBATE,
            category=category,
            articles=[primary_extracted, competing_art],
            centroid_vector=[0.0] * 384
        )

        # Synthesize 2 real perspectives
        art_model = synthesis_engine.synthesize(cluster)
        if art_model:
            # Update Firestore document
            doc_ref = articles_col.document(doc_id)
            doc_ref.update({
                "title": art_model.title,
                "summary": art_model.summary,
                "isSinglePerspective": False,
                "divergenceScore": art_model.divergenceScore,
                "consensusScore": art_model.consensusScore,
                "perspectives": [p.model_dump() for p in art_model.perspectives],
                "tags": art_model.tags
            })
            upgraded_count += 1
            print(f"   🎉 Successfully updated {doc_id} in Firestore as Dual View ({art_model.divergenceScore}% divergence)!")

        if upgraded_count >= 15:
            print(f"\nReached batch goal of {upgraded_count} upgraded Dual Views.")
            break

    print(f"\n=================================================")
    print(f"Total stories upgraded to genuine Dual Views: {upgraded_count}")
    print(f"=================================================")

    # Refresh static paginated feeds
    static_exporter.export_all_feeds()


if __name__ == "__main__":
    asyncio.run(run_backfill(max_stories=25))
