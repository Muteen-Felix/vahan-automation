from pathlib import Path
from alembic import command
from alembic.config import Config

if __name__ == "__main__":
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
