import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync

firestore_sync.initialize()
db = firestore_sync.db
articles_col = db.collection("articles")

print("Fetching all articles from Firestore...")
all_docs = list(articles_col.stream())
print(f"Total articles fetched: {len(all_docs)}")

# Let's inspect articles by title similarity / keywords to find real duplicate reporting from different publishers
articles_data = []
for doc in all_docs:
    d = doc.to_dict()
    articles_data.append({
        "id": doc.id,
        "title": d.get("title", ""),
        "category": d.get("category", ""),
        "publishedAt": d.get("publishedAt", ""),
        "perspectives": d.get("perspectives", []),
        "isSingle": d.get("isSinglePerspective", True),
        "sourceName": d.get("perspectives", [{}])[0].get("sourceName", "") if d.get("perspectives") else "",
        "domain": d.get("perspectives", [{}])[0].get("sourceDomain", "") if d.get("perspectives") else ""
    })

# Check articles with >= 2 perspectives
multi_p = [a for a in articles_data if len(a["perspectives"]) >= 2]
print(f"\nArticles currently in DB with >= 2 perspectives: {len(multi_p)}")
for a in multi_p:
    print(f"\n[{a['id']}] (isSingle: {a['isSingle']}) {a['title']}")
    for i, p in enumerate(a['perspectives'], 1):
        print(f"  Source {i}: {p.get('sourceName')} ({p.get('sourceDomain')}) -> {p.get('stanceTitle')[:60]}")
