from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv
import requests
import os


load_dotenv()


router = APIRouter(
    prefix="/aplicacao",
    tags=["Aplicação"]
)


@router.post("/enviar")
def enviar_aplicacao():

    url = os.getenv(
        "POWER_AUTOMATE_APLICACAO_URL"
    )

    if not url:
        raise HTTPException(
            status_code=500,
            detail=(
                "POWER_AUTOMATE_APLICACAO_URL "
                "não configurada"
            )
        )

    try:

        response = requests.post(
            url,
            json={
                "mensagem": "Fala, Rafa! :P"
            },
            timeout=60
        )

    except requests.RequestException as e:

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao chamar Power Automate: {str(e)}"
        )

    if response.status_code >= 400:

        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    try:

        dados = response.json()

    except ValueError:

        raise HTTPException(
            status_code=502,
            detail=(
                "Power Automate retornou uma resposta "
                "que não é JSON."
            )
        )

    if isinstance(dados, list):

        if not dados:

            return {
                "status": "ok",
                "mensagem": "Nenhuma aplicação encontrada.",
                "quantidade": 0,
                "dados": []
            }

        return {
            "status": "ok",
            "mensagem": "Aplicações encontradas.",
            "quantidade": len(dados),
            "dados": dados
        }

    return {
        "status": "ok",
        "mensagem": "Aplicação encontrada.",
        "quantidade": 1,
        "dados": dados
    }


@router.post("/enviar-48h")
def enviar_aplicacao_48h():

    url = os.getenv(
        "POWER_AUTOMATE_APLICACAO_48H_URL"
    )

    if not url:

        raise HTTPException(
            status_code=500,
            detail=(
                "POWER_AUTOMATE_APLICACAO_48H_URL "
                "não configurada"
            )
        )

    try:

        response = requests.post(
            url,
            json={
                "mensagem": "Fala, Rafa! :P"
            },
            timeout=60
        )

    except requests.Timeout:

        raise HTTPException(
            status_code=504,
            detail=(
                "O Power Automate demorou mais de "
                "60 segundos para responder à consulta "
                "das últimas 48 horas."
            )
        )

    except requests.RequestException as e:

        raise HTTPException(
            status_code=502,
            detail=(
                f"Erro ao chamar Power Automate 48h: "
                f"{str(e)}"
            )
        )

    if response.status_code >= 400:

        if response.status_code == 502:

            return {
                "status": "erro_power_automate",
                "mensagem": (
                    "O Power Automate não recebeu resposta "
                    "do servidor responsável pela consulta."
                ),
                "status_code": 502,
                "detalhes": response.text
            }

        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    try:

        dados = response.json()

    except ValueError:

        raise HTTPException(
            status_code=502,
            detail=(
                "Power Automate retornou uma resposta "
                "inválida ou que não está em formato JSON."
            )
        )

    if isinstance(dados, list):

        if not dados:

            return {
                "status": "ok",
                "mensagem": (
                    "Nenhuma aplicação encontrada "
                    "nas últimas 48 horas."
                ),
                "quantidade": 0,
                "dados": []
            }

        return {
            "status": "ok",
            "mensagem": (
                "Aplicações encontradas "
                "nas últimas 48 horas."
            ),
            "quantidade": len(dados),
            "dados": dados
        }

    return {
        "status": "ok",
        "mensagem": (
            "Aplicação encontrada "
            "nas últimas 48 horas."
        ),
        "quantidade": 1,
        "dados": dados
    }