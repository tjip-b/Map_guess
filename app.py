from flask import Flask, render_template_string, request, session, redirect, url_for
import random
import math
from capitals import CAPITALS, CAPITALS_AFRICA, CAPITALS_ASIA, CAPITALS_EUROPE, CAPITALS_NORTH_AMERICA, CAPITALS_SOUTH_AMERICA, CAPITALS_OCEANIA, FAMOUS_CITIES
import os
from sentinelhub import SHConfig, SentinelHubRequest, DataCollection, MimeType, CRS, BBox
import shutil

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key in production

# Adjusted zoom levels for the game: start with a few houses, end with the whole city
ZOOM_LEVELS = [19, 18, 17, 15, 13, 11]  # 19: a few houses, 11: whole city
MAX_ATTEMPTS = 6

SENTINEL_INSTANCE_ID = 'b5875af0-bb8b-42ec-b503-95d37950db43'

HTML_TEMPLATE = '''
<!doctype html>
<title>Guess the City</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
<style>
  html, body {
    height: 100%;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }
  body {
    display: flex;
    flex-direction: column;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
  }
  #map-container {
    flex: 1 1 auto;
    display: flex;
    align-items: stretch;
    justify-content: stretch;
    min-height: 0;
    min-width: 0;
  }
  #map {
    width: 100vw;
    height: 100%;
    flex: 1 1 auto;
    z-index: 1;
  }
  #controls {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 16px 0 8px 0;
    background: #f8f8f8;
    box-shadow: 0 -2px 8px rgba(0,0,0,0.05);
    z-index: 2;
  }
  #controls form, #controls .reset-btn {
    margin: 8px 0;
  }
  .reset-btn {
    padding: 8px 16px;
    background: #e74c3c;
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;
  }
  .reset-btn:hover {
    background: #c0392b;
  }
</style>
<h2 style="text-align:center; margin: 8px 0 0 0;">Guess the City!</h2>
<p style="text-align:center; margin: 0 0 8px 0;">Attempt {{ attempt }} of {{ max_attempts }}</p>
<div id="map-container">
  <div id="map"></div>
</div>
<div id="controls">
  <small><a href="https://www.openstreetmap.org/#map={{ zoom }}/{{ lat }}/{{ lon }}" target="_blank">View Larger Map</a></small>
  {% if not finished %}
  <form method="post" style="display:inline-block;">
      <input name="guess" list="citylist" autofocus autocomplete="off">
      <datalist id="citylist">
        {% for city in city_names %}
        <option value="{{ city }}">
        {% endfor %}
      </datalist>
      <button type="submit">Guess</button>
  </form>
  {% endif %}
  <form action="/reset" method="get" style="display:inline-block;">
    <button type="submit" class="reset-btn">Reset</button>
  </form>
  <form action="/picklist" method="get" style="display:inline-block;">
    <button type="submit" class="reset-btn">Pick Map List</button>
  </form>
  {% if message %}<p>{{ message }}</p>{% endif %}
  {% if finished %}<p>The answer was: <b>{{ capital }}</b></p>{% endif %}
  <p>Score: {{ score }}</p>
  <p>Current list: <b>{{ list_choice }}</b></p>
</div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
  var map = L.map('map', {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    tap: false,
    touchZoom: false
  }).setView([{{ lat }}, {{ lon }}], {{ zoom }});
  L.tileLayer('https://cartodb-basemaps-a.global.ssl.fastly.net/light_nolabels/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors, © CartoDB',
    noWrap: true
  }).addTo(map);
  var marker = L.marker([{{ lat }}, {{ lon }}]).addTo(map);
</script>
'''

LIST_OPTIONS = {
    'World Capitals': CAPITALS,
    'Africa': CAPITALS_AFRICA,
    'Asia': CAPITALS_ASIA,
    'Europe': CAPITALS_EUROPE,
    'North America': CAPITALS_NORTH_AMERICA,
    'South America': CAPITALS_SOUTH_AMERICA,
    'Oceania': CAPITALS_OCEANIA,
    'Famous Cities': FAMOUS_CITIES,
}

# Helper to pick a random point within radius (in km) of a lat/lon
def random_point_within_radius(lat, lon, radius_km):
    radius_deg = radius_km / 111  # Approximate conversion
    angle = random.uniform(0, 2 * math.pi)
    r = radius_deg * math.sqrt(random.uniform(0, 1))
    dlat = r * math.cos(angle)
    dlon = r * math.sin(angle) / math.cos(math.radians(lat))
    return lat + dlat, lon + dlon

# Sentinel Hub config (proof of concept, API key provided)
SENTINEL_CLIENT_ID = '35d62be7-6ca8-44a5-a5b4-d6db54ed13f5'
SENTINEL_CLIENT_SECRET = 'jo4WJVfZ5Rqi4oM3R5GU8iOYxWHTTeix'
SENTINEL_API_KEY = 'PLAK2ef5db4058bf4ba6883c982e26c14d7e'

config = SHConfig()
config.sh_client_id = SENTINEL_CLIENT_ID
config.sh_client_secret = SENTINEL_CLIENT_SECRET
config.sh_api_key = SENTINEL_API_KEY

SAT_IMAGE_PATH = os.path.join('static', 'sat_image.png')
os.makedirs('static', exist_ok=True)

def get_satellite_image(lat, lon, zoom):
    print(f"[DEBUG] Requesting satellite image for lat={lat}, lon={lon}, zoom={zoom}")
    # Use a larger base for bbox and Sentinel-2 L2A, and a wide date range
    base = 0.01  # Larger area for Sentinel-2
    delta = base * (2 ** (12 - zoom))
    min_lon = lon - delta
    min_lat = lat - delta
    max_lon = lon + delta
    max_lat = lat + delta
    print(f"[DEBUG] Calculated bbox: {min_lon}, {min_lat}, {max_lon}, {max_lat}")
    bbox = BBox(bbox=[min_lon, min_lat, max_lon, max_lat], crs=CRS.WGS84)
    try:
        request = SentinelHubRequest(
            data_folder='static',
            evalscript="""
            //VERSION=3
            function setup() {
              return {
                input: ["B04", "B03", "B02"],
                output: { bands: 3 }
              };
            }
            function stretch(val) {
              return Math.max(0, Math.min(1, (val - 0.05) / 0.3));
            }
            function evaluatePixel(sample) {
              return [
                Math.pow(stretch(sample.B04), 1/2.2),
                Math.pow(stretch(sample.B03), 1/2.2),
                Math.pow(stretch(sample.B02), 1/2.2)
              ];
            }
            """,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=('2015-05-27', '2025-05-27'),
                    mosaicking_order='leastCC',
                    other_args={"maxcc": 0.1, "acquisitionMode": "DAY"}  # Only daytime acquisitions
                )
            ],
            responses=[
                SentinelHubRequest.output_response('default', MimeType.PNG)
            ],
            bbox=bbox,
            size=(600, 400),
            config=config
        )
        print("[DEBUG] Sending SentinelHubRequest...")
        images = request.get_data(save_data=True)
        print(f"[DEBUG] Images returned: {images}")
        # Find the latest response.png in static/*/response.png
        latest_file = None
        latest_time = 0
        for root, dirs, files in os.walk('static'):
            for file in files:
                if file == 'response.png':
                    file_path = os.path.join(root, file)
                    mtime = os.path.getmtime(file_path)
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_file = file_path
        if latest_file:
            shutil.copy(latest_file, SAT_IMAGE_PATH)
            print(f"[DEBUG] Copied {latest_file} to {SAT_IMAGE_PATH}")
        else:
            print("[ERROR] No response.png found in static/ subfolders.")
            raise FileNotFoundError('No response.png found')
        print(f"[DEBUG] Satellite image saved to: {SAT_IMAGE_PATH}")
        return SAT_IMAGE_PATH
    except Exception as e:
        print(f"[ERROR] Exception in get_satellite_image: {e}")
        raise

def get_wide_satellite_image(lat, lon):
    print(f"[DEBUG] Requesting NOT ZOOMED satellite image for lat={lat}, lon={lon}")
    # Use a large bbox for a wide Paris view
    delta = 0.1  # ~11km in each direction
    min_lon = lon - delta
    min_lat = lat - delta
    max_lon = lon + delta
    max_lat = lat + delta
    print(f"[DEBUG] Calculated bbox: {min_lon}, {min_lat}, {max_lon}, {max_lat}")
    bbox = BBox(bbox=[min_lon, min_lat, max_lon, max_lat], crs=CRS.WGS84)
    try:
        request = SentinelHubRequest(
            data_folder='static',
            evalscript="""
            //VERSION=3
            function setup() {
              return {
                input: ["B04", "B03", "B02"],
                output: { bands: 3 }
              };
            }
            function stretch(val) {
              return Math.max(0, Math.min(1, (val - 0.05) / 0.3));
            }
            function evaluatePixel(sample) {
              return [
                Math.pow(stretch(sample.B04), 1/2.2),
                Math.pow(stretch(sample.B03), 1/2.2),
                Math.pow(stretch(sample.B02), 1/2.2)
              ];
            }
            """,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=('2015-05-27', '2025-05-27'),
                    mosaicking_order='leastCC',  # Use least cloud cover
                    other_args={"maxcc": 0.1}  # Maximum 10% cloud coverage
                )
            ],
            responses=[
                SentinelHubRequest.output_response('default', MimeType.PNG)
            ],
            bbox=bbox,
            size=(600, 400),
            config=config
        )
        print("[DEBUG] Sending SentinelHubRequest...")
        images = request.get_data(save_data=True)
        print(f"[DEBUG] Images returned: {images}")
        # Find the latest response.png in static/*/response.png
        latest_file = None
        latest_time = 0
        for root, dirs, files in os.walk('static'):
            for file in files:
                if file == 'response.png':
                    file_path = os.path.join(root, file)
                    mtime = os.path.getmtime(file_path)
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_file = file_path
        if latest_file:
            shutil.copy(latest_file, SAT_IMAGE_PATH)
            print(f"[DEBUG] Copied {latest_file} to {SAT_IMAGE_PATH}")
        else:
            print("[ERROR] No response.png found in static/ subfolders.")
            raise FileNotFoundError('No response.png found')
        print(f"[DEBUG] Satellite image saved to: {SAT_IMAGE_PATH}")
        return SAT_IMAGE_PATH
    except Exception as e:
        print(f"[ERROR] Exception in get_satellite_image: {e}")
        raise

def haversine(lat1, lon1, lat2, lon2):
    # Calculate the great-circle distance between two points (in km)
    R = 6371  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def bearing(lat1, lon1, lat2, lon2):
    # Calculate the initial bearing from (lat1, lon1) to (lat2, lon2)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
    theta = math.atan2(y, x)
    bearing_deg = (math.degrees(theta) + 360) % 360
    return bearing_deg

def bearing_to_arrow(bearing_deg):
    # Unicode arrows for 8 directions
    arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖', '↑']
    idx = int((bearing_deg + 22.5) // 45)
    return arrows[idx]

@app.route('/', methods=['GET', 'POST'])
def index():
    # Handle list selection
    if request.method == 'POST' and 'list_choice' in request.form:
        session.clear()
        session['list_choice'] = request.form['list_choice']
        session['score'] = session.get('score', {})
        return redirect(url_for('index'))

    list_choice = session.get('list_choice')
    if not list_choice:
        # Show list selection form
        return render_template_string('''
        <h2>Choose a City List</h2>
        <form method="post">
            <select name="list_choice">
                {% for key in options.keys() %}
                <option value="{{ key }}">{{ key }}</option>
                {% endfor %}
            </select>
            <button type="submit">Start</button>
        </form>
        ''', options=LIST_OPTIONS)

    city_list = LIST_OPTIONS[list_choice]
    if 'capital' not in session:
        city = random.choice(city_list)
        rand_lat, rand_lon = random_point_within_radius(city['lat'], city['lon'], 5)
        session['capital'] = city['name']
        session['lat'] = rand_lat
        session['lon'] = rand_lon
        session['attempt'] = 1
        session['finished'] = False
    else:
        city = {'name': session['capital'], 'lat': session['lat'], 'lon': session['lon']}
        rand_lat = session['lat']
        rand_lon = session['lon']
    attempt = session['attempt']
    finished = session.get('finished', False)
    zoom = ZOOM_LEVELS[attempt - 1] if attempt <= MAX_ATTEMPTS else ZOOM_LEVELS[-1]

    base = 0.05
    delta = base / (2 ** (zoom - 6))
    min_lon = rand_lon - delta
    min_lat = rand_lat - delta
    max_lon = rand_lon + delta
    max_lat = rand_lat + delta
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    if 'score' not in session:
        session['score'] = {}
    score_dict = session['score']
    score = score_dict.get(list_choice, 0)

    message = ''
    if request.method == 'POST' and not finished and 'guess' in request.form:
        guess = request.form.get('guess', '').strip().lower()
        # Only allow guesses that are in the current city list
        guessed_city = next((c for c in city_list if c['name'].lower() == guess), None)
        if not guessed_city:
            message = 'Please enter a valid city name from the current list.'
        elif guess == city['name'].lower():
            points = MAX_ATTEMPTS - attempt + 1
            message = f'Correct! You earned {points} points.'
            session['finished'] = True
            finished = True
            score_dict[list_choice] = score + points
            session['score'] = score_dict
        else:
            dist = haversine(guessed_city['lat'], guessed_city['lon'], city['lat'], city['lon'])
            bear = bearing(guessed_city['lat'], guessed_city['lon'], city['lat'], city['lon'])
            arrow = bearing_to_arrow(bear)
            message = f'Wrong! Your guess is {dist:.1f} km off {arrow}. Try again.'
            attempt += 1
            if attempt > MAX_ATTEMPTS:
                message = f'Out of attempts! The answer was: {city["name"]}'
                session['finished'] = True
                finished = True
            session['attempt'] = attempt

    leaflet_zoom = zoom
    city_names = [c['name'] for c in city_list]
    return render_template_string(
        HTML_TEMPLATE,
        attempt=attempt,
        max_attempts=MAX_ATTEMPTS,
        zoom=leaflet_zoom,
        message=message,
        finished=finished,
        lat=rand_lat,
        lon=rand_lon,
        capital=city['name'],
        list_choice=list_choice,
        score=score,
        city_names=city_names
    )

@app.route('/reset')
def reset():
    # Only reset the current round, not the score or list_choice
    for key in ['capital', 'lat', 'lon', 'attempt', 'finished']:
        session.pop(key, None)
    return redirect(url_for('index'))

@app.route('/picklist', methods=['GET', 'POST'])
def picklist():
    if request.method == 'POST' and 'list_choice' in request.form:
        session.clear()
        session['list_choice'] = request.form['list_choice']
        session['score'] = session.get('score', {})
        return redirect(url_for('index'))
    return render_template_string('''
        <h2>Choose a City List</h2>
        <form method="post">
            <select name="list_choice">
                {% for key in options.keys() %}
                <option value="{{ key }}">{{ key }}</option>
                {% endfor %}
            </select>
            <button type="submit">Start</button>
        </form>
        <form action="/" method="get"><button type="submit">Back to Game</button></form>
        ''', options=LIST_OPTIONS)

@app.route('/notzoomedparis')
def notzoomedparis():
    # Paris center
    lat, lon = 48.8566, 2.3522
    message = ''
    sat_image_url = None
    try:
        sat_image_path = get_wide_satellite_image(lat, lon)
        sat_image_url = '/' + sat_image_path.replace('\\', '/')
        print(f"[DEBUG] sat_image_url for HTML: {sat_image_url}")
        if not os.path.exists(sat_image_path) or os.path.getsize(sat_image_path) < 1000:
            sat_image_url = None
            message = 'Satellite image is empty or missing.'
    except Exception as e:
        sat_image_url = None
        message = f"Satellite image error: {e}"
    return f"<h2>Not Zoomed Paris Satellite Image</h2>" \
           f"<img src='{sat_image_url}' style='max-width:90vw; border:4px solid #e67e22;'>" \
           f"<p>{message}</p>"

@app.route('/wmsnotzoomedparis')
def wmsnotzoomedparis():
    # Paris center
    lat, lon = 48.8566, 2.3522
    # Use a much larger bbox for a wide Paris view
    delta = 0.1  # ~11km in each direction, so ~22km x 22km
    min_lon = lon - delta
    min_lat = lat - delta
    max_lon = lon + delta
    max_lat = lat + delta
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    wms_url = (
        f"https://services.sentinel-hub.com/ogc/wms/{SENTINEL_INSTANCE_ID}"
        f"?REQUEST=GetMap&BBOX={bbox}&LAYERS=1_TRUE_COLOR&MAXCC=10&WIDTH=1200&HEIGHT=800&FORMAT=image/png&CRS=EPSG:4326&TIME=2015-05-27/2025-05-27"
    )
    print(f"[DEBUG] WMS not zoomed Paris URL: {wms_url}")
    return f"<h2>WMS Not Zoomed Paris Satellite Image</h2>" \
           f"<img src='{wms_url}' style='max-width:90vw; border:4px solid #e67e22;'>" \
           f"<p style='font-size:small;word-break:break-all;'>WMS URL: {wms_url}</p>"

if __name__ == '__main__':
    app.run(debug=True)
