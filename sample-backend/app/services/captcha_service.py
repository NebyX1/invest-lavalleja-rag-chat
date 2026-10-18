import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app
from app.extensions import db
from app.models.captcha import CaptchaChallenge

TTL_SECONDS = 600


def answer_digest(challenge_id, answer):
    return hmac.new(
        current_app.config['SECRET_KEY'].encode(),
        f'citizen-captcha:{challenge_id}:{answer}'.encode(),
        hashlib.sha256,
    ).hexdigest()


def create_challenge():
    now = datetime.utcnow()
    CaptchaChallenge.query.filter(CaptchaChallenge.expires_at <= now).delete()
    left, right = secrets.randbelow(20) + 1, secrets.randbelow(20) + 1
    challenge_id = secrets.token_urlsafe(32)
    db.session.add(CaptchaChallenge(
        id=challenge_id, answer_digest=answer_digest(challenge_id, str(left + right)),
        expires_at=now + timedelta(seconds=TTL_SECONDS),
    ))
    db.session.commit()
    return {'id': challenge_id, 'question': f'{left} + {right}', 'expires_in': TTL_SECONDS}


def consume_challenge(challenge_id, answer):
    """Atomic one-use claim. Success commits with the ticket; rollback allows retry.

    An incorrect answer consumes the challenge immediately. No worker-local state
    or new Redis dependency; all workers share the existing SQL database.
    """
    if not isinstance(challenge_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge_id):
        return False
    if not isinstance(answer, str) or not re.fullmatch(r'[0-9]{1,2}', answer.strip()):
        return False
    digest = answer_digest(challenge_id, str(int(answer.strip())))
    valid = CaptchaChallenge.query.filter(
        CaptchaChallenge.id == challenge_id,
        CaptchaChallenge.answer_digest == digest,
        CaptchaChallenge.expires_at > datetime.utcnow(),
    ).delete(synchronize_session=False)
    if valid:
        return True
    CaptchaChallenge.query.filter_by(id=challenge_id).delete(synchronize_session=False)
    db.session.commit()
    return False
