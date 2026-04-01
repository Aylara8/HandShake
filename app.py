import os
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from io import BytesIO
from flask_migrate import Migrate
from sqlalchemy import inspect, or_, text
from ai_logic import HandshakeLiveEngine

app = Flask(__name__)
app.secret_key = 'handshake_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///handshake.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads/passports'
app.config['UPLOAD_FOLDER_ITEMS'] = 'static/uploads/items'
app.config['UPLOAD_FOLDER_PROFILES'] = 'static/uploads/profiles'
app.config['MAX_CONTENT_LENGTH'] = 24 * 1024 * 1024

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
expert_executor = ThreadPoolExecutor(max_workers=4)
live_engine = HandshakeLiveEngine()

# Seeded from current official administrative references for Turkmenistan,
# with Ashgabat streets and avenues taken from official city transport notices.
TURKMEN_LOCATION_DATA = [
    {
        "name": "Ashgabat",
        "kind": "city",
        "districts": [
            {
                "name": "Bagtyyarlyk",
                "category": "city_district",
                "neighborhoods": [
                    "Teke Bazar",
                    "A. Niyazov Avenue",
                    "M. Kashgari Street",
                    "D. Azady Street",
                ],
            },
            {
                "name": "Berkararlyk",
                "category": "city_district",
                "neighborhoods": [
                    "Central Ashgabat",
                    "Garashsyzlyk Avenue",
                    "Turkmenbashy Avenue",
                    "Ataturk Street",
                ],
            },
            {
                "name": "Kopetdag",
                "category": "city_district",
                "neighborhoods": [
                    "Archabil Avenue",
                    "Bitarap Turkmenistan Avenue",
                    "Chandybil Avenue",
                ],
            },
            {
                "name": "Buzmeyin",
                "category": "city_district",
                "neighborhoods": [
                    "Arzuv",
                    "10 yyl Abadanchylyk Street",
                    "B. Annanov Street",
                    "H.A. Yasavi Street",
                    "N. Andalib Street",
                ],
            },
        ],
    },
    {
        "name": "Ahal",
        "kind": "velayat",
        "districts": [
            {"name": "Ak bugday", "category": "district", "neighborhoods": ["Anau"]},
            {"name": "Altyn Asyr", "category": "district", "neighborhoods": ["Altyn Asyr"]},
            {"name": "Babadayhan", "category": "district", "neighborhoods": ["Babadayhan"]},
            {"name": "Baharly", "category": "district", "neighborhoods": ["Baharly"]},
            {"name": "Gokdepe", "category": "district", "neighborhoods": ["Gokdepe"]},
            {"name": "Kaka", "category": "district", "neighborhoods": ["Kaka"]},
            {"name": "Sarahs", "category": "district", "neighborhoods": ["Sarahs"]},
            {"name": "Tejen", "category": "district", "neighborhoods": ["Tejen"]},
        ],
    },
    {"name": "Balkan", "kind": "velayat", "districts": []},
    {"name": "Dashoguz", "kind": "velayat", "districts": []},
    {"name": "Lebap", "kind": "velayat", "districts": []},
    {"name": "Mary", "kind": "velayat", "districts": []},
    {"name": "Arkadag", "kind": "city", "districts": []},
]


def save_data_url_image(data_url, destination_path):
    if not data_url or ',' not in data_url:
        raise ValueError("Missing image data")

    _, encoded = data_url.split(',', 1)
    try:
        image_bytes = base64.b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid image data") from exc

    with open(destination_path, "wb") as fh:
        fh.write(image_bytes)


def find_chat_request_between(user_a_id, user_b_id):
    return ChatRequest.query.filter(
        ((ChatRequest.sender_id == user_a_id) & (ChatRequest.recipient_id == user_b_id)) |
        ((ChatRequest.sender_id == user_b_id) & (ChatRequest.recipient_id == user_a_id))
    ).order_by(ChatRequest.timestamp.desc()).first()


def has_accepted_chat_between(user_a_id, user_b_id):
    return ChatRequest.query.filter(
        (
            ((ChatRequest.sender_id == user_a_id) & (ChatRequest.recipient_id == user_b_id)) |
            ((ChatRequest.sender_id == user_b_id) & (ChatRequest.recipient_id == user_a_id))
        ) &
        (ChatRequest.status == 'accepted')
    ).first()


def find_pending_chat_request(sender_id, recipient_id):
    return ChatRequest.query.filter_by(
        sender_id=sender_id,
        recipient_id=recipient_id,
        status='pending'
    ).order_by(ChatRequest.timestamp.desc()).first()


def get_chat_connection_state(user_a_id, user_b_id):
    accepted = has_accepted_chat_between(user_a_id, user_b_id)
    if accepted:
        return 'accepted', accepted

    outgoing_pending = find_pending_chat_request(user_a_id, user_b_id)
    if outgoing_pending:
        return 'outgoing_pending', outgoing_pending

    incoming_pending = find_pending_chat_request(user_b_id, user_a_id)
    if incoming_pending:
        return 'incoming_pending', incoming_pending

    return 'none', None


def normalize_profile_pic_url(image_url):
    if not image_url:
        return image_url

    normalized = image_url.strip().replace("\\", "/")
    if normalized.startswith("http://") or normalized.startswith("https://") or normalized.startswith("/static/"):
        return normalized

    static_index = normalized.lower().find("static/")
    if static_index >= 0:
        return "/" + normalized[static_index:]

    if normalized.startswith("uploads/"):
        return url_for('static', filename=normalized)

    return normalized


def normalize_user_profile_pic(user):
    if not user:
        return
    user.profile_pic = normalize_profile_pic_url(user.profile_pic)


def get_location_tree():
    velayats = Velayat.query.order_by(
        db.case(
            (Velayat.name == 'Ashgabat', 0),
            (Velayat.name == 'Ahal', 1),
            else_=2
        ),
        Velayat.name.asc()
    ).all()
    tree = []
    for velayat in velayats:
        districts = []
        for district in sorted(velayat.districts, key=lambda item: item.name):
            neighborhoods = [
                {"id": neighborhood.id, "name": neighborhood.name}
                for neighborhood in sorted(district.neighborhoods, key=lambda item: item.name)
            ]
            districts.append(
                {
                    "id": district.id,
                    "name": district.name,
                    "category": district.category,
                    "neighborhoods": neighborhoods,
                }
            )
        tree.append(
            {
                "id": velayat.id,
                "name": velayat.name,
                "kind": velayat.kind,
                "districts": districts,
            }
        )
    return tree


def find_seeded_neighborhood(velayat_name, district_name, neighborhood_name):
    return Neighborhood.query.join(District).join(Velayat).filter(
        Velayat.name == velayat_name,
        District.name == district_name,
        Neighborhood.name == neighborhood_name
    ).first()


def resolve_legacy_location(legacy_loc):
    normalized = (legacy_loc or '').strip().lower()
    if not normalized:
        return find_seeded_neighborhood('Ashgabat', 'Berkararlyk', 'Central Ashgabat')

    mapping = [
        ('ashgabat', ('Ashgabat', 'Berkararlyk', 'Central Ashgabat')),
        ('anau', ('Ahal', 'Ak bugday', 'Anau')),
        ('ak bugday', ('Ahal', 'Ak bugday', 'Anau')),
        ('altyn asyr', ('Ahal', 'Altyn Asyr', 'Altyn Asyr')),
        ('babadayhan', ('Ahal', 'Babadayhan', 'Babadayhan')),
        ('baharly', ('Ahal', 'Baharly', 'Baharly')),
        ('gokdepe', ('Ahal', 'Gokdepe', 'Gokdepe')),
        ('kaka', ('Ahal', 'Kaka', 'Kaka')),
        ('sarahs', ('Ahal', 'Sarahs', 'Sarahs')),
        ('tejen', ('Ahal', 'Tejen', 'Tejen')),
    ]
    for token, target in mapping:
        if token in normalized:
            return find_seeded_neighborhood(*target)
    return find_seeded_neighborhood('Ashgabat', 'Berkararlyk', 'Central Ashgabat')


def ensure_location_schema():
    Velayat.__table__.create(bind=db.engine, checkfirst=True)
    District.__table__.create(bind=db.engine, checkfirst=True)
    Neighborhood.__table__.create(bind=db.engine, checkfirst=True)

    inspector = inspect(db.engine)
    item_columns = {column['name'] for column in inspector.get_columns('item')}
    if 'neighborhood_id' not in item_columns:
        db.session.execute(text('ALTER TABLE item ADD COLUMN neighborhood_id INTEGER'))
        db.session.commit()


def seed_location_data():
    for velayat_data in TURKMEN_LOCATION_DATA:
        velayat = Velayat.query.filter_by(name=velayat_data['name']).first()
        if not velayat:
            velayat = Velayat(name=velayat_data['name'], kind=velayat_data['kind'])
            db.session.add(velayat)
            db.session.flush()
        else:
            velayat.kind = velayat_data['kind']

        for district_data in velayat_data['districts']:
            district = District.query.filter_by(
                velayat_id=velayat.id,
                name=district_data['name']
            ).first()
            if not district:
                district = District(
                    name=district_data['name'],
                    category=district_data['category'],
                    velayat_id=velayat.id
                )
                db.session.add(district)
                db.session.flush()
            else:
                district.category = district_data['category']

            for neighborhood_name in district_data['neighborhoods']:
                neighborhood = Neighborhood.query.filter_by(
                    district_id=district.id,
                    name=neighborhood_name
                ).first()
                if not neighborhood:
                    db.session.add(Neighborhood(name=neighborhood_name, district_id=district.id))

    db.session.commit()


def backfill_item_locations():
    inspector = inspect(db.engine)
    item_columns = {column['name'] for column in inspector.get_columns('item')}
    has_legacy_loc = 'loc' in item_columns
    if has_legacy_loc:
        rows = db.session.execute(text('SELECT id, loc, neighborhood_id FROM item')).mappings().all()
        for row in rows:
            if row['neighborhood_id']:
                continue
            neighborhood = resolve_legacy_location(row['loc'])
            if neighborhood:
                db.session.execute(
                    text('UPDATE item SET neighborhood_id = :neighborhood_id WHERE id = :item_id'),
                    {"neighborhood_id": neighborhood.id, "item_id": row['id']}
                )
        db.session.commit()
        return

    items = Item.query.filter(Item.neighborhood_id.is_(None)).all()
    for item in items:
        neighborhood = resolve_legacy_location(None)
        if neighborhood:
            item.neighborhood_id = neighborhood.id
    db.session.commit()


def rebuild_item_table_without_legacy_loc():
    inspector = inspect(db.engine)
    item_columns = {column['name'] for column in inspector.get_columns('item')}
    if 'loc' not in item_columns:
        return

    db.session.execute(text('PRAGMA foreign_keys=OFF'))
    db.session.execute(text('DROP TABLE IF EXISTS item_new'))
    db.session.execute(text("""
        CREATE TABLE item_new (
            id INTEGER NOT NULL PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            price VARCHAR(50) NOT NULL,
            type VARCHAR(50) NOT NULL,
            description TEXT,
            image_url VARCHAR(500),
            category VARCHAR(100) NOT NULL,
            rating FLOAT,
            num_ratings INTEGER,
            user_id INTEGER,
            neighborhood_id INTEGER
        )
    """))
    db.session.execute(text("""
        INSERT INTO item_new (
            id, title, price, type, description, image_url,
            category, rating, num_ratings, user_id, neighborhood_id
        )
        SELECT
            id, title, price, type, description, image_url,
            category, rating, num_ratings, user_id, neighborhood_id
        FROM item
    """))
    db.session.execute(text('DROP TABLE item'))
    db.session.execute(text('ALTER TABLE item_new RENAME TO item'))
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    db.session.commit()


def apply_database_updates():
    db.create_all()
    ensure_location_schema()
    seed_location_data()
    backfill_item_locations()
    rebuild_item_table_without_legacy_loc()


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(_error):
    flash('The uploaded image is too large. Please use a smaller or compressed image.')

    if request.path == url_for('register'):
        return redirect(url_for('register'))
    if request.path == url_for('login'):
        return redirect(url_for('login'))
    if request.path == url_for('upload'):
        return redirect(url_for('upload'))
    if request.path == url_for('edit_profile'):
        return redirect(url_for('edit_profile'))
    return redirect(url_for('index'))

# Models
class Velayat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='velayat')
    districts = db.relationship('District', backref='velayat', lazy=True, cascade='all, delete-orphan')


class District(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20), nullable=False, default='district')
    velayat_id = db.Column(db.Integer, db.ForeignKey('velayat.id'), nullable=False)
    neighborhoods = db.relationship('Neighborhood', backref='district', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('velayat_id', 'name', name='uq_district_velayat_name'),
    )


class Neighborhood(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    district_id = db.Column(db.Integer, db.ForeignKey('district.id'), nullable=False)
    items = db.relationship('Item', backref='neighborhood', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('district_id', 'name', name='uq_neighborhood_district_name'),
    )

    @property
    def display_name(self):
        return f"{self.name}, {self.district.name}"

    @property
    def full_path(self):
        return f"{self.name}, {self.district.name}, {self.district.velayat.name}"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    region = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    rating = db.Column(db.Float, default=5.0)
    num_ratings = db.Column(db.Integer, default=1)
    passport_img = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(500), nullable=True)
    items = db.relationship('Item', backref='owner', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    received_messages = db.relationship('Message', foreign_keys='Message.recipient_id', backref='recipient', lazy=True)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Float, default=5.0)
    num_ratings = db.Column(db.Integer, default=1)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhood.id'), nullable=True)

    @property
    def location_label(self):
        if self.neighborhood:
            return self.neighborhood.full_path
        return "Ashgabat"

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    reviewer = db.relationship('User', foreign_keys=[reviewer_id], backref='reviews_written')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

class ChatRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, accepted, rejected
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_requests')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_requests')

class BlockedUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    normalize_user_profile_pic(user)
    return user


@app.context_processor
def inject_chat_request_count():
    pending_chat_request_count = 0
    if current_user.is_authenticated:
        pending_chat_request_count = ChatRequest.query.filter_by(
            recipient_id=current_user.id,
            status='pending'
        ).count()
    return {'pending_chat_request_count': pending_chat_request_count}

# Initialize Database with dummy data
with app.app_context():
    apply_database_updates()
    
    if not User.query.filter_by(email="nepes@handshake.com").first():
        # Create Dummy Users
        dummy_users = [
            {"name": "Nepes", "email": "nepes@handshake.com", "pass": "nepes123", "region": "Turkmenistan", "bio": "Photography enthusiast and tech geek.", "pic": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=400"},
            {"name": "Aman", "email": "aman@handshake.com", "pass": "aman123", "region": "Turkmenistan", "bio": "Professional driver, renting out my spare cars.", "pic": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400"},
            {"name": "Selbi", "email": "selbi@handshake.com", "pass": "selbi123", "region": "Turkmenistan", "bio": "I love books and sharing knowledge.", "pic": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400"},
            {"name": "Maral", "email": "maral@handshake.com", "pass": "maral123", "region": "Turkmenistan", "bio": "Home renovation expert. Rent my tools!", "pic": "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=400"},
            {"name": "Arslan", "email": "arslan@handshake.com", "pass": "arslan123", "region": "Turkmenistan", "bio": "Gaming is my life. renting my PS5 and games.", "pic": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400"},
            {"name": "User1", "email": "user1@handshake.com", "pass": "user1", "region": "Turkmenistan", "bio": "New HandShake member ready to rent!", "pic": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=400"}
        ]
        
        db_users = []
        for u in dummy_users:
            new_u = User(
                username=u['name'].lower(), full_name=u['name'], email=u['email'],
                password_hash=generate_password_hash(u['pass'], method='scrypt'),
                region=u['region'], bio=u['bio'], age=25, passport_img="verified.png",
                profile_pic=u['pic']
            )
            db.session.add(new_u)
            db_users.append(new_u)
        db.session.commit()

        items_data = [
            {"title": "Sony A7III Camera", "price": "200", "type": "rent", "cat": "hobbies", "user_idx": 0, "desc": "Perfect for professional shoots.", "img": "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=800"},
            {"title": "DJI Mavic Air 2", "price": "150", "type": "rent", "cat": "hobbies", "user_idx": 0, "desc": "4K drone for amazing aerial shots.", "img": "https://images.unsplash.com/photo-1508614589041-895b88991e3e?w=800"},
            {"title": "Toyota Camry 2022", "price": "500", "type": "rent", "cat": "cars", "user_idx": 1, "desc": "Clean, reliable, and comfortable.", "img": "https://images.unsplash.com/photo-1621007947382-bb3c3994e3fb?w=800"},
            {"title": "BMW X5", "price": "800", "type": "rent", "cat": "cars", "user_idx": 1, "desc": "Luxury SUV for special occasions.", "img": "https://images.unsplash.com/photo-1555215695-3004980ad54e?w=800"},
            {"title": "Mercedes-Benz G-Class", "price": "1500", "type": "rent", "cat": "cars", "user_idx": 1, "desc": "The ultimate luxury off-roader.", "img": "https://images.unsplash.com/photo-1520031441872-265e4ff70366?w=800"},
            {"title": "Rare Art History Collection", "price": "20", "type": "exchange", "cat": "books", "user_idx": 2, "desc": "Set of 5 books about Renaissance art.", "img": "https://images.unsplash.com/photo-1512820790803-83ca734da794?w=800"},
            {"title": "Bosch Drill Set", "price": "50", "type": "rent", "cat": "tools", "user_idx": 3, "desc": "Heavy duty drill with all attachments.", "img": "https://images.unsplash.com/photo-1504148455328-c376907d081c?w=800"},
            {"title": "Professional Toolkit", "price": "75", "type": "rent", "cat": "tools", "user_idx": 3, "desc": "150-piece tool set for all home repairs.", "img": "https://images.unsplash.com/photo-1581244277943-fe4a9c777189?w=800"},
            {"title": "PlayStation 5 + 2 Controllers", "price": "100", "type": "rent", "cat": "hobbies", "user_idx": 4, "desc": "Latest games included: GOW, Spider-Man.", "img": "https://images.unsplash.com/photo-1606813907291-d86efa9b94db?w=800"},
            {"title": "Canon EOS R5", "price": "350", "type": "rent", "cat": "hobbies", "user_idx": 5, "desc": "High-resolution full-frame mirrorless camera.", "img": "https://images.unsplash.com/photo-1510127034890-ba27508e9f1c?w=800"},
            {"title": "Electric Skateboard", "price": "80", "type": "rent", "cat": "hobbies", "user_idx": 5, "desc": "Fast and fun city commuting.", "img": "https://images.unsplash.com/photo-1547447134-cd3f5c716030?w=800"},
            {"title": "Table Tennis Rackets (Pair)", "price": "15", "type": "rent", "cat": "hobbies", "user_idx": 5, "desc": "Professional grade rackets for competitive play.", "img": "https://images.unsplash.com/photo-1534158914592-062992fbe900?w=800"},
            {"title": "Mountain Bike - Trek", "price": "60", "type": "rent", "cat": "hobbies", "user_idx": 5, "desc": "Durable bike for trail riding.", "img": "https://images.unsplash.com/photo-1485965120184-e220f721d03e?w=800"}
        ]

        for item in items_data:
            new_item = Item(
                title=item['title'], price=item['price'], type=item['type'],
                neighborhood_id=find_seeded_neighborhood('Ashgabat', 'Berkararlyk', 'Central Ashgabat').id,
                description=item['desc'], category=item['cat'],
                user_id=db_users[item['user_idx']].id,
                image_url=item['img']
            )
            db.session.add(new_item)
        db.session.commit()

        review = Review(content="Excellent camera, very well maintained!", rating=5, reviewer_id=db_users[1].id, item_id=1)
        db.session.add(review)
        db.session.commit()

    if not User.query.filter_by(email="friend@handshake.com").first():
        friend_user = User(
            username="friend",
            full_name="Message Friend",
            email="friend@handshake.com",
            password_hash=generate_password_hash("friend123", method='scrypt'),
            region="Ashgabat",
            bio="Seeded test account for chat checks.",
            age=27,
            passport_img="verified.png"
        )
        db.session.add(friend_user)
        db.session.commit()

@app.route('/')
def dashboard():
    all_items = Item.query.order_by(Item.id.desc()).all()
    return render_template('dashboard.html', items=all_items)


def render_marketplace():
    query = (request.args.get('q') or "").strip()
    raw_velayat_id = request.args.get('velayat_id') or ''
    raw_district_id = request.args.get('district_id') or ''
    raw_neighborhood_id = request.args.get('neighborhood_id') or ''

    try:
        velayat_id = int(raw_velayat_id) if raw_velayat_id else None
    except ValueError:
        velayat_id = None

    try:
        district_id = int(raw_district_id) if raw_district_id else None
    except ValueError:
        district_id = None

    try:
        neighborhood_id = int(raw_neighborhood_id) if raw_neighborhood_id else None
    except ValueError:
        neighborhood_id = None

    items_query = Item.query.outerjoin(Neighborhood).outerjoin(District)

    if query:
        like_query = f"%{query}%"
        items_query = items_query.filter(
            or_(
                Item.title.ilike(like_query),
                Item.description.ilike(like_query),
                Item.category.ilike(like_query),
            )
        )

    if velayat_id:
        items_query = items_query.filter(District.velayat_id == velayat_id)
    if district_id:
        items_query = items_query.filter(Neighborhood.district_id == district_id)
    if neighborhood_id:
        items_query = items_query.filter(Item.neighborhood_id == neighborhood_id)

    items = items_query.order_by(Item.id.desc()).all()
    location_tree = get_location_tree()
    selected_location = {
        "velayat_id": velayat_id,
        "district_id": district_id,
        "neighborhood_id": neighborhood_id,
    }
    return render_template(
        'index.html',
        items=items,
        search_query=query,
        location_tree=location_tree,
        selected_location=selected_location,
        expert_query=query if query else ''
    )


@app.route('/market')
def index():
    return render_marketplace()

@app.route('/search')
def search():
    return render_marketplace()

@app.route('/process-passport', methods=['POST'])
def process_passport():
    data = request.get_json()
    image_data = data.get('image')
    if not image_data:
        return jsonify({'error': 'No image data provided'}), 400
    return jsonify({'full_name': "NEPES TAYYAROW", 'age': 25})


@app.route('/api/expert', methods=['POST'])
def expert_api():
    payload = request.get_json(silent=True) or {}
    item_query = (payload.get('item_query') or '').strip()
    user_request = (payload.get('question') or '').strip()
    if not item_query:
        return jsonify({'error': 'item_query is required'}), 400

    future = expert_executor.submit(live_engine.generate_live_expert_result, item_query, user_request)
    try:
        result = future.result(timeout=30)
    except FuturesTimeoutError:
        future.cancel()
        fallback = live_engine.generate_live_expert_result(item_query, user_request)
        response = jsonify(fallback['payload'])
        response.headers['X-Expert-Source'] = fallback.get('source', 'fallback')
        response.headers['X-Live-Provider-Available'] = 'true' if fallback.get('live_provider_available') else 'false'
        return response
    except Exception:
        return jsonify({'error': 'Expert engine failed'}), 502

    if not result or not result.get('payload'):
        return jsonify({'error': 'No expert data available'}), 503

    response = jsonify(result['payload'])
    response.headers['X-Expert-Source'] = result.get('source', 'unknown')
    response.headers['X-Live-Provider-Available'] = 'true' if result.get('live_provider_available') else 'false'
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            if current_user.is_authenticated:
                logout_user()
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password')
    elif current_user.is_authenticated:
        flash('Sign in below to switch to another account.')
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not email:
            flash('Email is required.')
            return redirect(url_for('forgot_password'))
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.')
            return redirect(url_for('forgot_password'))
        if new_password != confirm_password:
            flash('Passwords do not match.')
            return redirect(url_for('forgot_password'))

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found with that email.')
            return redirect(url_for('forgot_password'))

        user.password_hash = generate_password_hash(new_password, method='scrypt')
        db.session.commit()
        flash('Password reset successful. Please sign in with your new password.')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = (request.form.get('email') or "").strip().lower()
        region = (request.form.get('region') or "").strip()
        password = request.form.get('password') or ""
        confirm_password = request.form.get('confirm_password') or ""

        if not region:
            flash('Please select your region.')
            return redirect(url_for('register'))
        if not email:
            flash('Email is required.')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.')
            return redirect(url_for('register'))
        if password != confirm_password:
            flash('Passwords do not match.')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))

        passport_data = request.form.get('passport_image')
        if not passport_data:
            flash('Passport photo is required for KYC verification.')
            return redirect(url_for('register'))

        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])

        try:
            filename = secure_filename(f"{email}_passport.png")
            passport_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            save_data_url_image(passport_data, passport_path)
        except ValueError:
            flash('Invalid passport image. Please upload again.')
            return redirect(url_for('register'))

        age_value = request.form.get('age')
        parsed_age = int(age_value) if age_value and age_value.isdigit() else None
        new_user = User(
            username=email.split("@")[0],
            full_name=request.form.get('full_name') or email.split("@")[0],
            email=email,
            password_hash=generate_password_hash(password, method='scrypt'),
            region=region,
            age=parsed_age,
            passport_img=filename
        )
        db.session.add(new_user)
        db.session.commit()
        if current_user.is_authenticated:
            logout_user()
        flash('Registration complete. You can now log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        neighborhood_id = request.form.get('neighborhood_id')
        neighborhood = None
        try:
            neighborhood = Neighborhood.query.get(int(neighborhood_id))
        except (TypeError, ValueError):
            neighborhood = None

        if not neighborhood:
            flash('Please select a valid neighborhood or street.')
            return redirect(url_for('upload'))

        file = request.files.get('item_image')
        camera_image = request.form.get('camera_image')
        image_url = "https://images.unsplash.com/photo-1555685812-4b943f1cb0eb?w=800"

        if not os.path.exists(app.config['UPLOAD_FOLDER_ITEMS']):
            os.makedirs(app.config['UPLOAD_FOLDER_ITEMS'])

        if file and file.filename != '':
            filename = secure_filename(f"{current_user.id}_{datetime.now().timestamp()}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER_ITEMS'], filename)
            file.save(file_path)
            image_url = url_for('static', filename=f'uploads/items/{filename}')
        elif camera_image:
            filename = secure_filename(f"{current_user.id}_{datetime.now().timestamp()}_capture.png")
            file_path = os.path.join(app.config['UPLOAD_FOLDER_ITEMS'], filename)
            save_data_url_image(camera_image, file_path)
            image_url = url_for('static', filename=f'uploads/items/{filename}')
            
        new_item = Item(
            title=request.form.get('title'), price=request.form.get('price'),
            type=request.form.get('type'), neighborhood_id=neighborhood.id,
            description=request.form.get('description'), image_url=image_url,
            category=request.form.get('category'), user_id=current_user.id
        )
        db.session.add(new_item)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('upload.html', location_tree=get_location_tree())

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = User.query.get_or_404(user_id)
    normalize_user_profile_pic(user)
    reviews = Review.query.filter_by(target_user_id=user_id).all()
    for review in reviews:
        normalize_user_profile_pic(review.reviewer)

    chat_request = None
    has_blocked_user = False
    blocked_by_user = False
    profile_pending_requests = []

    if current_user.is_authenticated:
        if current_user.id != user_id:
            _, chat_request = get_chat_connection_state(current_user.id, user_id)
        has_blocked_user = BlockedUser.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).first() is not None
        blocked_by_user = BlockedUser.query.filter_by(blocker_id=user_id, blocked_id=current_user.id).first() is not None
        if current_user.id == user_id:
            profile_pending_requests = ChatRequest.query.filter_by(
                recipient_id=current_user.id,
                status='pending'
            ).order_by(ChatRequest.timestamp.desc()).all()
            for req in profile_pending_requests:
                normalize_user_profile_pic(req.sender)

    return render_template(
        'profile.html',
        user=user,
        reviews=reviews,
        chat_request=chat_request,
        has_blocked_user=has_blocked_user,
        blocked_by_user=blocked_by_user,
        profile_pending_requests=profile_pending_requests
    )

@app.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        region = (request.form.get('region') or '').strip()
        bio = (request.form.get('bio') or '').strip()

        if not full_name:
            flash('Full name is required.')
            return redirect(url_for('edit_profile'))
        if not region:
            flash('Location is required.')
            return redirect(url_for('edit_profile'))

        current_user.full_name = full_name
        current_user.bio = bio
        current_user.region = region
        
        # Profile Picture
        file = request.files.get('profile_pic')
        camera_image = request.form.get('camera_image')
        
        if not os.path.exists(app.config['UPLOAD_FOLDER_PROFILES']):
            os.makedirs(app.config['UPLOAD_FOLDER_PROFILES'])
            
        if file and file.filename != '':
            filename = secure_filename(f"profile_{current_user.id}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename)
            file.save(file_path)
            current_user.profile_pic = url_for('static', filename=f'uploads/profiles/{filename}')
        elif camera_image:
            filename = secure_filename(f"profile_{current_user.id}_capture.png")
            file_path = os.path.join(app.config['UPLOAD_FOLDER_PROFILES'], filename)
            save_data_url_image(camera_image, file_path)
            current_user.profile_pic = url_for('static', filename=f'uploads/profiles/{filename}')

        normalize_user_profile_pic(current_user)
        db.session.commit()
        return redirect(url_for('profile', user_id=current_user.id))
    return render_template('edit_profile.html')

# Chat Logic
@app.route('/send-chat-request/<int:recipient_id>')
@login_required
def send_chat_request(recipient_id):
    User.query.get_or_404(recipient_id)

    if recipient_id == current_user.id:
        flash('You cannot chat-request yourself.')
        return redirect(url_for('profile', user_id=recipient_id))

    if BlockedUser.query.filter(
        ((BlockedUser.blocker_id == current_user.id) & (BlockedUser.blocked_id == recipient_id)) |
        ((BlockedUser.blocker_id == recipient_id) & (BlockedUser.blocked_id == current_user.id))
    ).first():
        flash('Chat request unavailable because one of you is blocked.')
        return redirect(url_for('profile', user_id=recipient_id))

    state, existing = get_chat_connection_state(current_user.id, recipient_id)
    if state == 'none':
        req = ChatRequest(sender_id=current_user.id, recipient_id=recipient_id)
        db.session.add(req)
        db.session.commit()
        flash('Chat request sent!')
    elif state == 'accepted':
        flash('You already have an active chat with this user.')
        return redirect(url_for('chat', recipient_id=recipient_id))
    elif state == 'outgoing_pending':
        flash('Chat request already exists.')
    else:
        flash('This user already sent you a request. Open Messages to accept it.')
        return redirect(url_for('chat', tab='requests'))
    return redirect(url_for('profile', user_id=recipient_id))

@app.route('/accept-chat-request/<int:request_id>')
@login_required
def accept_chat_request(request_id):
    req = ChatRequest.query.get_or_404(request_id)
    if req.recipient_id == current_user.id and req.status == 'pending':
        req.status = 'accepted'
        db.session.commit()
        return redirect(url_for('chat', recipient_id=req.sender_id))
    flash('This chat request is no longer available.')
    return redirect(url_for('chat'))

@app.route('/reject-chat-request/<int:request_id>')
@login_required
def reject_chat_request(request_id):
    req = ChatRequest.query.get_or_404(request_id)
    if req.recipient_id == current_user.id and req.status == 'pending':
        req.status = 'rejected'
        db.session.delete(req)
        db.session.commit()
    else:
        flash('This chat request is no longer available.')
    return redirect(url_for('chat'))

@app.route('/block-user/<int:user_id>')
@login_required
def block_user(user_id):
    if user_id == current_user.id:
        flash('You cannot block yourself.')
        return redirect(url_for('profile', user_id=current_user.id))

    existing = BlockedUser.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).first()
    if not existing:
        block = BlockedUser(blocker_id=current_user.id, blocked_id=user_id)
        db.session.add(block)
        # Also delete any chat requests
        ChatRequest.query.filter(
            ((ChatRequest.sender_id == current_user.id) & (ChatRequest.recipient_id == user_id)) |
            ((ChatRequest.sender_id == user_id) & (ChatRequest.recipient_id == current_user.id))
        ).delete()
        db.session.commit()
        flash('User blocked.')
    return redirect(url_for('index'))

@app.route('/unblock-user/<int:user_id>')
@login_required
def unblock_user(user_id):
    BlockedUser.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).delete()
    db.session.commit()
    flash('User unblocked.')
    return redirect(url_for('profile', user_id=user_id))

@app.route('/chat')
@app.route('/chat/<int:recipient_id>')
@login_required
def chat(recipient_id=None):
    # Only show accepted chats
    accepted_requests = ChatRequest.query.filter(
        ((ChatRequest.sender_id == current_user.id) | (ChatRequest.recipient_id == current_user.id)) &
        (ChatRequest.status == 'accepted')
    ).order_by(ChatRequest.timestamp.desc()).all()
    
    active_chat_users = []
    seen_user_ids = set()
    for req in accepted_requests:
        other_user = req.recipient if req.sender_id == current_user.id else req.sender
        if other_user and other_user.id not in seen_user_ids:
            normalize_user_profile_pic(other_user)
            active_chat_users.append(other_user)
            seen_user_ids.add(other_user.id)

    pending_requests = ChatRequest.query.filter_by(
        recipient_id=current_user.id,
        status='pending'
    ).order_by(ChatRequest.timestamp.desc()).all()
    for req in pending_requests:
        normalize_user_profile_pic(req.sender)

    messages = []
    active_recipient = None
    initial_tab = request.args.get('tab', 'chats')
    if initial_tab not in ('chats', 'requests'):
        initial_tab = 'chats'
    if 'tab' not in request.args and pending_requests:
        initial_tab = 'requests'

    if recipient_id:
        state, _ = get_chat_connection_state(current_user.id, recipient_id)

        if state == 'accepted':
            active_recipient = User.query.get_or_404(recipient_id)
            normalize_user_profile_pic(active_recipient)
            messages = Message.query.filter(
                ((Message.sender_id == current_user.id) & (Message.recipient_id == recipient_id)) |
                ((Message.sender_id == recipient_id) & (Message.recipient_id == current_user.id))
            ).order_by(Message.timestamp.asc()).all()
            initial_tab = 'chats'
        elif state == 'incoming_pending':
            flash("This user requested to chat with you. Accept it in Requests first.")
            return redirect(url_for('chat', tab='requests'))
        elif state == 'outgoing_pending':
            flash("Your chat request is still pending approval.")
            return redirect(url_for('chat'))
        else:
            flash("Send a chat request first before messaging this user.")
            return redirect(url_for('profile', user_id=recipient_id))

    if initial_tab == 'chats' and not active_recipient and pending_requests and not active_chat_users:
        initial_tab = 'requests'

    return render_template(
        'chat.html',
        active_chat_users=active_chat_users,
        pending_requests=pending_requests,
        messages=messages,
        active_recipient=active_recipient,
        initial_tab=initial_tab
    )

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    recipient_id = request.form.get('recipient_id')
    body = (request.form.get('body') or '').strip()

    try:
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        flash("Invalid message recipient.")
        return redirect(url_for('chat'))
    
    # Check if either side has blocked the other.
    if BlockedUser.query.filter(
        ((BlockedUser.blocker_id == recipient_id) & (BlockedUser.blocked_id == current_user.id)) |
        ((BlockedUser.blocker_id == current_user.id) & (BlockedUser.blocked_id == recipient_id))
    ).first():
        flash("Messaging is unavailable because one of you is blocked.")
        return redirect(url_for('chat'))

    if not has_accepted_chat_between(current_user.id, recipient_id):
        flash("You need an accepted chat request before sending messages.")
        return redirect(url_for('profile', user_id=recipient_id))

    if recipient_id and body:
        msg = Message(sender_id=current_user.id, recipient_id=recipient_id, body=body)
        db.session.add(msg)
        db.session.commit()
        return redirect(url_for('chat', recipient_id=recipient_id))
    return redirect(url_for('chat'))

@app.route('/item/<int:item_id>')
def item_detail(item_id):
    item = Item.query.get_or_404(item_id)
    reviews = Review.query.filter_by(item_id=item_id).all()
    chat_request = None
    chat_state = 'none'
    if current_user.is_authenticated and item.owner and current_user.id != item.owner.id:
        chat_state, chat_request = get_chat_connection_state(current_user.id, item.owner.id)
    return render_template('item_detail.html', item=item, reviews=reviews, chat_request=chat_request, chat_state=chat_state)

@app.route('/rate_item/<int:item_id>', methods=['POST'])
@login_required
def rate_item(item_id):
    item = Item.query.get_or_404(item_id)
    rating = int(request.form.get('rating') or 0)
    content = (request.form.get('content') or '').strip()
    if rating < 1 or rating > 5:
        flash('Rating must be between 1 and 5.')
        return redirect(url_for('item_detail', item_id=item_id))
    if not content:
        flash('Review cannot be empty.')
        return redirect(url_for('item_detail', item_id=item_id))
    review = Review(content=content, rating=rating, reviewer_id=current_user.id, item_id=item_id)
    item.rating = (item.rating * item.num_ratings + rating) / (item.num_ratings + 1)
    item.num_ratings += 1
    db.session.add(review)
    db.session.commit()
    return redirect(url_for('item_detail', item_id=item_id))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))






    



if __name__ == '__main__':
    app.run(debug=True)
