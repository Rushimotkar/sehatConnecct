
import os

# Only allow insecure transport in development, not in production
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '0')

import sys
import re
import certifi
import requests
from datetime import datetime
from doctor_service import search_doctors, search_pharmacies
from map_builder import build_doctor_map
from doctor_routes import doctor_bp, init_doctor_bp
import pandas as pd
import random
from flask import (
    Flask,
    request,
    render_template,
    jsonify,
    redirect,
    url_for,
    flash,
    send_from_directory,
    send_file,
    session
)
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from prescription_pdf import create_prescription_pdf

load_dotenv()

from src.logger import logging
from src.exception import CustomException
from src.pipeline.prediction_pipeline import (
    PredictPipeline,
    CustomData
)

# Static mapping for specialty icons (Requirement 5)
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

# ── Flask App ──────────────────────────────────
app = Flask(__name__)
app.secret_key = 'super_secret_medico_key'
# Database Configuration (MongoDB)
app.config['UPLOAD_FOLDER'] = os.path.join('artifacts', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Add hasattr to Jinja2 globals
app.jinja_env.globals.update(hasattr=hasattr, getattr=getattr)

mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')

# MongoDB connection with robust SSL/TLS error handling
def create_mongo_connection():
    """Create MongoDB connection with retry logic for SSL handshake issues."""
    import time
    import ssl
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            if 'mongodb+srv://' in mongo_uri:
                # MongoDB Atlas - add SSL parameters to URI if not present
                uri = mongo_uri
                if 'retryWrites' not in uri:
                    uri = uri + ('&' if '?' in uri else '?') + 'retryWrites=true'
                
                # MongoDB Atlas connection with comprehensive SSL configuration
                conn = MongoClient(
                    uri,
                    tlsCAFile=certifi.where(),
                    tlsAllowInvalidCertificates=False,
                    tlsAllowInvalidHostnames=False,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=20000,
                    socketTimeoutMS=None,
                    maxPoolSize=50,
                    minPoolSize=10,
                    retryWrites=True,
                    w='majority'
                )
            else:
                # Local MongoDB connection
                conn = MongoClient(
                    mongo_uri,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=20000
                )
            
            # Test connection with ping
            conn.admin.command('ping')
            logging.info("✓ MongoDB connection successful")
            return conn
            
        except Exception as e:
            retry_count += 1
            error_msg = str(e)
            
            logging.warning(f"MongoDB connection attempt {retry_count}/{max_retries} failed: {e}")
            if retry_count < max_retries:
                wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                logging.info(f"Retrying MongoDB connection in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                logging.error(f"✗ MongoDB connection failed after {max_retries} attempts: {error_msg}")
                raise CustomException(
                    f"MongoDB connection error after {max_retries} attempts: {error_msg}\n"
                    f"Check your internet connection and verify that your IP is whitelisted (0.0.0.0/0) in MongoDB Atlas Network Access.",
                    sys
                )
    
    return None

try:
    client = create_mongo_connection()
except Exception as e:
    logging.error(f"Failed to establish MongoDB connection: {e}")
    raise

db = client['medico']

# ── Appointment Slot Helpers ─────────────────────────────────
def parse_time_to_minutes(time_value):
    if time_value is None:
        return None

    text = str(time_value).strip().upper()
    if not text:
        return None

    match = re.match(r'^(?P<h>\d{1,2}):(?P<m>\d{2})(?:\s*(?P<ampm>AM|PM))?$', text)
    if not match:
        return None

    hour = int(match.group('h'))
    minute = int(match.group('m'))
    ampm = match.group('ampm')

    if ampm == 'PM' and hour != 12:
        hour += 12
    if ampm == 'AM' and hour == 12:
        hour = 0

    return hour * 60 + minute


def format_time_from_minutes(total_minutes):
    total_minutes = int(total_minutes) % (24 * 60)
    hour = total_minutes // 60
    minute = total_minutes % 60
    suffix = 'AM' if hour < 12 else 'PM'
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour}:{minute:02d} {suffix}"


def time_overlaps(start1, end1, start2, end2):
    return start1 < end2 and end1 > start2


def add_minutes_to_time(time_value, minutes):
    start_minutes = parse_time_to_minutes(time_value)
    if start_minutes is None:
        return time_value
    return format_time_from_minutes(start_minutes + int(minutes))


def has_slot_conflict(doctor_id, date_str, start_time, duration_minutes=60, db_conn=None):
    if db_conn is None:
        db_conn = db

    start_minutes = parse_time_to_minutes(start_time)
    if start_minutes is None:
        return False

    end_minutes = start_minutes + int(duration_minutes)

    for appointment in db_conn.consultations.find({
        'doctor_id': doctor_id,
        'consultation_date': date_str,
        'status': {'$nin': ['Cancelled', 'Rejected', 'Completed']}
    }):
        existing_start = appointment.get('start_time') or appointment.get('appointment_time')
        if not existing_start:
            continue

        existing_start_minutes = parse_time_to_minutes(existing_start)
        if existing_start_minutes is None:
            continue

        existing_duration = appointment.get('duration_minutes') or 60
        existing_end_minutes = existing_start_minutes + int(existing_duration)

        if time_overlaps(start_minutes, end_minutes, existing_start_minutes, existing_end_minutes):
            return True

    return False

# Auto-seed drugs if empty
if db.drugs.count_documents({}) == 0:
    try:
        from seed_drugs import seed_drugs
        seed_drugs()
    except Exception as e:
        logging.error(f"Error auto-seeding drugs: {e}")

# ── Doctor Blueprint ──────────────────────────────────────────
app.register_blueprint(doctor_bp)
init_doctor_bp(db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.name = user_data.get('name')
        self.email = user_data.get('email')
        self.password = user_data.get('password')
        self.mobile_number = user_data.get('mobile_number')
        self.google_id = user_data.get('google_id')

# ── OAuth Configuration ────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'token_endpoint_auth_method': 'client_secret_basic'
    },
    update_token=lambda token, refresh_token=None, access_token=None: None
)

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = db.users.find_one({"_id": ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except Exception:
        pass
    return None

@app.context_processor
def inject_emergency_contacts():
    if current_user.is_authenticated:
        contacts = list(db.emergency_contacts.find({'user_id': current_user.id}))
        for c in contacts:
            c['id'] = str(c['_id'])
        return dict(global_emergency_contacts=contacts)
    return dict(global_emergency_contacts=[])

# ── HOME ROUTE ─────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    logging.info("Home page accessed")
    return render_template("index.html")


# ── PREDICT ROUTE ───────────────────────────────
@app.route("/predict", methods=["GET", "POST"])
@login_required
def predict():
    if request.method == "GET":
        return render_template("home.html")

    try:
        logging.info("Prediction request received")

        # ── Get form data ──────────────────────
        data = CustomData(
            symptoms  = request.form.get("symptoms"),
            age_group = request.form.get("age_group"),
            severity  = request.form.get("severity"),
            allergies = request.form.get("allergies")
        )

        # ── Convert to DataFrame ───────────────
        df = data.get_data_as_dataframe()
        logging.info(f"Input DataFrame:\n{df}")

        # ── Run Prediction ─────────────────────
        pipeline = PredictPipeline()
        result   = pipeline.predict(df)
        details  = pipeline.get_medicine_details(
            result["medicine"]
        )

        # Save to SymptomHistory
        new_history = {
            'user_id': current_user.id,
            'symptoms': request.form.get("symptoms"),
            'severity': request.form.get("severity"),
            'predicted_medicine': result["medicine"],
            'date_added': datetime.utcnow()
        }
        db.symptom_history.insert_one(new_history)

        logging.info(f"Prediction result: {result}")
        
        emergency_alert = False
        severity = request.form.get("severity", "")
        if severity.lower() == "severe":
            emergency_alert = True

        return render_template(
            "home.html",
            result    = result,
            details   = details,
            symptoms  = request.form.get("symptoms"),
            age_group = request.form.get("age_group"),
            severity  = request.form.get("severity"),
            allergies = request.form.get("allergies"),
            emergency_alert = emergency_alert
        )

    except Exception as e:
        logging.error(f"Prediction error: {e}")
        raise CustomException(e, sys)


# ── API ROUTE (JSON) ────────────────────────────
@app.route("/api/predict", methods=["POST"])
@login_required
def api_predict():
    try:
        # Get JSON data
        body = request.get_json()

        data = CustomData(
            symptoms  = body.get("symptoms"),
            age_group = body.get("age_group", "Adult"),
            severity  = body.get("severity",  "Mild"),
            allergies = body.get("allergies", "None")
        )

        df       = data.get_data_as_dataframe()
        pipeline = PredictPipeline()
        result   = pipeline.predict(df)
        details  = pipeline.get_medicine_details(
            result["medicine"]
        )
        
        emergency_alert = False
        if body.get("severity", "").lower() == "severe":
            emergency_alert = True

        return jsonify({
            "success"   : True,
            "medicine"  : result["medicine"],
            "specialty" : result["specialty"],
            "confidence": result["confidence"],
            "details"   : details,
            "emergency_alert": emergency_alert

        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error"  : str(e)
        }), 500
    

# Helper to recalculate a doctor's average rating (Requirement 5)
def recalculate_doctor_rating(doctor_id):
    try:
        reviews = list(db.reviews.find({"doctor_id": str(doctor_id)}))
        total_reviews = len(reviews)
        if total_reviews > 0:
            avg_rating = sum(float(r["rating"]) for r in reviews) / total_reviews
            avg_rating = round(avg_rating, 1)
        else:
            avg_rating = 0.0
            
        db.doctors.update_one(
            {"_id": ObjectId(doctor_id)},
            {"$set": {
                "rating": avg_rating,
                "total_reviews": total_reviews
            }}
        )
        logging.info(f"Recalculated doctor {doctor_id} average rating to {avg_rating} based on {total_reviews} reviews.")
        return avg_rating, total_reviews
    except Exception as e:
        logging.error(f"Error in recalculate_doctor_rating: {e}")
        return 0.0, 0


# Route to add doctor reviews (Requirement 5)
@app.route("/doctors/<doctor_id>/reviews", methods=["POST"])
@login_required
def add_review(doctor_id):
    try:
        rating = request.form.get("rating")
        comment = request.form.get("comment", "")
        
        if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
            flash("Invalid rating. Must be between 1 and 5.")
            return redirect(url_for('doctors'))
            
        new_review = {
            "doctor_id": str(doctor_id),
            "user_id": str(current_user.id),
            "rating": int(rating),
            "comment": comment.strip(),
            "created_at": datetime.utcnow()
        }
        
        db.reviews.insert_one(new_review)
        recalculate_doctor_rating(doctor_id)
        
        flash("Review added successfully!")
        return redirect(url_for('doctors'))
    except Exception as e:
        logging.error(f"Error adding review: {e}")
        flash("An error occurred while saving your review.")
        return redirect(url_for('doctors'))


# ── DOCTOR SEARCH ROUTE ─────────────────────────
@app.route("/doctors", methods=["GET", "POST"])
def doctors():
    try:
        # Retrieve filters from either query string (GET) or form data (POST) (Requirement 3)
        specialty = request.args.get("specialty") or request.form.get("specialty") or ""
        city = request.args.get("city") or request.form.get("city") or ""
        hospital = request.args.get("hospital") or request.form.get("hospital") or ""
        location = request.args.get("location") or request.form.get("location") or ""
        
        # Advanced filters (Requirement 3)
        min_rating = request.args.get("min_rating") or ""
        max_fee = request.args.get("max_fee") or ""
        available_today = request.args.get("available_today") in ["true", "1"]
        sort_by = request.args.get("sort_by") or ""

        # Normalize "All" option selections from dropdowns
        if specialty.lower() == "all": specialty = ""
        if city.lower() == "all": city = ""
        if hospital.lower() == "all": hospital = ""

        # Build MongoDB query for internal doctors (supporting combined filters)
        query = {"is_active": True}
        if specialty:
            query["specialization"] = {"$regex": specialty.strip(), "$options": "i"}
        if city:
            query["city"] = {"$regex": city.strip(), "$options": "i"}
        if hospital:
            query["hospital_name"] = {"$regex": hospital.strip(), "$options": "i"}
        if min_rating:
            try:
                query["rating"] = {"$gte": float(min_rating)}
            except ValueError:
                pass
        if max_fee:
            try:
                query["consultation_fee"] = {"$lte": int(max_fee)}
            except ValueError:
                pass

        logging.info(f"Filtering internal verified doctors with query: {query}")
        all_docs = list(db.doctors.find(query))

        # Dynamic Availability Checks (Requirement 3)
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        internal_doctors = []
        for doc in all_docs:
            doc_id_str = str(doc["_id"])
            
            # Query booked consultations for this doctor today
            booked_consults = list(db.consultations.find({
                "doctor_id": doc_id_str,
                "consultation_date": today_str
            }))
            booked_times = [c.get("appointment_time") for c in booked_consults if c.get("appointment_time")]
            
            # Daily clinical slots
            all_slots = ["09:00 AM", "10:00 AM", "11:00 AM", "02:00 PM", "03:00 PM"]
            open_slots = [slot for slot in all_slots if slot not in booked_times]
            
            is_available = len(open_slots) > 0
            doc["is_available_today"] = is_available
            doc["next_slot"] = f"Today at {open_slots[0]}" if is_available else "Tomorrow at 09:00 AM"
            
            # Filter by availability if requested
            if available_today and not is_available:
                continue
                
            doc['id'] = doc_id_str
            internal_doctors.append(doc)

        # Sorting logic (Requirement 3)
        if sort_by == "rating_desc":
            internal_doctors = sorted(internal_doctors, key=lambda x: x.get("rating", 0.0), reverse=True)
        elif sort_by == "fee_asc":
            internal_doctors = sorted(internal_doctors, key=lambda x: x.get("consultation_fee", 0))
        elif sort_by == "fee_desc":
            internal_doctors = sorted(internal_doctors, key=lambda x: x.get("consultation_fee", 0), reverse=True)

        # AJAX partial rendering (Requirement 4)
        if request.args.get("ajax") == "1":
            return render_template("doctor_cards_partial.html", internal_doctors=internal_doctors)

        # Query external clinical facilities (from OSM Nominatim API)
        external_location = location or city
        if specialty or external_location:
            logging.info(f"Searching external facilities for '{specialty}' in '{external_location}'")
            doctor_list = search_doctors(specialty or "doctor", external_location or "near me")
        else:
            doctor_list = []

        # Generate map view for external results
        map_html = build_doctor_map(doctor_list) if doctor_list else None

        # Retrieve distinct values dynamically from DB to populate dropdown filters (Requirement 4)
        distinct_specialties = sorted([s for s in db.doctors.distinct("specialization") if s])
        distinct_cities = sorted([c for c in db.doctors.distinct("city") if c])
        distinct_hospitals = sorted([h for h in db.doctors.distinct("hospital_name") if h])

        # Flag indicating if any search filter is active
        search_performed = bool(specialty or city or hospital or location or min_rating or max_fee or available_today or sort_by)

        return render_template(
            "doctor.html",
            doctors=doctor_list,
            internal_doctors=internal_doctors,
            map_html=map_html,
            specialty=specialty,
            city=city,
            hospital=hospital,
            location=location,
            min_rating=min_rating,
            max_fee=max_fee,
            available_today=available_today,
            sort_by=sort_by,
            distinct_specialties=distinct_specialties,
            distinct_cities=distinct_cities,
            distinct_hospitals=distinct_hospitals,
            count=len(doctor_list) + len(internal_doctors),
            success=search_performed
        )

    except Exception as e:
        logging.error(f"Error in doctor finder route: {e}")
        raise CustomException(e, sys)


# ── PHARMACY SEARCH ROUTE ─────────────────────────
@app.route("/pharmacies", methods=["GET", "POST"])
def pharmacies():
    if request.method == "GET":
        return render_template("pharmacy.html")

    try:
        location  = request.form.get("location")
        logging.info(f"Searching pharmacies near {location}")

        pharmacy_list = search_pharmacies(location)
        map_html = build_doctor_map(pharmacy_list) # Reusing map builder

        return render_template(
            "pharmacy.html",
            pharmacies = pharmacy_list,
            map_html  = map_html,
            location  = location
        )
    except Exception as e:
        raise CustomException(e, sys)

# ── APPOINTMENT BOOKING ────────────────────────
@app.route("/book/<doctor_id>", methods=["GET", "POST"])
@login_required
def book_appointment(doctor_id):
    doctor = db.doctors.find_one({"_id": ObjectId(doctor_id)})
    if not doctor:
        flash("Doctor not found.")
        return redirect(url_for('doctors'))

    if request.method == "POST":
        apt_date = request.form.get("date")
        apt_time = request.form.get("time")
        complaint = request.form.get("complaint")
        doctor_upi = (doctor.get("upi_id") or doctor.get("upi") or f"dr.{doctor['name'].lower().replace(' ', '')}@upi").strip()

        slot_duration_minutes = 60
        if has_slot_conflict(doctor_id, apt_date, apt_time, duration_minutes=slot_duration_minutes):
            flash("This time slot is already booked for this doctor. Please choose another time.")
            return redirect(url_for('book_appointment', doctor_id=doctor_id))

        # Create consultation record
        new_consult = {
            "doctor_id": doctor_id,
            "user_id": current_user.id,
            "patient_name": current_user.name,
            "patient_age": 30,
            "patient_gender": "Not Specified",
            "patient_dob": "N/A",
            "patient_blood_group": "N/A",
            "patient_contact": current_user.email,
            "slot_number": random.randint(1, 20),
            "appointment_time": apt_time,
            "start_time": apt_time,
            "end_time": add_minutes_to_time(apt_time, slot_duration_minutes),
            "duration_minutes": slot_duration_minutes,
            "chief_complaint": complaint,
            "status": "Payment Pending",
            "payment_status": "Pending",
            "payment_requested_upi": doctor_upi,
            "payment_verified_by_doctor": False,
            "priority": "Normal",
            "queue_type": "today",
            "consultation_date": apt_date,
            "vitals": {"bp": "-", "temp": "-", "pulse": "-", "spo2": "-", "weight": "-"},
            "created_at": datetime.utcnow()
        }
        result = db.consultations.insert_one(new_consult)

        # Create notification for doctor
        notification = {
            "doctor_id": doctor_id,
            "appointment_id": str(result.inserted_id),
            "consultation_date": apt_date,
            "appointment_time": apt_time,
            "message": f"Payment request sent by {current_user.name} for {apt_date} at {apt_time}. Please verify UPI payment before accepting.",
            "type": "appointment",
            "is_read": False,
            "created_at": datetime.utcnow()
        }
        db.doctor_notifications.insert_one(notification)

        flash(f"UPI payment request sent to {doctor['name']}. Please complete the payment to confirm your appointment.")
        return redirect(url_for('appointment_payment', apt_id=str(result.inserted_id)))

    return render_template("book_appointment.html", doctor=doctor)

# ── AUTHENTICATION ROUTES ───────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = db.users.find_one({'email': email})
        if user:
            flash('Email address already exists')
            return redirect(url_for('register'))
            
        new_user_data = {
            'name': name, 
            'email': email, 
            'password': generate_password_hash(password, method='pbkdf2:sha256')
        }
        res = db.users.insert_one(new_user_data)
        new_user_data['_id'] = res.inserted_id
        
        login_user(User(new_user_data))
        return redirect(url_for('predict'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_data = db.users.find_one({'email': email})
        
        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Please check your login details and try again.')
            return redirect(url_for('login'))
            
        login_user(User(user_data))
        
        # Redirect to Admin Panel if user is admin
        if user_data.get('email') == 'admin@medico.com':
            return redirect(url_for('admin_panel'))
            
        return redirect(url_for('predict'))
        
    return render_template('login.html')

# ── Google Login Routes ───────────────────────
@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def google_authorize():
    token = google.authorize_access_token()
    
    # Extract user info from id_token (OpenID Connect)
    user_info = token.get('userinfo')
    
    if not user_info:
        flash("Could not retrieve user information from Google.")
        return redirect(url_for('login'))
    
    email = user_info.get('email')
    google_id = user_info.get('sub')  # 'sub' is the standard OpenID Connect user ID claim
    name = user_info.get('name')
    
    if not email:
        flash("Could not retrieve email from Google.")
        return redirect(url_for('login'))
        
    # Check if user exists
    user_data = db.users.find_one({'email': email})
    
    if not user_data:
        # Create new user
        user_data = {
            'name': name,
            'email': email,
            'google_id': google_id,
            'password': generate_password_hash(os.urandom(24).hex(), method='pbkdf2:sha256')
        }
        res = db.users.insert_one(user_data)
        user_data['_id'] = res.inserted_id
    else:
        # Update google_id if not present
        if 'google_id' not in user_data:
            db.users.update_one({'_id': user_data['_id']}, {'$set': {'google_id': google_id}})
            user_data['google_id'] = google_id

    login_user(User(user_data))
    
    # Redirect to Admin if user is admin
    if email.lower() == 'admin@medico.com':
        return redirect(url_for('admin_panel'))
        
    return redirect(url_for('predict'))

# ── Mobile Login Routes ───────────────────────
@app.route('/login/mobile', methods=['GET', 'POST'])
def mobile_login():
    if request.method == 'POST':
        mobile_number = request.form.get('mobile_number')
        if not mobile_number:
            flash("Please enter a mobile number")
            return redirect(url_for('mobile_login'))
        
        # Mock OTP generation
        otp = str(random.randint(100000, 999999))
        # In a real app, send this via SMS. Here we just store it in session.
        session['mobile_number'] = mobile_number
        session['otp'] = otp
        
        flash(f"OTP sent to {mobile_number}. (Demo OTP: {otp})")
        return render_template('verify_otp.html', mobile_number=mobile_number)
    
    return render_template('mobile_login.html')

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    entered_otp = request.form.get('otp')
    stored_otp = session.get('otp')
    mobile_number = session.get('mobile_number')
    
    if entered_otp == stored_otp:
        # Check if user exists by mobile number
        user_data = db.users.find_one({'mobile_number': mobile_number})
        
        if not user_data:
            # Create new user or ask for details? 
            # For simplicity, create a user with "Mobile User" name
            user_data = {
                'name': f"User {mobile_number[-4:]}",
                'email': f"{mobile_number}@medico.local", # Dummy email
                'mobile_number': mobile_number,
                'password': generate_password_hash(os.urandom(24).hex(), method='pbkdf2:sha256')
            }
            res = db.users.insert_one(user_data)
            user_data['_id'] = res.inserted_id
        
        login_user(User(user_data))
        # Clear session
        session.pop('otp', None)
        
        # Redirect to Admin if user is admin
        if user_data.get('email', '').lower() == 'admin@medico.com':
            return redirect(url_for('admin_panel'))
            
        return redirect(url_for('predict'))
    else:
        flash("Invalid OTP. Please try again.")
        return render_template('verify_otp.html', mobile_number=mobile_number)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    name = request.form.get('name')
    email = request.form.get('email')
    
    if name and email:
        existing = db.users.find_one({'email': email})
        if existing and str(existing['_id']) != current_user.id:
            flash("Email already in use.")
        else:
            db.users.update_one(
                {'_id': ObjectId(current_user.id)}, 
                {'$set': {'name': name, 'email': email}}
            )
            current_user.name = name
            current_user.email = email
            flash("Profile updated successfully.")
            
    return redirect(url_for('dashboard'))

def build_doctor_admin_directory(search=None, sort_by=None):
    search_value = (search or '').strip().lower()
    doctors = list(db.doctors.find({}))

    if search_value:
        filtered = []
        for doctor in doctors:
            haystack = ' '.join([
                doctor.get('name', ''),
                doctor.get('specialization', ''),
                doctor.get('hospital_name', ''),
                doctor.get('city', '')
            ]).lower()
            if search_value in haystack:
                filtered.append(doctor)
        doctors = filtered

    if sort_by == 'rating_asc':
        doctors = sorted(doctors, key=lambda d: float(d.get('rating', 0) or 0))
    elif sort_by == 'rating_desc':
        doctors = sorted(doctors, key=lambda d: float(d.get('rating', 0) or 0), reverse=True)
    elif sort_by == 'city_asc':
        doctors = sorted(doctors, key=lambda d: str(d.get('city', '')).lower())
    elif sort_by == 'city_desc':
        doctors = sorted(doctors, key=lambda d: str(d.get('city', '')).lower(), reverse=True)
    elif sort_by == 'fee_asc':
        doctors = sorted(doctors, key=lambda d: int(d.get('consultation_fee', 0) or 0))
    elif sort_by == 'fee_desc':
        doctors = sorted(doctors, key=lambda d: int(d.get('consultation_fee', 0) or 0), reverse=True)
    else:
        doctors = sorted(doctors, key=lambda d: d.get('created_at', datetime.utcnow()), reverse=True)

    for doctor in doctors:
        doctor['id'] = str(doctor['_id'])
        doctor['rating'] = float(doctor.get('rating', 0) or 0)
        doctor['consultation_fee'] = int(doctor.get('consultation_fee', 0) or 0)

    return doctors


# ── ADMIN PANEL ─────────────────────────────────
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.email or current_user.email.lower() != 'admin@medico.com':
        flash('Access denied. Admin privileges required.')
        return redirect(url_for('dashboard'))

    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'rating_desc')
    doctor_list = build_doctor_admin_directory(search=search, sort_by=sort_by)

    total_users = db.users.count_documents({})
    total_records = db.medical_records.count_documents({})
    total_checks = db.symptom_history.count_documents({})
    recent_users = list(db.users.find().sort('_id', -1).limit(5))
    for u in recent_users: u['id'] = str(u['_id'])
    recent_checks = list(db.symptom_history.find().sort('date_added', -1).limit(10))
    for c in recent_checks: c['id'] = str(c['_id'])

    return render_template(
        'admin.html',
        total_users=total_users,
        total_records=total_records,
        total_checks=total_checks,
        recent_users=recent_users,
        recent_checks=recent_checks,
        doctors=doctor_list,
        search=search,
        sort_by=sort_by,
    )


@app.route('/admin/doctor/<doctor_id>')
@login_required
def admin_doctor_detail(doctor_id):
    if not current_user.email or current_user.email.lower() != 'admin@medico.com':
        flash('Access denied. Admin privileges required.')
        return redirect(url_for('dashboard'))

    doctor = db.doctors.find_one({'_id': ObjectId(doctor_id)})
    if not doctor:
        flash('Doctor not found.')
        return redirect(url_for('admin_panel'))

    doctor['id'] = str(doctor['_id'])
    patient_visits = list(db.consultations.find({'doctor_id': doctor['id']}).sort('consultation_date', -1))
    for visit in patient_visits:
        visit['id'] = str(visit['_id'])
        if visit.get('user_id'):
            user = db.users.find_one({'_id': ObjectId(visit['user_id'])})
            if user:
                visit['patient_email'] = user.get('email')

    return render_template('admin_doctor_detail.html', doctor=doctor, patient_visits=patient_visits)


@app.route('/admin/doctor/<doctor_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_doctor(doctor_id):
    if not current_user.email or current_user.email.lower() != 'admin@medico.com':
        flash('Access denied. Admin privileges required.')
        return redirect(url_for('dashboard'))

    doctor = db.doctors.find_one({'_id': ObjectId(doctor_id)})
    if not doctor:
        flash('Doctor not found.')
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        updates = {
            'name': request.form.get('name', doctor.get('name')),
            'email': request.form.get('email', doctor.get('email')),
            'specialization': request.form.get('specialization', doctor.get('specialization')),
            'hospital_name': request.form.get('hospital_name', doctor.get('hospital_name')),
            'city': request.form.get('city', doctor.get('city')),
            'consultation_fee': int(request.form.get('consultation_fee', doctor.get('consultation_fee', 0) or 0)),
            'rating': float(request.form.get('rating', doctor.get('rating', 0) or 0)),
        }
        db.doctors.update_one({'_id': doctor['_id']}, {'$set': updates})
        flash('Doctor details updated successfully.')
        return redirect(url_for('admin_doctor_detail', doctor_id=doctor_id))

    return render_template('admin_doctor_form.html', doctor=doctor)


@app.route('/admin/doctor/<doctor_id>/delete', methods=['POST'])
@login_required
def admin_delete_doctor(doctor_id):
    if not current_user.email or current_user.email.lower() != 'admin@medico.com':
        flash('Access denied. Admin privileges required.')
        return redirect(url_for('dashboard'))

    db.doctors.delete_one({'_id': ObjectId(doctor_id)})
    db.consultations.delete_many({'doctor_id': doctor_id})
    flash('Doctor deleted successfully.')
    return redirect(url_for('admin_panel'))

# ── DASHBOARD (MEDICAL RECORDS) ─────────────────
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST':
        record_type = request.form.get('record_type')
        description = request.form.get('description')
        file = request.files.get('file')
        
        file_path = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
        new_record = {
            'user_id': current_user.id,
            'record_type': record_type,
            'description': description,
            'file_path': file_path,
            'date_added': datetime.utcnow()
        }
        db.medical_records.insert_one(new_record)
        flash('Record added successfully')
        return redirect(url_for('dashboard'))
        
    records = list(db.medical_records.find({'user_id': current_user.id}).sort('date_added', -1))
    for r in records: r['id'] = str(r['_id'])
    symptom_history = list(db.symptom_history.find({'user_id': current_user.id}).sort('date_added', -1))
    for s in symptom_history: s['id'] = str(s['_id'])
    contacts = list(db.emergency_contacts.find({'user_id': current_user.id}))
    for c in contacts: c['id'] = str(c['_id'])
    
    # Fetch booked appointments
    appointments = list(db.consultations.find({'user_id': current_user.id}).sort('consultation_date', 1))
    for a in appointments:
        a['id'] = str(a['_id'])
        # Link doctor name
        doc = db.doctors.find_one({"_id": ObjectId(a['doctor_id'])})
        a['doctor_name'] = doc['name'] if doc else "Unknown Doctor"

    # Fetch patient notifications
    patient_notifications = list(db.patient_notifications.find({'user_id': current_user.id}).sort('created_at', -1).limit(10))
    patient_unread_count = sum(1 for n in patient_notifications if not n['is_read'])
    for n in patient_notifications: n['id'] = str(n['_id'])

    # Fetch patient prescriptions
    user_prescriptions = list(db.prescriptions.find({'patient_id': current_user.id}).sort('created_at', -1))
    for p in user_prescriptions: p['id'] = str(p['_id'])

    return render_template('dashboard.html', 
                           user=current_user, 
                           records=records, 
                           symptom_history=symptom_history, 
                           contacts=contacts, 
                           appointments=appointments,
                           notifications=patient_notifications,
                           unread_count=patient_unread_count,
                           prescriptions=user_prescriptions)

@app.route('/appointment/<apt_id>/payment', methods=['GET'])
@login_required
def appointment_payment(apt_id):
    consult = db.consultations.find_one({'_id': ObjectId(apt_id), 'user_id': current_user.id})
    if not consult:
        flash('Appointment not found.')
        return redirect(url_for('dashboard'))
    consult['id'] = str(consult['_id'])

    doctor = db.doctors.find_one({'_id': ObjectId(consult['doctor_id'])})
    if not doctor:
        flash('Doctor details unavailable for this appointment.')
        return redirect(url_for('dashboard'))

    doctor_upi = (doctor.get('upi_id') or doctor.get('upi') or f"dr.{doctor.get('name', 'doctor').lower().replace(' ', '')}@upi").strip()
    amount = doctor.get('consultation_fee') or 500
    return render_template('appointment_payment.html', appointment=consult, doctor=doctor, doctor_upi=doctor_upi, amount=amount)


@app.route('/appointment/<apt_id>/mark-paid', methods=['POST'])
@login_required
def mark_appointment_paid(apt_id):
    consult = db.consultations.find_one({'_id': ObjectId(apt_id), 'user_id': current_user.id})
    if not consult:
        flash('Appointment not found.')
        return redirect(url_for('dashboard'))

    doctor = db.doctors.find_one({'_id': ObjectId(consult['doctor_id'])})
    amount = doctor.get('consultation_fee') if doctor else 500

    db.consultations.update_one(
        {'_id': ObjectId(apt_id)},
        {'$set': {
            'payment_status': 'Paid',
            'paid_amount': amount,
            'status': 'Requested',
            'paid_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }}
    )

    if doctor:
        db.doctor_notifications.insert_one({
            'doctor_id': str(doctor['_id']),
            'appointment_id': str(consult['_id']),
            'consultation_date': consult.get('consultation_date'),
            'appointment_time': consult.get('appointment_time'),
            'message': f"{current_user.name} has paid ₹{amount} via UPI for appointment on {consult.get('consultation_date')} at {consult.get('appointment_time')}. Please verify the payment.",
            'type': 'payment',
            'is_read': False,
            'created_at': datetime.utcnow()
        })

    flash('Payment marked as sent. The doctor will verify it and confirm the appointment.')
    return redirect(url_for('dashboard'))


@app.route('/consultation/<apt_id>')
@login_required
def view_consultation(apt_id):
    consult = db.consultations.find_one({'_id': ObjectId(apt_id), 'user_id': current_user.id})
    if not consult:
        flash("Consultation record not found.")
        return redirect(url_for('dashboard'))
    
    # Get doctor info
    doctor = db.doctors.find_one({'_id': ObjectId(consult['doctor_id'])})
    return render_template('view_consultation.html', consult=consult, doctor=doctor)

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/view_record/<record_id>')
@login_required
def view_record(record_id):
    record = db.medical_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        flash('Record not found')
        return redirect(url_for('dashboard'))
    if record.get('user_id') != current_user.id:
        flash('Unauthorized access')
        return redirect(url_for('dashboard'))
    
    if not record.get('file_path'):
        flash('No file associated with this record')
        return redirect(url_for('dashboard'))
        
    filename = os.path.basename(record['file_path'])
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/edit_record/<record_id>', methods=['POST'])
@login_required
def edit_record(record_id):
    record = db.medical_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if record.get('user_id') != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    update_data = {}
    record_type = request.form.get('record_type')
    if record_type: update_data['record_type'] = record_type
    description = request.form.get('description')
    if description: update_data['description'] = description
    
    file = request.files.get('file')
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        update_data['file_path'] = file_path
        
    if update_data:
        db.medical_records.update_one({'_id': ObjectId(record_id)}, {'$set': update_data})
    
    flash('Record updated successfully')
    return redirect(url_for('dashboard'))

@app.route('/delete_record/<record_id>')
@login_required
def delete_record(record_id):
    record = db.medical_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        flash('Record not found')
        return redirect(url_for('dashboard'))
    if record.get('user_id') != current_user.id:
        flash('Unauthorized access')
        return redirect(url_for('dashboard'))
    
    db.medical_records.delete_one({'_id': ObjectId(record_id)})
    flash('Record deleted')
    return redirect(url_for('dashboard'))

# ── EMERGENCY CONTACTS ───────────────────────
@app.route('/add_contact', methods=['POST'])
@login_required
def add_contact():
    name = request.form.get('name')
    phone = request.form.get('phone')
    new_contact = {'user_id': current_user.id, 'name': name, 'phone': phone}
    db.emergency_contacts.insert_one(new_contact)
    flash('Contact added')
    return redirect(url_for('dashboard'))

@app.route('/delete_contact/<contact_id>')
@login_required
def delete_contact(contact_id):
    contact = db.emergency_contacts.find_one({'_id': ObjectId(contact_id)})
    if contact and contact.get('user_id') == current_user.id:
        db.emergency_contacts.delete_one({'_id': ObjectId(contact_id)})
        flash('Contact deleted')
    return redirect(url_for('dashboard'))

# ── MEDICINE INTERACTION CHECKER ────────────────
def get_drug_safety_note(drug_name):
    """Fetch a live medicine safety note from the FDA drug label API."""
    drug_name = (drug_name or '').strip()
    if not drug_name:
        return None

    try:
        search = f'openfda.generic_name:"{drug_name}" OR openfda.brand_name:"{drug_name}"'
        response = requests.get(
            'https://api.fda.gov/drug/label.json',
            params={'search': search, 'limit': 1},
            timeout=10,
        )
        if response.status_code != 200:
            return None

        data = response.json()
        results = data.get('results') or []
        if not results:
            return None

        result = results[0]
        for field in ('warnings', 'warnings_and_precautions', 'boxed_warning', 'indications_and_usage'):
            value = result.get(field)
            if value:
                text = ' '.join(str(value).split())
                return text[:260]

        return 'FDA label info available for this medicine.'
    except Exception as exc:
        logging.warning(f"FDA drug safety lookup failed for {drug_name}: {exc}")
        return None


def get_drug_interaction_result(med1, med2):
    """Use a live third-party safety API to surface medicine safety notes."""
    med1 = (med1 or '').strip()
    med2 = (med2 or '').strip()

    if not med1 or not med2:
        return "Please enter both medications to check for interactions."

    note1 = get_drug_safety_note(med1)
    note2 = get_drug_safety_note(med2)

    if not note1 and not note2:
        return (
            "Live safety data is currently unavailable for these medicines. "
            "Please consult your doctor or pharmacist before combining medications."
        )

    parts = []
    if note1:
        parts.append(f"{med1.title()}: {note1}")
    if note2:
        parts.append(f"{med2.title()}: {note2}")

    return "Live medicine safety notes: " + ' | '.join(parts)


@app.route("/interactions", methods=["GET", "POST"])
def interactions():
    if request.method == "GET":
        return render_template("interactions.html")

    med1 = request.form.get("medicine_1", "").strip()
    med2 = request.form.get("medicine_2", "").strip()
    interaction_result = get_drug_interaction_result(med1, med2)
    return render_template("interactions.html", med1=med1, med2=med2, result=interaction_result)

# ── MEDICATION REMINDERS ────────────────
@app.route("/reminders", methods=["GET", "POST"])
@login_required
def reminders():
    if request.method == "POST":
        medicine_name = request.form.get("medicine_name")
        dosage = request.form.get("dosage")
        time = request.form.get("time")
        
        new_reminder = {
            'user_id': current_user.id,
            'medicine_name': medicine_name,
            'dosage': dosage,
            'time': time,
            'date_added': datetime.utcnow()
        }
        db.medication_reminders.insert_one(new_reminder)
        flash("Reminder added successfully!")
        return redirect(url_for("reminders"))
        
    user_reminders = list(db.medication_reminders.find({'user_id': current_user.id}))
    for r in user_reminders: r['id'] = str(r['_id'])
    return render_template("reminders.html", reminders=user_reminders)

@app.route('/delete_reminder/<reminder_id>')
@login_required
def delete_reminder(reminder_id):
    reminder = db.medication_reminders.find_one({'_id': ObjectId(reminder_id)})
    if reminder and reminder.get('user_id') == current_user.id:
        db.medication_reminders.delete_one({'_id': ObjectId(reminder_id)})
        flash('Reminder deleted')
    return redirect(url_for('reminders'))

@app.route('/api/reminders')
@login_required
def api_reminders():
    user_reminders = list(db.medication_reminders.find({'user_id': current_user.id}))
    reminders_data = [{"medicine_name": r.get('medicine_name'), "time": r.get('time')} for r in user_reminders]
    return jsonify({"reminders": reminders_data})

# ── CLINICAL AI CHATBOT SYSTEM ──────────────────────────────────

# List of critical symptoms for immediate red-flag emergency screening
EMERGENCY_KEYWORDS = [
    "chest pain", 
    "can't breathe", 
    "severe bleeding", 
    "unconscious", 
    "stroke symptoms",
    "difficulty breathing",
    "heart attack",
    "heavy bleeding",
    "severe burn"
]

# Hardcoded mapping of common symptoms to clinical medical specialties
SYMPTOM_SPECIALTY_MAP = {
    # General Physician
    "fever": "General Physician",
    "cough": "General Physician",
    "cold": "General Physician",
    "flu": "General Physician",
    "sore throat": "General Physician",
    "runny nose": "General Physician",
    "headache": "General Physician",
    "stomach pain": "General Physician",
    "acidity": "General Physician",
    "vomiting": "General Physician",
    "nausea": "General Physician",
    
    # Cardiologist
    "chest pain": "Cardiologist",
    "heart racing": "Cardiologist",
    "palpitations": "Cardiologist",
    "shortness of breath": "Cardiologist",
    
    # Dermatologist
    "skin issues": "Dermatologist",
    "rash": "Dermatologist",
    "itching": "Dermatologist",
    "acne": "Dermatologist",
    "hair loss": "Dermatologist",
    
    # Gynecologist
    "pregnancy": "Gynecologist",
    "menstrual pain": "Gynecologist",
    "gynecological": "Gynecologist",
    
    # Dentist
    "toothache": "Dentist",
    "cavity": "Dentist",
    "bleeding gums": "Dentist",
    
    # Orthopedist
    "joint pain": "Orthopedist",
    "back pain": "Orthopedist",
    "fracture": "Orthopedist",
    "sprain": "Orthopedist",
    "knee pain": "Orthopedist",
    
    # Nephrologist / Urologist
    "kidney stones": "Nephrologist",
    "urinary issue": "Urologist",
    
    # Endocrinologist
    "diabetes": "Endocrinologist",
    "thyroid": "Endocrinologist",
    
    # Ophthalmologist
    "vision issues": "Ophthalmologist",
    "blurry vision": "Ophthalmologist",
    "eye pain": "Ophthalmologist",
    
    # ENT Specialist
    "ear pain": "ENT Specialist",
    "hearing loss": "ENT Specialist",
    "nasal congestion": "ENT Specialist",
    "throat infection": "ENT Specialist",
    
    # Psychiatrist
    "anxiety": "Psychiatrist",
    "depression": "Psychiatrist",
    "panic attack": "Psychiatrist",
    
    # Neurologist
    "seizure": "Neurologist",
    "numbness": "Neurologist",
    "migraine": "Neurologist",
    "dizziness": "Neurologist",
    
    # Pulmonologist
    "asthma": "Pulmonologist",
    "chronic cough": "Pulmonologist",
    
    # Allergist
    "allergy": "Allergist",
    
    # Pediatrician
    "kid symptoms": "Pediatrician",
    "child health": "Pediatrician",
    "pediatric": "Pediatrician"
}

# In-memory dictionary to track appointment confirmation states
# Keyed by user_id -> dict with details
pending_bookings = {}

def classify_symptom_via_ollama(message: str) -> str:
    """
    Calls a local LLM via Ollama (llama3.1:8b) on localhost:11434 to classify
    the symptom description into a medical specialty. Includes error handling.
    """
    import requests
    
    url = "http://localhost:11434/api/generate"
    prompt = (
        "You are a medical symptom classifier. Classify this user's natural language symptom "
        "description into EXACTLY ONE of the following clinical specialties:\n"
        "General Physician, Cardiologist, Dermatologist, Gynecologist, Dentist, Orthopedist, "
        "Nephrologist, Urologist, Endocrinologist, Ophthalmologist, ENT Specialist, Psychiatrist, "
        "Neurologist, Pulmonologist, Allergist, Pediatrician.\n\n"
        f"User message: '{message}'\n\n"
        "Return ONLY the specialty name in plain text, with no punctuation or extra words."
    )
    
    try:
        logging.info("Requesting specialty classification from local Ollama service...")
        response = requests.post(url, json={
            "model": "llama3.1:8b",
            "prompt": prompt,
            "stream": False
        }, timeout=6)  # Keep timeout reasonable to protect user experience
        
        if response.status_code == 200:
            res_json = response.json()
            specialty = res_json.get("response", "").strip()
            # Clean quotes if any
            specialty = specialty.replace('"', '').replace("'", "").strip()
            logging.info(f"Ollama successfully classified symptom to: '{specialty}'")
            return specialty
        else:
            logging.warning(f"Ollama returned status code {response.status_code}")
            
    except requests.exceptions.Timeout:
        logging.error("Ollama connection timed out (model llama3.1:8b may be loading or slow)")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ollama connection error: {e}")
        
    return None


@app.route("/chatbot", methods=["GET"])
@login_required
def chatbot_get():
    """Renders the dedicated chatbot UI page."""
    return render_template("chatbot.html")


@app.route("/chatbot", methods=["POST"])
def chatbot_post():
    """
    Handles natural language chatbot conversation state machine for symptom-based booking.
    """
    from datetime import timedelta
    try:
        # Check authentication manually to return clean JSON response
        if not current_user or not current_user.is_authenticated:
            return jsonify({
                "success": True,
                "reply": "Please log in to your account first so I can assist you with booking an appointment."
            })

        body = request.get_json()
        if not body or not body.get("message"):
            return jsonify({"success": False, "error": "No message provided"}), 400

        user_msg = body["message"].strip()
        user_msg_lower = user_msg.lower()
        user_id = current_user.id

        # ── STATE CHECK: PENDING CONFIRMATIONS ───────────────────────
        if user_id in pending_bookings:
            pending = pending_bookings[user_id]
            confirm_keywords = ["yes", "confirm", "y", "sure", "ok", "please", "book it", "yeah", "yep", "confirm booking"]
            cancel_keywords = ["no", "cancel", "stop", "dont", "change", "abort", "nope"]
            
            if any(k in user_msg_lower for k in confirm_keywords):
                # 7. Create the Appointment record and return a success message
                doctor = db.doctors.find_one({"_id": ObjectId(pending["doctor_id"])})
                if not doctor:
                    del pending_bookings[user_id]
                    return jsonify({
                        "success": True,
                        "reply": "I'm sorry, but that doctor is no longer available. Please describe your symptoms to start a new booking."
                    })
                
                # Insert appointment (consultation)
                new_consult = {
                    "doctor_id": pending["doctor_id"],
                    "user_id": user_id,
                    "patient_name": current_user.name,
                    "patient_age": 30,  # Default age
                    "patient_gender": "Not Specified",
                    "patient_dob": "N/A",
                    "patient_blood_group": "N/A",
                    "patient_contact": current_user.email,
                    "slot_number": random.randint(1, 20),
                    "appointment_time": pending["time"],
                    "chief_complaint": pending["symptom"],
                    "status": "Requested",
                    "priority": "Normal",
                    "queue_type": "today",
                    "consultation_date": pending["date"],
                    "vitals": {"bp": "-", "temp": "-", "pulse": "-", "spo2": "-", "weight": "-"},
                    "created_at": datetime.utcnow()
                }
                db.consultations.insert_one(new_consult)

                # Create notification for doctor
                doc_notification = {
                    "doctor_id": pending["doctor_id"],
                    "message": f"New appointment booked by {current_user.name} for {pending['date']} at {pending['time']}",
                    "type": "appointment",
                    "is_read": False,
                    "created_at": datetime.utcnow()
                }
                db.doctor_notifications.insert_one(doc_notification)

                # Create notification for patient
                pat_notification = {
                    "user_id": user_id,
                    "message": f"Your appointment with Dr. {doctor['name']} ({pending['specialty']}) for {pending['date']} at {pending['time']} is requested.",
                    "type": "success",
                    "is_read": False,
                    "created_at": datetime.utcnow()
                }
                db.patient_notifications.insert_one(pat_notification)

                # Clear confirmation state
                del pending_bookings[user_id]

                return jsonify({
                    "success": True,
                    "reply": f"🎉 **Success!** Your appointment with **Dr. {doctor['name']}** has been scheduled for **{pending['date']} at {pending['time']}**.\n\nYou can track this booking on your [Patient Dashboard](/dashboard)."
                })
                
            elif any(k in user_msg_lower for k in cancel_keywords):
                # Clear state
                del pending_bookings[user_id]
                return jsonify({
                    "success": True,
                    "reply": "Booking cancelled. What else can I help you with today?"
                })
            else:
                return jsonify({
                    "success": True,
                    "reply": f"I have a pending appointment booking for **Dr. {pending['doctor_name']}** ({pending['specialty']}) on **{pending['date']} at {pending['time']}**.\n\nPlease reply **'yes'** to confirm this booking, or **'no'** to cancel it."
                })

        # ── EMERGENCY SCREENING (RED FLAG CHECK) ────────────────────
        # 4. If emergency keywords match, skip booking entirely and direct to 108 (no LLM)
        is_emergency = False
        matched_flag = ""
        for keyword in EMERGENCY_KEYWORDS:
            if keyword in user_msg_lower:
                is_emergency = True
                matched_flag = keyword
                break
                
        if is_emergency:
            logging.warning(f"Emergency Red Flag triggered by keyword: '{matched_flag}'")
            return jsonify({
                "success": True,
                "reply": "🚨 **CRITICAL MEDICAL ALERT!** 🚨\n\n"
                         "Based on the symptom you described (*" + matched_flag + "*), this may be a severe medical emergency.\n\n"
                         "**Please immediately dial emergency services (108 / 112) or proceed to the nearest emergency room.**\n\n"
                         "*Online booking is disabled for critical symptoms to prevent delay in care.*"
            })

        # ── INTENT DETECTION: BOOKING REQUEST ───────────────────────
        booking_intent = any(k in user_msg_lower for k in ["book", "appointment", "schedule", "doctor", "consult", "reserve", "see a"])
        
        if not booking_intent:
            return jsonify({
                "success": True,
                "reply": "👋 Hello! I am your Medico AI Assistant.\n\n"
                         "I can help you schedule appointments with our specialists. Try typing:\n"
                         "• *'book an appointment for my fever'*\n"
                         "• *'I need to see a cardiologist for a chest pain'*"
            })

        # ── SYMPTOM CLASSIFICATION & SPECIALTY MAPPING ──────────────
        matched_specialty = None
        matched_symptom = None

        # 2. Map the symptom using a hardcoded lookup table first
        for sym, spec in SYMPTOM_SPECIALTY_MAP.items():
            if sym in user_msg_lower:
                matched_specialty = spec
                matched_symptom = sym
                logging.info(f"Symptom hardcoded match: '{sym}' mapped to '{spec}'")
                break

        # 3. Call local LLM via Ollama if not in lookup table
        if not matched_specialty:
            logging.info("Symptom not matched in lookup table. Directing classification to Ollama...")
            classified_spec = classify_symptom_via_ollama(user_msg)
            
            # Match Ollama output against known valid specialties
            valid_specialties = set(SYMPTOM_SPECIALTY_MAP.values())
            if classified_spec:
                for spec in valid_specialties:
                    if spec.lower() in classified_spec.lower():
                        matched_specialty = spec
                        break
            
            if matched_specialty:
                matched_symptom = user_msg
                logging.info(f"Ollama resolved specialty: '{matched_specialty}'")
            else:
                # Fallback to General Physician if Ollama output is invalid/offline
                logging.info("Ollama resolution failed or was offline. Defaulting to General Physician.")
                matched_specialty = "General Physician"
                matched_symptom = "general symptoms"

        # ── 5. FIND AN AVAILABLE DOCTOR ──────────────────────────────
        # Search db.doctors for the specialty
        doctor = db.doctors.find_one({"specialization": matched_specialty, "is_active": True})
        
        if not doctor:
            # Fallback to General Physician if specialty is not present in database
            logging.warning(f"No doctor registered for specialty '{matched_specialty}'. Falling back to General Physician.")
            doctor = db.doctors.find_one({"specialization": "General Physician", "is_active": True})
            if not doctor:
                return jsonify({
                    "success": True,
                    "reply": "We apologize, but we do not have any active doctors registered in our clinic right now. Please check back later."
                })
            matched_specialty = "General Physician"

        # Generate appointment slot
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        slot_time = "10:00 AM"

        # Store pending booking state
        pending_bookings[user_id] = {
            "doctor_id": str(doctor["_id"]),
            "doctor_name": doctor["name"],
            "specialty": matched_specialty,
            "date": tomorrow,
            "time": slot_time,
            "symptom": matched_symptom or "symptom consultation"
        }

        # ── 6. SHOW CONFIRMATION STEP ────────────────────────────────
        reply_text = (
            f"🩺 Based on your symptoms, I have mapped your request to a **{matched_specialty}**.\n\n"
            f"I found **{doctor['name']}** ({matched_specialty}) available on **{tomorrow} at {slot_time}**.\n\n"
            f"Shall I confirm this booking? (Reply **'yes'** to confirm, **'no'** to cancel)"
        )

        return jsonify({
            "success": True,
            "reply": reply_text
        })

    except Exception as e:
        logging.error(f"Chatbot POST error: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500


# ── CHATBOT ROUTE ───────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        body = request.get_json()
        if not body or not body.get("message"):
            return jsonify({"success": False, "error": "No message provided"}), 400

        user_msg = body["message"].strip().lower()
        reply = _chatbot_reply(user_msg)

        return jsonify({
            "success": True,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logging.error(f"Chatbot error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _chatbot_reply(msg: str) -> str:
    """Rule-based medical chatbot logic."""
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
    if any(g in msg for g in greetings):
        return ("👋 Hello! I'm **MediBot**, your AI health assistant.\n\n"
                "I can help you with:\n"
                "• 🩺 Understanding symptoms\n"
                "• 💊 General medicine info\n"
                "• 🏥 Finding a specialist\n"
                "• 🚨 Emergency guidance\n\n"
                "What health question can I help you with today?")

    if any(w in msg for w in ["bye", "goodbye", "thanks", "thank you"]):
        return "Take care and stay healthy! 💚 Don't hesitate to come back if you have more health questions."

    emergency_keywords = ["chest pain", "heart attack", "stroke", "can't breathe",
                          "unconscious", "severe bleeding", "overdose", "seizure", "emergency"]
    if any(k in msg for k in emergency_keywords):
        return ("🚨 **This sounds like a medical emergency!**\n\n"
                "**Please call emergency services (112 / 108 / 911) immediately.**\n\n"
                "**Go to the nearest hospital or call 108 NOW.**")

    if re.search(r"fever|high temperature|chills|pyrexia", msg):
        return ("🌡️ **Fever Guidance**\n\n"
                "• Rest and drink plenty of fluids\n"
                "• Paracetamol (500mg every 4–6 hours) for adults\n"
                "• See a doctor if fever > 39.5°C or lasts more than 3 days")

    if re.search(r"headache|migraine|head pain", msg):
        return ("🧠 **Headache Guidance**\n\n"
                "• Rest in a quiet, dark room\n"
                "• Stay hydrated\n"
                "• Paracetamol or Ibuprofen (if no allergies)\n"
                "• Seek urgent care for sudden severe headache")

    if re.search(r"cold|flu|cough|runny nose|sore throat|sneezing", msg):
        return ("🤧 **Cold & Flu Guidance**\n\n"
                "• Rest and drink warm fluids\n"
                "• Steam inhalation for congestion\n"
                "• Paracetamol for fever/body aches\n"
                "• See a doctor if symptoms worsen after 5 days")

    if re.search(r"stomach|nausea|vomit|diarrhea|acidity|heartburn", msg):
        return ("🫃 **Digestive Issue Guidance**\n\n"
                "• Sip clear fluids slowly\n"
                "• ORS for diarrhea\n"
                "• Antacids for acidity/heartburn\n"
                "• Seek care if symptoms last > 3 days")

    if re.search(r"doctor|specialist|find|hospital|near me", msg):
        return ("🏥 **Finding a Doctor**\n\n"
                "Use our [Doctor Finder](/doctors) to search for specialists near you!\n\n"
                "Enter a specialty (e.g. Cardiologist) and your city to see results on a map.")

    return ("🤔 I'm not sure I fully understand that. Could you rephrase?\n\n"
            "You can ask me about: fever, headache, cold, stomach issues, or finding a doctor nearby.")


# ── DOCTOR LOGIN (redirect wrapper so url_for('doctor_login') works) ────────────
@app.route('/doctor/login', methods=['GET', 'POST'])
def doctor_login():
    # The real handler lives in doctor_bp; this stub keeps url_for('doctor_login') intact
    return redirect(url_for('doctor.login'))

# ── E-PRESCRIBER & DRUG SEARCH ROUTES ────────────────────────

@app.route('/api/drugs/search', methods=['GET'])
def search_drugs_api():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    regex = re.compile(re.escape(query), re.IGNORECASE)
    results = list(db.drugs.find({
        '$or': [
            {'name': {'$regex': regex}},
            {'generic_name': {'$regex': regex}}
        ]
    }).limit(20))
    match_list = []
    for d in results:
        match_list.append({
            'id': str(d['_id']),
            'name': d.get('name'),
            'generic_name': d.get('generic_name', ''),
            'common_dosages': d.get('common_dosages', ''),
            'dosage_form': d.get('dosage_form', '')
        })
    return jsonify(match_list)


@app.route('/appointment/<apt_id>/prescribe', methods=['GET', 'POST'])
def prescribe_appointment(apt_id):
    # Doctor auth check: check session['doctor_id'] or current_user
    doc_id = session.get('doctor_id')
    doctor = None
    if doc_id:
        try:
            doctor = db.doctors.find_one({'_id': ObjectId(doc_id)})
        except Exception:
            pass
    elif current_user.is_authenticated:
        doctor = db.doctors.find_one({'email': current_user.email})

    if not doctor and not session.get('doctor_id'):
        flash("Doctor access required to prescribe medications.")
        return redirect(url_for('doctor.login'))

    try:
        consult = db.consultations.find_one({'_id': ObjectId(apt_id)})
    except Exception:
        consult = None

    if not consult:
        flash("Appointment not found.")
        return redirect(url_for('doctor.dashboard'))

    consult['id'] = str(consult['_id'])

    if not doctor:
        doc_id = consult.get('doctor_id')
        if doc_id:
            try:
                doctor = db.doctors.find_one({'_id': ObjectId(doc_id)})
            except Exception:
                pass
        if not doctor:
            doctor = {
                'name': session.get('doctor_name', 'Dr. Specialist'),
                'specialization': session.get('doctor_spec', 'Physician'),
                'registration_number': 'REG-100234'
            }

    existing_presc = db.prescriptions.find_one({'appointment_id': consult['id']})
    is_finalized = False
    if existing_presc:
        existing_presc['id'] = str(existing_presc['_id'])
        if existing_presc.get('status') == 'finalized':
            is_finalized = True

    if request.method == 'POST':
        if is_finalized:
            flash("This prescription has already been finalized and cannot be modified.")
            return redirect(url_for('prescribe_appointment', apt_id=apt_id))

        action = request.form.get('action', 'save_draft')
        notes = request.form.get('notes', '').strip()

        drug_names = request.form.getlist('drug_name[]')
        drug_ids = request.form.getlist('drug_id[]')
        dosages = request.form.getlist('dosage[]')
        frequencies = request.form.getlist('frequency[]')
        durations = request.form.getlist('duration[]')
        instructions_list = request.form.getlist('instructions[]')

        items = []
        for i in range(len(drug_names)):
            if drug_names[i].strip():
                items.append({
                    'drug_id': drug_ids[i] if i < len(drug_ids) else '',
                    'drug_name': drug_names[i].strip(),
                    'dosage': dosages[i].strip() if i < len(dosages) else '',
                    'frequency': frequencies[i].strip() if i < len(frequencies) else '1-0-1',
                    'duration': durations[i].strip() if i < len(durations) else '5 days',
                    'instructions': instructions_list[i].strip() if i < len(instructions_list) else ''
                })

        status = 'finalized' if action == 'finalize' else 'draft'

        doc_name = doctor.get('name', 'Doctor') if isinstance(doctor, dict) else 'Doctor'
        doc_reg = doctor.get('registration_number', 'REG-100234') if isinstance(doctor, dict) else 'REG-100234'

        presc_doc = {
            'appointment_id': consult['id'],
            'doctor_id': str(doctor['_id']) if isinstance(doctor, dict) and '_id' in doctor else str(session.get('doctor_id', '')),
            'patient_id': str(consult.get('user_id', '')),
            'doctor_name': doc_name,
            'doctor_reg_no': doc_reg,
            'patient_name': consult.get('patient_name', 'Patient'),
            'patient_age': consult.get('patient_age', 'N/A'),
            'patient_gender': consult.get('patient_gender', 'N/A'),
            'notes': notes,
            'status': status,
            'items': items,
            'updated_at': datetime.utcnow()
        }

        if existing_presc:
            db.prescriptions.update_one({'_id': existing_presc['_id']}, {'$set': presc_doc})
            presc_id = str(existing_presc['_id'])
        else:
            presc_doc['created_at'] = datetime.utcnow()
            res = db.prescriptions.insert_one(presc_doc)
            presc_id = str(res.inserted_id)

        # Update consultation record with prescription status
        db.consultations.update_one(
            {'_id': ObjectId(apt_id)},
            {'$set': {
                'prescription_id': presc_id,
                'prescription_issued': True,
                'status': 'Completed' if status == 'finalized' else consult.get('status', 'In Progress')
            }}
        )

        if status == 'finalized':
            if consult.get('user_id'):
                db.patient_notifications.insert_one({
                    'user_id': consult['user_id'],
                    'message': f"Dr. {doc_name} has finalized your e-prescription.",
                    'type': 'success',
                    'is_read': False,
                    'created_at': datetime.utcnow()
                })
            flash("Prescription finalized successfully!")
        else:
            flash("Prescription draft saved.")

        return redirect(url_for('prescribe_appointment', apt_id=apt_id))

    return render_template(
        'prescribe.html',
        appointment=consult,
        doctor=doctor,
        prescription=existing_presc,
        is_finalized=is_finalized
    )


@app.route('/prescription/<presc_id>/pdf', methods=['GET'])
def generate_prescription_pdf(presc_id):
    try:
        presc = db.prescriptions.find_one({'_id': ObjectId(presc_id)})
    except Exception:
        presc = None

    if not presc:
        flash("Prescription not found.")
        return redirect(url_for('dashboard'))

    presc['id'] = str(presc['_id'])
    
    doctor_info = None
    if presc.get('doctor_id'):
        try:
            doctor_info = db.doctors.find_one({'_id': ObjectId(presc['doctor_id'])})
        except Exception:
            pass

    pdf_buffer = create_prescription_pdf(presc, doctor_info=doctor_info)
    patient_clean = (presc.get('patient_name') or 'Patient').replace(' ', '_')
    filename = f"Prescription_{patient_clean}_{presc_id[:8]}.pdf"
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename
    )


@app.route('/prescription/<presc_id>/share', methods=['GET', 'POST'])
def share_prescription(presc_id):
    try:
        presc = db.prescriptions.find_one({'_id': ObjectId(presc_id)})
    except Exception:
        presc = None

    if not presc:
        return jsonify({'error': 'Prescription not found'}), 404

    s = URLSafeTimedSerializer(app.secret_key)
    token = s.dumps(str(presc['_id']), salt='share-prescription')
    share_url = url_for('view_shared_prescription', token=token, _external=True)

    return jsonify({'share_url': share_url, 'token': token})


@app.route('/prescription/shared/<token>', methods=['GET'])
def view_shared_prescription(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        presc_id = s.loads(token, salt='share-prescription', max_age=86400 * 30)
    except Exception:
        flash("Invalid or expired prescription link.")
        return redirect(url_for('index'))

    try:
        presc = db.prescriptions.find_one({'_id': ObjectId(presc_id)})
    except Exception:
        presc = None

    if not presc:
        flash("Prescription not found.")
        return redirect(url_for('index'))

    presc['id'] = str(presc['_id'])
    return render_template('shared_prescription.html', presc=presc, token=token)


@app.route('/prescription/shared/<token>/pdf', methods=['GET'])
def view_shared_prescription_pdf(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        presc_id = s.loads(token, salt='share-prescription', max_age=86400 * 30)
    except Exception:
        flash("Invalid or expired prescription link.")
        return redirect(url_for('index'))

    try:
        presc = db.prescriptions.find_one({'_id': ObjectId(presc_id)})
    except Exception:
        presc = None

    if not presc:
        flash("Prescription not found.")
        return redirect(url_for('index'))

    presc['id'] = str(presc['_id'])
    doctor_info = None
    if presc.get('doctor_id'):
        try:
            doctor_info = db.doctors.find_one({'_id': ObjectId(presc['doctor_id'])})
        except Exception:
            pass

    pdf_buffer = create_prescription_pdf(presc, doctor_info=doctor_info)
    filename = f"Prescription_{presc_id[:8]}.pdf"

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename
    )


# ── JITSI VIDEO CONSULTATION ROUTE ───────────────────────────

@app.route('/consultation/<apt_id>/video', methods=['GET'])
def consultation_video_call(apt_id):
    try:
        consult = db.consultations.find_one({'_id': ObjectId(apt_id)})
    except Exception:
        consult = None

    if not consult:
        flash("Consultation session not found.")
        return redirect(url_for('dashboard'))

    consult['id'] = str(consult['_id'])

    # Determine user identity & role
    user_role = 'patient'
    display_name = consult.get('patient_name', 'Patient')

    doc_id = session.get('doctor_id')
    if doc_id:
        user_role = 'doctor'
        display_name = session.get('doctor_name', 'Dr. Specialist')
    elif current_user.is_authenticated:
        doc_match = db.doctors.find_one({'email': current_user.email})
        if doc_match and (str(doc_match['_id']) == str(consult.get('doctor_id')) or doc_match.get('email') == current_user.email):
            user_role = 'doctor'
            display_name = doc_match.get('name', current_user.name)
        else:
            user_role = 'patient'
            display_name = current_user.name
    else:
        flash("Please log in to join the video consultation.")
        return redirect(url_for('login'))

    doctor_info = None
    if consult.get('doctor_id'):
        try:
            doctor_info = db.doctors.find_one({'_id': ObjectId(consult['doctor_id'])})
        except Exception:
            pass

    room_name = f"Medico_Telehealth_{apt_id}"

    return render_template(
        'video_consultation.html',
        appointment=consult,
        doctor=doctor_info,
        user_role=user_role,
        display_name=display_name,
        room_name=room_name
    )

# ── RUN ────────────────────────────────────────
if __name__ == "__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(
        host  = "0.0.0.0",
        port  = port,
        debug = True
    )
