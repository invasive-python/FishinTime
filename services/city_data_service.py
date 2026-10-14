import requests


def get_city_data(city_name: str):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": city_name,
        "count": 1
    }

    response = requests.get(url, params=params)
    data = response.json()

    if "results" in data and len(data["results"]) > 0:
        result = data["results"][0]
        return result
    else:
        print("Location not found.")    

