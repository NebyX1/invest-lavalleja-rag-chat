from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from app.models.enums import TicketStatus

class UpdateTicketStatusForm(FlaskForm):
    # Usamos s.value para el valor enviado y s.label para el texto mostrado
    status = SelectField('Estado', choices=[(s.value, s.label) for s in TicketStatus], validators=[DataRequired(message="Campo obligatorio")])
    note = TextAreaField('Nota Interna', validators=[Length(max=500, message="Máximo 500 caracteres")])
    submit = SubmitField('Actualizar Ticket')

class ContactForm(FlaskForm):
    name = StringField('Nombre de la Dirección / Municipio', validators=[DataRequired(message="Campo obligatorio"), Length(max=100)])
    email = StringField('Correo Electrónico', validators=[DataRequired(message="Campo obligatorio"), Email(message="Email inválido")])
    submit = SubmitField('Guardar en Agenda')

class SendEmailForm(FlaskForm):
    contact_id = SelectField('Destinatario (Agenda)', coerce=int, validators=[DataRequired(message="Debe seleccionar un destinatario")])
    ticket_ids = SelectMultipleField('Tickets Relacionados (Pendientes)', coerce=str)
    subject = StringField('Asunto', validators=[DataRequired(message="Campo obligatorio"), Length(max=255)])
    message = TextAreaField('Mensaje / Cuerpo del Correo', validators=[DataRequired(message="Campo obligatorio")])
    submit = SubmitField('Enviar Correo')


class AdminUserCreateForm(FlaskForm):
    username = StringField(
        'Nombre de usuario',
        validators=[
            DataRequired(message='Campo obligatorio'),
            Length(min=3, max=64, message='Entre 3 y 64 caracteres'),
        ],
    )
    email = StringField(
        'Correo electrónico',
        validators=[
            DataRequired(message='Campo obligatorio'),
            Email(message='Email inválido'),
            Length(max=255),
        ],
    )
    password = PasswordField(
        'Contraseña temporal',
        validators=[
            DataRequired(message='Campo obligatorio'),
            Length(min=8, max=128, message='Mínimo 8 caracteres'),
        ],
    )
    confirm_password = PasswordField(
        'Confirmar contraseña',
        validators=[
            DataRequired(message='Campo obligatorio'),
            EqualTo('password', message='Las contraseñas no coinciden'),
        ],
    )
    is_superuser = BooleanField('Crear como super admin')
    submit = SubmitField('Crear administrador')


class AdminUserUpdateForm(FlaskForm):
    username = StringField(
        'Nombre de usuario',
        validators=[
            DataRequired(message='Campo obligatorio'),
            Length(min=3, max=64, message='Entre 3 y 64 caracteres'),
        ],
    )
    email = StringField(
        'Correo electrónico',
        validators=[
            DataRequired(message='Campo obligatorio'),
            Email(message='Email inválido'),
            Length(max=255),
        ],
    )
    password = PasswordField(
        'Nueva contraseña',
        validators=[
            Optional(),
            Length(min=8, max=128, message='Mínimo 8 caracteres'),
        ],
    )
    confirm_password = PasswordField(
        'Confirmar nueva contraseña',
        validators=[
            Optional(),
            EqualTo('password', message='Las contraseñas no coinciden'),
        ],
    )
    is_active = BooleanField('Usuario activo')
    submit = SubmitField('Guardar cambios')


class DeleteUserForm(FlaskForm):
    submit = SubmitField('Eliminar usuario')
