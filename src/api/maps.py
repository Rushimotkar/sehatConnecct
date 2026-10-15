import folium
from src.logger import logging


def build_doctor_map(doctors: list) -> str:
    """
    Build folium map with doctor markers (Nominatim version)
    Returns HTML string
    """

    if not doctors:
        return "<p>No doctors found nearby.</p>"

    # Convert lat/lon to float (important!)
    for d in doctors:
        d["latitude"] = float(d["latitude"])
        d["longitude"] = float(d["longitude"])

    # Center map
    avg_lat = sum(d["latitude"] for d in doctors) / len(doctors)
    avg_lon = sum(d["longitude"] for d in doctors) / len(doctors)

    m = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=13,
        tiles="CartoDB positron"
    )

    colors = ["blue", "red", "green", "purple", "orange"]

    for i, doc in enumerate(doctors):

        # Google Maps link using lat/lon
        maps_url = f"https://www.google.com/maps?q={doc['latitude']},{doc['longitude']}"

        popup_html = f"""
        <div style="font-family:sans-serif;min-width:220px">
            <h4 style="color:#1A73E8">👨‍⚕️ {doc['name']}</h4>
            <p>📍 {doc['full_address']}</p>
            <p>🗂 Type: {doc['type']}</p>
            <a href="{maps_url}" target="_blank" style="color:#1A73E8">
                Open in Google Maps →
            </a>
        </div>
        """

        folium.Marker(
            location=[doc["latitude"], doc["longitude"]],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=doc["name"],
            icon=folium.Icon(
                color=colors[i % len(colors)],
                icon="plus-sign",
                prefix="glyphicon"
            )
        ).add_to(m)

    logging.info("Map built successfully ✅")
    return m._repr_html_()