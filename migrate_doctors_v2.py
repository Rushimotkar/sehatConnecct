import os
import random
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

def migrate_doctors_v2():
    """
    Migration script to add rating, consultation_fee, and total_reviews
    to existing doctor records in MongoDB.
    """
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    client = MongoClient(mongo_uri)
    db = client["medico"]
    
    print("[MIGRATION] Scanning doctors collection for V2 fields...")
    doctors = list(db.doctors.find())
    
    updated_count = 0
    for doc in doctors:
        updates = {}
        
        # 1. rating (float, default 0.0, but seeding with realistic 4.0-4.9 stars)
        if "rating" not in doc:
            updates["rating"] = round(random.uniform(4.2, 4.9), 1)
            
        # 2. consultation_fee (integer, in rupees)
        if "consultation_fee" not in doc:
            updates["consultation_fee"] = random.choice([300, 400, 450, 500, 600, 700, 800])
            
        # 3. total_reviews (integer, default 0, but seeding with realistic reviews count)
        if "total_reviews" not in doc:
            updates["total_reviews"] = random.randint(5, 30)
            
        if updates:
            db.doctors.update_one({"_id": doc["_id"]}, {"$set": updates})
            updated_count += 1
            print(f"  [UPDATED] Dr. {doc.get('name')} -> {updates}")
            
    print(f"[MIGRATION] Completed. Updated {updated_count} doctors with V2 fields.")

if __name__ == "__main__":
    migrate_doctors_v2()
