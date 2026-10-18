import uuid
import logging
from datetime import timedelta
from werkzeug.datastructures import FileStorage
from minio import Minio
from minio.error import S3Error
from flask import current_app

class StorageError(Exception):
    """Excepción base para errores de almacenamiento."""
    pass

class MinioService:
    def __init__(self, app=None):
        self.client = None
        self.bucket_name = None
        self.public_base_url = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Inicializa el cliente MinIO con la configuración de la app."""
        endpoint = app.config.get('MINIO_ENDPOINT')
        access_key = app.config.get('MINIO_ACCESS_KEY')
        secret_key = app.config.get('MINIO_SECRET_KEY')
        secure = app.config.get('MINIO_SECURE', True)
        self.bucket_name = app.config.get('MINIO_BUCKET')
        self.public_base_url = app.config.get('MINIO_PUBLIC_BASE_URL')

        if not all([endpoint, access_key, secret_key, self.bucket_name]):
            logging.warning("MinIO configuration incomplete. Storage service will fail.")
            return

        try:
            self.client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure
            )
            self.ensure_bucket_exists()
        except Exception as e:
            logging.error(f"Failed to initialize MinIO client: {str(e)}")
            # No lanzamos error aquí para no romper el inicio de la app, 
            # pero fallará al intentar usarlo.

    def ensure_bucket_exists(self):
        """Verifica si el bucket existe, lo crea si es necesario y aplica política pública de lectura."""
        import json
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logging.info(f"Bucket '{self.bucket_name}' created successfully.")
            else:
                logging.info(f"Bucket '{self.bucket_name}' already exists.")

            # Aplicar siempre política pública de lectura para que las URLs directas funcionen.
            # Sin esto, MinIO generaría URLs presignadas con el hostname interno de Docker,
            # que son inaccesibles desde el navegador.
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}"]
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"]
                    }
                ]
            }
            self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
            logging.info(f"Public read policy applied to bucket '{self.bucket_name}'.")
        except S3Error as e:
            logging.error(f"Error checking/creating bucket: {e}")
            raise StorageError("Could not initialize storage bucket.")

    def upload_file(self, file: FileStorage, tracking_code: str) -> dict:
        """
        Sube un archivo al bucket.
        Retorna dict con metadata {object_key, file_name, content_type, size_bytes}
        """
        if not self.client:
            raise StorageError("Storage service not initialized.")

        size = 0
        try:
            # Obtener extensión y generar key único
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'bin'
            object_name = f"tickets/{tracking_code}/{uuid.uuid4()}.{ext}"
            
            # Preparar archivo para lectura
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)

            # Subir
            self.client.put_object(
                self.bucket_name,
                object_name,
                file,
                size,
                content_type=file.content_type
            )
            
            logging.info(f"File uploaded: {object_name}")
            
            return {
                "object_key": object_name,
                "file_name": file.filename,
                "content_type": file.content_type,
                "size_bytes": size
            }

        except S3Error as e:
            logging.error(f"MinIO Upload Error: {e}")
            raise StorageError("Failed to upload file to storage.")
        except Exception as e:
            logging.error(f"Unexpected Upload Error: {e}")
            raise StorageError("An unexpected error occurred during file upload.")

    def get_file_url(self, object_key: str, expires_in_hours: int = 1) -> str:
        """
        Genera una URL para acceder al archivo.
        Si MINIO_PUBLIC_BASE_URL está configurado, retorna URL directa.
        Si no, genera una URL pres firmada.
        """
        if not self.client:
            raise StorageError("Storage service not initialized.")

        try:
            if self.public_base_url:
                # Construcción manual de URL pública (ej: CDN o alias)
                # Aseguramos que no haya doble slash
                base = self.public_base_url.rstrip('/')
                key = object_key.lstrip('/')
                return f"{base}/{self.bucket_name}/{key}"
            else:
                # Presigned URL para acceso temporal seguro
                return self.client.get_presigned_url(
                    "GET",
                    self.bucket_name,
                    object_key,
                    expires=timedelta(hours=expires_in_hours)
                )
        except S3Error as e:
            logging.error(f"MinIO URL Gen Error: {e}")
            raise StorageError("Could not generate file access URL.")

    def delete_file(self, object_key: str):
        """Borra un objeto del bucket."""
        if not self.client:
            raise StorageError("Storage service not initialized.")
            
        try:
            self.client.remove_object(self.bucket_name, object_key)
            logging.info(f"File deleted: {object_key}")
        except S3Error as e:
            logging.error(f"MinIO Delete Error: {e}")
            raise StorageError("Failed to delete file from storage.")

    def get_file_content(self, object_key: str):
        """
        Obtiene el contenido binario de un archivo en MinIO.
        """
        if not self.client:
            raise StorageError("Storage service not initialized.")
            
        try:
            response = self.client.get_object(self.bucket_name, object_key)
            return response.read()
        except Exception as e:
            logging.error(f"MinIO Get Error: {e}")
            return None

# Instancia global (se inicializará en create_app)
minio_service = MinioService()
