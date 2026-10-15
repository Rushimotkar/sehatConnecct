import app


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


def test_build_doctor_admin_directory_filters_and_sorts(monkeypatch):
    fake_rows = [
        {"name": "Dr. Beta", "city": "Pune", "specialization": "Cardiologist", "rating": 3.5},
        {"name": "Dr. Alpha", "city": "Delhi", "specialization": "Neurologist", "rating": 4.8},
        {"name": "Dr. Gamma", "city": "Mumbai", "specialization": "Dermatologist", "rating": 4.4},
    ]

    monkeypatch.setattr(app.db.doctors, "find", lambda query: FakeCursor(fake_rows))

    rows = app.build_doctor_admin_directory(search='alpha', sort_by='rating_desc')
    assert len(rows) == 1
    assert rows[0]["name"] == "Dr. Alpha"

    rows = app.build_doctor_admin_directory(sort_by='city_asc')
    assert [r["city"] for r in rows] == ["Delhi", "Mumbai", "Pune"]
