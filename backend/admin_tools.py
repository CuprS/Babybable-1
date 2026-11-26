"""Admin account tools, run on the server (never through the website).

The admin password can't be reset by email, so that someone who gets into the admin mailbox
still can't take over the admin account. Change it here instead:

    docker compose exec api python admin_tools.py set-password     # on the Hetzner server
    python admin_tools.py set-password                             # local development

Commands:
    set-password   choose a new admin password (asked for twice, never shown); signs out every
                   admin session
    sign-out       sign the admin out everywhere (e.g. after a lost laptop)
"""
import asyncio
import getpass
import sys

from core import ADMIN_EMAIL, db, hash_password, now_iso

MIN_LENGTH = 12


async def _admin() -> dict:
    admin = await db.users.find_one({"email": ADMIN_EMAIL, "is_admin": True}, {"_id": 0, "id": 1}) if ADMIN_EMAIL else None
    if not admin:
        sys.exit("No admin account found for ADMIN_EMAIL. Check the environment (deploy/.env).")
    return admin


async def set_password() -> None:
    admin = await _admin()
    pw = getpass.getpass(f"New admin password (at least {MIN_LENGTH} characters): ")
    if len(pw) < MIN_LENGTH or len(pw) > 72:
        sys.exit(f"Use between {MIN_LENGTH} and 72 characters. Nothing changed.")
    if getpass.getpass("Type it again: ") != pw:
        sys.exit("The two passwords didn't match. Nothing changed.")
    await db.users.update_one({"id": admin["id"]}, {
        "$set": {"password_hash": hash_password(pw), "password_changed_at": now_iso()},
        "$inc": {"token_version": 1},
    })
    await db.auth_codes.delete_many({"user_id": admin["id"]})
    print("Admin password changed. Every admin session has been signed out.")
    print("Remove ADMIN_INITIAL_PASSWORD from deploy/.env if it's still there.")


async def sign_out() -> None:
    admin = await _admin()
    await db.users.update_one({"id": admin["id"]}, {"$inc": {"token_version": 1}})
    print("The admin is signed out everywhere.")


COMMANDS = {"set-password": set_password, "sign-out": sign_out}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    asyncio.run(COMMANDS[sys.argv[1]]())
