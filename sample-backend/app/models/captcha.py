from app.extensions import db


class CaptchaChallenge(db.Model):
    __tablename__ = 'captcha_challenges'

    id = db.Column(db.String(43), primary_key=True)
    answer_digest = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
