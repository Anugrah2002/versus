"""
Unit tests for data models and schema validity with Flutter ArticleModel.
"""

from datetime import datetime, timezone
from src.storage.models import ArticleModel, PerspectiveModel, PerspectiveType


def test_article_model_schema():
    perspectives = [
        PerspectiveModel(
            id="p_001_a",
            type="viewpoint1",
            sourceName="TechCrunch",
            sourceDomain="techcrunch.com",
            biasTag="Innovation & Growth",
            sourceCredibility=96,
            stanceTitle="Essential for Scientific Breakthroughs & Global Tech Leadership",
            summary="Massive AI compute hubs are necessary to speed up discoveries in medicine.",
            keyPoints=["Crucial compute infrastructure", "Speeds up discoveries"]
        ),
        PerspectiveModel(
            id="p_001_b",
            type="viewpoint2",
            sourceName="Reuters",
            sourceDomain="reuters.com",
            biasTag="Costs & Resources",
            sourceCredibility=94,
            stanceTitle="Spike in Power Bills and Heavy Strain on Public Utilities",
            summary="A single mega AI cluster can consume electricity equal to 2.5 lakh homes.",
            keyPoints=["Power grid instability", "Tariff hikes"]
        )
    ]

    article = ArticleModel(
        id="art-001",
        title="Tech Giants Invest $100B in AI Data Centers: Big Boom or Power Grid Strain?",
        summary="A massive surge in mega data centers promises breakthroughs but strains grids.",
        category="Tech & AI",
        publishedAt=datetime.now(timezone.utc).isoformat(),
        divergenceScore=92,
        consensusScore=8,
        heroImageUrl="https://example.com/img.jpg",
        perspectives=perspectives,
        tags=["AI", "Tech", "Energy"]
    )

    data = article.to_firestore_dict()
    assert data["id"] == "art-001"
    assert data["divergenceScore"] == 92
    assert len(data["perspectives"]) == 2
    assert data["perspectives"][0]["type"] == "viewpoint1"
    assert data["perspectives"][1]["type"] == "viewpoint2"
    assert data["isSinglePerspective"] is False


def test_single_direct_report_schema():
    perspectives = [
        PerspectiveModel(
            id="p_002_direct",
            type="directReport",
            sourceName="ISRO Official",
            sourceDomain="isro.gov.in",
            biasTag="Official Launch",
            sourceCredibility=99,
            stanceTitle="Dual-Frequency Radar Enters Orbit to Map Global Environmental Changes",
            summary="NISAR observatory launched into orbit aboard GSLV rocket."
        )
    ]

    article = ArticleModel(
        id="art-002",
        title="ISRO and NASA Launch NISAR Satellite",
        category="Space & Science",
        publishedAt=datetime.now(timezone.utc).isoformat(),
        divergenceScore=0,
        consensusScore=100,
        heroImageUrl="https://example.com/satellite.jpg",
        perspectives=perspectives,
        isSinglePerspective=True
    )

    data = article.to_firestore_dict()
    assert data["divergenceScore"] == 0
    assert data["consensusScore"] == 100
    assert data["isSinglePerspective"] is True
    assert len(data["perspectives"]) == 1
    assert data["perspectives"][0]["type"] == "directReport"
