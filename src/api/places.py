import requests
import sys
from src.logger import logging
from src.exception import CustomException


def search_doctors(specialty: str, location: str, limit: int = 100):
    """
    Search doctors using OpenStreetMap Nominatim API
    """
    try:
        url = "https://nominatim.openstreetmap.org/search"

        query = f"{specialty} doctor in {location}"

        params = {
            "q": query,
            "format": "json",
            "limit": limit
        }

        headers = {
            "User-Agent": "doctor-finder-app"   # Required!
        }

        response = requests.get(url, params=params, headers=headers)

        if response.status_code != 200:
            logging.error(f"API Error: {response.text}")
            return []

        data = response.json()

        doctors = []

        for place in data:
            doctor_data = {
                "name": place.get("display_name", "N/A").split(",")[0],
                "full_address": place.get("display_name", "N/A"),
                "latitude": place.get("lat"),
                "longitude": place.get("lon"),
                "type": place.get("type"),
                "osm_type": place.get("osm_type")
            }

            doctors.append(doctor_data)

        logging.info(f"Found {len(doctors)} doctors using OpenStreetMap")
        return doctors

    except Exception as e:
        raise CustomException(e, sys)


# 🔥 Example usage
if __name__ == "__main__":
    try:
        doctors = search_doctors("cardiologist", "Aurangabad", limit=5)

        for doc in doctors:
            print("=" * 50)
            print(f"Name        : {doc['name']}")
            print(f"Address     : {doc['full_address']}")
            print(f"Latitude    : {doc['latitude']}")
            print(f"Longitude   : {doc['longitude']}")
            print(f"Type        : {doc['type']}")
            print(f"OSM Type    : {doc['osm_type']}")

    except Exception as e:
        logging.error(e)