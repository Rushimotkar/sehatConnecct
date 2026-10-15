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
    session
)
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

load_dotenv()

from src.logger import logging
from src.exception import CustomException
from src.pipeline.prediction_pipeline import (
    PredictPipeline,
    CustomData
)

# ── Flask App ──────────────────────────────────
app = Flask(__name__)
application=app
app.secret_key = 'super_secret_medico_key'
# Database Configuration (MongoDB)
app.config['UPLOAD_FOLDER'] = os.path.join('artifacts', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Add hasattr to Jinja2 globals
app.jinja_env.globals.update(hasattr=hasattr, getattr=getattr)

mongo_uri = os.environ.get('MONGO_URI', '')

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
            
            if 'ssl handshake' in error_msg.lower() or 'certificate' in error_msg.lower():
                logging.warning(f"SSL handshake attempt {retry_count}/{max_retries} failed: {e}")
                
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"✗ MongoDB SSL connection failed after {max_retries} attempts")
                    raise CustomException(
                        f"MongoDB SSL handshake failed: {error_msg}\n"
                        f"Make sure your IP is whitelisted in MongoDB Atlas and certifi is installed.",
                        sys
                    )
            else:
                logging.error(f"✗ MongoDB connection error: {e}")
                raise CustomException(f"MongoDB connection error: {e}", sys)
    
    return None

try:
    client = create_mongo_connection()
except Exception as e:
    logging.error(f"Failed to establish MongoDB connection: {e}")
    raise

db = client['medico']

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
    

# ── DOCTOR SEARCH ROUTE ─────────────────────────
# ── DOCTOR SEARCH ROUTE ─────────────────────────
@app.route("/doctors", methods=["GET", "POST"])
def doctors():
    if request.method == "GET":
        return render_template("doctor.html")

    try:
        specialty = request.form.get("specialty")
        location  = request.form.get("location")

        # Optional: replace radius with limit
        ##limit = int(request.form.get("limit") or 5)
        

        logging.info(f"Searching {specialty} near {location}")

        if specialty or location:
            # ✅ Search Internal Verified Doctors
            internal_doctors = list(db.doctors.find({
                "specialization": {"$regex": specialty or "", "$options": "i"}
            }))
            # ✅ Search External Facilities
            doctor_list = search_doctors(specialty or "doctor", location or "near me")
        else:
            # ✅ Show all internal doctors by default
            internal_doctors = list(db.doctors.find())
            doctor_list = [] # Don't search external if no input

        for d in internal_doctors: d['id'] = str(d['_id'])

        # ✅ Build map (if search performed)
        map_html = build_doctor_map(doctor_list) if doctor_list else None

        return render_template(
            "doctor.html",
            doctors   = doctor_list,
            internal_doctors = internal_doctors,
            map_html  = map_html,
            specialty = specialty,
            location  = location,
            count = len(doctor_list) + len(internal_doctors),
            success = True if (specialty or location) else False
        )

    except Exception as e:
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
            "chief_complaint": complaint,
            "status": "Requested",
            "priority": "Normal",
            "queue_type": "today",
            "consultation_date": apt_date,
            "vitals": {"bp": "-", "temp": "-", "pulse": "-", "spo2": "-", "weight": "-"},
            "created_at": datetime.utcnow()
        }
        db.consultations.insert_one(new_consult)

        # Create notification for doctor
        notification = {
            "doctor_id": doctor_id,
            "message": f"New appointment booked by {current_user.name} for {apt_date} at {apt_time}",
            "type": "appointment",
            "is_read": False,
            "created_at": datetime.utcnow()
        }
        db.doctor_notifications.insert_one(notification)

        flash(f"Appointment booked with {doctor['name']} for {apt_date} at {apt_time}")
        return redirect(url_for('dashboard'))

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

    return render_template('dashboard.html', 
                           user=current_user, 
                           records=records, 
                           symptom_history=symptom_history, 
                           contacts=contacts, 
                           appointments=appointments,
                           notifications=patient_notifications,
                           unread_count=patient_unread_count)

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

# ── RUN ────────────────────────────────────────
if __name__ == "__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(
        host  = "0.0.0.0",
        port  = port,
        debug = False
    )
