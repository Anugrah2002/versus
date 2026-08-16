"""
Data models for Versus Backend.
Maintains 1:1 schema compatibility with the Flutter mobile app's ArticleModel and PerspectiveModel.
Supports Pydantic v2 when available, with standard library fallback.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum


class PerspectiveType(str, Enum):
    VIEWPOINT_1 = "viewpoint1"       # Cyan - Angle 1
    VIEWPOINT_2 = "viewpoint2"       # Magenta - Angle 2 / Counter-perspective
    DIRECT_REPORT = "directReport"   # Emerald/Teal - Verified single event/announcement


class ClusterClassification(str, Enum):
    NEW_DEBATE = "NEW_DEBATE"         # 2+ sources from different domains
    SINGLE_REPORT = "SINGLE_REPORT"   # 1 source or all from same domain
    UPGRADE_STORY = "UPGRADE_STORY"   # Matches an existing single-perspective story in active window


try:
    from pydantic import BaseModel, Field

    class FeedDefinition(BaseModel):
        name: str
        url: str
        domain: str
        category: str
        credibility: int = 90
        defaultBias: str = "Industry Perspective"

    class RawCandidate(BaseModel):
        url: str
        canonical_url: str
        url_hash: str
        title: str
        feed_name: str
        domain: str
        category: str
        credibility: int
        default_bias: str
        published_at: Optional[datetime] = None
        raw_summary: str = ""
        image_url: Optional[str] = None
        discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class ExtractedArticle(BaseModel):
        url: str
        url_hash: str
        title: str
        cleaned_body: str
        word_count: int
        hero_image_url: Optional[str] = None
        feed_name: str
        domain: str
        category: str
        credibility: int
        default_bias: str
        published_at: datetime
        extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class PerspectiveModel(BaseModel):
        id: str
        type: str = "viewpoint1"
        sourceName: str
        sourceDomain: str
        biasTag: str
        sourceCredibility: int = Field(default=90, ge=0, le=100)
        stanceTitle: str
        summary: str
        keyPoints: List[str] = Field(default_factory=list)
        quote: str = ""
        quoteAuthor: str = ""
        fullMarkdownContent: str = ""

    class ArticleModel(BaseModel):
        id: str
        title: str
        summary: str = ""
        category: str
        publishedAt: str
        divergenceScore: int = Field(default=85, ge=0, le=100)
        consensusScore: int = Field(default=15, ge=0, le=100)
        heroImageUrl: str
        videoUrl: str = ""
        videoDuration: str = "02:45"
        perspectives: List[PerspectiveModel] = Field(default_factory=list)
        likesCount: int = 1420
        commentsCount: int = 48
        sharesCount: int = 210
        bookmarksCount: int = 340
        readTimeMinutes: int = 2
        isSinglePerspective: bool = False
        tags: List[str] = Field(default_factory=list)
        isLiked: bool = False
        isBookmarked: bool = False

        def to_firestore_dict(self) -> Dict[str, Any]:
            return self.model_dump()

    class StoryCluster(BaseModel):
        cluster_id: str
        classification: ClusterClassification
        category: str
        articles: List[ExtractedArticle]
        centroid_vector: Optional[List[float]] = None
        matched_existing_article_id: Optional[str] = None
        created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class ActiveStoryState(BaseModel):
        article_id: str
        title: str
        category: str
        divergence_score: int = Field(default=0)
        is_single_perspective: bool = Field(default=False)
        centroid_vector: List[float] = Field(default_factory=list)
        published_at: str = Field(default="")
        domains: List[str] = Field(default_factory=list)
        last_updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    class PipelineSummary(BaseModel):
        run_timestamp: str
        feeds_checked: int
        feeds_with_304: int
        candidate_urls_found: int
        scraped_articles_passed: int
        clusters_formed: int
        new_debates: int
        single_reports: int
        upgraded_stories: int
        firestore_writes_committed: int
        ai_calls_made: int
        ai_provider_used: str
        duration_seconds: float

except ImportError:
    from dataclasses import dataclass, field, asdict

    @dataclass
    class FeedDefinition:
        name: str
        url: str
        domain: str
        category: str
        credibility: int = 90
        defaultBias: str = "Industry Perspective"

    @dataclass
    class RawCandidate:
        url: str
        canonical_url: str
        url_hash: str
        title: str
        feed_name: str
        domain: str
        category: str
        credibility: int
        default_bias: str
        published_at: Optional[datetime] = None
        raw_summary: str = ""
        image_url: Optional[str] = None
        discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @dataclass
    class ExtractedArticle:
        url: str
        url_hash: str
        title: str
        cleaned_body: str
        word_count: int
        feed_name: str
        domain: str
        category: str
        credibility: int
        default_bias: str
        published_at: datetime
        hero_image_url: Optional[str] = None
        extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @dataclass
    class PerspectiveModel:
        id: str
        sourceName: str
        sourceDomain: str
        biasTag: str
        stanceTitle: str
        summary: str
        type: str = "viewpoint1"
        sourceCredibility: int = 90
        keyPoints: List[str] = field(default_factory=list)
        quote: str = ""
        quoteAuthor: str = ""
        fullMarkdownContent: str = ""

        def model_dump(self):
            return asdict(self)

    @dataclass
    class ArticleModel:
        id: str
        title: str
        category: str
        publishedAt: str
        heroImageUrl: str
        summary: str = ""
        divergenceScore: int = 85
        consensusScore: int = 15
        videoUrl: str = ""
        videoDuration: str = "02:45"
        perspectives: List[PerspectiveModel] = field(default_factory=list)
        likesCount: int = 1420
        commentsCount: int = 48
        sharesCount: int = 210
        bookmarksCount: int = 340
        readTimeMinutes: int = 2
        isSinglePerspective: bool = False
        tags: List[str] = field(default_factory=list)
        isLiked: bool = False
        isBookmarked: bool = False

        def model_dump(self):
            return asdict(self)

        def to_firestore_dict(self) -> Dict[str, Any]:
            return asdict(self)

    @dataclass
    class StoryCluster:
        cluster_id: str
        classification: ClusterClassification
        category: str
        articles: List[ExtractedArticle]
        centroid_vector: Optional[List[float]] = None
        matched_existing_article_id: Optional[str] = None
        created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @dataclass
    class ActiveStoryState:
        article_id: str
        title: str
        category: str
        divergence_score: int = 0
        is_single_perspective: bool = False
        centroid_vector: List[float] = field(default_factory=list)
        published_at: str = ""
        domains: List[str] = field(default_factory=list)
        last_updated_at: str = ""

        def model_dump(self):
            return asdict(self)

    @dataclass
    class PipelineSummary:
        run_timestamp: str
        feeds_checked: int
        feeds_with_304: int
        candidate_urls_found: int
        scraped_articles_passed: int
        clusters_formed: int
        new_debates: int
        single_reports: int
        upgraded_stories: int
        firestore_writes_committed: int
        ai_calls_made: int
        ai_provider_used: str
        duration_seconds: float
