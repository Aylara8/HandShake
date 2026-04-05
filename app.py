import os
import base64
import binascii
import hashlib
import secrets
import smtplib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from email.message import EmailMessage
from io import BytesIO
from flask_migrate import Migrate
from sqlalchemy import inspect, or_, text
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args, **_kwargs):
        return False
from ai_logic import HandshakeLiveEngine

load_dotenv()

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
PASSWORD_RESET_TOKEN_TTL_MINUTES = 20
ADMIN_EMAIL = (os.getenv('ADMIN_EMAIL') or '').strip().lower()
ALLOW_LOCAL_RESET_LINK = os.getenv('ALLOW_LOCAL_RESET_LINK', 'true').lower() == 'true'
SUPPORTED_LANGUAGES = {
    'en': 'English',
    'tm': 'Turkmen',
    'ru': 'Russian',
}
TRANSLATIONS = {
    'en': {
        'nav.search_placeholder': 'Search for anything...',
        'nav.marketplace': 'Marketplace',
        'nav.messages': 'Messages',
        'nav.post_item': 'Post Item',
        'nav.edit_profile': 'Edit Profile',
        'nav.my_listings': 'My Listings',
        'nav.logout': 'Log out',
        'nav.login': 'Log in',
        'nav.signup': 'Sign up',
        'lang.label': 'Language',
        'market.title': 'Find What You Need',
        'market.subtitle': 'Use keywords and location filters to narrow listings fast.',
        'market.keyword': 'Keyword',
        'market.keyword_placeholder': 'Camera, toolkit, car, apartment...',
        'market.velayat': 'Velayat',
        'market.district': 'District',
        'market.neighborhood': 'Neighborhood',
        'market.all_velayats': 'All velayats',
        'market.all_districts': 'All districts',
        'market.all_neighborhoods': 'All neighborhoods / streets',
        'market.all_streets': 'All streets / avenues',
        'market.search': 'Search',
        'market.clear': 'Clear',
        'market.showing': 'Showing {count} listing{suffix}{query_suffix}.',
        'market.no_results': 'No listings matched the current filters.',
        'auth.login_title': 'Secure Sign In',
        'auth.login_subtitle': 'Enter your credentials to access your HandShake account.',
        'auth.email_address': 'Email Address',
        'auth.password': 'Password',
        'auth.remember_me': 'Remember me',
        'auth.forgot_password': 'Forgot password?',
        'auth.secure_login': 'Secure Login',
        'auth.no_account': "Don't have an account?",
        'auth.start_kyc': 'Start KYC Verification',
        'auth.recovery_title': 'Secure Password Recovery',
        'auth.recovery_subtitle': 'This flow requires a one-time reset token. Tokens expire after 20 minutes and can be used once.',
        'auth.step1': '1. Request reset token',
        'auth.step2': '2. Reset password with token',
        'auth.email_placeholder': 'Your account email',
        'auth.generate_token': 'Generate Token',
        'auth.token_placeholder': 'One-time reset token',
        'auth.new_password': 'New password',
        'auth.confirm_new_password': 'Confirm new password',
        'auth.reset_password': 'Reset Password',
        'auth.no_email_notice': 'No email sender is configured in this app, so token delivery is handled by admin/server logs.',
        'auth.back_to_login': 'Back to',
        'auth.reset_intro': 'Enter your email and new password. If you do not have a token yet, submit once to generate one.',
        'auth.reset_token': 'Reset token',
        'auth.generate_or_reset': 'Generate Token / Reset',
        'auth.forgot_intro': 'Enter your Gmail/email and we will send a verification link.',
        'auth.send_verification': 'Send verification email',
        'auth.check_email_msg': 'If the account exists, a verification email has been sent.',
        'auth.email_service_off': 'Email service is not configured on server. Contact admin.',
        'auth.reset_from_email': 'Create new password',
        'flash.invalid_login': 'Invalid email/username or password.',
        'flash.email_required': 'Email is required.',
        'flash.new_password_len': 'New password must be at least 6 characters.',
        'flash.passwords_mismatch': 'Passwords do not match.',
        'flash.no_account_email': 'No account found with that email.',
        'flash.token_generated': 'Reset token generated: {token}. Use it within {minutes} minutes.',
        'flash.invalid_token': 'Invalid or expired reset token.',
        'flash.reset_success': 'Password reset successful. Please sign in with your new password.',
    },
    'tm': {
        'nav.search_placeholder': 'Islendik zady gozle...',
        'nav.marketplace': 'Bazar',
        'nav.messages': 'Habarlar',
        'nav.post_item': 'Haryt Gos',
        'nav.edit_profile': 'Profili Uytget',
        'nav.my_listings': 'Bildirislerim',
        'nav.logout': 'Cyk',
        'nav.login': 'Gir',
        'nav.signup': 'Hasap Ac',
        'lang.label': 'Dil',
        'market.title': 'Gerek Zadyny Tap',
        'market.subtitle': 'Netijeleri calt daraltmak ucin acar soz we yerlesis suzguclerini ulanyn.',
        'market.keyword': 'Acar soz',
        'market.keyword_placeholder': 'Kamera, gurallar, ulag, oy...',
        'market.velayat': 'Welayat',
        'market.district': 'Etrap',
        'market.neighborhood': 'Yer / koce',
        'market.all_velayats': 'Ahli welayatlar',
        'market.all_districts': 'Ahli etraplar',
        'market.all_neighborhoods': 'Ahli yerler / koceler',
        'market.all_streets': 'Ahli koceler / sayollar',
        'market.search': 'Gozle',
        'market.clear': 'Arassala',
        'market.showing': '{count} bildiris gorkezilyar{query_suffix}.',
        'market.no_results': 'Su suzguclere layyk bildiris tapylmady.',
        'auth.login_title': 'Howpsuz Giris',
        'auth.login_subtitle': 'HandShake hasabynyza girmek ucin maglumatlarynyzy girizin.',
        'auth.email_address': 'Email salgy',
        'auth.password': 'Parol',
        'auth.remember_me': 'Yatda sakla',
        'auth.forgot_password': 'Acar sozunizi unutdynyzmy?',
        'auth.secure_login': 'Howpsuz Giris',
        'auth.no_account': 'Hasabynyz yokmy?',
        'auth.start_kyc': 'KYC barlagyny basla',
        'auth.recovery_title': 'Howpsuz Parol Dikeldis',
        'auth.recovery_subtitle': 'Bu akym bir gezeklik token talap edýär. Token 20 minutda mohleti gecyar we dine bir gezek ulanylyar.',
        'auth.step1': '1. Dikeldis tokenini sora',
        'auth.step2': '2. Token bilen paroly tazele',
        'auth.email_placeholder': 'Hasabynyzyn emaili',
        'auth.generate_token': 'Token Doret',
        'auth.token_placeholder': 'Bir gezeklik dikeldis tokeni',
        'auth.new_password': 'Taze parol',
        'auth.confirm_new_password': 'Taze paroly tassyklap',
        'auth.reset_password': 'Paroly Tazele',
        'auth.no_email_notice': 'Bu programmada email iberis yok, token serwer loglary arkaly berilyar.',
        'auth.back_to_login': 'Yza dolan',
        'auth.reset_intro': 'Email we taze paroly girizin. Token yok bolsa, ilki token doretmek ucin ugrat.',
        'auth.reset_token': 'Dikeldis tokeni',
        'auth.generate_or_reset': 'Token Doret / Tazele',
        'auth.forgot_intro': 'Gmail/email salgyňyzy giriziň, barlag salgysy ugradylar.',
        'auth.send_verification': 'Barlag emailini ugrat',
        'auth.check_email_msg': 'Hasap bar bolsa, barlag emaili ugradyldy.',
        'auth.email_service_off': 'Serwerde email hyzmaty sazlanmady. Admin bilen habarlaşyň.',
        'auth.reset_from_email': 'Taze parol doret',
        'flash.invalid_login': 'Email/ulanyjy ady ya-da parol nadogry.',
        'flash.email_required': 'Email hokmanydyr.',
        'flash.new_password_len': 'Taze parol azyndan 6 nyshan bolmaly.',
        'flash.passwords_mismatch': 'Parollar gabat gelenok.',
        'flash.no_account_email': 'Bu email bilen hasap tapylmady.',
        'flash.token_generated': 'Token doredildi: {token}. Ony {minutes} minut icinde ulanyn.',
        'flash.invalid_token': 'Token nadogry ya-da mohleti gecdi.',
        'flash.reset_success': 'Parol ustunlikli tazelendi. Taze parol bilen girin.',
    },
    'ru': {
        'nav.search_placeholder': 'Искать что угодно...',
        'nav.marketplace': 'Маркетплейс',
        'nav.messages': 'Сообщения',
        'nav.post_item': 'Добавить товар',
        'nav.edit_profile': 'Редактировать профиль',
        'nav.my_listings': 'Мои объявления',
        'nav.logout': 'Выйти',
        'nav.login': 'Войти',
        'nav.signup': 'Регистрация',
        'lang.label': 'Язык',
        'market.title': 'Найдите то, что нужно',
        'market.subtitle': 'Используйте ключевые слова и фильтры по локации для быстрого поиска.',
        'market.keyword': 'Ключевое слово',
        'market.keyword_placeholder': 'Камера, инструменты, машина, квартира...',
        'market.velayat': 'Велаят',
        'market.district': 'Этрап',
        'market.neighborhood': 'Район / улица',
        'market.all_velayats': 'Все велаяты',
        'market.all_districts': 'Все этрапы',
        'market.all_neighborhoods': 'Все районы / улицы',
        'market.all_streets': 'Все улицы / проспекты',
        'market.search': 'Поиск',
        'market.clear': 'Сброс',
        'market.showing': 'Показано {count} объявлений{query_suffix}.',
        'market.no_results': 'По текущим фильтрам ничего не найдено.',
        'auth.login_title': 'Безопасный вход',
        'auth.login_subtitle': 'Введите данные для входа в аккаунт HandShake.',
        'auth.email_address': 'Email адрес',
        'auth.password': 'Пароль',
        'auth.remember_me': 'Запомнить меня',
        'auth.forgot_password': 'Забыли пароль?',
        'auth.secure_login': 'Безопасный вход',
        'auth.no_account': 'Нет аккаунта?',
        'auth.start_kyc': 'Начать KYC проверку',
        'auth.recovery_title': 'Безопасное восстановление пароля',
        'auth.recovery_subtitle': 'Этот процесс требует одноразовый токен. Токен действует 20 минут и используется один раз.',
        'auth.step1': '1. Запросите токен восстановления',
        'auth.step2': '2. Сбросьте пароль с токеном',
        'auth.email_placeholder': 'Email вашего аккаунта',
        'auth.generate_token': 'Создать токен',
        'auth.token_placeholder': 'Одноразовый токен',
        'auth.new_password': 'Новый пароль',
        'auth.confirm_new_password': 'Подтвердите новый пароль',
        'auth.reset_password': 'Сбросить пароль',
        'auth.no_email_notice': 'Почтовый сервис не настроен, поэтому токен передается через логи сервера/админа.',
        'auth.back_to_login': 'Назад к',
        'auth.reset_intro': 'Введите email и новый пароль. Если токена нет, отправьте форму один раз для генерации.',
        'auth.reset_token': 'Токен сброса',
        'auth.generate_or_reset': 'Создать токен / Сбросить',
        'auth.forgot_intro': 'Введите Gmail/email, и мы отправим ссылку подтверждения.',
        'auth.send_verification': 'Отправить письмо',
        'auth.check_email_msg': 'Если аккаунт существует, письмо подтверждения отправлено.',
        'auth.email_service_off': 'Почтовый сервис не настроен на сервере. Обратитесь к администратору.',
        'auth.reset_from_email': 'Создать новый пароль',
        'flash.invalid_login': 'Неверный email/логин или пароль.',
        'flash.email_required': 'Требуется email.',
        'flash.new_password_len': 'Новый пароль должен быть не менее 6 символов.',
        'flash.passwords_mismatch': 'Пароли не совпадают.',
        'flash.no_account_email': 'Аккаунт с таким email не найден.',
        'flash.token_generated': 'Токен создан: {token}. Используйте его в течение {minutes} минут.',
        'flash.invalid_token': 'Неверный или просроченный токен.',
        'flash.reset_success': 'Пароль успешно обновлен. Войдите с новым паролем.',
    },
}

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


def hash_password_reset_token(raw_token):
    payload = f"{app.secret_key}:{raw_token}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_locale():
    lang = session.get('lang', 'en')
    return lang if lang in SUPPORTED_LANGUAGES else 'en'


def tr(key, **kwargs):
    locale = get_locale()
    value = TRANSLATIONS.get(locale, {}).get(key)
    if value is None:
        value = TRANSLATIONS['en'].get(key, key)
    if kwargs:
        return value.format(**kwargs)
    return value


def is_admin_email(email):
    normalized = (email or '').strip().lower()
    return bool(ADMIN_EMAIL) and normalized == ADMIN_EMAIL


def get_reset_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt='password-reset-v1')


def build_reset_token(user):
    serializer = get_reset_serializer()
    return serializer.dumps({'uid': user.id, 'email': user.email})


def verify_reset_token(token, max_age_seconds):
    serializer = get_reset_serializer()
    try:
        return serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def send_password_reset_email(to_email, reset_link):
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    smtp_from = os.getenv('SMTP_FROM') or smtp_user
    use_tls = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'

    if not smtp_host or not smtp_user or not smtp_pass or not smtp_from:
        return False

    msg = EmailMessage()
    msg['Subject'] = 'HandShake password reset verification'
    msg['From'] = smtp_from
    msg['To'] = to_email
    msg.set_content(
        f"Open this link to reset your password:\n\n{reset_link}\n\n"
        f"This link expires in {PASSWORD_RESET_TOKEN_TTL_MINUTES} minutes."
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if use_tls:
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
    return True


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

    user_columns = {column['name'] for column in inspector.get_columns('user')}
    if 'kyc_status' not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN kyc_status VARCHAR(20) DEFAULT 'pending'"))
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
            price_unit VARCHAR(20) DEFAULT "day",
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
            id, title, price, price_unit, type, description, image_url,
            category, rating, num_ratings, user_id, neighborhood_id
        )
        SELECT
            id, title, price, "day", type, description, image_url,
            category, rating, num_ratings, user_id, neighborhood_id
        FROM item
    """))
    db.session.execute(text('DROP TABLE item'))
    db.session.execute(text('ALTER TABLE item_new RENAME TO item'))
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    db.session.commit()


def update_rent_duration_schema():
    inspector = inspect(db.engine)
    item_columns = {column['name'] for column in inspector.get_columns('item')}
    if 'price_unit' not in item_columns:
        db.session.execute(text('ALTER TABLE item ADD COLUMN price_unit VARCHAR(20) DEFAULT "day"'))
        db.session.commit()
    
    transaction_columns = {column['name'] for column in inspector.get_columns('transaction')}
    if 'duration' not in transaction_columns:
        db.session.execute(text('ALTER TABLE "transaction" ADD COLUMN duration INTEGER DEFAULT 1'))
        db.session.commit()

def apply_database_updates():
    db.create_all()
    update_rent_duration_schema()
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
    kyc_status = db.Column(db.String(20), default='pending') # pending, processing, verified, rejected
    wallet_balance = db.Column(db.Float, default=1000.0) # Mock money for transactions
    items = db.relationship('Item', backref='owner', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    received_messages = db.relationship('Message', foreign_keys='Message.recipient_id', backref='recipient', lazy=True)


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User', backref='password_reset_tokens')


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    price_unit = db.Column(db.String(20), default='day') # 'hour' or 'day'
    deposit_price = db.Column(db.Float, default=0.0) # Added for theft protection
    type = db.Column(db.String(50), nullable=False) # 'rent' or 'sell'
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    category = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Float, default=5.0)
    num_ratings = db.Column(db.Integer, default=1)
    is_available = db.Column(db.Boolean, default=True) # Added to track active rentals
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    neighborhood_id = db.Column(db.Integer, db.ForeignKey('neighborhood.id'), nullable=True)

    @property
    def location_label(self):
        if self.neighborhood:
            return self.neighborhood.full_path
        return "Ashgabat"

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    commission = db.Column(db.Float, default=0.0)
    deposit_amount = db.Column(db.Float, default=0.0) # Escrowed deposit
    total_amount = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Integer, default=1) # Number of hours/days
    status = db.Column(db.String(20), default='active') # active, completed, disputed, returned
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship('User', foreign_keys=[buyer_id], backref='purchases')
    seller = db.relationship('User', foreign_keys=[seller_id], backref='sales')
    item = db.relationship('Item', backref='transactions')

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
    return {
        'pending_chat_request_count': pending_chat_request_count,
        't': tr,
        'current_locale': get_locale(),
        'supported_languages': SUPPORTED_LANGUAGES,
    }


@app.route('/set-language/<lang_code>')
def set_language(lang_code):
    code = (lang_code or '').strip().lower()
    if code in SUPPORTED_LANGUAGES:
        session['lang'] = code
    next_url = request.args.get('next') or request.referrer or url_for('index')
    return redirect(next_url)

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
        identity = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter(
            (User.email == identity) | (User.username == identity)
        ).first()
        if user and check_password_hash(user.password_hash, password):
            if current_user.is_authenticated:
                logout_user()
            login_user(user)
            return redirect(url_for('index'))
        flash(tr('flash.invalid_login'))
    elif current_user.is_authenticated:
        flash('Sign in below to switch to another account.')
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash(tr('flash.email_required'))
            return redirect(url_for('forgot_password'))

        user = User.query.filter_by(email=email).first()
        if user:
            token = build_reset_token(user)
            reset_link = url_for('reset_password', token=token, _external=True)
            try:
                sent = send_password_reset_email(user.email, reset_link)
            except Exception:
                sent = False
                app.logger.exception("Password reset email failed for %s", user.email)
            if not sent:
                app.logger.warning("Email service unavailable. Reset link for %s: %s", user.email, reset_link)
                if ALLOW_LOCAL_RESET_LINK and is_admin_email(user.email):
                    flash(f"Admin local reset link: {reset_link}")
                else:
                    flash(tr('auth.email_service_off'))
                return redirect(url_for('forgot_password', email=email))

        flash(tr('auth.check_email_msg'))
        return redirect(url_for('login'))

    prefill_email = (request.args.get('email') or '').strip().lower()
    return render_template('forgot_password.html', prefill_email=prefill_email)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    payload = verify_reset_token(token, PASSWORD_RESET_TOKEN_TTL_MINUTES * 60)
    if not payload:
        flash(tr('flash.invalid_token'))
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(id=payload.get('uid'), email=payload.get('email')).first()
    if not user:
        flash(tr('flash.no_account_email'))
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        if len(new_password) < 6:
            flash(tr('flash.new_password_len'))
            return redirect(url_for('reset_password', token=token))
        if new_password != confirm_password:
            flash(tr('flash.passwords_mismatch'))
            return redirect(url_for('reset_password', token=token))

        user.password_hash = generate_password_hash(new_password, method='scrypt')
        db.session.commit()
        flash(tr('flash.reset_success'))
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = (request.form.get('email') or "").strip().lower()
        region = (request.form.get('region') or "").strip()
        full_name = (request.form.get('full_name') or "").strip()
        age_value = request.form.get('age')
        password = request.form.get('password') or ""
        confirm_password = request.form.get('confirm_password') or ""

        if not region:
            flash('Please select your region.')
            return redirect(url_for('register'))
        if not full_name:
            flash('Full name is required.')
            return redirect(url_for('register'))
        if not age_value or not age_value.isdigit():
            flash('Valid age is required.')
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

        parsed_age = int(age_value)
        new_user = User(
            username=email.split("@")[0],
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password, method='scrypt'),
            region=region,
            age=parsed_age,
            passport_img=filename,
            kyc_status='processing',
            wallet_balance=1000.0 # Start with some mock money
        )
        db.session.add(new_user)
        db.session.commit()
        if current_user.is_authenticated:
            logout_user()
        flash('Registration complete. We sent your information to admin. Your KYC status is processing.')
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
            price_unit=request.form.get('price_unit', 'day'),
            type=request.form.get('type'), neighborhood_id=neighborhood.id,
            description=request.form.get('description'), image_url=image_url,
            category=request.form.get('category'), user_id=current_user.id
        )
        db.session.add(new_item)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('upload.html', location_tree=get_location_tree())

def parse_price(price_str):
    if not price_str:
        return 0.0
    import re
    cleaned = re.sub(r'[^\d.]', '', price_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

@app.route('/buy/<int:item_id>')
@login_required
def buy_item(item_id):
    item = Item.query.get_or_404(item_id)
    duration = request.args.get('duration', 1, type=int)
    
    if item.user_id == current_user.id:
        flash("You cannot rent/buy your own item!")
        return redirect(url_for('item_detail', item_id=item_id))

    if not item.is_available:
        flash("This item is currently rented out.")
        return redirect(url_for('item_detail', item_id=item_id))

    price_val = parse_price(item.price)
    rental_total = price_val * duration if item.type == 'rent' else price_val
    commission = rental_total * 0.05
    deposit = item.deposit_price or (rental_total * 2 if item.type == 'rent' else 0)
    total_val = rental_total + commission + deposit

    # Create a pending negotiation at the listed price
    new_tx = Transaction(
        buyer_id=current_user.id,
        seller_id=item.user_id,
        item_id=item.id,
        amount=price_val,
        duration=duration,
        status='negotiating',
        commission=commission,
        deposit_amount=deposit,
        total_amount=total_val
    )
    db.session.add(new_tx)
    db.session.commit()
    flash("Rental request sent to the owner! Wait for their approval and meet to scan the QR code.")
    return redirect(url_for('profile', user_id=current_user.id))

@app.route('/negotiate/<int:item_id>', methods=['POST'])
@login_required
def negotiate(item_id):
    item = Item.query.get_or_404(item_id)
    if item.user_id == current_user.id:
        flash("You cannot negotiate with yourself!")
        return redirect(url_for('item_detail', item_id=item_id))

    duration = request.form.get('duration', 1, type=int)
    proposed_price = request.form.get('proposed_price', type=float)

    if not proposed_price:
        flash("Please enter a proposed price.")
        return redirect(url_for('item_detail', item_id=item_id))

    rental_total = proposed_price * duration if item.type == 'rent' else proposed_price
    commission = rental_total * 0.05
    deposit = item.deposit_price or (rental_total * 2 if item.type == 'rent' else 0)
    total_val = rental_total + commission + deposit

    # Create a pending negotiation
    new_tx = Transaction(
        buyer_id=current_user.id,
        seller_id=item.user_id,
        item_id=item.id,
        amount=proposed_price,
        duration=duration,
        status='negotiating',
        commission=commission,
        deposit_amount=deposit,
        total_amount=total_val
    )
    db.session.add(new_tx)
    db.session.commit()
    flash("Negotiation request sent to the owner!")
    return redirect(url_for('profile', user_id=current_user.id))

@app.route('/accept_negotiation/<int:transaction_id>')
@login_required
def accept_negotiation(transaction_id):
    tx = Transaction.query.get_or_404(transaction_id)
    if tx.seller_id != current_user.id:
        flash("Unauthorized.")
        return redirect(url_for('profile', user_id=current_user.id))

    tx.status = 'accepted'
    db.session.commit()
    flash("Deal accepted! Show the QR code to the renter when you meet.")
    return redirect(url_for('profile', user_id=current_user.id))

@app.route('/decline_negotiation/<int:transaction_id>')
@login_required
def decline_negotiation(transaction_id):
    tx = Transaction.query.get_or_404(transaction_id)
    if tx.seller_id != current_user.id and tx.buyer_id != current_user.id:
        flash("Unauthorized.")
        return redirect(url_for('profile', user_id=current_user.id))

    db.session.delete(tx)
    db.session.commit()
    flash("Negotiation cancelled.")
    return redirect(url_for('profile', user_id=current_user.id))

@app.route('/confirm_deal/<int:transaction_id>')
@login_required
def confirm_deal(transaction_id):
    tx = Transaction.query.get_or_404(transaction_id)
    if tx.buyer_id != current_user.id:
        flash("Only the renter can confirm the hand-off.")
        return redirect(url_for('index'))
    
    if tx.status != 'accepted':
        flash("This deal is not ready for confirmation.")
        return redirect(url_for('profile', user_id=current_user.id))

    # Calculate final amounts based on negotiated price
    price_val = tx.amount
    
    # SECURITY: Prevent unverified users from renting expensive items
    if price_val > 100 and current_user.kyc_status != 'verified':
        flash("You must be a verified user to rent high-value items. Please wait for admin approval.")
        return redirect(url_for('profile', user_id=current_user.id))

    duration = tx.duration
    rental_total = price_val * duration if tx.item.type == 'rent' else price_val
    commission = rental_total * 0.05
    deposit = tx.item.deposit_price or (rental_total * 2 if tx.item.type == 'rent' else 0)
    total_val = rental_total + commission + deposit
    
    return render_template('payment.html', item=tx.item, price_val=rental_total, commission=commission, deposit=deposit, total_val=total_val, duration=duration, transaction_id=tx.id)

@app.route('/process_negotiated_payment/<int:transaction_id>', methods=['POST'])
@login_required
def process_negotiated_payment(transaction_id):
    tx = Transaction.query.get_or_404(transaction_id)
    if tx.buyer_id != current_user.id:
        flash("Unauthorized.")
        return redirect(url_for('index'))

    # Recalculate to be sure
    price_val = tx.amount
    duration = tx.duration
    rental_total = price_val * duration if tx.item.type == 'rent' else price_val
    commission = rental_total * 0.05
    deposit = tx.item.deposit_price or (rental_total * 2 if tx.item.type == 'rent' else 0)
    total_val = rental_total + commission + deposit

    if current_user.wallet_balance < total_val:
        flash("Insufficient funds!")
        return redirect(url_for('confirm_deal', transaction_id=tx.id))

    try:
        current_user.wallet_balance -= total_val
        seller = User.query.get(tx.seller_id)
        if seller:
            seller.wallet_balance += rental_total

        tx.item.is_available = False
        
        # Cancel all other pending/accepted negotiations for this item
        Transaction.query.filter(
            Transaction.item_id == tx.item_id,
            Transaction.id != tx.id,
            Transaction.status.in_(['negotiating', 'accepted'])
        ).delete()

        tx.commission = commission
        tx.deposit_amount = deposit
        tx.total_amount = total_val
        tx.status = 'active'
        tx.timestamp = datetime.utcnow()
        db.session.commit()

        flash("Payment successful! HandShake is holding the deposit. Rental started!")
        return redirect(url_for('profile', user_id=current_user.id))
    except Exception as e:
        db.session.rollback()
        flash("Transaction failed.")
        return redirect(url_for('confirm_deal', transaction_id=tx.id))


@app.route('/return_item/<int:transaction_id>')
@login_required
def return_item(transaction_id):
    # This route is used by the SELLER to confirm they got their item back
    tx = Transaction.query.get_or_404(transaction_id)
    if tx.seller_id != current_user.id:
        flash("Only the owner can confirm return.")
        return redirect(url_for('dashboard'))
    
    if tx.status != 'active':
        flash("Invalid action.")
        return redirect(url_for('dashboard'))

    try:
        # Return Deposit to Buyer
        buyer = User.query.get(tx.buyer_id)
        buyer.wallet_balance += tx.deposit_amount
        
        # Mark Item as available
        item = Item.query.get(tx.item_id)
        item.is_available = True
        
        tx.status = 'returned'
        db.session.commit()
        flash("Item return confirmed! Security deposit released back to the renter.")
    except:
        db.session.rollback()
        flash("Error processing return.")
    return redirect(url_for('dashboard'))

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
