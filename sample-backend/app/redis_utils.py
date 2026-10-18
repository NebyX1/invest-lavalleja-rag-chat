import os
from typing import Mapping
from urllib.parse import quote

import redis

_REDIS_PROBE_TIMEOUT = 2


def build_redis_url_from_env(env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ

    redis_url = (source.get("REDIS_URL") or "").strip()
    if redis_url:
        return redis_url

    host = (source.get("REDIS_HOST") or "redis").strip()
    port = (source.get("REDIS_PORT") or "6379").strip()
    db = (source.get("REDIS_DB") or "0").strip()
    password = source.get("REDIS_PASSWORD")

    if password:
        encoded_password = quote(password, safe="")
        return f"redis://:{encoded_password}@{host}:{port}/{db}"

    return f"redis://{host}:{port}/{db}"


def is_redis_available(
    redis_url: str | None,
    timeout_seconds: int = _REDIS_PROBE_TIMEOUT,
) -> tuple[bool, str | None]:
    if not redis_url:
        return False, "Redis URL vacía"

    try:
        client = redis.from_url(
            redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        client.ping()
        return True, None
    except Exception as exc:
        return False, str(exc)


def init_redis(app) -> bool:
    """
    Intenta conectar a Redis usando REDIS_URL de la configuración de la app.
    Si falla, loguea un WARNING y deja REDIS_AVAILABLE = False.
    Nunca lanza excepciones: es seguro llamar en create_app().
    """
    redis_url = app.config.get('REDIS_URL', '').strip()

    if not redis_url:
        app.logger.warning("REDIS_URL no configurada. Redis no estará disponible.")
        app.config['REDIS_AVAILABLE'] = False
        return False

    try:
        client = redis.from_url(
            redis_url,
            socket_connect_timeout=_REDIS_PROBE_TIMEOUT,
            socket_timeout=_REDIS_PROBE_TIMEOUT,
        )
        client.ping()
        app.config['REDIS_AVAILABLE'] = True
        app.logger.info(f"Redis disponible en: {redis_url}")
        return True
    except Exception as exc:
        app.config['REDIS_AVAILABLE'] = False
        app.logger.warning(
            f"Redis no disponible ({redis_url}): {exc}. "
            "Rate limiting usando memoria local."
        )
        return False
