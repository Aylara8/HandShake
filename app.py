import sqlite3
import requests
from flask import Flask, render_template, g, jsonify

app = Flask(__name__)
DATABASE = 'database.db'
NASA_API_KEY = 'DEMO_KEY' 

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row 
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            discovery_date TEXT,
            description TEXT,
            distance TEXT
        )''')
        if db.execute('SELECT count(*) FROM planets').fetchone()[0] == 0:
            db.execute("INSERT INTO planets (name, discovery_date, description, distance) VALUES ('Mars', 'Ancient Times', 'The Red Planet is a cold, desert world.', '225M km')")
            db.execute("INSERT INTO planets (name, discovery_date, description, distance) VALUES ('Jupiter', '1610', 'The largest planet in our solar system.', '778M km')")
        db.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/planet/<int:planet_id>')
def planet_detail(planet_id):
    db = get_db()
    planet = db.execute('SELECT * FROM planets WHERE id = ?', (planet_id,)).fetchone()
    nasa_img = "https://images-assets.nasa.gov/image/PIA04816/PIA04816~orig.jpg" # High-res fallback
    return render_template('planet.html', planet=planet, nasa_img=nasa_img)

@app.route('/api/planets')
def api_planets():
    db = get_db()
    rows = db.execute('SELECT * FROM planets').fetchall()
    return jsonify([dict(row) for row in rows])

if __name__ == '__main__':
    init_db()
    app.run(debug=True)