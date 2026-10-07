from fastapi import APIRouter, HTTPException

from services.geometria_missao import (
    buscar_talhao_por_chavesig
)


router = APIRouter(
    prefix="/shape",
    tags=["Shape"]
)


@router.get("/{chavesig}")
def obter_talhao(chavesig: str):

    try:

        resultado = buscar_talhao_por_chavesig(
            chavesig
        )

        return {
            "status": "ok",
            "dados": resultado
        }

    except ValueError as e:

        raise HTTPException(
            status_code=404,
            detail=str(e)
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao buscar talhão: {e}"
        )