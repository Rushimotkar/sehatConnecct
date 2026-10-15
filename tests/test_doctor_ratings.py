import sys
import unittest
from unittest.mock import MagicMock, patch
from bson.objectid import ObjectId
from datetime import datetime

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
from app import app
import app as app_module
app_module.db = mock_db

class DoctorRatingsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        # Reset DB mocks
        mock_db.reset_mock()
        mock_db.health_tips.count_documents.return_value = 15

    def tearDown(self):
        self.app_context.pop()

    def test_recalculate_doctor_rating_helper(self):
        """Test recalculating doctor rating average and total reviews based on review documents."""
        doctor_id = "60c72b2f9b1d8e1f5c8b1234"
        
        # 1. Setup mock reviews in database
        mock_db.reviews.find.return_value = [
            {"rating": 5, "comment": "Excellent!"},
            {"rating": 4, "comment": "Good doctor"},
            {"rating": 3, "comment": "Average service"}
        ]
        
        # 2. Trigger rating recalculation helper
        from app import recalculate_doctor_rating
        avg_rating, total_reviews = recalculate_doctor_rating(doctor_id)
        
        # Average of 5, 4, 3 is 4.0
        self.assertEqual(avg_rating, 4.0)
        self.assertEqual(total_reviews, 3)
        
        # 3. Assert correct db update was executed
        mock_db.doctors.update_one.assert_called_once_with(
            {"_id": ObjectId(doctor_id)},
            {"$set": {
                "rating": 4.0,
                "total_reviews": 3
            }}
        )

    @patch('app.search_doctors')
    def test_advanced_doctor_filters_and_sorting(self, mock_search_docs):
        """Test search filters for ratings, fees, availability, and fee sorting."""
        mock_search_docs.return_value = []
        
        # 1. Setup fake doctor documents in DB
        doctor_1 = {
            "_id": ObjectId("60c72b2f9b1d8e1f5c8b4567"),
            "name": "Dr. Cheap Great",
            "specialization": "Cardiologist",
            "city": "Mumbai",
            "rating": 4.8,
            "consultation_fee": 300,
            "is_active": True
        }
        doctor_2 = {
            "_id": ObjectId("60c72b2f9b1d8e1f5c8b4568"),
            "name": "Dr. Expensive Average",
            "specialization": "Cardiologist",
            "city": "Mumbai",
            "rating": 3.8,
            "consultation_fee": 900,
            "is_active": True
        }
        mock_db.doctors.find.return_value = [doctor_1, doctor_2]
        
        # Mock consultation query return (no consultations booked today, meaning slots are free)
        mock_db.consultations.find.return_value = []
        
        # 2. Query with rating filter min_rating=4.0 and max_fee=500
        response = self.app.get('/doctors?min_rating=4.0&max_fee=500&sort_by=fee_asc')
        
        self.assertEqual(response.status_code, 200)
        
        # 3. Verify query arguments built inside MongoDB find call
        called_args = mock_db.doctors.find.call_args[0][0]
        self.assertEqual(called_args["is_active"], True)
        self.assertEqual(called_args["rating"]["$gte"], 4.0)
        self.assertEqual(called_args["consultation_fee"]["$lte"], 500)

    @patch('app.search_doctors')
    def test_ajax_partial_render_detection(self, mock_search_docs):
        """Verify AJAX requests return only partial doctor cards instead of full base pages."""
        mock_search_docs.return_value = []
        mock_db.doctors.find.return_value = []
        
        # Trigger AJAX call with ajax=1 param
        response = self.app.get('/doctors?ajax=1')
        self.assertEqual(response.status_code, 200)
        
        # The partial template should not contain the header block/Find Specialists title
        html_content = response.data.decode('utf-8')
        self.assertNotIn("Find & Book a <span", html_content)
        self.assertIn("No Matching Doctors Found", html_content)

if __name__ == '__main__':
    unittest.main()
