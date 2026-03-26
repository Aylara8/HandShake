import os
import base64
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from io import BytesIO

# Import OCR related libs
try:
    from PIL import Image
    import pytesseract
except ImportError:
    pytesseract = None

app = Flask(__name__)
app.secret_key = 'handshake_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///handshake.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads/passports'
app.config['UPLOAD_FOLDER_ITEMS'] = 'static/uploads/items'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    region = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    passport_img = db.Column(db.String(200), nullable=False)
    items = db.relationship('Item', backref='owner', lazy=True)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    loc = db.Column(db.String(200), nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper function to extract info from text
def extract_passport_data(text):
    full_name = "Verified User"
    age = 25
    name_match = re.search(r"Name:?\s+([A-Z\s]+)", text, re.IGNORECASE)
    if name_match: full_name = name_match.group(1).strip()
    return full_name, age

# Initialize Database
with app.app_context():
    db.create_all()
    nepes_email = "nepes@handshake.com"
    if not User.query.filter_by(email=nepes_email).first():
        nepes_pass = "nepes123! @flutter/engine/src/flutter/impeller/fixtures/sa%m#ple.vert"
        new_user = User(
            username="nepes", full_name="Nepes", email=nepes_email,
            password_hash=generate_password_hash(nepes_pass, method='scrypt'),
            region="Turkmenistan", age=25, passport_img="initial.png"
        )
        db.session.add(new_user)
        db.session.commit()

    if not Item.query.first():
        mock_items = [
            Item(title="PlayStation 5", price="150", type="rent", loc="Ashgabat", image_url="https://images.unsplash.com/photo-1605462863863-10d9e47e15ee?w=800", category="hobbies"),
            Item(title="Canon EOS R5", price="500", type="rent", loc="Ashgabat", image_url="https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=800", category="hobbies")
        ]
        db.session.bulk_save_objects(mock_items)
        db.session.commit()

@app.route('/')
def dashboard():
    all_items = Item.query.order_by(Item.id.desc()).all()
    return render_template('dashboard.html', items=all_items)

@app.route('/market')
def index():
    all_items = Item.query.order_by(Item.id.desc()).all()
    return render_template('index.html', items=all_items)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        
        passport_data = request.form.get('passport_image')
        if passport_data:
            # Create folder if it doesn't exist
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])

            filename = secure_filename(f"{email}_passport.png")
            passport_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the base64 image
            with open(passport_path, "wb") as fh:
                fh.write(base64.b64decode(passport_data.split(',')[1]))
            
            new_user = User(
                username=email, 
                full_name=request.form.get('full_name'),
                email=email, 
                password_hash=generate_password_hash(request.form.get('password'), method='scrypt'),
                region=request.form.get('region'), 
                age=int(request.form.get('age') or 0), 
                passport_img=filename
            )
            db.session.add(new_user)
            db.session.commit()
            return redirect(url_for('login'))
            
    return render_template('register.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('item_image')
        if file and file.filename != '':
            # Create folder if it doesn't exist
            if not os.path.exists(app.config['UPLOAD_FOLDER_ITEMS']):
                os.makedirs(app.config['UPLOAD_FOLDER_ITEMS'])

            filename = secure_filename(f"{current_user.id}_{datetime.now().timestamp()}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER_ITEMS'], filename)
            file.save(file_path)
            
            new_item = Item(
                title=request.form.get('title'), 
                price=request.form.get('price'),
                type=request.form.get('type'), 
                loc=request.form.get('loc'),
                # Adjusting image_url to point correctly to the subfolder
                image_url=url_for('static', filename=f'uploads/items/{filename}'),
                category=request.form.get('category'), 
                user_id=current_user.id
            )
            db.session.add(new_item)
            db.session.commit()
            return redirect(url_for('index'))
            
    return render_template('upload.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    # Fetch only items uploaded by the logged-in user
    user_items = Item.query.filter_by(user_id=current_user.id).all()
    
    # Debugging: Print to console so you can see if items are actually found
    print(f"DEBUG: Found {len(user_items)} items for user {current_user.username}")
    
    return render_template('profile.html', items=user_items)



if __name__ == '__main__':
    app.run(debug=True)