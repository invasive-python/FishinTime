from urllib import response
#from services.weather_service import get_grid_data

import re
import requests
import os
#import json

def get_moon_phase_data(date, coords):
    base_url = "https://aa.usno.navy.mil/api/rstt/oneday"
    temp_coords = str(coords)
    final_coords = re.sub('[()]','',temp_coords)
    params = {
        'date': date,
        'coords': final_coords
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def get_moon_phase_from_city_data(city_data, date):
    lat = city_data["latitude"]
    lon = city_data["longitude"]
    coords = lat, lon

    moon_phase_data = get_moon_phase_data(date, coords)
    if moon_phase_data:
        properties = moon_phase_data.get('properties', {})
        return properties
    else:
        print("Failed to retrieve moon phase data.")

# if __name__ == "__main__":
#     get_moon_phase_from_city_data({}, '2026-10-08')