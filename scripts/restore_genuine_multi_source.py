import os
import sys

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("src"))

from src.storage.firestore_sync import firestore_sync

firestore_sync.initialize()
db = firestore_sync.db
articles_col = db.collection("articles")

print("Checking articles in Firestore...")
all_docs = list(articles_col.stream())

batch = db.batch()
has_writes = False
updated_count = 0
invalid_count = 0

for doc in all_docs:
    d = doc.to_dict()
    perspectives = d.get("perspectives", [])
    if len(perspectives) < 2:
        continue
        
    doc_id = doc.id
    title = d.get("title", "")
    p1 = perspectives[0]
    p2 = perspectives[1]
    p1_t = p1.get("stanceTitle", "")
    p2_t = p2.get("stanceTitle", "")
    p1_s = p1.get("summary", "")
    p2_s = p2.get("summary", "")
    
    # Check for obvious cross-universe hallucinations
    is_everest_deepseek = "everest" in (title + p1_t).lower() and "deepseek" in (p2_t + p2_s).lower()
    is_solar_indie = "sun" in (title + p1_t).lower() and "indie games" in (p2_t + p2_s).lower()
    is_ai_pull_requests = "visual and physical ai" in (title + p1_t).lower() and "pull requests" in (p2_t + p2_s).lower()
    is_student_drug_racket = "student" in (title + p1_t).lower() and "drug racket" in (p2_t + p2_s).lower()
    is_congress_tribal = "merger" in (title + p1_t).lower() and "ken-betwa" in (p2_t + p2_s).lower()
    is_ev_soyoil = "electric car" in (title + p1_t).lower() and "soyoil" in (p2_t + p2_s).lower()
    
    is_invalid = is_everest_deepseek or is_solar_indie or is_ai_pull_requests or is_student_drug_racket or is_congress_tribal or is_ev_soyoil
    
    if is_invalid:
        print(f"❌ Keeping as Brief (Mismatched): [{doc_id}] {title}")
        print(f"   P1: {p1_t}")
        print(f"   P2: {p2_t}")
        if not d.get("isSinglePerspective", True):
            batch.update(doc.reference, {
                "isSinglePerspective": True,
                "divergenceScore": 0,
                "consensusScore": 100
            })
            has_writes = True
            invalid_count += 1
    else:
        print(f"✅ ACTIVATING GENUINE DUAL VIEW: [{doc_id}] {title}")
        print(f"   P1 [{p1.get('sourceName')}]: {p1_t}")
        print(f"   P2 [{p2.get('sourceName')}]: {p2_t}")
        batch.update(doc.reference, {
            "isSinglePerspective": False,
            "divergenceScore": 85,
            "consensusScore": 15
        })
        has_writes = True
        updated_count += 1

if has_writes:
    batch.commit()
    print(f"\n🎉 Successfully committed updates! Activated {updated_count} genuine Dual Views. Fixed {invalid_count} mismatched articles.")
else:
    print("\nNo updates needed.")
