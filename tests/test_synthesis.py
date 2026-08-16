"""
Unit tests for stance synthesis engine and local fallback synthesizer.
"""

from datetime import datetime, timezone
from src.synthesis.providers.fallback_provider import local_fallback_synthesizer
from src.synthesis.llm_engine import synthesis_engine
from src.storage.models import (
    ExtractedArticle,
    StoryCluster,
    ClusterClassification
)


def test_local_fallback_synthesizer_debate():
    now = datetime.now(timezone.utc)
    articles = [
        ExtractedArticle(
            url="https://techcrunch.com/a1",
            url_hash="hash1",
            title="Tech Giants Invest $100B in Compute Hubs",
            cleaned_body="Massive AI compute hubs are necessary to speed up discoveries in medicine and climate solutions. Nations investing heavily will lead the next economy.",
            word_count=25,
            hero_image_url="https://example.com/img.jpg",
            feed_name="TechCrunch",
            domain="techcrunch.com",
            category="Tech & AI",
            credibility=96,
            default_bias="Innovation & Growth",
            published_at=now
        ),
        ExtractedArticle(
            url="https://reuters.com/a2",
            url_hash="hash2",
            title="AI Power Draw Strains Municipal Utilities",
            cleaned_body="A single mega AI cluster consumes power equal to 2.5 lakh households. Experts warn of grid instability during peak summer months.",
            word_count=23,
            hero_image_url="https://example.com/img.jpg",
            feed_name="Reuters",
            domain="reuters.com",
            category="Tech & AI",
            credibility=94,
            default_bias="Costs & Resources",
            published_at=now
        )
    ]

    cluster = StoryCluster(
        cluster_id="test_cluster_01",
        classification=ClusterClassification.NEW_DEBATE,
        category="Tech & AI",
        articles=articles
    )

    result = local_fallback_synthesizer.synthesize_cluster(cluster)
    assert "title" in result
    assert result["divergenceScore"] == 88
    assert len(result["perspectives"]) == 2
    assert result["perspectives"][0]["type"] == "viewpoint1"
    assert result["perspectives"][1]["type"] == "viewpoint2"
    assert len(result["perspectives"][0]["keyPoints"]) == 2


def test_synthesis_engine_end_to_end():
    now = datetime.now(timezone.utc)
    articles = [
        ExtractedArticle(
            url="https://isro.gov.in/p1",
            url_hash="hash_isro",
            title="ISRO Launches Earth Radar Satellite NISAR",
            cleaned_body="The NISAR spacecraft entered orbit successfully to map global environmental changes and natural hazard zones.",
            word_count=18,
            hero_image_url="https://example.com/isro.jpg",
            feed_name="ISRO Official",
            domain="isro.gov.in",
            category="Space & Science",
            credibility=99,
            default_bias="Official Update",
            published_at=now
        )
    ]

    cluster = StoryCluster(
        cluster_id="test_cluster_single",
        classification=ClusterClassification.SINGLE_REPORT,
        category="Space & Science",
        articles=articles
    )

    article_model = synthesis_engine.synthesize(cluster)
    assert article_model is not None
    assert article_model.isSinglePerspective is True
    assert article_model.divergenceScore == 0
    assert article_model.consensusScore == 100
    assert len(article_model.perspectives) == 1
    assert article_model.perspectives[0].type == "directReport"
