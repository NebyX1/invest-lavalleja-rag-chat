"""Comprueba conexión, TLS y credenciales SMTP sin enviar mensajes ni mostrar secretos."""
import os
import smtplib
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: F401: carga backend/.env respetando el entorno del contenedor


def main():
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "t")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
    host = os.getenv("MAIL_SERVER")
    if not host or use_ssl == use_tls:
        sys.exit("Configurá MAIL_SERVER y exactamente uno de MAIL_USE_TLS o MAIL_USE_SSL.")
    port = int(os.getenv("MAIL_PORT", "465" if use_ssl else "587"))
    context = ssl.create_default_context()
    try:
        client = smtplib.SMTP_SSL(host, port, context=context, timeout=20) if use_ssl else smtplib.SMTP(host, port, timeout=20)
        with client as smtp:
            if use_tls:
                smtp.starttls(context=context)
            if os.getenv("MAIL_USERNAME"):
                smtp.login(os.environ["MAIL_USERNAME"], os.getenv("MAIL_PASSWORD", ""))
            smtp.noop()
    except smtplib.SMTPAuthenticationError as exc:
        sys.exit(f"El servidor SMTP rechazó la autenticación (código {exc.smtp_code}). No se enviaron mensajes.")
    except Exception as exc:
        sys.exit(f"No se pudo verificar SMTP ({type(exc).__name__}). No se enviaron mensajes.")
    print("SMTP verificado: conexión cifrada y autenticación correctas. No se enviaron mensajes.")


if __name__ == "__main__":
    main()
