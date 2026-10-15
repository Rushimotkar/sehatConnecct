"""
tests/test_eprescription.py — Comprehensive tests for the E-Prescription module.
"""
import unittest
import json
import io
from bson.objectid import ObjectId
from datetime import datetime

# Import flask app and db
from app import app, db

class EPrescriptionTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.secret_key = 'test_secret_key'
        self.app = app.test_client()

        # Setup mock test data in MongoDB
        self.test_user_id = str(ObjectId())
        self.test_user = {
            '_id': ObjectId(self.test_user_id),
            'name': 'John Patient',
            'email': 'john.patient@test.com',
            'password': 'hashed_password'
        }
        db.users.update_one({'_id': ObjectId(self.test_user_id)}, {'$set': self.test_user}, upsert=True)

        self.test_doctor_id = str(ObjectId())
        self.test_doctor = {
            '_id': ObjectId(self.test_doctor_id),
            'name': 'Dr. Sarah Connor',
            'email': 'sarah.connor@test.com',
            'specialization': 'Cardiologist',
            'registration_number': 'REG-TEST-9988',
            'is_active': True
        }
        db.doctors.update_one({'_id': ObjectId(self.test_doctor_id)}, {'$set': self.test_doctor}, upsert=True)

        self.test_apt_id = str(ObjectId())
        self.test_apt = {
            '_id': ObjectId(self.test_apt_id),
            'doctor_id': self.test_doctor_id,
            'user_id': self.test_user_id,
            'patient_name': 'John Patient',
            'patient_age': 35,
            'patient_gender': 'Male',
            'chief_complaint': 'High Blood Pressure',
            'status': 'In Progress',
            'consultation_date': '2026-08-01',
            'created_at': datetime.utcnow()
        }
        db.consultations.update_one({'_id': ObjectId(self.test_apt_id)}, {'$set': self.test_apt}, upsert=True)

        # Seed sample drugs if missing
        db.drugs.update_one(
            {'name': 'Paracetamol'},
            {'$set': {'name': 'Paracetamol', 'generic_name': 'Acetaminophen', 'common_dosages': '500mg, 650mg', 'dosage_form': 'tablet'}},
            upsert=True
        )
        db.drugs.update_one(
            {'name': 'Amoxicillin'},
            {'$set': {'name': 'Amoxicillin', 'generic_name': 'Amoxicillin Trihydrate', 'common_dosages': '250mg, 500mg', 'dosage_form': 'capsule'}},
            upsert=True
        )

    def tearDown(self):
        # Cleanup test data
        db.users.delete_one({'_id': ObjectId(self.test_user_id)})
        db.doctors.delete_one({'_id': ObjectId(self.test_doctor_id)})
        db.consultations.delete_one({'_id': ObjectId(self.test_apt_id)})
        db.prescriptions.delete_many({'appointment_id': self.test_apt_id})

    def test_1_drug_autocomplete_api(self):
        """Test /api/drugs/search?q= search endpoint."""
        response = self.app.get('/api/drugs/search?q=Paracetamol')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode('utf-8'))
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]['name'], 'Paracetamol')

    def test_2_prescribe_get_route(self):
        """Test GET /appointment/<id>/prescribe."""
        with self.app.session_transaction() as sess:
            sess['doctor_id'] = self.test_doctor_id

        response = self.app.get(f'/appointment/{self.test_apt_id}/prescribe')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'John Patient', response.data)
        self.assertIn(b'Dr. Sarah Connor', response.data)

    def test_3_prescribe_post_draft_and_finalize(self):
        """Test POST /appointment/<id>/prescribe for draft save and finalization locking."""
        with self.app.session_transaction() as sess:
            sess['doctor_id'] = self.test_doctor_id

        # 1. Save Draft
        post_data = {
            'action': 'save_draft',
            'notes': 'Rest well and drink water.',
            'drug_name[]': ['Paracetamol', 'Amoxicillin'],
            'dosage[]': ['650mg', '500mg'],
            'frequency[]': ['1-0-1', '1-1-1'],
            'duration[]': ['5 days', '7 days'],
            'instructions[]': ['After food', 'After food']
        }
        res1 = self.app.post(f'/appointment/{self.test_apt_id}/prescribe', data=post_data, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        presc = db.prescriptions.find_one({'appointment_id': self.test_apt_id})
        self.assertIsNotNone(presc)
        self.assertEqual(presc['status'], 'draft')
        self.assertEqual(len(presc['items']), 2)

        # 2. Finalize Prescription
        post_data['action'] = 'finalize'
        res2 = self.app.post(f'/appointment/{self.test_apt_id}/prescribe', data=post_data, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        presc_final = db.prescriptions.find_one({'appointment_id': self.test_apt_id})
        self.assertEqual(presc_final['status'], 'finalized')

        # 3. Verify locked state prevents edits
        post_data['notes'] = 'Attempting to edit finalized prescription'
        res3 = self.app.post(f'/appointment/{self.test_apt_id}/prescribe', data=post_data, follow_redirects=True)
        self.assertIn(b'already been finalized and cannot be modified', res3.data)

    def test_4_pdf_generation(self):
        """Test /prescription/<id>/pdf route generating ReportLab PDF."""
        # Create finalized prescription record
        presc_doc = {
            'appointment_id': self.test_apt_id,
            'doctor_id': self.test_doctor_id,
            'patient_id': self.test_user_id,
            'doctor_name': 'Dr. Sarah Connor',
            'doctor_reg_no': 'REG-TEST-9988',
            'patient_name': 'John Patient',
            'patient_age': 35,
            'notes': 'Take medicines on time.',
            'status': 'finalized',
            'items': [
                {'drug_name': 'Paracetamol', 'dosage': '650mg', 'frequency': '1-0-1', 'duration': '5 days', 'instructions': 'After food'}
            ],
            'created_at': datetime.utcnow()
        }
        res = db.prescriptions.insert_one(presc_doc)
        presc_id = str(res.inserted_id)

        response = self.app.get(f'/prescription/{presc_id}/pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertTrue(response.data.startswith(b'%PDF'))

    def test_5_shareable_link_and_public_access(self):
        """Test /prescription/<id>/share and /prescription/shared/<token> routes."""
        presc_doc = {
            'appointment_id': self.test_apt_id,
            'doctor_id': self.test_doctor_id,
            'patient_id': self.test_user_id,
            'doctor_name': 'Dr. Sarah Connor',
            'patient_name': 'John Patient',
            'patient_age': 35,
            'status': 'finalized',
            'items': [{'drug_name': 'Paracetamol', 'dosage': '500mg', 'frequency': '1-0-1', 'duration': '3 days'}],
            'created_at': datetime.utcnow()
        }
        res = db.prescriptions.insert_one(presc_doc)
        presc_id = str(res.inserted_id)

        # Generate share URL
        share_res = self.app.get(f'/prescription/{presc_id}/share')
        self.assertEqual(share_res.status_code, 200)
        data = json.loads(share_res.data.decode('utf-8'))
        self.assertIn('token', data)

        token = data['token']

        # Access public shared view without login
        public_res = self.app.get(f'/prescription/shared/{token}')
        self.assertEqual(public_res.status_code, 200)
        self.assertIn(b'Verified Digital Prescription', public_res.data)
        self.assertIn(b'Paracetamol', public_res.data)

        # Download PDF from public shared link
        public_pdf_res = self.app.get(f'/prescription/shared/{token}/pdf')
        self.assertEqual(public_pdf_res.status_code, 200)
        self.assertEqual(public_pdf_res.mimetype, 'application/pdf')
        self.assertTrue(public_pdf_res.data.startswith(b'%PDF'))

if __name__ == '__main__':
    unittest.main()
