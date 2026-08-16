"""
Unit tests for local semantic clustering and delayed viewpoint matching.
"""

from datetime import datetime, timezone
from src.clustering.clusterer import SemanticClusterer
from src.clustering.embedder import embedder
from src.storage.models import (
    ExtractedArticle,
    ActiveStoryState,
    ClusterClassification
)


def create_mock_article(url_hash: str, title: str, domain: str, category: str, body: str) -> ExtractedArticle:
    return ExtractedArticle(
        url=f"https://{domain}/{url_hash}",
        url_hash=url_hash,
        title=title,
        cleaned_body=body,
        word_count=len(body.split()),
        hero_image_url="https://example.com/img.jpg",
        feed_name=domain.split(".")[0].capitalize(),
        domain=domain,
        category=category,
        credibility=95,
        default_bias="Standard",
        published_at=datetime.now(timezone.utc)
    )


def test_embedder_output_shape():
    import math
    texts = [
        "Tech Giants Invest $100B in AI Data Centers and power grids.",
        "ISRO and NASA successfully launch NISAR radar satellite."
    ]
    vectors = embedder.embed_texts(texts)
    assert len(vectors) == 2
    assert len(vectors[0]) == 384
    # Check unit norm
    for v in vectors:
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 0.05


def test_clustering_multi_source_debate():
    clusterer = SemanticClusterer(threshold=0.45)
    articles = [
        create_mock_article(
            "h1",
            "Tech Giants Invest $100B in AI Mega Data Centers",
            "techcrunch.com",
            "Tech & AI",
            "Artificial intelligence compute clusters require billions in capital investment to advance frontier foundation models and scientific discoveries."
        ),
        create_mock_article(
            "h2",
            "AI Data Centers Strain Electricity Grids and Water Utilities",
            "reuters.com",
            "Tech & AI",
            "Surging electricity consumption from artificial intelligence data centers threatens public power grids and risks tariff increases."
        ),
        create_mock_article(
            "h3",
            "ISRO Launches NISAR Satellite to Map Earth Ecosystems",
            "thehindu.com",
            "Space & Science",
            "The Indian Space Research Organisation launched the radar imaging spacecraft from Sriharikota."
        )
    ]

    clusters = clusterer.cluster_articles(articles, active_stories=[])
    assert len(clusters) >= 2

    # Verify that techcrunch + reuters formed a debate cluster
    ai_cluster = next((c for c in clusters if c.category == "Tech & AI"), None)
    assert ai_cluster is not None
    assert len(ai_cluster.articles) == 2
    assert ai_cluster.classification == ClusterClassification.NEW_DEBATE


def test_delayed_perspective_upgrade_matching():
    clusterer = SemanticClusterer(threshold=0.45)

    # Simulate existing active single-perspective story from 1 hour ago
    existing_text = "Global 4-Day Work Week Trials Show 35% Reduction in Burnout"
    existing_vec = embedder.embed_texts([existing_text])[0]

    active_story = ActiveStoryState(
        article_id="art-work-001",
        title="4-Day Work Week Pilot Shows Strong Wellness Gains",
        category="Work & Economy",
        divergence_score=0,
        is_single_perspective=True,
        centroid_vector=existing_vec if isinstance(existing_vec, list) else existing_vec.tolist(),
        published_at=datetime.now(timezone.utc).isoformat(),
        domains=["livemint.com"],
        last_updated_at=datetime.now(timezone.utc).isoformat()
    )

    # New article arriving in current run with counter-perspective from different domain
    new_article = create_mock_article(
        "h_counter",
        "Factories and Startups Warn 4-Day Work Week Hurts Output and Productivity",
        "economictimes.com",
        "Work & Economy",
        "Manufacturing executives explain that four-day work week schedules cannot operate without 20% extra payroll."
    )

    clusters = clusterer.cluster_articles([new_article], active_stories=[active_story])
    assert len(clusters) == 1
    assert clusters[0].classification == ClusterClassification.UPGRADE_STORY
    assert clusters[0].matched_existing_article_id == "art-work-001"


def test_alias_and_graph_multi_source_clustering():
    clusterer = SemanticClusterer(threshold=0.40)
    articles = [
        create_mock_article(
            "a1",
            "Anthropic Weighs $2 Trillion Valuation IPO for September",
            "bloomberg.com",
            "Tech & AI",
            "Claude AI maker Anthropic is preparing for a public market debut on NASDAQ."
        ),
        create_mock_article(
            "a2",
            "Claude Maker Explores Initial Public Offering on Wall Street",
            "reuters.com",
            "Work & Economy",  # Different category!
            "The AI startup led by Dario Amodei considers IPO listing amidst booming enterprise compute demand."
        ),
        create_mock_article(
            "a3",
            "Boeing 737 MAX Deliveries Resume Following FAA Regulatory Clearance",
            "wsj.com",
            "World Affairs",
            "Aviation regulators cleared Boeing to ramp commercial jetliner assembly."
        )
    ]

    clusters = clusterer.cluster_articles(articles, active_stories=[])
    assert len(clusters) == 2  # Anthropic cluster + Boeing cluster

    anthropic_cluster = next((c for c in clusters if any("bloomberg.com" in a.domain for a in c.articles)), None)
    assert anthropic_cluster is not None
    assert len(anthropic_cluster.articles) == 2
    assert anthropic_cluster.classification == ClusterClassification.NEW_DEBATE
    assert set(a.domain for a in anthropic_cluster.articles) == {"bloomberg.com", "reuters.com"}

    boeing_cluster = next((c for c in clusters if any("wsj.com" in a.domain for a in c.articles)), None)
    assert boeing_cluster is not None
    assert len(boeing_cluster.articles) == 1
    assert boeing_cluster.classification == ClusterClassification.SINGLE_REPORT
