from flask import render_template, redirect, url_for, flash, request, session, abort, Response, current_app
from flask_login import login_user, login_required, logout_user, current_user
from datetime import datetime
import csv
import io
import random
import secrets

from app.extensions import db, limiter, login_manager
from app.models.user import User, TwoFactorCode
from app.models.ticket import Ticket, TicketAttachment, TicketStatus, TicketStatusHistory
from app.models.audit import ActivityLog
from app.models.contact import Contact, EmailLog, ReceivedEmail
from app.forms.admin import (
    AdminUserCreateForm,
    AdminUserUpdateForm,
    ContactForm,
    DeleteUserForm,
    SendEmailForm,
    UpdateTicketStatusForm,
)
from app.services.mail_service import send_2fa_email, mail_service
from app.services.minio_service import minio_service
from app.services.localizacion_service import (
    DEFAULT_ACTIVE_STATUSES,
    STATUS_LABEL,
    compute_summary,
    export_tickets_csv,
    filters_to_query_string,
    get_distinct_areas,
    get_distinct_categories,
    get_localizar_filters,
    query_tickets_for_map,
    serialize_markers,
)
from app.utils.logging_helper import log_activity

from . import admin_bp

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def require_superuser():
    if current_user.is_superuser:
        return

    log_activity(
        action='UNAUTHORIZED_ACCESS',
        details='Intento de acceso a gestión de administradores sin privilegios.',
        user=current_user,
    )
    abort(403)


def user_has_management_history(user):
    return bool(user.status_changes or user.sent_emails or user.activity_logs)


def active_superuser_count():
    return User.query.filter_by(is_superuser=True, is_active=True).count()

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'GET':
        if current_user.is_authenticated:
            return redirect(url_for('admin.dashboard'))
        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        session['captcha_result'] = num1 + num2
        captcha_question = f"¿Cuánto es {num1} + {num2}?"
        return render_template('admin/login.html', captcha_question=captcha_question)

    # POST
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    captcha_answer = request.form.get('captcha', '')

    stored_captcha = session.get('captcha_result')
    if not stored_captcha or str(captcha_answer) != str(stored_captcha):
        session.pop('captcha_result', None)
        flash('Captcha incorrecto. Intenta de nuevo.', 'error')
        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        session['captcha_result'] = num1 + num2
        captcha_question = f"¿Cuánto es {num1} + {num2}?"
        return render_template('admin/login.html', captcha_question=captcha_question)

    session.pop('captcha_result', None)

    user = User.query.filter_by(email=email).first()
    if user and user.is_active and user.check_password(password):
        code = ''.join([secrets.choice('0123456789') for _ in range(6)])
        tf_code = TwoFactorCode(user_id=user.id, code=code)
        db.session.add(tf_code)
        db.session.commit()
        send_2fa_email(user.email, code)
        session['2fa_user_id'] = user.id
        flash('Código de verificación enviado a tu correo.', 'info')
        return redirect(url_for('admin.verify_2fa'))

    # Mensaje genérico para evitar user enumeration
    flash('Email o contraseña inválidos.', 'error')
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    session['captcha_result'] = num1 + num2
    captcha_question = f"¿Cuánto es {num1} + {num2}?"
    return render_template('admin/login.html', captcha_question=captcha_question)

@admin_bp.route('/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_2fa():
    user_id = session.get('2fa_user_id')
    if not user_id:
        return redirect(url_for('admin.login'))

    user = User.query.get(user_id)
    if not user:
        session.pop('2fa_user_id', None)
        return redirect(url_for('admin.login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        tf_code = TwoFactorCode.query.filter_by(user_id=user.id, consumed_at=None) \
            .order_by(TwoFactorCode.created_at.desc()).first()

        if tf_code and tf_code.verify_code(code):
            tf_code.consumed_at = datetime.utcnow()
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            login_user(user)
            log_activity(
                action='LOGIN',
                details='Inicio de sesión exitoso con 2FA',
                user=user
            )
            session.pop('2fa_user_id', None)
            flash('Sesión iniciada correctamente.', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Código inválido o expirado.', 'error')

    return render_template('admin/verify_2fa.html')

@admin_bp.route('/logout')
@login_required
def logout():
    log_activity(
        action='LOGOUT',
        details='Cierre de sesión manual',
        user=current_user
    )
    logout_user()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    # Stats counters
    stats = {
        'NEW': Ticket.query.filter_by(status=TicketStatus.NEW).count(),
        'IN_PROGRESS': Ticket.query.filter_by(status=TicketStatus.IN_PROGRESS).count(),
        'RESOLVED': Ticket.query.filter_by(status=TicketStatus.RESOLVED).count(),
        'ARCHIVED': Ticket.query.filter_by(status=TicketStatus.ARCHIVED).count(),
    }
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/tickets')
@login_required
def tickets_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    search_query = request.args.get('q')

    query = filtered_tickets_query(status_filter, search_query)

    pagination = query.paginate(page=page, per_page=20)
    
    return render_template(
        'admin/tickets.html', 
        tickets=pagination, 
        current_status=status_filter
    )


def filtered_tickets_query(status_filter, search_query):
    query = Ticket.query

    if status_filter and status_filter in TicketStatus.__members__:
        query = query.filter_by(status=TicketStatus(status_filter))

    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            (Ticket.tracking_code.like(search)) |
            (Ticket.email.like(search))
        )

    return query.order_by(Ticket.created_at.desc())


@admin_bp.route('/tickets/export.csv')
@login_required
def tickets_export_csv():
    status_filter = request.args.get('status')
    search_query = request.args.get('q')
    tickets = filtered_tickets_query(status_filter, search_query).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID', 'Código de seguimiento', 'Estado', 'Municipio o destino',
        'Categoría', 'Nombre completo', 'Correo electrónico', 'Latitud',
        'Longitud', 'Fecha de creación', 'Fecha de actualización',
        'Dirección IP', 'Agente de usuario',
    ])

    for ticket in tickets:
        writer.writerow([
            ticket.id,
            ticket.tracking_code,
            ticket.status.label,
            ticket.municipality_or_destination,
            ticket.category,
            ticket.full_name,
            ticket.email,
            ticket.location_lat if ticket.location_lat is not None else '',
            ticket.location_lng if ticket.location_lng is not None else '',
            (
                ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')
                if ticket.created_at else ''
            ),
            (
                ticket.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                if ticket.updated_at else ''
            ),
            ticket.ip_address or '',
            ticket.user_agent or '',
        ])

    log_activity(
        action='EXPORT_TICKETS_CSV',
        details=(
            f'Exportación CSV de tickets: {len(tickets)} resultado(s), '
            f'estado={status_filter or "todos"}, '
            f'búsqueda={search_query or "sin filtro"}'
        ),
        user=current_user,
    )

    filename = (
        f"tickets_extracto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )

@admin_bp.route('/tickets/<int:id>', methods=['GET'])
@login_required
def ticket_detail(id):
    ticket = Ticket.query.get_or_404(id)
    form = UpdateTicketStatusForm(status=ticket.status.value)
    
    # Generar URLs para adjuntos
    files_urls = []
    for attachment in ticket.attachments:
        url = minio_service.get_file_url(attachment.object_key)
        files_urls.append({
            'name': attachment.file_name,
            'url': url,
            'size': attachment.size_bytes
        })

    return render_template(
        'admin/ticket_detail.html', 
        ticket=ticket, 
        form=form,
        files_urls=files_urls
    )

@admin_bp.route('/tickets/<int:id>/update', methods=['POST'])
@login_required
def update_ticket_status(id):
    ticket = Ticket.query.get_or_404(id)
    form = UpdateTicketStatusForm()
    
    if form.validate_on_submit():
        new_status = form.status.data
        note = form.note.data
        
        if new_status != ticket.status.value or note:
            # Registrar historial
            history = TicketStatusHistory(
                ticket_id=ticket.id,
                old_status=ticket.status.value,
                new_status=new_status,
                changed_by_user_id=current_user.id,
                note=note
            )
            db.session.add(history)
            
            # Actualizar ticket
            ticket.status = TicketStatus(new_status)
            db.session.commit()

            # Registrar Actividad de Gestión
            log_activity(
                action='UPDATE_TICKET',
                details=f'Cambio de estado del ticket #{ticket.tracking_code} a {new_status}. Nota: {note[:50]}...',
                user=current_user
            )
            
            flash('Ticket actualizado correctamente.', 'success')
            
            # Opcional: Enviar correo al ciudadano notificando cambio de estado
            
    return redirect(url_for('admin.ticket_detail', id=ticket.id))

@admin_bp.route('/logs')
@login_required
def view_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action')
    user_filter = request.args.get('username')
    date_filter = request.args.get('date')

    query = ActivityLog.query

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)
    if user_filter:
        query = query.filter(ActivityLog.username == user_filter)
    if date_filter:
        query = query.filter(db.func.date(ActivityLog.created_at) == date_filter)

    pagination = query.order_by(ActivityLog.created_at.desc()).paginate(page=page, per_page=50)
    logs = pagination.items

    actions = db.session.query(ActivityLog.action).distinct().all()
    actions = sorted([a[0] for a in actions])

    users = db.session.query(ActivityLog.username).distinct().all()
    users = sorted([u[0] for u in users if u[0]])

    return render_template(
        'admin/audit_logs.html',
        logs=logs,
        pagination=pagination,
        actions=actions,
        users=users,
        current_action=action_filter,
        current_username=user_filter,
        current_date=date_filter
    )

@admin_bp.route('/logs/export')
@login_required
def export_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de exportar logs sin privilegios de super admin.',
            user=current_user
        )
        abort(403)

    action_filter = request.args.get('action')
    user_filter = request.args.get('username')
    date_filter = request.args.get('date')

    query = ActivityLog.query

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)
    if user_filter:
        query = query.filter(ActivityLog.username == user_filter)
    if date_filter:
        query = query.filter(db.func.date(ActivityLog.created_at) == date_filter)

    logs = query.order_by(ActivityLog.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Timestamp', 'Usuario', 'Acción', 'Detalles', 'IP Address', 'User Agent'])

    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.username or (log.user.email if log.user else 'Anónimo'),
            log.action,
            log.details,
            log.ip_address,
            log.user_agent
        ])

    output.seek(0)
    filename = f"auditoria_extracto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={filename}'}
    )


@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    require_superuser()

    create_form = AdminUserCreateForm(prefix='create')
    delete_form = DeleteUserForm(prefix='delete')

    if create_form.validate_on_submit():
        username = create_form.username.data.strip()
        email = create_form.email.data.strip().lower()

        existing_email = User.query.filter(
            db.func.lower(User.email) == email
        ).first()
        existing_username = User.query.filter(
            db.func.lower(User.username) == username.lower()
        ).first()

        if existing_email:
            flash('Ya existe un usuario con ese correo.', 'error')
        elif existing_username:
            flash('Ya existe un usuario con ese nombre.', 'error')
        else:
            user = User(
                username=username,
                email=email,
                is_active=True,
                is_superuser=create_form.is_superuser.data,
            )
            user.set_password(create_form.password.data)
            db.session.add(user)
            db.session.commit()

            role_label = 'Super Admin' if user.is_superuser else 'Administrador'

            log_activity(
                action='CREATE_ADMIN_USER',
                details=(
                    f'{role_label} creado: {user.username} ({user.email})'
                ),
                user=current_user,
            )
            flash(f'{role_label} creado correctamente.', 'success')
            return redirect(url_for('admin.manage_users'))

    users = User.query.order_by(
        User.is_active.desc(),
        User.is_superuser.desc(),
        User.created_at.desc(),
    ).all()
    return render_template(
        'admin/users.html',
        create_form=create_form,
        delete_form=delete_form,
        users=users,
    )


@admin_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    require_superuser()

    user = User.query.get_or_404(id)
    form = AdminUserUpdateForm(prefix='edit', obj=user)
    delete_form = DeleteUserForm(prefix='delete')

    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()

        existing_email = User.query.filter(
            db.func.lower(User.email) == email,
            User.id != user.id,
        ).first()
        existing_username = User.query.filter(
            db.func.lower(User.username) == username.lower(),
            User.id != user.id,
        ).first()

        if existing_email:
            flash('Ya existe un usuario con ese correo.', 'error')
        elif existing_username:
            flash('Ya existe un usuario con ese nombre.', 'error')
        elif user.id == current_user.id and not form.is_active.data:
            flash(
                'No puedes desactivar tu propio usuario mientras tienes la sesión activa.',
                'error',
            )
        elif user.is_superuser and not form.is_active.data and active_superuser_count() <= 1:
            flash(
                'No puedes desactivar al último super admin activo.',
                'error',
            )
        else:
            user.username = username
            user.email = email
            user.is_active = form.is_active.data

            if form.password.data:
                user.set_password(form.password.data)

            db.session.commit()

            log_activity(
                action='UPDATE_ADMIN_USER',
                details=(
                    f'Usuario de panel actualizado: {user.username} ({user.email})'
                ),
                user=current_user,
            )
            flash('Usuario actualizado correctamente.', 'success')
            return redirect(url_for('admin.manage_users'))

    return render_template(
        'admin/user_edit.html',
        delete_form=delete_form,
        form=form,
        managed_user=user,
    )


@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
def delete_user(id):
    require_superuser()

    form = DeleteUserForm(prefix='delete')
    if not form.validate_on_submit():
        abort(400)

    user = User.query.get_or_404(id)

    if user.id == current_user.id:
        flash('No puedes eliminar tu propio usuario activo.', 'error')
        return redirect(url_for('admin.manage_users'))

    if user.is_superuser and active_superuser_count() <= 1:
        flash('No puedes eliminar al último super admin activo.', 'error')
        return redirect(url_for('admin.manage_users'))

    if user_has_management_history(user):
        user.is_active = False
        db.session.commit()

        log_activity(
            action='DEACTIVATE_ADMIN_USER',
            details=(
                f'Usuario de panel desactivado por historial asociado: '
                f'{user.username} ({user.email})'
            ),
            user=current_user,
        )
        flash(
            'El usuario tenía historial asociado y fue desactivado para '
            'conservar la auditoría.',
            'info',
        )
    else:
        username = user.username
        email = user.email
        db.session.delete(user)
        db.session.commit()

        log_activity(
            action='DELETE_ADMIN_USER',
            details=f'Usuario de panel eliminado: {username} ({email})',
            user=current_user,
        )
        flash('Usuario eliminado correctamente.', 'success')

    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():
    form = ContactForm()
    if form.validate_on_submit():
        contact = Contact(name=form.name.data, email=form.email.data)
        db.session.add(contact)
        db.session.commit()
        
        log_activity(
            action='CREATE_CONTACT',
            details=f'Añadido contacto: {contact.name} ({contact.email})',
            user=current_user
        )
        flash('Contacto guardado en la agenda.', 'success')
        return redirect(url_for('admin.agenda'))
    
    contacts = Contact.query.order_by(Contact.name.asc()).all()
    return render_template('admin/agenda.html', form=form, contacts=contacts)

@admin_bp.route('/email/send', methods=['GET', 'POST'])
@login_required
def send_email():
    contact_id = request.args.get('contact_id', type=int)
    form = SendEmailForm()
    
    # Poblar el desplegable de contactos
    contacts = Contact.query.order_by(Contact.name.asc()).all()
    form.contact_id.choices = [(c.id, c.name) for c in contacts]

    # Poblar el multiselect de tickets pendientes con una consulta específica de columnas
    pending_data = db.session.query(Ticket.id, Ticket.description, Ticket.category).filter(
        Ticket.status == TicketStatus.NEW
    ).order_by(Ticket.created_at.desc()).all()
    
    form.ticket_ids.choices = [(str(t.id), f"#{t.id} [{t.category}] - {t.description[:50]}...") for t in pending_data]
    
    # Si viene un contact_id por URL (desde Agenda), pre-seleccionamos
    if request.method == 'GET' and contact_id:
        form.contact_id.data = contact_id
    
    if form.validate_on_submit():
        contact = Contact.query.get(form.contact_id.data)
        if contact:
            try:
                # Obtener detalles de los tickets seleccionados para el correo
                selected_tickets = []
                attachments_to_send = []
                
                if form.ticket_ids.data:
                    selected_tickets = Ticket.query.filter(Ticket.id.in_(form.ticket_ids.data)).all()
                    
                    # Recolectar adjuntos de estos tickets
                    for ticket in selected_tickets:
                        for att in ticket.attachments:
                            file_content = minio_service.get_file_content(att.object_key)
                            if file_content:
                                attachments_to_send.append({
                                    'filename': att.file_name,
                                    'content_type': att.content_type,
                                    'data': file_content
                                })

                # Enviar el mail real usando el servicio existente
                mail_service.send_email(
                    subject=form.subject.data,
                    recipients=[contact.email],
                    template='emails/internal_communication.html',
                    title=form.subject.data,
                    message=form.message.data,
                    tickets=selected_tickets,
                    attachments=attachments_to_send
                )
                
                # Registrar el log del email (podemos guardar los IDs de los tickets en el body o una tabla nueva, 
                # por ahora los incluiremos en el detalle del log)
                ticket_info = f" | Tickets: {', '.join(form.ticket_ids.data)}" if form.ticket_ids.data else ""
                
                email_log = EmailLog(
                    recipient_name=contact.name,
                    recipient_email=contact.email,
                    subject=form.subject.data,
                    body=form.message.data + ticket_info,
                    sent_by_id=current_user.id
                )
                db.session.add(email_log)
                db.session.commit()
                
                log_activity(
                    action='SEND_INTERNAL_EMAIL',
                    details=f'Correo enviado a {contact.name} ({contact.email}) - Asunto: {form.subject.data}',
                    user=current_user
                )
                
                flash(f'Correo enviado correctamente a {contact.name}.', 'success')
                return redirect(url_for('admin.email_logs'))
            except Exception as e:
                flash(f'Error al enviar el correo: {str(e)}', 'error')
    
    return render_template('admin/send_email.html', form=form)

@admin_bp.route('/email/logs')
@login_required
def email_logs():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs de correos enviados sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    logs = EmailLog.query.order_by(EmailLog.sent_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/email_logs.html', logs=logs)

@admin_bp.route('/email/received')
@login_required
def email_received():
    if not current_user.is_superuser:
        log_activity(
            action='UNAUTHORIZED_ACCESS',
            details='Intento de acceso a logs de correos recibidos sin privilegios de super admin.',
            user=current_user
        )
        abort(403)
    page = request.args.get('page', 1, type=int)
    
    # Solo mostrar si el remitente está en la agenda (Contact)
    contacts = Contact.query.all()
    contact_emails = [c.email for c in contacts]
    contacts_name_map = {c.email: c.name for c in contacts}
    
    query = ReceivedEmail.query.filter(ReceivedEmail.sender_email.in_(contact_emails))
    
    emails = query.order_by(ReceivedEmail.received_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/email_received.html', emails=emails, contacts_name_map=contacts_name_map)

@admin_bp.route('/email/sync')
@login_required
def email_sync():
    """Trigger manual de sincronización de correos."""
    count = mail_service.fetch_received_emails()
    if count > 0:
        flash(f'¡Sincronización completa! Se recibieron {count} correos nuevos.', 'success')
    else:
        flash('No hay correos nuevos de las direcciones agendadas.', 'info')
    return redirect(url_for('admin.email_received'))



# =====================================================================
# Módulo "Localizar Denuncias" — mapa geoespacial en panel admin.
# El backend serializa los tickets a JSON y el template renderiza el mapa
# con Leaflet JS directo desde unpkg.com (ya permitido por la CSP del
# proyecto). No se publica nada en el frontend React; solo dentro del
# admin Flask.
# =====================================================================

def _localizar_active_status_set(filters):
    """Conjunto (frozenset) de estados activos para comparar con defaults."""
    return frozenset(filters.active_status_values())


@admin_bp.route('/localizar-denuncias')
@login_required
def localizar_denuncias():
    """Renderiza el panel de mapa con filtros y resumen analítico."""
    filters = get_localizar_filters(request.args)
    tickets = query_tickets_for_map(filters)
    summary = compute_summary(tickets, filters)

    # Serializar markers a JSON para que Leaflet JS los renderice en el template.
    markers = serialize_markers(tickets)

    # Bandera para el botón "Limpiar filtros": sólo cuando los filtros difieren del default.
    is_default_filters = (
        _localizar_active_status_set(filters) == frozenset(DEFAULT_ACTIVE_STATUSES)
        and not filters.date_from
        and not filters.date_to
        and not filters.category
        and not filters.area
        and not filters.q
        and filters.has_photo == 'all'
    )

    return render_template(
        'admin/localizar_denuncias.html',
        filters=filters,
        tickets=tickets,
        summary=summary,
        markers_json=markers,
        status_label=STATUS_LABEL,
        default_active_statuses=DEFAULT_ACTIVE_STATUSES,
        is_default_filters=is_default_filters,
        distinct_areas=get_distinct_areas(),
        distinct_categories=get_distinct_categories(),
        csv_query_string=filters_to_query_string(filters),
    )


@admin_bp.route('/localizar-denuncias/export.csv')
@login_required
def localizar_denuncias_export_csv():
    """Descarga CSV analítico respetando los filtros activos."""
    filters = get_localizar_filters(request.args)
    csv_bytes, filename = export_tickets_csv(filters)

    log_activity(
        action='EXPORT_LOCALIZAR_CSV',
        details=(
            f'Exportación CSV de Localizar Denuncias '
            f'({summary_size_hint(filters)} filtros aplicados)'
        ),
        user=current_user,
    )

    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
        },
    )


def summary_size_hint(filters) -> str:
    """Texto compacto para el log de auditoría."""
    parts = []
    if filters.statuses:
        parts.append(f"estados={','.join(filters.statuses)}")
    if filters.date_from:
        parts.append(f"desde={filters.date_from:%Y-%m-%d}")
    if filters.date_to:
        parts.append(f"hasta={filters.date_to:%Y-%m-%d}")
    if filters.area:
        parts.append(f"area={filters.area}")
    if filters.category:
        parts.append(f"categoria={filters.category}")
    if filters.has_photo and filters.has_photo != 'all':
        parts.append(f"foto={filters.has_photo}")
    if filters.q:
        parts.append(f"q={filters.q[:30]}")
    return ' | '.join(parts) or 'sin filtros adicionales'
