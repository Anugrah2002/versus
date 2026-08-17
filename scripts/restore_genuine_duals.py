import os
import sys

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync

firestore_sync.initialize()
db = firestore_sync.db
articles_col = db.collection("articles")

# Target articles with >= 2 perspectives that are genuine debates
print("Auditing and restoring genuine Dual Views in Firestore...")

all_docs = list(articles_col.stream())
restored = 0
kept_brief = 0

batch = db.batch()
has_writes = False

for doc in all_docs:
    d = doc.to_dict()
    perspectives = d.get("perspectives", [])
    if len(perspectives) < 2:
        continue
        
    doc_id = doc.id
    title = d.get("title", "")
    p1_t = perspectives[0].get("stanceTitle", "")
    p2_t = perspectives[1].get("stanceTitle", "")
    p1_s = perspectives[0].get("summary", "")
    p2_s = perspectives[1].get("summary", "")
    
    # Check if genuinely unrelated (e.g. Everest vs DeepSeek)
    is_everest_deepseek = "everest" in (title + p1_t).lower() and "deepseek" in (p2_t + p2_s).lower()
    is_solar_indie_games = "sun" in (title + p1_t).lower() and "indie games" in (p2_t + p2_s).lower()
    is_school_mercedes = "high school class" in (title + p1_t).lower() and "mercedes" in (p2_t + p2_s).lower()
    is_ai_pull_requests = "visual and physical ai" in (title + p1_t).lower() and "pull requests" in (p2_t + p2_s).lower()
    
    if is_everest_deepseek or is_solar_indie_games or is_school_mercedes or is_ai_pull_requests:
        print(f"❌ Keeping as Brief (Mismatched topics): [{doc_id}] {title}")
        print(f"   P1: {p1_t}")
        print(f"   P2: {p2_t}")
        kept_brief += 1
    else:
        print(f"✅ RESTORING TO DUAL VIEW: [{doc_id}] {title}")
        print(f"   P1: {p1_t}")
        print(f"   P2: {p2_t}")
        batch.update(doc.reference, {
            "isSinglePerspective": False,
            "divergenceScore": 85,
            "consensusScore": 15
        })
        has_writes = True
        restored += 1

if has_writes:
    batch.commit()
    print(f"\n🎉 Successfully committed updates! Restored {restored} Dual Views. Kept {kept_brief} mismatched as Briefs.")
else:
    print(f"\nNo updates needed.")
