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

app = Flask(__name__)
app.secret_key = 'handshake_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///handshake.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads/passports'
app.config['UPLOAD_FOLDER_ITEMS'] = 'static/uploads/items'
app.config['UPLOAD_FOLDER_PROFILES'] = 'static/uploads/profiles'
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
    loc = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Float, default=5.0)
    num_ratings = db.Column(db.Integer, default=1)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

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
    return User.query.get(int(user_id))

# Initialize Database with dummy data
with app.app_context():
    db.create_all()
    
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
                loc="Ashgabat", description=item['desc'], category=item['cat'],
                user_id=db_users[item['user_idx']].id,
                image_url=item['img']
            )
            db.session.add(new_item)
        db.session.commit()

        review = Review(content="Excellent camera, very well maintained!", rating=5, reviewer_id=db_users[1].id, item_id=1)
        db.session.add(review)
        db.session.commit()

@app.route('/')
def dashboard():
    all_items = Item.query.order_by(Item.id.desc()).all()
    return render_template('dashboard.html', items=all_items)

@app.route('/market')
def index():
    all_items = Item.query.order_by(Item.id.desc()).all()
    return render_template('index.html', items=all_items)

@app.route('/search')
def search():
    query = request.args.get('q')
    if query:
        items = Item.query.filter(Item.title.contains(query) | Item.description.contains(query) | Item.category.contains(query)).all()
    else:
        items = Item.query.all()
    return render_template('index.html', items=items)

@app.route('/process-passport', methods=['POST'])
def process_passport():
    data = request.get_json()
    image_data = data.get('image')
    if not image_data:
        return jsonify({'error': 'No image data provided'}), 400
    return jsonify({'full_name': "NEPES TAYYAROW", 'age': 25})

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
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            filename = secure_filename(f"{email}_passport.png")
            passport_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            with open(passport_path, "wb") as fh:
                fh.write(base64.b64decode(passport_data.split(',')[1]))
            new_user = User(
                username=email, full_name=request.form.get('full_name'),
                email=email, password_hash=generate_password_hash(request.form.get('password'), method='scrypt'),
                region=request.form.get('region'), age=int(request.form.get('age') or 0), 
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
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(camera_image.split(',')[1]))
            image_url = url_for('static', filename=f'uploads/items/{filename}')
            
        new_item = Item(
            title=request.form.get('title'), price=request.form.get('price'),
            type=request.form.get('type'), loc=request.form.get('loc'),
            description=request.form.get('description'), image_url=image_url,
            category=request.form.get('category'), user_id=current_user.id
        )
        db.session.add(new_item)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('upload.html')

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = User.query.get_or_404(user_id)
    reviews = Review.query.filter_by(target_user_id=user_id).all()
    # Check if a chat request exists or if users are blocked
    chat_request = ChatRequest.query.filter(
        ((ChatRequest.sender_id == current_user.id) & (ChatRequest.recipient_id == user_id)) |
        ((ChatRequest.sender_id == user_id) & (ChatRequest.recipient_id == current_user.id))
    ).first() if current_user.is_authenticated else None
    
    is_blocked = BlockedUser.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).first() if current_user.is_authenticated else None
    
    return render_template('profile.html', user=user, reviews=reviews, chat_request=chat_request, is_blocked=is_blocked)

@app.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name')
        current_user.bio = request.form.get('bio')
        current_user.region = request.form.get('region')
        
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
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(camera_image.split(',')[1]))
            current_user.profile_pic = url_for('static', filename=f'uploads/profiles/{filename}')
            
        db.session.commit()
        return redirect(url_for('profile', user_id=current_user.id))
    return render_template('edit_profile.html')

# Chat Logic
@app.route('/send-chat-request/<int:recipient_id>')
@login_required
def send_chat_request(recipient_id):
    existing = ChatRequest.query.filter_by(sender_id=current_user.id, recipient_id=recipient_id).first()
    if not existing:
        req = ChatRequest(sender_id=current_user.id, recipient_id=recipient_id)
        db.session.add(req)
        db.session.commit()
        flash('Chat request sent!')
    return redirect(url_for('profile', user_id=recipient_id))

@app.route('/accept-chat-request/<int:request_id>')
@login_required
def accept_chat_request(request_id):
    req = ChatRequest.query.get_or_404(request_id)
    if req.recipient_id == current_user.id:
        req.status = 'accepted'
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/reject-chat-request/<int:request_id>')
@login_required
def reject_chat_request(request_id):
    req = ChatRequest.query.get_or_404(request_id)
    if req.recipient_id == current_user.id:
        req.status = 'rejected'
        db.session.delete(req)
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/block-user/<int:user_id>')
@login_required
def block_user(user_id):
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
    return redirect(url_for('market'))

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
    ).all()
    
    active_chat_users = []
    for req in accepted_requests:
        other_user = req.recipient if req.sender_id == current_user.id else req.sender
        active_chat_users.append(other_user)
        
    pending_requests = ChatRequest.query.filter_by(recipient_id=current_user.id, status='pending').all()
    
    messages = []
    active_recipient = None
    if recipient_id:
        # Verify they are in an accepted chat
        is_authorized = ChatRequest.query.filter(
            ((ChatRequest.sender_id == current_user.id) & (ChatRequest.recipient_id == recipient_id) |
             (ChatRequest.sender_id == recipient_id) & (ChatRequest.recipient_id == current_user.id)) &
            (ChatRequest.status == 'accepted')
        ).first()
        
        if is_authorized:
            active_recipient = User.query.get_or_404(recipient_id)
            messages = Message.query.filter(
                ((Message.sender_id == current_user.id) & (Message.recipient_id == recipient_id)) |
                ((Message.sender_id == recipient_id) & (Message.recipient_id == current_user.id))
            ).order_by(Message.timestamp.asc()).all()
        else:
            flash("You need an accepted chat request to message this user.")
            return redirect(url_for('chat'))

    return render_template('chat.html', active_chat_users=active_chat_users, pending_requests=pending_requests, messages=messages, active_recipient=active_recipient)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    recipient_id = request.form.get('recipient_id')
    body = request.form.get('body')
    
    # Check if blocked
    if BlockedUser.query.filter_by(blocker_id=recipient_id, blocked_id=current_user.id).first():
        flash("You are blocked by this user.")
        return redirect(url_for('chat'))

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
    return render_template('item_detail.html', item=item, reviews=reviews)

@app.route('/rate_item/<int:item_id>', methods=['POST'])
@login_required
def rate_item(item_id):
    item = Item.query.get_or_404(item_id)
    rating = int(request.form.get('rating'))
    content = request.form.get('content')
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
