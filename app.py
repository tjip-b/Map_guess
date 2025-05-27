from flask import Flask, render_template_string, request, session, redirect, url_for
import random
import math
from capitals import CAPITALS, CAPITALS_AFRICA, CAPITALS_ASIA, CAPITALS_EUROPE, CAPITALS_NORTH_AMERICA, CAPITALS_SOUTH_AMERICA, CAPITALS_OCEANIA, FAMOUS_CITIES
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key in production

# Adjusted zoom levels for the game: start with a few houses, end with the whole city
ZOOM_LEVELS = [19, 18, 17, 15, 13, 11]  # 19: a few houses, 11: whole city
MAX_ATTEMPTS = 6

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
