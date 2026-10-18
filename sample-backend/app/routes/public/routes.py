import logging
from flask import request, jsonify, current_app
from marshmallow import ValidationError

from app.extensions import db, limiter
from app.models.ticket import Ticket, TicketAttachment
from app.schemas.ticket import TicketCreateSchema, TicketTrackingQuerySchema
from app.services.minio_service import minio_service
from app.services.mail_service import mail_service
from app.utils.validators import validate_upload_file, FileValidationError

from . import public_bp
from app.services.captcha_service import create_challenge, consume_challenge


@public_bp.route('/api/captcha', methods=['GET'])
@limiter.limit("20 per minute")
def captcha():
    try:
        response = jsonify(create_challenge())
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Could not create citizen captcha')
        return jsonify(error='No se pudo cargar la verificación. Intentá nuevamente.'), 503

@public_bp.route('/api/tickets', methods=['POST'])
@limiter.limit("10 per minute")
def create_ticket():
    """
    Crea un nuevo ticket ciudadano.
    Acepta JSON o Multipart/Form-Data si incluye adjuntos.
    """
    # 1. Obtener datos (JSON o Form)
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    if not isinstance(data, dict):
        return jsonify(error='Datos del reporte inválidos.'), 400
    captcha_id = data.pop('captcha_id', None)
    captcha_answer = data.pop('captcha_answer', None)

    # 2. Validar input con Schema
    schema = TicketCreateSchema()
    try:
        validated_data = schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Error de validación", "details": err.messages}), 400

    # 3. Procesar archivo adjunto (si existe)
    file = request.files.get('file')
    file_metadata = None
    
    if file:
        try:
            validate_upload_file(file)
            # Nota: La subida real se hace después de tener el tracking code
        except FileValidationError as e:
            return jsonify({"error": "Archivo inválido", "details": str(e)}), 400

    # 4. Crear Ticket e Insertar
    try:
        if current_app.config.get('CAPTCHA_REQUIRED', True) or captcha_id is not None or captcha_answer is not None:
            if not consume_challenge(captcha_id, captcha_answer):
                return jsonify(
                    error='La verificación es incorrecta, venció o ya fue utilizada. Resolvé una nueva suma.',
                    code='captcha_invalid',
                ), 400
        tracking_code = Ticket.generate_tracking_code()
        
        ticket = Ticket(
            tracking_code=tracking_code,
            municipality_or_destination=validated_data['municipality_or_destination'],
            category=validated_data['category'],
            full_name=validated_data['full_name'],
            email=validated_data['email'],
            description=validated_data['description'],
            location_lat=validated_data.get('location_lat'),
            location_lng=validated_data.get('location_lng'),
            ip_address=request.remote_addr,
            user_agent=str(request.user_agent)
        )
        
        db.session.add(ticket)
        # Flush para obtener ID si fuera necesario (aunque tracking es el key público)
        db.session.flush() 

        # 5. Subir archivo a MinIO y crear registro Attachment
        if file:
            try:
                # Subir archivo
                upload_result = minio_service.upload_file(file, tracking_code)
                
                attachment = TicketAttachment(
                    ticket=ticket, # SQLAlchemy manejará la FK con el objeto
                    object_key=upload_result['object_key'],
                    file_name=upload_result['file_name'],
                    content_type=upload_result['content_type'],
                    size_bytes=upload_result['size_bytes']
                )
                db.session.add(attachment)
            except Exception as e:
                # Si falla la subida, hacemos rollback de todo el ticket
                db.session.rollback()
                logging.error(f"Error uploading file for ticket {tracking_code}: {e}")
                return jsonify({"error": "Error del sistema al procesar el archivo"}), 500

        # 6. Commit final
        db.session.commit()
        
        # 7. Enviar Correo (Asíncrono)
        mail_service.send_ticket_received_email(ticket)

        return jsonify({
            "message": "Ticket creado exitosamente",
            "tracking_code": ticket.tracking_code,
            "status": ticket.status.value,
            "created_at": ticket.created_at.isoformat()
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Unexpected error creating ticket: {e}")
        return jsonify({"error": "Ocurrió un error inesperado."}), 500

@public_bp.route('/api/tickets/<string:tracking_code>', methods=['GET'])
@limiter.limit("30 per minute")
def get_ticket_status(tracking_code):
    """
    Consulta el estado de un ticket por su código de seguimiento.
    """
    # 1. Validar formato del tracking code
    schema = TicketTrackingQuerySchema()
    try:
        # Pasamos como dict para validar
        schema.load({'tracking_code': tracking_code})
    except ValidationError:
        # No damos pistas de formato incorrecto vs no encontrado para evitar enumeración,
        # aunque el error 404 es estándar.
        return jsonify({"error": "Ticket no encontrado"}), 404

    # 2. Buscar en DB
    ticket = Ticket.query.filter_by(tracking_code=tracking_code).first()
    
    if not ticket:
        return jsonify({"error": "Ticket no encontrado"}), 404

    # 3. Construir respuesta (Solo datos públicos)
    response_data = {
        "tracking_code": ticket.tracking_code,
        "status": ticket.status.value,
        "category": ticket.category,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "municipality": ticket.municipality_or_destination,
        "location": {
            "lat": ticket.location_lat,
            "lng": ticket.location_lng
        } if ticket.location_lat is not None else None,
        # Historial resumido (sin autores internos)
        "history": [
            {
                "status": h.new_status,
                "date": h.created_at.isoformat(),
                "note": h.note if h.note else None
            } for h in ticket.history
        ]
    }

    return jsonify(response_data), 200

