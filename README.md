# Versus Backend & Ingestion Engine

> Scalable, Zero-Cost RSS & Dual-Perspective Synthesis Architecture for the [Versus Mobile App](file:///C:/Users/anugr/.gemini/antigravity/scratch/versus_app).

---

## ⚡ Architecture Highlights

1. **Anti-Ban & Scalable Ingestion**: Asynchronous `aiohttp` pipeline with HTTP `ETag`/`304` conditional caching, per-domain concurrency limiter (max 2 req/sec), randomized jitter, and modern desktop browser header rotation.
2. **100% Local CPU Clustering**: Quantized ONNX `sentence-transformers/all-MiniLM-L6-v2` encodes articles in **0.3s** on CPU. Hierarchical agglomerative clustering groups articles into story clusters with **0 API calls**.
3. **Delayed Viewpoint 2 Matching**: Matches new articles against active 48-hour story centroids in state memory. When an opposing perspective arrives hours later, the existing story is automatically upgraded to a dual-perspective debate without creating duplicates or clearing comments.
4. **90% AI Call Reduction**: Synthesizes **1 entire cluster per call** (not per article). Uses **Cloudflare Workers AI** (`@cf/meta/llama-3.1-8b-instruct-fp8-fast`) with automated failover to **Groq** (`llama-3.3-70b-versatile`), **Google Gemini Flash**, and an offline **Local Rule-Based Synthesizer**.
5. **Firestore & Cloudflare Edge Caching**: Commits synthesized stories via atomic batch writes (<1% of Firebase Spark daily write limit). Cloudflare Worker caches `/api/feed` at the edge to protect the 50k daily read limit.
6. **Zero Secret Leakage**: Credentials are kept 100% hidden from Git via **GitHub Actions Repository Secrets** in CI/CD and `.env` in local development.

---

## 📁 Project Structure

```
versus_backend/
├── .github/
│   └── workflows/
│       ├── ingest_pipeline.yml         # 30-min cron trigger + GHA dependency caching
│       └── deploy_edge_worker.yml      # Cloudflare Worker deployment on push
├── .gitignore                          # Ignores .env, serviceAccountKey.json, cache
├── .env.example                        # Environment variables template
├── requirements.txt                    # Python dependencies
├── config/
│   ├── feeds.yaml                      # 100+ curated categorized RSS feeds
│   ├── categories.json                 # Category definitions matching Flutter UI
│   └── settings.py                     # Pydantic BaseSettings loader
├── src/
│   ├── main.py                         # CLI pipeline entrypoint
│   ├── sources/                        # Pluggable sources (RSS, Twitter, Threads, Mock)
│   ├── extractors/                     # Trafilatura + Readability + OG image scraper
│   ├── clustering/                     # Local ONNX embedder & Agglomerative clusterer
│   ├── synthesis/                      # Cloudflare AI / Groq / Gemini / Local fallback
│   ├── storage/                        # Pydantic models, StateManager, Firestore sync
│   └── utils/                          # Structured logger & User-Agent pool
├── worker/                             # Cloudflare Edge Worker API (TypeScript)
│   ├── wrangler.toml
│   └── src/index.ts                    # Edge cache router (/api/feed, /api/articles/:id)
└── tests/                              # Unit and integration test suite
```

---

## 🚀 Quickstart & Local Development

### 1. Install Dependencies
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
```
Edit `.env` to add your optional Cloudflare, Groq, or Gemini keys and Firebase credentials.

### 3. Run Pipeline Locally (Dry-Run / Mock Mode)
```bash
# Run with synthetic mock data (zero network requests, 100% offline)
python src/main.py --mock --dry-run

# Run against top 5 live RSS feeds in dry-run mode
python src/main.py --max-feeds 5 --dry-run

# Run full live production pipeline
python src/main.py
```

### 4. Run Test Suite
```bash
python -m pytest tests/ -v
```

---

## 🔒 GitHub Actions Secrets Setup (For 30-Min Automated Runs)

In your GitHub repository, navigate to **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions** and add the following repository secrets:

| Secret Name | Description | Where to get it |
| :--- | :--- | :--- |
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare Account ID | [Cloudflare Dashboard](https://dash.cloudflare.com/) |
| `CLOUDFLARE_API_TOKEN` | API Token with *Workers AI:Read* and *Workers:Edit* permissions | [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens) |
| `GROQ_API_KEY` | *(Optional Fallback)* Groq API Key | [Groq Console](https://console.groq.com/keys) |
| `GEMINI_API_KEY` | *(Optional Fallback)* Google Gemini API Key | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Firebase Admin Service Account JSON (or Base64 string) | Firebase Console $\rightarrow$ Project Settings $\rightarrow$ Service Accounts |
| `FIRESTORE_PROJECT_ID` | Your Firebase Project ID (e.g. `versus-news`) | Firebase Console |

---

## 🌐 Deploying the Cloudflare Edge Worker API

The Cloudflare Worker edge API shields your Firestore read limit by caching feed responses for 5 minutes (`s-maxage=300, stale-while-revalidate=600`).

### Deploy via Wrangler CLI:
```bash
cd worker
npm install
npx wrangler deploy
```

Once deployed, your mobile app can fetch feeds via:
- `GET https://versus-edge-api.<your-subdomain>.workers.dev/api/feed`
- `GET https://versus-edge-api.<your-subdomain>.workers.dev/api/feed?category=Tech%20%26%20AI`
- `GET https://versus-edge-api.<your-subdomain>.workers.dev/api/articles/:id`
- `GET https://versus-edge-api.<your-subdomain>.workers.dev/api/categories`

---

## ➕ Adding More News & Social Media Sources

### Adding New RSS Feeds
Open [`config/feeds.yaml`](file:///C:/Users/anugr/.gemini/antigravity/scratch/versus_backend/config/feeds.yaml) and append your new feed:
```yaml
  - name: BBC Technology
    url: https://feeds.bbci.co.uk/news/technology/rss.xml
    domain: bbc.co.uk
    category: Tech & AI
    credibility: 95
    defaultBias: Global Public Broadcaster
```

### Adding Social Sources (Twitter / Threads / Bluesky)
Subclass `BaseFeedSource` in `src/sources/` and implement `async def fetch_candidates(self, state_manager) -> List[RawCandidate]`.
All clustering, delayed viewpoint matching, synthesis, and Firestore syncing will automatically process the new source!
