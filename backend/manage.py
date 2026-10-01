"""Preparación, migraciones, cuentas y arranque de Gianna sin cambiar su stack."""
import argparse
import getpass
import json
import sqlite3
import sys
from pathlib import Path


def boolean(value):
    if value.lower() not in ("true", "false"):
        raise argparse.ArgumentTypeError("Usá true o false para el rol de superadministrador.")
    return value.lower() == "true"


def seed_data():
    from config import ADMIN_DATA_DIR, CORS_ORIGINS
    from admin_runtime import RuntimeLock
    from db_migrations import upgrade_all
    ADMIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with RuntimeLock(ADMIN_DATA_DIR / "runtime.lock"):
        versions = upgrade_all(ADMIN_DATA_DIR)
        from admin_db import AdminDB
        from admin_auth import AdminAuth
        from chat_access import ChatAccess
        from knowledge_admin import KnowledgeAdmin
        db = AdminDB(ADMIN_DATA_DIR)
        with db.connect() as conn:
            before = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        auth = AdminAuth(db)
        ChatAccess(ADMIN_DATA_DIR, auth.secret, CORS_ORIGINS)
        knowledge = KnowledgeAdmin(db, None, {})
        knowledge.bootstrap_legacy()
        with db.connect() as conn:
            after = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return {"versions": versions, "admin_created": after > before,
                "knowledge_ready": knowledge.active_id() is not None,
                "chunks": knowledge.manifest()["chunks"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Comandos de operación de Invest Lavalleja.")
    commands = parser.add_subparsers(dest="command", required=True)
    db = commands.add_parser("db", help="Operar las migraciones SQLite.")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    upgrade = db_commands.add_parser("upgrade", help="Aplicar migraciones pendientes sin borrar datos.")
    from db_migrations import MIGRATIONS_DIR
    upgrade.add_argument("-d", "--directory", type=Path, default=MIGRATIONS_DIR)
    commands.add_parser("seed-data", help="Preparar directorios, cuenta inicial e índice existente.")
    create = commands.add_parser("create-admin", help="Crear administrador o superadministrador.")
    create.add_argument("name")
    create.add_argument("email")
    create.add_argument("password", nargs="?", help="Si se omite, se solicita de forma interactiva.")
    create.add_argument("is_superadmin", nargs="?", type=boolean, default=False)
    create.add_argument("--super-admin", action="store_true")
    reset = commands.add_parser("reset-password", help="Recuperar la contraseña de una cuenta.")
    reset.add_argument("--email", required=True)
    commands.add_parser("list-admins", help="Listar cuentas, nombres y roles.")
    run = commands.add_parser("run", help="Iniciar la API con Uvicorn.")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8010)
    run.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "db":
            from config import ADMIN_DATA_DIR
            from admin_runtime import RuntimeLock
            from db_migrations import upgrade_all
            ADMIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
            with RuntimeLock(ADMIN_DATA_DIR / "runtime.lock"):
                print(json.dumps(upgrade_all(ADMIN_DATA_DIR, args.directory)))
        elif args.command == "seed-data":
            print(json.dumps(seed_data()))
        elif args.command == "create-admin":
            from config import ADMIN_DATA_DIR
            from admin_db import AdminDB
            from admin_auth import AdminAuth
            password = args.password
            if password is None:
                password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
                if password != getpass.getpass("Repetí la contraseña: "):
                    raise ValueError("Las contraseñas no coinciden.")
            AdminAuth(AdminDB(ADMIN_DATA_DIR), bootstrap=False).create_user(
                args.email, password, "cli", args.name, args.is_superadmin or args.super_admin)
            print("Cuenta creada. El acceso requiere contraseña y código por correo.")
        elif args.command in ("reset-password", "list-admins"):
            from admin_cli import main as admin_command
            admin_command(["list"] if args.command == "list-admins" else ["reset-password", "--email", args.email])
        elif args.command == "run":
            from asgi import main as run_api
            run_api(["--host", args.host, "--port", str(args.port), *(["--reload"] if args.reload else [])])
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
