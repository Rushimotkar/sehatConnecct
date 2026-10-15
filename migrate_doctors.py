import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Static specialty icons mapping
SPECIALTY_ICONS = {
    "General Physician": "/static/icons/general.svg",
    "Cardiologist": "/static/icons/cardiology.svg",
    "Dermatologist": "/static/icons/derma.svg",
    "Pediatrician": "/static/icons/pediatrician.svg",
    "Orthopedic": "/static/icons/orthopedic.svg",
    "Orthopedist": "/static/icons/orthopedic.svg",
    "Gynecologist": "/static/icons/gynecologist.svg",
    "ENT Specialist": "/static/icons/ent.svg",
    "Psychiatrist": "/static/icons/psychiatrist.svg",
    "Dentist": "/static/icons/dentist.svg",
    "Ophthalmologist": "/static/icons/ophthalmologist.svg"
}

def migrate_doctors():
    """
    Migration script to add city, hospital_name, hospital_address, and specialty_icon
    fields to existing Doctor documents in MongoDB.
    """
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    client = MongoClient(mongo_uri)
    db = client["medico"]
    
    print("[MIGRATION] Scanning doctors collection for updates...")
    doctors = list(db.doctors.find())
    
    updated_count = 0
    for doc in doctors:
        updates = {}
        
        # 1. Populate city if missing (default to Mumbai)
        if "city" not in doc:
            updates["city"] = "Mumbai"
            
        # 2. Populate hospital_name if missing (copy from hospital, or set default)
        if "hospital_name" not in doc:
            if "hospital" in doc:
                updates["hospital_name"] = doc["hospital"]
            else:
                updates["hospital_name"] = "MediGuide Central Hospital"
                
        # 3. Populate hospital_address if missing (default to standard text)
        if "hospital_address" not in doc:
            updates["hospital_address"] = "123 Healthcare Lane, Main Road"
            
        # 4. Populate specialty_icon if missing (autofill based on specialty map)
        if "specialty_icon" not in doc:
            spec = doc.get("specialization", "General Physician")
            icon_path = SPECIALTY_ICONS.get(spec, "/static/icons/general.svg")
            updates["specialty_icon"] = icon_path
            
        # Apply updates if any missing columns were detected
        if updates:
            db.doctors.update_one({"_id": doc["_id"]}, {"$set": updates})
            updated_count += 1
            print(f"  [UPDATED] Dr. {doc.get('name')} -> {updates}")
            
    print(f"[MIGRATION] Doctor migration finished. {updated_count} documents updated.")

if __name__ == "__main__":
    migrate_doctors()
