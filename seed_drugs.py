"""
seed_drugs.py — Seeds ~50 common medicines into MongoDB `drugs` collection.
"""
import os
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

DRUG_DATA = [
    {"name": "Paracetamol", "generic_name": "Acetaminophen", "common_dosages": "250mg, 500mg, 650mg", "dosage_form": "tablet/syrup"},
    {"name": "Amoxicillin", "generic_name": "Amoxicillin Trihydrate", "common_dosages": "250mg, 500mg", "dosage_form": "capsule/syrup"},
    {"name": "Ibuprofen", "generic_name": "Ibuprofen", "common_dosages": "200mg, 400mg, 600mg", "dosage_form": "tablet"},
    {"name": "Cetirizine", "generic_name": "Cetirizine Hydrochloride", "common_dosages": "5mg, 10mg", "dosage_form": "tablet/syrup"},
    {"name": "Azithromycin", "generic_name": "Azithromycin", "common_dosages": "250mg, 500mg", "dosage_form": "tablet/suspension"},
    {"name": "Pantoprazole", "generic_name": "Pantoprazole Sodium", "common_dosages": "20mg, 40mg", "dosage_form": "tablet"},
    {"name": "Metformin", "generic_name": "Metformin Hydrochloride", "common_dosages": "500mg, 850mg, 1000mg", "dosage_form": "tablet"},
    {"name": "Amlodipine", "generic_name": "Amlodipine Besylate", "common_dosages": "2.5mg, 5mg, 10mg", "dosage_form": "tablet"},
    {"name": "Atorvastatin", "generic_name": "Atorvastatin Calcium", "common_dosages": "10mg, 20mg, 40mg", "dosage_form": "tablet"},
    {"name": "Omeprazole", "generic_name": "Omeprazole", "common_dosages": "10mg, 20mg, 40mg", "dosage_form": "capsule"},
    {"name": "Ciprofloxacin", "generic_name": "Ciprofloxacin Hydrochloride", "common_dosages": "250mg, 500mg, 750mg", "dosage_form": "tablet"},
    {"name": "Doxycycline", "generic_name": "Doxycycline Hyclate", "common_dosages": "50mg, 100mg", "dosage_form": "capsule"},
    {"name": "Metronidazole", "generic_name": "Metronidazole", "common_dosages": "200mg, 400mg", "dosage_form": "tablet"},
    {"name": "Losartan", "generic_name": "Losartan Potassium", "common_dosages": "25mg, 50mg, 100mg", "dosage_form": "tablet"},
    {"name": "Salbutamol", "generic_name": "Albuterol / Salbutamol", "common_dosages": "2mg, 4mg, 100mcg/puff", "dosage_form": "syrup/inhaler"},
    {"name": "Montelukast", "generic_name": "Montelukast Sodium", "common_dosages": "4mg, 5mg, 10mg", "dosage_form": "tablet"},
    {"name": "Telmisartan", "generic_name": "Telmisartan", "common_dosages": "20mg, 40mg, 80mg", "dosage_form": "tablet"},
    {"name": "Ranitidine", "generic_name": "Ranitidine Hydrochloride", "common_dosages": "150mg, 300mg", "dosage_form": "tablet"},
    {"name": "Levothyroxine", "generic_name": "Levothyroxine Sodium", "common_dosages": "25mcg, 50mcg, 100mcg", "dosage_form": "tablet"},
    {"name": "Gliclazide", "generic_name": "Gliclazide", "common_dosages": "30mg, 60mg, 80mg", "dosage_form": "tablet"},
    {"name": "Diclofenac", "generic_name": "Diclofenac Sodium", "common_dosages": "50mg, 75mg, 100mg", "dosage_form": "tablet/gel"},
    {"name": "Aceclofenac", "generic_name": "Aceclofenac", "common_dosages": "100mg", "dosage_form": "tablet"},
    {"name": "Tramadol", "generic_name": "Tramadol Hydrochloride", "common_dosages": "37.5mg, 50mg, 100mg", "dosage_form": "capsule/tablet"},
    {"name": "Clopidogrel", "generic_name": "Clopidogrel Bisulfate", "common_dosages": "75mg", "dosage_form": "tablet"},
    {"name": "Rosuvastatin", "generic_name": "Rosuvastatin Calcium", "common_dosages": "5mg, 10mg, 20mg", "dosage_form": "tablet"},
    {"name": "Furosemide", "generic_name": "Furosemide", "common_dosages": "20mg, 40mg", "dosage_form": "tablet"},
    {"name": "Spironolactone", "generic_name": "Spironolactone", "common_dosages": "25mg, 50mg, 100mg", "dosage_form": "tablet"},
    {"name": "Gabapentin", "generic_name": "Gabapentin", "common_dosages": "100mg, 300mg, 400mg", "dosage_form": "capsule"},
    {"name": "Pregabalin", "generic_name": "Pregabalin", "common_dosages": "75mg, 150mg, 300mg", "dosage_form": "capsule"},
    {"name": "Alprazolam", "generic_name": "Alprazolam", "common_dosages": "0.25mg, 0.5mg, 1mg", "dosage_form": "tablet"},
    {"name": "Clonazepam", "generic_name": "Clonazepam", "common_dosages": "0.25mg, 0.5mg, 2mg", "dosage_form": "tablet"},
    {"name": "Sertraline", "generic_name": "Sertraline Hydrochloride", "common_dosages": "25mg, 50mg, 100mg", "dosage_form": "tablet"},
    {"name": "Escitalopram", "generic_name": "Escitalopram Oxalate", "common_dosages": "5mg, 10mg, 20mg", "dosage_form": "tablet"},
    {"name": "Prednisolone", "generic_name": "Prednisolone", "common_dosages": "5mg, 10mg, 20mg", "dosage_form": "tablet/syrup"},
    {"name": "Dexamethasone", "generic_name": "Dexamethasone", "common_dosages": "0.5mg, 2mg, 4mg", "dosage_form": "tablet"},
    {"name": "Loperamide", "generic_name": "Loperamide Hydrochloride", "common_dosages": "2mg", "dosage_form": "capsule"},
    {"name": "ORS (Oral Rehydration Salts)", "generic_name": "Electrolyte Solution", "common_dosages": "1 sachet in 1L water", "dosage_form": "powder"},
    {"name": "ONDANSETRON", "generic_name": "Ondansetron Hydrochloride", "common_dosages": "4mg, 8mg", "dosage_form": "tablet/syrup"},
    {"name": "Domperidone", "generic_name": "Domperidone", "common_dosages": "10mg", "dosage_form": "tablet"},
    {"name": "Rabeprazole", "generic_name": "Rabeprazole Sodium", "common_dosages": "20mg", "dosage_form": "tablet"},
    {"name": "Esomeprazole", "generic_name": "Esomeprazole Magnesium", "common_dosages": "20mg, 40mg", "dosage_form": "capsule"},
    {"name": "Ofloxacin", "generic_name": "Ofloxacin", "common_dosages": "200mg, 400mg", "dosage_form": "tablet/eye drops"},
    {"name": "Levofloxacin", "generic_name": "Levofloxacin", "common_dosages": "250mg, 500mg, 750mg", "dosage_form": "tablet"},
    {"name": "Clarithromycin", "generic_name": "Clarithromycin", "common_dosages": "250mg, 500mg", "dosage_form": "tablet"},
    {"name": "Cefixime", "generic_name": "Cefixime", "common_dosages": "100mg, 200mg, 400mg", "dosage_form": "tablet/syrup"},
    {"name": "Cefuroxime", "generic_name": "Cefuroxime Axetil", "common_dosages": "250mg, 500mg", "dosage_form": "tablet"},
    {"name": "Chlorpheniramine", "generic_name": "Chlorpheniramine Maleate", "common_dosages": "2mg, 4mg", "dosage_form": "tablet/syrup"},
    {"name": "Folic Acid", "generic_name": "Vitamin B9", "common_dosages": "1mg, 5mg", "dosage_form": "tablet"},
    {"name": "Multivitamin", "generic_name": "Essential Vitamins & Minerals", "common_dosages": "1 capsule daily", "dosage_form": "capsule"},
    {"name": "Calcium & Vitamin D3", "generic_name": "Calcium Carbonate + Cholecalciferol", "common_dosages": "500mg + 250IU", "dosage_form": "tablet"}
]

def seed_drugs():
    mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
    if 'mongodb+srv://' in mongo_uri:
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
    else:
        client = MongoClient(mongo_uri)
        
    db = client['medico']
    
    # Upsert drugs by name
    inserted = 0
    updated = 0
    for drug in DRUG_DATA:
        res = db.drugs.update_one(
            {"name": drug["name"]},
            {"$set": drug},
            upsert=True
        )
        if res.upserted_id:
            inserted += 1
        else:
            updated += 1
            
    print(f"[OK] Drug Seeding Complete: {inserted} inserted, {updated} updated. Total in DB: {db.drugs.count_documents({})}")

if __name__ == "__main__":
    seed_drugs()
