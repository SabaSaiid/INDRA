"""
INDRA Platform — Indian Geospatial Resolver & Geocoding Normalizer

Validates, sanitizes, and normalizes geographical coordinates for raw reports
and verified events within Indian territorial boundaries.
Prevents coordinate inversion (lat/lng swapped) and auto-resolves coordinates
for incoming reports with missing GPS.
"""

import math
import re
from typing import Optional, Tuple, Dict, Any

# Indian sovereign territory geographic bounding box
INDIA_MIN_LAT = 6.5
INDIA_MAX_LAT = 37.6
INDIA_MIN_LNG = 68.0
INDIA_MAX_LNG = 97.5

# High-precision gazetteer of Indian state capitals and disaster nodes
INDIAN_GAZETTEER: Dict[str, Dict[str, Any]] = {
    "patna": {"city": "Patna", "state": "Bihar", "lat": 25.6093, "lng": 85.1376},
    "gaya": {"city": "Gaya", "state": "Bihar", "lat": 24.7914, "lng": 85.0002},
    "kolkata": {"city": "Kolkata", "state": "West Bengal", "lat": 22.5726, "lng": 88.3639},
    "siliguri": {"city": "Siliguri", "state": "West Bengal", "lat": 26.7271, "lng": 88.3953},
    "darjeeling": {"city": "Darjeeling", "state": "West Bengal", "lat": 27.0410, "lng": 88.2663},
    "bhubaneswar": {"city": "Bhubaneswar", "state": "Odisha", "lat": 20.2961, "lng": 85.8245},
    "puri": {"city": "Puri", "state": "Odisha", "lat": 19.8135, "lng": 85.8312},
    "cuttack": {"city": "Cuttack", "state": "Odisha", "lat": 20.4625, "lng": 85.8828},
    "ranchi": {"city": "Ranchi", "state": "Jharkhand", "lat": 23.3441, "lng": 85.3096},
    "mumbai": {"city": "Mumbai", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    "pune": {"city": "Pune", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567},
    "nagpur": {"city": "Nagpur", "state": "Maharashtra", "lat": 21.1458, "lng": 79.0882},
    "nashik": {"city": "Nashik", "state": "Maharashtra", "lat": 19.9975, "lng": 73.7898},
    "ahmedabad": {"city": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lng": 72.5714},
    "surat": {"city": "Surat", "state": "Gujarat", "lat": 21.1702, "lng": 72.8311},
    "vadodara": {"city": "Vadodara", "state": "Gujarat", "lat": 22.3072, "lng": 73.1812},
    "panaji": {"city": "Panaji", "state": "Goa", "lat": 15.4909, "lng": 73.8278},
    "new delhi": {"city": "New Delhi", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "delhi": {"city": "New Delhi", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "lucknow": {"city": "Lucknow", "state": "Uttar Pradesh", "lat": 26.8467, "lng": 80.9462},
    "varanasi": {"city": "Varanasi", "state": "Uttar Pradesh", "lat": 25.3176, "lng": 82.9739},
    "kanpur": {"city": "Kanpur", "state": "Uttar Pradesh", "lat": 26.4499, "lng": 80.3319},
    "dehradun": {"city": "Dehradun", "state": "Uttarakhand", "lat": 30.3165, "lng": 78.0322},
    "shimla": {"city": "Shimla", "state": "Himachal Pradesh", "lat": 31.1048, "lng": 77.1734},
    "manali": {"city": "Manali", "state": "Himachal Pradesh", "lat": 32.2432, "lng": 77.1892},
    "srinagar": {"city": "Srinagar", "state": "Jammu and Kashmir", "lat": 34.0837, "lng": 74.7973},
    "jammu": {"city": "Jammu", "state": "Jammu and Kashmir", "lat": 32.7266, "lng": 74.8570},
    "chandigarh": {"city": "Chandigarh", "state": "Punjab", "lat": 30.7333, "lng": 76.7794},
    "amritsar": {"city": "Amritsar", "state": "Punjab", "lat": 31.6340, "lng": 74.8723},
    "jaipur": {"city": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lng": 75.7873},
    "jodhpur": {"city": "Jodhpur", "state": "Rajasthan", "lat": 26.2389, "lng": 73.0243},
    "barmer": {"city": "Barmer", "state": "Rajasthan", "lat": 25.7521, "lng": 71.3967},
    "chennai": {"city": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    "coimbatore": {"city": "Coimbatore", "state": "Tamil Nadu", "lat": 11.0168, "lng": 76.9558},
    "bengaluru": {"city": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "bangalore": {"city": "Bengaluru", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "mangalore": {"city": "Mangalore", "state": "Karnataka", "lat": 12.9141, "lng": 74.8560},
    "hyderabad": {"city": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    "visakhapatnam": {"city": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lng": 83.2185},
    "vizag": {"city": "Visakhapatnam", "state": "Andhra Pradesh", "lat": 17.6868, "lng": 83.2185},
    "vijayawada": {"city": "Vijayawada", "state": "Andhra Pradesh", "lat": 16.5062, "lng": 80.6480},
    "kochi": {"city": "Kochi", "state": "Kerala", "lat": 9.9312, "lng": 76.2673},
    "thiruvananthapuram": {"city": "Thiruvananthapuram", "state": "Kerala", "lat": 8.5241, "lng": 76.9366},
    "wayanad": {"city": "Wayanad", "state": "Kerala", "lat": 11.6854, "lng": 76.1320},
    "idukki": {"city": "Idukki", "state": "Kerala", "lat": 9.8494, "lng": 76.9804},
    "guwahati": {"city": "Guwahati", "state": "Assam", "lat": 26.1445, "lng": 91.7362},
    "silchar": {"city": "Silchar", "state": "Assam", "lat": 24.8333, "lng": 92.7789},
    "shillong": {"city": "Shillong", "state": "Meghalaya", "lat": 25.5788, "lng": 91.8933},
    "imphal": {"city": "Imphal", "state": "Manipur", "lat": 24.8170, "lng": 93.9368},
    "agartala": {"city": "Agartala", "state": "Tripura", "lat": 23.8315, "lng": 91.2868},
    "bhopal": {"city": "Bhopal", "state": "Madhya Pradesh", "lat": 23.2599, "lng": 77.4126},
    "indore": {"city": "Indore", "state": "Madhya Pradesh", "lat": 22.7196, "lng": 75.8577},
    "raipur": {"city": "Raipur", "state": "Chhattisgarh", "lat": 21.2514, "lng": 81.6296},
    "port blair": {"city": "Port Blair", "state": "Andaman and Nicobar", "lat": 11.6234, "lng": 92.7265},
}


class OutOfIndiaBoundsError(ValueError):
    """Coordinates were supplied but fall outside India's bounding box."""

    def __init__(self, lat: float, lng: float):
        self.lat = lat
        self.lng = lng
        super().__init__(
            f"Coordinates ({lat}, {lng}) are outside India's bounds "
            f"(lat {INDIA_MIN_LAT}–{INDIA_MAX_LAT}, lng {INDIA_MIN_LNG}–{INDIA_MAX_LNG})"
        )


def is_within_india(lat: float, lng: float) -> bool:
    """Check if lat/lng is within Indian boundaries."""
    return (
        INDIA_MIN_LAT <= lat <= INDIA_MAX_LAT and
        INDIA_MIN_LNG <= lng <= INDIA_MAX_LNG
    )


def is_inverted(lat: float, lng: float) -> bool:
    """Detect inverted coordinates (lat/lng swapped)."""
    return (
        INDIA_MIN_LNG <= lat <= INDIA_MAX_LNG and
        INDIA_MIN_LAT <= lng <= INDIA_MAX_LAT
    )


def sanitize_coordinates(
    lat: Optional[float],
    lng: Optional[float],
    text_hint: Optional[str] = None,
    city_hint: Optional[str] = None,
    snap_out_of_bounds: bool = False,
) -> Tuple[float, float, str, str]:
    """
    Sanitizes coordinates, auto-corrects inverted pairs, or falls back to
    Gazetteer lookup from text/city hints.

    Coordinates that are present but outside India raise OutOfIndiaBoundsError
    unless `snap_out_of_bounds` is True. Snapping them to a gazetteer match or
    the (22, 82) national centroid used to be unconditional, and with
    DBSCAN_MIN_SAMPLES=2 any two junk or GPS-glitched reports then clustered at
    that one point and manufactured a verified event in the middle of India.

    Missing coordinates still resolve from the hints — there is nothing to
    reject, only a location to look up.

    Returns: (lat, lng, city, state)
    """
    if lat is not None and lng is not None:
        try:
            f_lat = float(lat)
            f_lng = float(lng)
        except (ValueError, TypeError):
            f_lat = f_lng = None

        if f_lat is not None and f_lng is not None:
            # A swapped pair is a recoverable client bug, not junk: the swap
            # lands inside India, so it is corrected rather than rejected.
            if is_inverted(f_lat, f_lng):
                f_lat, f_lng = f_lng, f_lat

            if is_within_india(f_lat, f_lng):
                return f_lat, f_lng, city_hint or "India Node", ""

            if not snap_out_of_bounds:
                raise OutOfIndiaBoundsError(f_lat, f_lng)

    # Resolve from text or city hint
    search_str = f"{city_hint or ''} {text_hint or ''}".lower()
    for key, loc in INDIAN_GAZETTEER.items():
        if re.search(rf"\b{re.escape(key)}\b", search_str) or key in search_str:
            return loc["lat"], loc["lng"], loc["city"], loc["state"]

    # National command centroid fallback
    return 22.0, 82.0, "National Command Grid", "India"
