import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_password: str
    admin_notify_id: int | None
    database_path: str


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Add it to .env locally or Railway Variables.")

    notify_id = os.getenv("ADMIN_NOTIFY_ID", "").strip()
    return Config(
        bot_token=bot_token,
        admin_password=os.getenv("ADMIN_PASSWORD", "4458").strip(),
        admin_notify_id=int(notify_id) if notify_id.isdigit() else None,
        database_path=os.getenv("DATABASE_PATH", "./data/sliva.db").strip(),
    )
