import requests
import os
from datetime import date, datetime, timedelta

def get_tide_data(station_id, begin_date, end_date):
    base_url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    params = {
        'begin_date': begin_date,
        'end_date': end_date,
        'station': station_id,
        'product': 'predictions',
        'datum': 'MLLW',
        'time_zone': 'lst_ldt',
        'interval': 'hilo',
        'units': 'english',
        'application': 'DataAPI_Sample',
        'format': 'json'
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        return None


def get_tides_from_station_id_and_dates(city_name, begin_date):
    # TODO: endpoint returns all stations, 
    # (1) drop-down filter by state
    # (2) 2nd drop-down filter by station name and get ID
    # https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions&units=english

    

    station_id= "8722937"   # Ft Lauderdale, FL (example station ID)
    begin_date = datetime.strptime(begin_date, "%Y-%m-%d")
    end_date = begin_date + timedelta(days=1)

    tide_data = get_tide_data(station_id, begin_date, end_date)
    if tide_data:
        predictions = tide_data.get('predictions', [])
        if not predictions:
            print("No tide predictions found.")
        else:
            return predictions
    else:
        print("Failed to retrieve tide data.")

# if __name__ == "__main__":
#     main()        