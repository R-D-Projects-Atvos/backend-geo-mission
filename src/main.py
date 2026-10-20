from fastapi import FastAPI
import asyncio

from routers.aplicacao import router as aplicacao_router

from services.rotina_aplicacao import rotina_aplicacao

app = FastAPI(
    title="Backend Geo"
)

app.include_router(
    aplicacao_router
)

@app.get("/")
def health_check():

    return {
        "message": "API funcionando"
    }

@app.on_event("startup")
async def startup_event():

    print("=" * 80)
    print("BACKEND GEO INICIADO")
    print("=" * 80)

    asyncio.create_task(
        rotina_aplicacao()
    )