"""Arranque local de FastAPI: python asgi.py."""
import argparse
import os

import config  # Carga .env antes de configurar Uvicorn.


def main(argv=None):
    parser = argparse.ArgumentParser(description="Iniciar la API de Gianna con Uvicorn.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--reload", action="store_true", help="Recargar código durante desarrollo.")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    import uvicorn
    uvicorn.run("main:app", host=args.host, port=args.port, workers=1, reload=args.reload,
                proxy_headers=True, forwarded_allow_ips=os.getenv("PROXY_TRUSTED_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
