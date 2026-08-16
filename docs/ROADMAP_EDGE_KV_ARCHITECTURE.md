# 📌 Roadmap: Storing All News Articles in Cloudflare Edge KV

> **Status**: Planned (Deferred for future implementation)  
> **Objective**: Store 100% of synthesized news stories directly in Cloudflare KV edge storage for ultra-fast 15ms global delivery, zero Firebase read load, and 100% free operation up to 25,000+ daily active users.

---

## 🎯 Why This Architecture?

1. **Global 15ms Read Latency**: All articles are replicated across 300+ global Cloudflare data centers, close to every user.
2. **Zero Firebase Read Billing**: 100% of news feed reads are served by Cloudflare Edge ($0.00), leaving Firebase exclusively for user comments, likes, and bookmarks.
3. **Huge Free Headroom**:
   * Cloudflare KV provides **1 GB Storage** (enough for ~500,000 articles) and **100,000 reads/day for $0.00**.
   * Our 1,500 active articles take only **~3 MB** (< 0.3% of the limit).

---

## 🏗️ Target Architecture

```
                       ┌──────────────────────────────────────────────┐
                       │           GitHub Actions Cron                │
                       │     (Runs every 30 mins to ingest RSS)       │
                       └──────────────┬───────────────────────────────┘
                                      │
                 ┌────────────────────┴────────────────────┐
                 │                                         │
                 ▼                                         ▼
   ┌───────────────────────────┐             ┌───────────────────────────┐
   │    Cloudflare KV Store    │             │    Firebase Firestore     │
   │   (Public News Library)   │             │   (User Data & Archival)  │
   │  • Key: 'feed_latest_40'  │             │  • Comments / Likes       │
   │  • Key: 'article_{id}'    │             │  • Bookmarks & Profiles   │
   │  • Key: 'feed_category_*' │             │  • 30-Day TTL Archival    │
   └─────────────┬─────────────┘             └───────────────────────────┘
                 │
                 ▼
   ┌───────────────────────────┐
   │  Cloudflare Edge Worker   │  <=== Serves Flutter App in <25ms ($0.00)
   └───────────────────────────┘
```

---

## 📋 Step-by-Step Implementation Guide (When Ready)

### Step 1: Create the Cloudflare KV Namespace
Run the following in the `worker/` directory:
```bash
npx wrangler kv:namespace create "VERSUS_ARTICLES_KV"
```
Add the returned ID to `worker/wrangler.toml`:
```toml
[[kv_namespaces]]
binding = "VERSUS_ARTICLES_KV"
id = "<YOUR_KV_NAMESPACE_ID>"
```

---

### Step 2: Push Articles to KV during Pipeline Run
In `src/storage/firestore_sync.py`, add a direct push to Cloudflare KV REST API after synthesizing articles:
```python
def sync_to_cloudflare_kv(articles_list):
    url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{settings.CLOUDFLARE_KV_ID}/values/feed_latest_40"
    headers = {
        "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    requests.put(url, headers=headers, json=articles_list)
```

---

### Step 3: Serve Directly from KV in `worker/worker.js`
Update `worker/worker.js`:
```javascript
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/feed') {
      // 1. Fetch directly from Edge KV (instant 15ms response)
      const cachedFeed = await env.VERSUS_ARTICLES_KV.get('feed_latest_40', { type: 'json' });
      if (cachedFeed) {
        return new Response(JSON.stringify(cachedFeed), {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=180'
          }
        });
      }
    }

    return new Response('Not Found', { status: 404 });
  }
};
```

---

### Step 4: Update Flutter Client
In `versus_app/lib/services/news_repository.dart`:
```dart
static const String _feedUrl = 'https://versus-edge-api.yourdomain.workers.dev/api/feed';
```

---

## 🔔 Reminder Note
Whenever you are ready to switch the app to Edge KV, simply say:  
👉 **"Let's implement the Edge KV architecture from the roadmap file."**
