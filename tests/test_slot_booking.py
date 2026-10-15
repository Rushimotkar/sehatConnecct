import sys
import unittest
from unittest.mock import MagicMock

# Mock database setup before importing the app
sys.modules['pymongo'] = MagicMock()

from app import parse_time_to_minutes, has_slot_conflict


class SlotBookingTestCase(unittest.TestCase):
    def test_parse_time_to_minutes_handles_am_pm(self):
        self.assertEqual(parse_time_to_minutes('09:00 AM'), 540)
        self.assertEqual(parse_time_to_minutes('12:30 PM'), 750)
        self.assertEqual(parse_time_to_minutes('09:00'), 540)

    def test_has_slot_conflict_detects_overlapping_slots(self):
        mock_db = MagicMock()
        mock_db.consultations.find.return_value = [
            {
                'doctor_id': 'doc-1',
                'consultation_date': '2026-10-12',
                'status': 'Waiting',
                'start_time': '09:00 AM',
                'end_time': '10:00 AM'
            },
            {
                'doctor_id': 'doc-2',
                'consultation_date': '2026-10-12',
                'status': 'Waiting',
                'start_time': '09:00 AM',
                'end_time': '10:00 AM'
            }
        ]

        self.assertTrue(has_slot_conflict('doc-1', '2026-10-12', '09:30 AM', db_conn=mock_db))
        self.assertFalse(has_slot_conflict('doc-1', '2026-10-12', '10:00 AM', db_conn=mock_db))
        self.assertFalse(has_slot_conflict('doc-2', '2026-10-12', '09:30 AM', db_conn=mock_db))


if __name__ == '__main__':
    unittest.main()
