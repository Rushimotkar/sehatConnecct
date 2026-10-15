"""
tests/test_jitsi_video.py — Tests for Jitsi Meet Video Consultation feature.
"""
import unittest
from bson.objectid import ObjectId
from datetime import datetime
from app import app, db

class JitsiVideoTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.secret_key = 'test_secret_key'
        self.app = app.test_client()

        # Create test patient
        self.test_user_id = str(ObjectId())
        self.test_user = {
            '_id': ObjectId(self.test_user_id),
            'name': 'Alice Patient',
            'email': 'alice.patient@test.com',
            'password': 'hashed_password'
        }
        db.users.update_one({'_id': ObjectId(self.test_user_id)}, {'$set': self.test_user}, upsert=True)

        # Create test doctor
        self.test_doctor_id = str(ObjectId())
        self.test_doctor = {
            '_id': ObjectId(self.test_doctor_id),
            'name': 'Dr. Robert House',
            'email': 'robert.house@test.com',
            'specialization': 'Diagnostician',
            'is_active': True
        }
        db.doctors.update_one({'_id': ObjectId(self.test_doctor_id)}, {'$set': self.test_doctor}, upsert=True)

        # Create test consultation
        self.test_apt_id = str(ObjectId())
        self.test_apt = {
            '_id': ObjectId(self.test_apt_id),
            'doctor_id': self.test_doctor_id,
            'user_id': self.test_user_id,
            'patient_name': 'Alice Patient',
            'patient_age': 29,
            'patient_gender': 'Female',
            'chief_complaint': 'Chronic Fatigue',
            'status': 'Waiting',
            'consultation_date': '2026-08-01',
            'created_at': datetime.utcnow()
        }
        db.consultations.update_one({'_id': ObjectId(self.test_apt_id)}, {'$set': self.test_apt}, upsert=True)

    def tearDown(self):
        db.users.delete_one({'_id': ObjectId(self.test_user_id)})
        db.doctors.delete_one({'_id': ObjectId(self.test_doctor_id)})
        db.consultations.delete_one({'_id': ObjectId(self.test_apt_id)})

    def test_1_unauthenticated_access_denied(self):
        """Test unauthenticated user accessing video consultation redirects to login."""
        response = self.app.get(f'/consultation/{self.test_apt_id}/video')
        self.assertEqual(response.status_code, 302)

    def test_2_doctor_video_session(self):
        """Test doctor accessing video consultation."""
        with self.app.session_transaction() as sess:
            sess['doctor_id'] = self.test_doctor_id
            sess['doctor_name'] = 'Dr. Robert House'

        response = self.app.get(f'/consultation/{self.test_apt_id}/video')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'https://meet.jit.si/external_api.js', response.data)
        self.assertIn(b'Medico_Telehealth_', response.data)
        self.assertIn(b'Dr. Robert House', response.data)
        self.assertIn(b'DOCTOR VIEW', response.data)

    def test_3_patient_video_session(self):
        """Test patient accessing video consultation."""
        with self.app.session_transaction() as sess:
            sess['_user_id'] = self.test_user_id

        response = self.app.get(f'/consultation/{self.test_apt_id}/video')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'https://meet.jit.si/external_api.js', response.data)
        self.assertIn(b'Alice Patient', response.data)

if __name__ == '__main__':
    unittest.main()
