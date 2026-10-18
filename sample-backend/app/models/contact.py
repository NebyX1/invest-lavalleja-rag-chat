from datetime import datetime
from app.extensions import db

class Contact(db.Model):
    """
    Agenda de contactos (Municipios / Direcciones).
    """
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Contact {self.name}>'

class ReceivedEmail(db.Model):
    """
    Registro de correos externos recibidos desde direcciones agendadas.
    """
    __tablename__ = 'received_emails'

    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(100))
    sender_email = db.Column(db.String(255), nullable=False, index=True)
    subject = db.Column(db.String(255))
    body = db.Column(db.Text)
    uid = db.Column(db.String(100), unique=True) # ID único del servidor de correo para evitar duplicados
    received_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class EmailLog(db.Model):
    """
    Registro de correos externos enviados a las direcciones/municipios.
    """
    __tablename__ = 'sent_emails'

    id = db.Column(db.Integer, primary_key=True)
    recipient_name = db.Column(db.String(100), nullable=False)
    recipient_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    sent_by = db.relationship('User', backref='sent_emails')
