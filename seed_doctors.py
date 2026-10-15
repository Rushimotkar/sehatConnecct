# -*- coding: utf-8 -*-
"""
seed_doctors.py  -- Run once to populate MongoDB with doctor accounts & consultation data.
Usage:  python seed_doctors.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random, os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017/"))
db = client["medico"]

# ── Clean previous seed data ──────────────────────────────────
for col in ["doctors", "consultations", "referrals", "ipd_requests"]:
    db[col].drop()

print("[SEED] Seeding doctors...")

# Static mapping for specialty icons as requested in step 5
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

RAW_DOCTORS = [
    {
        "name": "Dr. Aisha Khan",
        "email": "dr.aisha@medico.com",
        "password": "Doctor@123",
        "specialization": "Cardiologist",
        "license_id": "MCI-CAR-00101",
        "department": "Cardiology",
        "phone": "+91-9000000001",
        "experience_years": 12,
        "hospital_name": "Apollo Hospital",
        "hospital_address": "Film City Road, Goregaon, Mumbai",
        "city": "Mumbai",
        "avatar_initials": "AK",
        "avatar_color": "#0ABFA3",
        "rating": 4.8,
        "consultation_fee": 700,
        "total_reviews": 25,
    },
    {
        "name": "Dr. Rajan Mehta",
        "email": "dr.rajan@medico.com",
        "password": "Doctor@456",
        "specialization": "General Physician",
        "license_id": "MCI-GP-00202",
        "department": "General Medicine",
        "phone": "+91-9000000002",
        "experience_years": 8,
        "hospital_name": "Ruby Hall Clinic",
        "hospital_address": "40 Sassoon Road, Pune",
        "city": "Pune",
        "avatar_initials": "RM",
        "avatar_color": "#6C5CE7",
        "rating": 4.5,
        "consultation_fee": 400,
        "total_reviews": 12,
    },
    {
        "name": "Dr. Sneha Patil",
        "email": "dr.sneha@medico.com",
        "password": "Doctor@789",
        "specialization": "Dermatologist",
        "license_id": "MCI-DER-00303",
        "department": "Dermatology",
        "phone": "+91-9000000003",
        "experience_years": 10,
        "hospital_name": "Kokilaben Hospital",
        "hospital_address": "Rao Saheb Achutrao Patwardhan Marg, Mumbai",
        "city": "Mumbai",
        "avatar_initials": "SP",
        "avatar_color": "#FF7675",
        "rating": 4.7,
        "consultation_fee": 500,
        "total_reviews": 18,
    },
    {
        "name": "Dr. Vikram Malhotra",
        "email": "dr.vikram@medico.com",
        "password": "Doctor@101",
        "specialization": "Pediatrician",
        "license_id": "MCI-PED-00404",
        "department": "Pediatrics",
        "phone": "+91-9000000004",
        "experience_years": 15,
        "hospital_name": "Manipal Hospital",
        "hospital_address": "98 Hal Airport Road, Bangalore",
        "city": "Bangalore",
        "avatar_initials": "VM",
        "avatar_color": "#26DE81",
        "rating": 4.9,
        "consultation_fee": 600,
        "total_reviews": 30,
    },
    {
        "name": "Dr. Amit Deshmukh",
        "email": "dr.amit@medico.com",
        "password": "Doctor@202",
        "specialization": "Orthopedic",
        "license_id": "MCI-ORT-00505",
        "department": "Orthopedics",
        "phone": "+91-9000000005",
        "experience_years": 11,
        "hospital_name": "Sancheti Hospital",
        "hospital_address": "16 Shivajinagar, Pune",
        "city": "Pune",
        "avatar_initials": "AD",
        "avatar_color": "#FD9644",
        "rating": 4.4,
        "consultation_fee": 450,
        "total_reviews": 8,
    },
    {
        "name": "Dr. Kavita Rao",
        "email": "dr.kavita@medico.com",
        "password": "Doctor@303",
        "specialization": "Gynecologist",
        "license_id": "MCI-GYN-00606",
        "department": "Gynecology",
        "phone": "+91-9000000006",
        "experience_years": 14,
        "hospital_name": "Hinduja Hospital",
        "hospital_address": "Veer Savarkar Marg, Mahim, Mumbai",
        "city": "Mumbai",
        "avatar_initials": "KR",
        "avatar_color": "#D980FA",
        "rating": 4.6,
        "consultation_fee": 550,
        "total_reviews": 14,
    },
    {
        "name": "Dr. Nihal Joshi",
        "email": "dr.nihal@medico.com",
        "password": "Doctor@404",
        "specialization": "ENT Specialist",
        "license_id": "MCI-ENT-00707",
        "department": "ENT",
        "phone": "+91-9000000007",
        "experience_years": 9,
        "hospital_name": "Max Healthcare",
        "hospital_address": "1 Press Enclave Road, Saket, Delhi",
        "city": "Delhi",
        "avatar_initials": "NJ",
        "avatar_color": "#2BCBBA",
        "rating": 4.3,
        "consultation_fee": 350,
        "total_reviews": 22,
    },
    {
        "name": "Dr. Shalini Sen",
        "email": "dr.shalini@medico.com",
        "password": "Doctor@505",
        "specialization": "Psychiatrist",
        "license_id": "MCI-PSY-00808",
        "department": "Psychiatry",
        "phone": "+91-9000000008",
        "experience_years": 13,
        "hospital_name": "NIMHANS Hospital",
        "hospital_address": "Hosur Road, Bangalore",
        "city": "Bangalore",
        "avatar_initials": "SS",
        "avatar_color": "#A55EEA",
        "rating": 4.8,
        "consultation_fee": 650,
        "total_reviews": 19,
    },
    {
        "name": "Dr. Rajesh Gokhale",
        "email": "dr.rajesh@medico.com",
        "password": "Doctor@606",
        "specialization": "Dentist",
        "license_id": "MCI-DEN-00909",
        "department": "Dental",
        "phone": "+91-9000000009",
        "experience_years": 7,
        "hospital_name": "Deenanath Mangeshkar Hospital",
        "hospital_address": "Erandwane, Pune",
        "city": "Pune",
        "avatar_initials": "RG",
        "avatar_color": "#FC5C65",
        "rating": 4.2,
        "consultation_fee": 300,
        "total_reviews": 10,
    },
    {
        "name": "Dr. Anita Verma",
        "email": "dr.anita@medico.com",
        "password": "Doctor@707",
        "specialization": "Ophthalmologist",
        "license_id": "MCI-OPH-01010",
        "department": "Ophthalmology",
        "phone": "+91-9000000010",
        "experience_years": 16,
        "hospital_name": "Fortis Hospital",
        "hospital_address": "Okhla Road, Delhi",
        "city": "Delhi",
        "avatar_initials": "AV",
        "avatar_color": "#20BF6B",
        "rating": 4.7,
        "consultation_fee": 800,
        "total_reviews": 27,
    }
]

DOCTORS = []
for rd in RAW_DOCTORS:
    # Auto-fill specialty_icon based on specialization as requested in step 5
    spec = rd["specialization"]
    icon_path = SPECIALTY_ICONS.get(spec, "/static/icons/general.svg")
    
    doc_doc = {
        "name": rd["name"],
        "email": rd["email"],
        "password": generate_password_hash(rd["password"], method="pbkdf2:sha256"),
        "specialization": rd["specialization"],
        "license_id": rd["license_id"],
        "department": rd["department"],
        "phone": rd["phone"],
        "experience_years": rd["experience_years"],
        "hospital_name": rd["hospital_name"],
        "hospital": rd["hospital_name"], # Backward compatibility
        "hospital_address": rd["hospital_address"],
        "city": rd["city"],
        "specialty_icon": icon_path,
        "rating": rd.get("rating", 0.0),
        "consultation_fee": rd.get("consultation_fee", 0),
        "total_reviews": rd.get("total_reviews", 0),
        "avatar_initials": rd["avatar_initials"],
        "avatar_color": rd["avatar_color"],
        "is_active": True,
        "created_at": datetime.utcnow()
    }
    DOCTORS.append(doc_doc)

result = db.doctors.insert_many(DOCTORS)
doctor_ids = [str(d) for d in result.inserted_ids]

print(f"  [OK] Inserted {len(doctor_ids)} doctors with new columns city, hospital_name, hospital_address, specialty_icon")

# ── Helper data ───────────────────────────────────────────────
NAMES = ["Priya Sharma","Arjun Patel","Sunita Devi","Mohammed Ali","Kavya Reddy",
         "Rohan Singh","Meena Iyer","Vikram Nair","Deepa Gupta","Sanjay Joshi"]
GENDERS = ["Female","Male","Female","Male","Female","Male","Female","Male","Female","Male"]
BLOOD_GRP = ["A+","O+","B+","AB+","A-","O-","B+","A+","O+","B-"]
COMPLAINTS = ["Chest pain and shortness of breath","Persistent headache","High fever for 3 days",
               "Knee pain","Diabetes follow-up","Hypertension check","Cough and cold",
               "Back pain","Eye irritation","Stomach cramps"]
STATUSES_QUEUE = ["Waiting","In Progress","Completed","No-Show","Waiting","Completed",
                  "Waiting","In Progress","Completed","Waiting"]
PRIORITIES = ["Urgent","Normal","Follow-up","Urgent","Normal","Normal","Follow-up","Urgent","Normal","Normal"]
DIAGNOSES = ["Hypertensive Crisis","Migraine","Viral fever","Osteoarthritis","Type 2 Diabetes",
              "Essential Hypertension","URTI","Lumbar Spondylosis","Conjunctivitis","IBS"]

now = datetime.utcnow()

# ── Build consultations for each doctor ───────────────────────
all_consultations = []
for i, did in enumerate(doctor_ids):
    # Only seed 3 consultations per doctor to avoid overloading local MongoDB with 100+ documents
    for j in range(3):
        pname = NAMES[j]
        age = random.randint(22, 72)
        apt_time = (now.replace(hour=9, minute=0, second=0) + timedelta(minutes=j*20)).strftime("%I:%M %p")
        status_today = STATUSES_QUEUE[j]

        all_consultations.append({
            "doctor_id": did,
            "patient_name": pname,
            "patient_age": age,
            "patient_gender": GENDERS[j],
            "patient_dob": (now - timedelta(days=age*365)).strftime("%Y-%m-%d"),
            "patient_blood_group": BLOOD_GRP[j],
            "patient_contact": f"+91-98{random.randint(10000000,99999999)}",
            "slot_number": j + 1,
            "appointment_time": apt_time,
            "chief_complaint": COMPLAINTS[j],
            "symptoms": ["fever","fatigue","nausea"][:random.randint(1,3)],
            "status": status_today,
            "priority": PRIORITIES[j],
            "queue_type": "today",
            "vitals": {
                "bp": f"{random.randint(100,160)}/{random.randint(60,100)} mmHg",
                "temp": f"{round(random.uniform(97.0, 103.0),1)} °F",
                "pulse": f"{random.randint(60,110)} bpm",
                "spo2": f"{random.randint(94,100)}%",
                "weight": f"{random.randint(45,100)} kg",
            },
            "medical_history": ["Diabetes","Hypertension"][:random.randint(0,2)],
            "current_medications": ["Metformin 500mg","Amlodipine 5mg"][:random.randint(0,2)],
            "allergies": random.choice(["None","Penicillin","Aspirin","Sulfa drugs"]),
            "doctor_notes": "",
            "investigation_requests": [],
            "prescription": [],
            "follow_up_date": None,
            "consultation_date": now.strftime("%Y-%m-%d"),
            "diagnosis": DIAGNOSES[j] if status_today == "Completed" else "",
            "prescription_issued": status_today == "Completed",
            "follow_up_scheduled": random.choice([True, False]) if status_today == "Completed" else False,
            "patient_rating": random.randint(3,5) if status_today == "Completed" else None,
            "created_at": now,
        })

db.consultations.insert_many(all_consultations)
print(f"  [OK] Inserted {len(all_consultations)} consultation records")

# ── Referrals ─────────────────────────────────────────────────
referrals = []
for i, did in enumerate(doctor_ids):
    referrals.append({
        "to_doctor_id": did,
        "from_doctor": "Dr. S. Verma (Ortho)",
        "from_department": "Orthopedics",
        "patient_name": NAMES[0],
        "patient_age": 45,
        "referral_reason": "Pre-op cardiac clearance",
        "urgency": "Urgent",
        "referral_date": now.strftime("%Y-%m-%d"),
        "status": "Pending",
        "created_at": now,
    })

db.referrals.insert_many(referrals)
print(f"  [OK] Inserted {len(referrals)} referrals")

# ── IPD Requests ──────────────────────────────────────────────
ipd_requests = []
for i, did in enumerate(doctor_ids):
    ipd_requests.append({
        "to_doctor_id": did,
        "patient_name": NAMES[1],
        "patient_age": 52,
        "ward": "ICU",
        "bed_number": "Bed-12",
        "requesting_doctor": "Dr. J. Singh",
        "condition_summary": "Post-op cardiac monitoring",
        "request_datetime": now.strftime("%Y-%m-%d %H:%M"),
        "response_status": "Pending",
        "created_at": now,
    })

db.ipd_requests.insert_many(ipd_requests)
print(f"  [OK] Inserted {len(ipd_requests)} IPD requests")

print("\n[DONE] Seeding complete!")
print("\n[CREDENTIALS] Doctor Logins:")
for rd in RAW_DOCTORS[:3]:
    print(f"  Email: {rd['email']}   | Password: {rd['password']}  ({rd['specialization']})")
