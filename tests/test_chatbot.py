import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from bson.objectid import ObjectId

# ── WORKAROUND FOR WERKZEUG VERSION CONFLICT ──────────────────
# Newer Werkzeug versions removed __version__ which causes older Flask test clients to crash.
import werkzeug
if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = "3.0.0"

# ── MOCK PYMONGO BEFORE APP IMPORT ─────────────────────────────
mock_pymongo = MagicMock()
sys.modules['pymongo'] = mock_pymongo

mock_client = MagicMock()
mock_db = MagicMock()
mock_client.__getitem__.return_value = mock_db
mock_pymongo.MongoClient.return_value = mock_client

mock_db.health_tips.count_documents.return_value = 15

sys.modules['dns'] = MagicMock()
sys.modules['dns.resolver'] = MagicMock()

# Now import app
from app import app, EMERGENCY_KEYWORDS, SYMPTOM_SPECIALTY_MAP, pending_bookings
import app as app_module

app_module.db = mock_db

class ChatbotTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        # Reset mocks and clear state
        mock_db.reset_mock()
        mock_db.health_tips.count_documents.return_value = 15
        pending_bookings.clear()

    def tearDown(self):
        self.app_context.pop()
        pending_bookings.clear()

    @patch('app.current_user')
    def test_unauthenticated_user(self, mock_current_user):
        """Test that unauthenticated users are prompted to log in."""
        mock_current_user.is_authenticated = False
        
        response = self.app.post('/chatbot', 
                                 data=json.dumps({"message": "book an appointment for fever"}),
                                 content_type='application/json')
        
        data = json.loads(response.data.decode('utf-8'))
        self.assertTrue(data['success'])
        self.assertIn("log in", data['reply'].lower())

    @patch('app.current_user')
    def test_emergency_red_flag(self, mock_current_user):
        """Test that emergency keywords block booking and prompt urgent care."""
        mock_current_user.is_authenticated = True
        mock_current_user.id = "test_user_123"
        
        for keyword in EMERGENCY_KEYWORDS:
            response = self.app.post('/chatbot', 
                                     data=json.dumps({"message": f"Help me book for my {keyword}"}),
                                     content_type='application/json')
            
            data = json.loads(response.data.decode('utf-8'))
            self.assertTrue(data['success'])
            self.assertIn("critical medical alert", data['reply'].lower())

    @patch('app.current_user')
    def test_lookup_table_booking_flow(self, mock_current_user):
        """Test the standard booking lookup, doctor mapping, pending state, and confirmation."""
        mock_current_user.is_authenticated = True
        mock_current_user.id = "user_abc"
        mock_current_user.name = "John Doe"
        mock_current_user.email = "john@example.com"
        
        # Mock Doctor DB lookup response
        mock_doctor = {
            "_id": ObjectId("60c72b2f9b1d8e1f5c8b4567"),
            "name": "Dr. Aisha Khan",
            "specialization": "Cardiologist",
            "is_active": True
        }
        mock_db.doctors.find_one.return_value = mock_doctor
        
        # Trigger booking request for a symptom in the hardcoded map
        response = self.app.post('/chatbot', 
                                 data=json.dumps({"message": "book an appointment for palpitations"}),
                                 content_type='application/json')
        
        data = json.loads(response.data.decode('utf-8'))
        self.assertTrue(data['success'])
        self.assertIn("Dr. Aisha Khan", data['reply'])
        self.assertIn("Cardiologist", data['reply'])
        
        # Verify state is saved in pending_bookings
        self.assertIn("user_abc", pending_bookings)
        self.assertEqual(pending_bookings["user_abc"]["doctor_name"], "Dr. Aisha Khan")
        
        # Confirm booking
        response_confirm = self.app.post('/chatbot',
                                         data=json.dumps({"message": "yes, please confirm"}),
                                         content_type='application/json')
        
        data_confirm = json.loads(response_confirm.data.decode('utf-8'))
        self.assertTrue(data_confirm['success'])
        self.assertIn("scheduled", data_confirm['reply'].lower())
        
        # Check that DB insertions were triggered
        self.assertTrue(mock_db.consultations.insert_one.called)
        self.assertTrue(mock_db.doctor_notifications.insert_one.called)
        self.assertTrue(mock_db.patient_notifications.insert_one.called)
        
        # Verify state was cleaned up
        self.assertNotIn("user_abc", pending_bookings)

if __name__ == '__main__':
    unittest.main()
