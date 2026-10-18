import secrets
import string
import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from argon2 import PasswordHasher

from app.extensions import mail, db
from app.models.user import User, TwoFactorCode
from app.utils.security import generate_random_code, hash_code, verify_code

class MailService:
    def _send_async_email(self, app, msg, code_for_log=None):
        with app.app_context():
            try:
                logging.info(f"Connecting to {app.config.get('MAIL_SERVER')}:{app.config.get('MAIL_PORT')} (SSL: {app.config.get('MAIL_USE_SSL')}, TLS: {app.config.get('MAIL_USE_TLS')})...")
                # Forzar el código a consola para no perder tiempo si el mail tarda
                if code_for_log:
                    logging.info(f"--- [2FA CODE] ---")
                    logging.info(f"USER: {msg.recipients}")
                    logging.info(f"CODE: {code_for_log}")
                    logging.info(f"------------------")
                
                mail.send(msg)
                logging.info(f"Email sent successfully to {msg.recipients}")
            except Exception as e:
                logging.error(f"CRITICAL: Failed to send email to {msg.recipients}: {str(e)}")

    def send_email(self, subject, recipients, template, code_for_log=None, sync=False, attachments=None, **kwargs):
        """
        Envía un correo. Por defecto es asíncrono.
        Si sync=True, se envía en el mismo hilo (bloqueante).
        attachments: Lista de dicts [{'filename': str, 'content_type': str, 'data': bytes}]
        """
        app = current_app._get_current_object()
        msg = Message(subject, recipients=recipients)
        msg.html = render_template(template, **kwargs)
        
        # Agregar adjuntos si existen
        if attachments:
            for att in attachments:
                msg.attach(
                    filename=att['filename'],
                    content_type=att['content_type'],
                    data=att['data']
                )
        
        if sync or app.debug:
            # En modo debug, enviamos síncrono para ver el error de inmediato
            self._send_async_email(app, msg, code_for_log)
        else:
            thr = Thread(target=self._send_async_email, args=(app, msg, code_for_log))
            thr.start()

    def send_ticket_received_email(self, ticket):
        """
        Envía confirmación de ticket al ciudadano.
        """
        from app.models.enums import CATEGORY_MAPPING
        try:
            category_label = CATEGORY_MAPPING.get(ticket.category, ticket.category)
            self.send_email(
                subject=f"Confirmación de Ticket: {ticket.tracking_code}",
                recipients=[ticket.email],
                template='emails/ticket_received.html',
                ticket=ticket,
                category_label=category_label
            )
            logging.info(f"Confirmation email queued for ticket {ticket.tracking_code}")
        except Exception as e:
            logging.error(f"Error preparing ticket email: {e}")

    def send_admin_2fa_code(self, user, code):
        """
        Envía el código 2FA al admin.
        """
        try:
            self.send_email(
                subject="Código de Verificación - Buzón Admin",
                recipients=[user.email],
                template='emails/admin_2fa_code.html',
                code_for_log=code,
                code=code,
                user=user
            )
            logging.info(f"2FA email queued for user {user.id}")
        except Exception as e:
            logging.error(f"Error preparing 2FA email: {e}")

    def fetch_received_emails(self):
        """
        Filtra y descarga correos desde la bandeja de entrada.
        """
        from app.models.contact import ReceivedEmail, Contact
        
        app = current_app._get_current_object()
        server = app.config.get('MAIL_SERVER')
        user = app.config.get('MAIL_USERNAME')
        password = app.config.get('MAIL_PASSWORD')
        
        # Lógica simple de conexión (asumimos servidor IMAP estándar)
        imap_host = server.replace('smtp', 'imap') if server else None
        if not imap_host or not user or not password:
            return 0

        new_count = 0
        try:
            # Conexión SSL (standard for imap.gmail.com etc)
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(user, password)
            mail.select("inbox")

            # Buscar correos de los últimos 7 días para no saturar
            date_filter = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            _, messages = mail.search(None, f'(SINCE "{date_filter}")')

            for num in messages[0].split():
                _, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        uid = num.decode() # Usamos el num como UID temporal para simplicidad
                        
                        # Evitar duplicados
                        if ReceivedEmail.query.filter_by(uid=uid).first():
                            continue

                        # Decodificar Asunto
                        subject_raw = msg.get("Subject", "(Sin Asunto)")
                        subject = subject_raw
                        try:
                            decoded_subject = decode_header(subject_raw)
                            subject_parts = []
                            for part, enc in decoded_subject:
                                if isinstance(part, bytes):
                                    subject_parts.append(part.decode(enc or "utf-8", errors="ignore"))
                                else:
                                    subject_parts.append(part)
                            subject = " ".join(subject_parts)
                        except:
                            pass
                        
                        sender_raw = msg.get("From", "")
                        sender_email = email.utils.parseaddr(sender_raw)[1]

                        # Solo guardar si el remitente está en la agenda
                        contact = Contact.query.filter_by(email=sender_email).first()
                        if not contact:
                            continue

                        # Decodificar nombre del remitente de forma segura
                        sender_name = sender_raw
                        try:
                            decoded_parts = decode_header(sender_raw)
                            decoded_name = ""
                            for part, enc in decoded_parts:
                                if isinstance(part, bytes):
                                    decoded_name += part.decode(enc or "utf-8", errors="ignore")
                                else:
                                    decoded_name += part
                            sender_name = decoded_name
                        except:
                            pass

                        # Extraer cuerpo (simplificado)
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode(errors="ignore")
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode(errors="ignore")

                        new_email = ReceivedEmail(
                            sender_name=sender_name,
                            sender_email=sender_email,
                            subject=subject,
                            body=body,
                            uid=uid,
                            received_at=datetime.now()
                        )
                        db.session.add(new_email)
                        new_count += 1
            
            db.session.commit()
            mail.logout()
            return new_count
        except Exception as e:
            logging.error(f"Error fetching emails: {e}")
            return 0

class AuthService:
    """
    Servicio encargado de la lógica de seguridad y autenticación (2FA generation).
    Separado del MailService para mantener SRP.
    """
    RATE_LIMIT_MINUTES = 1 # Cooldown entre reenvíos de código

    def generate_and_send_2fa(self, user: User, mail_service: MailService):
        """
        Genera un código 2FA seguro, lo hashea, lo guarda en DB y lo envía por mail.
        Verifica rate limits antes de generar uno nuevo.
        """
        # 1. Check Rate Limit (Cooldown)
        last_code = TwoFactorCode.query.filter_by(user_id=user.id)\
            .order_by(TwoFactorCode.created_at.desc()).first()
        
        if last_code:
            delta = datetime.utcnow() - last_code.created_at
            if delta < timedelta(minutes=self.RATE_LIMIT_MINUTES):
                raise ValueError(f"Por favor espere {self.RATE_LIMIT_MINUTES} minuto(s) antes de solicitar un nuevo código.")

        # 2. Generate Secure Code using centralized security util
        code = generate_random_code(length=6, numeric_only=True)
        
        # 3. Hash Code using centralized security util
        code_hash = hash_code(code)
        
        # 4. Save to DB
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        
        # Opcional: Invalidar códigos anteriores del usuario
        # TwoFactorCode.query.filter_by(user_id=user.id).delete()
        
        new_2fa = TwoFactorCode(
            user_id=user.id,
            code_hash=code_hash,
            expires_at=expires_at
        )
        
        db.session.add(new_2fa)
        db.session.commit()
        
        # 5. Send Email
        mail_service.send_admin_2fa_code(user, code)
        
        return True

    def verify_2fa_code(self, user: User, code: str) -> bool:
        """
        Valida que el código sea correcto y no haya expirado.
        Marca el código como consumido si es válido.
        """
        # Buscar códigos válidos no consumidos
        valid_code_entry = TwoFactorCode.query.filter(
            TwoFactorCode.user_id == user.id,
            TwoFactorCode.consumed_at.is_(None),
            TwoFactorCode.expires_at > datetime.utcnow()
        ).order_by(TwoFactorCode.created_at.desc()).first()

        if not valid_code_entry:
            return False

        # Verificar Hash
        if not verify_code(valid_code_entry.code_hash, code):
            # Incrementar intentos fallidos (opcional, para bloqueo)
            valid_code_entry.attempts += 1
            db.session.commit()
            return False

        # Marcar como consumido
        valid_code_entry.consumed_at = datetime.utcnow()
        db.session.commit()
        return True

# Singleton instances
mail_service = MailService()
auth_service = AuthService()


def send_2fa_email(to_email: str, code: str) -> None:
    """
    Standalone function to send 2FA code email.
    Compatible with sample-backend pattern (called directly from routes).
    """
    mail_service.send_email(
        subject="[Buzón Ciudadano] Código de Verificación",
        recipients=[to_email],
        template='emails/admin_2fa_code.html',
        code_for_log=code,
        code=code
    )
