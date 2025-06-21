import requests
import json
import os
from dotenv import load_dotenv
import difflib

# Load environment variables
load_dotenv()
AGENCY_API_KEY = os.getenv('AGENCY_API_KEY')
if not AGENCY_API_KEY:
    print("Error: AGENCY_API_KEY not found in .env file.")
    exit()

API_URL = 'https://nilidon.com/api/v2'
SERVICES_FILE = 'services.json'

def get_api_services():
    """Fetches the list of services from the provider's API."""
    params = {
        'key': AGENCY_API_KEY,
        'action': 'services'
    }
    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status()  # Raises an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching services from API: {e}")
        return None

def find_best_match(local_name, api_services):
    """Finds the best matching API service for a local service name."""
    api_names = [s['name'] for s in api_services]
    best_matches = difflib.get_close_matches(local_name, api_names, n=1, cutoff=0.6)
    if not best_matches:
        return None
    
    best_match_name = best_matches[0]
    return next((s for s in api_services if s['name'] == best_match_name), None)

def update_local_services():
    """Updates the local services.json file with data from the API."""
    print("Fetching latest services from the API...")
    api_services = get_api_services()
    if not api_services:
        print("Could not retrieve services from the API. Aborting update.")
        return

    print("Loading local services.json file...")
    try:
        with open(SERVICES_FILE, 'r', encoding='utf-8') as f:
            local_services = json.load(f)
    except FileNotFoundError:
        print(f"Error: {SERVICES_FILE} not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode {SERVICES_FILE}. Is it a valid JSON?")
        return

    updated_count = 0
    not_found_count = 0

    print("Matching and updating local services...")
    for local_service in local_services:
        service_name = local_service.get('service')
        if not service_name:
            continue

        api_service_match = find_best_match(service_name, api_services)
        
        if api_service_match:
            # Update local service with API data
            local_service['api_service_id'] = int(api_service_match['service'])
            local_service['min'] = int(api_service_match['min'])
            local_service['max'] = int(api_service_match['max'])
            print(f"  [✓] Matched '{service_name}' -> '{api_service_match['name']}' (ID: {api_service_match['service']})")
            updated_count += 1
        else:
            print(f"  [!] No match found for '{service_name}'")
            not_found_count += 1

    print("\nSaving updated services back to services.json...")
    try:
        with open(SERVICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(local_services, f, indent=4)
        print("Successfully saved updated services.json!")
    except Exception as e:
        print(f"Error saving updated file: {e}")

    print(f"\nUpdate complete. {updated_count} services updated, {not_found_count} services not found.")

if __name__ == '__main__':
    update_local_services() 