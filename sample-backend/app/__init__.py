import logging
import uuid
import os
from flask import Flask, g, request, send_from_directory
from flask_cors import CORS
from .config import config
from .extensions import db, migrate, login_manager, csrf, mail, limiter, talisman, ma
from .services.minio_service import minio_service
from .error_handlers import register_error_handlers
from .commands import create_admin, rotate_secret, init_bucket
from .redis_utils import init_redis
from .health import health_bp
from .metrics import init_metrics
import logging.config


def _init_limiter_safe(app):
    """Inicializa Flask-Limiter con fallback automático a memory://."""
    redis_available = app.config.get('REDIS_AVAILABLE', False)
    redis_url = app.config.get('REDIS_URL', '')

    if redis_available and redis_url:
        app.config['RATELIMIT_STORAGE_URL'] = redis_url
    else:
        app.config['RATELIMIT_STORAGE_URL'] = 'memory://'

    try:
        limiter.init_app(app)
        app.logger.info(f"Flask-Limiter usando: {app.config['RATELIMIT_STORAGE_URL']}")
    except Exception as exc:
        app.logger.warning(f"Flask-Limiter falló: {exc}. Reintentando con memory://")
        app.config['RATELIMIT_STORAGE_URL'] = 'memory://'
        try:
            limiter.init_app(app)
        except Exception as exc2:
            app.logger.error(f"Flask-Limiter no pudo inicializarse: {exc2}")


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    public_dir = os.path.normpath(os.path.join(app.root_path, '..', 'public'))

    @app.route('/public/<path:filename>')
    def backend_public_file(filename):
        return send_from_directory(public_dir, filename)

    # Configure Logging (Structured)
    if not app.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(module)s: %(message)s',
            handlers=[logging.StreamHandler()]
        )
    else:
        logging.basicConfig(level=logging.DEBUG)

    # Probar Redis y almacenar disponibilidad
    init_redis(app)

    # CORS usando flask-cors (orígenes configurables por env)
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config.get('CORS_ALLOWED_ORIGINS', [])}},
        supports_credentials=True
    )

    # Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    ma.init_app(app)

    # Flask-Limiter con fallback Redis → memory
    _init_limiter_safe(app)

    # Correlation ID por request
    @app.before_request
    def attach_request_id():
        g.request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())

    @app.after_request
    def add_request_id_header(response):
        request_id = getattr(g, 'request_id', None)
        if request_id:
            response.headers['X-Request-ID'] = request_id
        return response

    @app.teardown_request
    def teardown_request(_exc):
        db.session.remove()

    # Initialize Services
    try:
        minio_service.init_app(app)
    except Exception as exc:
        app.logger.warning(f"MinIO no disponible al iniciar: {exc}")

    # Prometheus metrics
    init_metrics(app)

    # Register Error Handlers
    register_error_handlers(app)

    # Register CLI Commands
    app.cli.add_command(create_admin)
    app.cli.add_command(rotate_secret)
    app.cli.add_command(init_bucket)

    # Login Manager Configuration
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    login_manager.login_message_category = 'info'

    # Talisman (Security Headers)
    # Define Content Security Policy
    csp = {
        'default-src': '\'self\'',
        'img-src': ['\'self\'', 'data:', app.config.get('MINIO_PUBLIC_BASE_URL') or '*', 'https://unpkg.com', 'https://*.tile.openstreetmap.org'],
        'script-src': [
            '\'self\'',
            '\'unsafe-inline\'',
            'https://cdn.tailwindcss.com',
            'https://cdnjs.cloudflare.com',
            'https://unpkg.com'
        ],
        'style-src': [
            '\'self\'',
            '\'unsafe-inline\'',
            'https://cdnjs.cloudflare.com',
            'https://fonts.googleapis.com',
            'https://unpkg.com'
        ],
        'font-src': [
            '\'self\'',
            'https://fonts.gstatic.com'
        ]
    }
    
    force_https = (config_name == 'production')
    
    talisman.init_app(
        app, 
        content_security_policy=csp, 
        force_https=force_https
    )

    # Register Blueprints
    csrf.exempt(health_bp)
    app.register_blueprint(health_bp)

    from .routes.public import public_bp
    from .routes.admin import admin_bp

    csrf.exempt(public_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Context Processor for Templates
    from .models.enums import STATUS_TRANSLATIONS, CATEGORY_MAPPING
    
    @app.context_processor
    def inject_enums():
        return dict(
            STATUS_TRANSLATIONS=STATUS_TRANSLATIONS,
            CATEGORY_MAPPING=CATEGORY_MAPPING
        )

    # Date Filter
    @app.template_filter('date_es')
    def date_es_filter(dt):
        if not dt: return ''
        months = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return f"{dt.day} de {months[dt.month-1]} de {dt.year}, {dt.strftime('%H:%M')}"

    return app
