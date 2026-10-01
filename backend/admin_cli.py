"""Alta y recuperación de administradores sin publicar contraseñas en argumentos."""
import argparse
import getpass
import os

from admin_auth import AdminAuth, normalize_email, password_hash
from admin_db import AdminDB
from config import ADMIN_DATA_DIR


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "reset-password", "list"))
    parser.add_argument("--email")
    parser.add_argument("--name")
    parser.add_argument("--super-admin", action="store_true")
    args = parser.parse_args(argv)
    db = AdminDB(ADMIN_DATA_DIR)
    if args.command == "list":
        with db.connect() as conn:
            for row in conn.execute("SELECT name,email,is_superadmin,active FROM users ORDER BY created"):
                print(row["name"], row["email"], "superadministrador" if row["is_superadmin"] else "administrador",
                      "activo" if row["active"] else "desactivado")
        return
    email = normalize_email(args.email or input("Correo del administrador: "))
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    if not os.getenv("ADMIN_PASSWORD") and password != getpass.getpass("Repetí la contraseña: "):
        parser.error("Las contraseñas no coinciden.")
    if args.command == "create":
        AdminAuth(db, bootstrap=False).create_user(email, password, "cli", args.name, args.super_admin)
    else:
        encoded = password_hash(password)
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                parser.error("No existe ese administrador.")
            conn.execute("UPDATE users SET password_hash=?,active=1 WHERE id=?", (encoded, row["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        db.audit("cli", "admin.password_reset", email)
    print("Administrador configurado. El acceso requiere un código enviado por correo.")


if __name__ == "__main__":
    main()
