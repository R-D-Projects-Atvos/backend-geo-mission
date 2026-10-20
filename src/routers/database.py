from fastapi import APIRouter
from sqlalchemy import text
from config.database import engine

router = APIRouter(prefix="/db",tags=["Database"])

@router.get("/")
def test_database():

    with engine.connect() as connection:

        result = connection.execute(
            text("SELECT @@VERSION")
        ).scalar()

    return {
        "database": "conectado :)",
        "version": result
    }