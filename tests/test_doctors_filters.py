import sys
import unittest
from unittest.mock import MagicMock, patch
from bson.objectid import ObjectId

# ── MOCK PYMONGO BEFORE APP IMPORT ─────────────────────────────
mock_pymongo = MagicMock()
sys.modules['pymongo'] = mock_pymongo

mock_client = MagicMock()
mock_db = MagicMock()
mock_client.__getitem__.return_value = mock_db
mock_pymongo.MongoClient.return_value = mock_client

mock_db.health_tips.count_documents.return_value = 15

# Workaround for Werkzeug
import werkzeug
if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = "3.0.0"

# Now import app
from app import app, SPECIALTY_ICONS
import app as app_module
app_module.db = mock_db

class DoctorFiltersTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        # Reset mock database calls
        mock_db.reset_mock()
        mock_db.health_tips.count_documents.return_value = 15
        
        # Mock values for distinct options
        mock_db.doctors.distinct.side_effect = lambda field: {
            "specialization": ["Cardiologist", "General Physician", "Dermatologist"],
            "city": ["Mumbai", "Pune", "Delhi"],
            "hospital_name": ["Apollo Hospital", "Ruby Hall Clinic"]
        }.get(field, [])

    def tearDown(self):
        self.app_context.pop()

    @patch('app.search_doctors')
    def test_doctors_combined_filters(self, mock_search_docs):
        """Test search filters for specialty, city, and hospital combinability."""
        mock_search_docs.return_value = []
        
        # 1. Setup mock query return for find()
        mock_doctor = {
            "_id": ObjectId("60c72b2f9b1d8e1f5c8b4567"),
            "name": "Dr. Aisha Khan",
            "specialization": "Cardiologist",
            "city": "Mumbai",
            "hospital_name": "Apollo Hospital",
            "specialty_icon": "/static/icons/cardiology.svg",
            "is_active": True
        }
        mock_db.doctors.find.return_value = [mock_doctor]
        
        # 2. Trigger request with combined filters
        response = self.app.get('/doctors?specialty=Cardiologist&city=Mumbai&hospital=Apollo')
        
        self.assertEqual(response.status_code, 200)
        
        # 3. Assert correct filter query was built
        called_args = mock_db.doctors.find.call_args[0][0]
        self.assertEqual(called_args["is_active"], True)
        self.assertIn("specialization", called_args)
        self.assertIn("city", called_args)
        self.assertIn("hospital_name", called_args)
        
        # Check specific regex matching values
        self.assertEqual(called_args["specialization"]["$regex"], "Cardiologist")
        self.assertEqual(called_args["city"]["$regex"], "Mumbai")
        self.assertEqual(called_args["hospital_name"]["$regex"], "Apollo")

    def test_specialty_icons_autofill_mapping(self):
        """Verify that SPECIALTY_ICONS covers all requested specialties."""
        required_specs = [
            "General Physician", "Cardiologist", "Dermatologist", 
            "Pediatrician", "Orthopedic", "Gynecologist", 
            "ENT Specialist", "Psychiatrist", "Dentist", "Ophthalmologist"
        ]
        for spec in required_specs:
            self.assertIn(spec, SPECIALTY_ICONS)
            self.assertTrue(SPECIALTY_ICONS[spec].endswith('.svg'))

if __name__ == '__main__':
    unittest.main()
