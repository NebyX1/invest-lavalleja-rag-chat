# Buzon Backend

Backend modular con Flask, SQLAlchemy, blueprints, y validación estricta.

## Estructura

- `app/`
  - `routes/`: Endpoints organizados por dominios (public, admin).
  - `services/`: Lógica de negocio.
  - `repositories/`: Capa de acceso a datos.
  - `schemas/`: Serialización y validación con Marshmallow.
  - `models/`: Modelos ORM SQLAlchemy.
  - `utils/`: Utilidades generales.

## Setup

### 1. Crear entorno virtual (venv)

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

Copiar y renombrar el archivo de ejemplo:

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Editar el archivo `.env` con tus credenciales de base de datos, correo y MinIO.

### 4. Inicializar Base de Datos

Asegurate de que MariaDB esté corriendo y la base de datos `buzon_db` (o la que hayas puesto en .env) exista.

```bash
# Inicializar migraciones (solo la primera vez si no existe carpeta migrations)
flask db init

# Generar script de migración inicial
flask db migrate -m "Initial migration"

# Aplicar cambios a la DB
flask db upgrade
```

### 5. Correr en modo desarrollo
Activar entorno:
```bash
venv\Scripts\activate
```

```bash
flask run
# O usando wsgi.py directamente
python wsgi.py
```

El servidor estará en `http://127.0.0.1:5000`.

## Comandos útiles

- `flask routes`: Ver todas las rutas registradas.
- `flask db upgrade`: Aplicar migraciones pendientes.

### Comandos Personalizados (CLI)

1.  **Crear Usuario Administrador**:
    Crea un admin (o super admin) con username, email, password y flag.
    ```bash
    flask create-admin nombre-de-admin mail-de-admin contraseña-de-admin true/false-super-admin
    ```

2.  **Inicializar Bucket MinIO**:
    Verifica que la conexión a MinIO funcione y crea el bucket si no existe.
    ```bash
    flask init-bucket
    ```

3.  **Generar Secret Key**:
    Genera un token seguro para pegar en tu `.env`.
    ```bash
    flask rotate-secret
    ```

## Testing

```bash
pytest
```
