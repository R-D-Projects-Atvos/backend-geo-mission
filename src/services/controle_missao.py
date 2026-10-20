from sqlalchemy import text
from config.database import engine


def obter_dados_missao(registro):

    unidade = str(
        registro.get(
            "Aplicacao[Unidade]",
            ""
        )
    ).strip()

    chavesig = str(
        registro.get(
            "Aplicacao[Chavesig]",
            ""
        )
    ).strip()

    numero_os_raw = registro.get(
        "Aplicacao[NO_OS]"
    )

    cd_operacao_raw = registro.get(
        "Aplicacao[CD_OPERACAO]"
    )

    de_operacao = str(
        registro.get(
            "Aplicacao[DE_OPERACAO]",
            ""
        )
    ).strip()

    responsavel_raw = registro.get(
        "Aplicacao[responsavel]"
    )

    descricao_responsavel = str(
        registro.get(
            "Aplicacao[descricao]",
            ""
        )
    ).strip()

    if not unidade:
        raise ValueError(
            "UNIDADE não encontrada."
        )

    if not chavesig:
        raise ValueError(
            "CHAVESIG não encontrado."
        )

    if numero_os_raw is None:
        raise ValueError(
            "NUMERO_OS não encontrado."
        )

    try:
        numero_os = int(
            float(numero_os_raw)
        )
    except (ValueError, TypeError):
        raise ValueError(
            f"NUMERO_OS inválido: {numero_os_raw}"
        )

    cd_operacao = None

    if cd_operacao_raw is not None:

        try:
            cd_operacao = int(
                float(cd_operacao_raw)
            )

        except (ValueError, TypeError):

            raise ValueError(
                f"CD_OPERACAO inválido: {cd_operacao_raw}"
            )

    responsavel = None

    if responsavel_raw is not None:

        try:
            responsavel = int(
                float(responsavel_raw)
            )

        except (ValueError, TypeError):

            raise ValueError(
                f"RESPONSAVEL inválido: {responsavel_raw}"
            )

    chave_missao = (
        f"{unidade}_"
        f"{numero_os}_"
        f"{chavesig}"
    )

    return {
        "unidade": unidade,
        "numero_os": numero_os,
        "chavesig": chavesig,
        "chave_missao": chave_missao,
        "cd_operacao": cd_operacao,
        "de_operacao": de_operacao,
        "responsavel": responsavel,
        "descricao_responsavel": descricao_responsavel
    }


def obter_missao(dados):

    sql = text("""
        SELECT
            ID,
            STATUS
        FROM ATVOSPUBLICADOR.MISSOES_PROCESSADAS
        WHERE
            UNIDADE = :unidade
            AND NUMERO_OS = :numero_os
            AND CHAVESIG = :chavesig
    """)

    with engine.connect() as connection:

        resultado = connection.execute(
            sql,
            dados
        ).mappings().first()

    return resultado


def limpar_dados_missao(missao_id):

    sql_geometria = text("""
        DELETE FROM ATVOSPUBLICADOR.GEOMETRIAS_MISSAO
        WHERE MISSAO_ID = :missao_id
    """)

    sql_resultado = text("""
        DELETE FROM ATVOSPUBLICADOR.RESULTADOS_MISSAO
        WHERE MISSAO_ID = :missao_id
    """)

    with engine.begin() as connection:

        connection.execute(
            sql_geometria,
            {
                "missao_id": missao_id
            }
        )

        connection.execute(
            sql_resultado,
            {
                "missao_id": missao_id
            }
        )

    print(
        f"[DADOS ANTIGOS REMOVIDOS] "
        f"MISSÃO ID {missao_id}"
    )


def registrar_ou_recuperar_missao(registro):

    dados = obter_dados_missao(
        registro
    )

    missao = obter_missao(
        dados
    )

    if missao is None:

        sql_insert = text("""
            INSERT INTO ATVOSPUBLICADOR.MISSOES_PROCESSADAS (
                UNIDADE,
                NUMERO_OS,
                CHAVESIG,
                CHAVE_MISSAO,
                CD_OPERACAO,
                DE_OPERACAO,
                RESPONSAVEL,
                DESCRICAO_RESPONSAVEL,
                STATUS,
                VERSAO_PROCESSAMENTO
            )
            VALUES (
                :unidade,
                :numero_os,
                :chavesig,
                :chave_missao,
                :cd_operacao,
                :de_operacao,
                :responsavel,
                :descricao_responsavel,
                'PROCESSANDO',
                'V1'
            )
        """)

        sql_id = text("""
            SELECT ID
            FROM ATVOSPUBLICADOR.MISSOES_PROCESSADAS
            WHERE CHAVE_MISSAO = :chave_missao
        """)

        with engine.begin() as connection:

            connection.execute(
                sql_insert,
                dados
            )

            missao_id = connection.execute(
                sql_id,
                {
                    "chave_missao": dados[
                        "chave_missao"
                    ]
                }
            ).scalar_one()

        print(
            f"[NOVA MISSÃO] "
            f"{dados['chave_missao']}"
        )

        return {
            "acao": "PROCESSAR",
            "status": "PROCESSANDO",
            "era_reprocessamento": False,
            "missao_id": missao_id,
            **dados
        }

    missao_id = missao["ID"]
    status = missao["STATUS"]

    if status == "CONCLUIDO":

        print(
            f"[IGNORAR] "
            f"{dados['chave_missao']} "
            f"já está CONCLUIDO."
        )

        return {
            "acao": "IGNORAR",
            "status": "CONCLUIDO",
            "era_reprocessamento": False,
            "missao_id": missao_id,
            **dados
        }

    limpar_dados_missao(
        missao_id
    )

    sql = text("""
        UPDATE ATVOSPUBLICADOR.MISSOES_PROCESSADAS
        SET
            CD_OPERACAO = :cd_operacao,
            DE_OPERACAO = :de_operacao,
            RESPONSAVEL = :responsavel,
            DESCRICAO_RESPONSAVEL = :descricao_responsavel,
            STATUS = 'PROCESSANDO',
            PROCESSADO_EM = NULL,
            ATUALIZADO_EM = SYSDATETIME()
        WHERE
            ID = :missao_id
            AND STATUS <> 'CONCLUIDO'
    """)

    with engine.begin() as connection:

        connection.execute(
            sql,
            {
                "cd_operacao": dados[
                    "cd_operacao"
                ],
                "de_operacao": dados[
                    "de_operacao"
                ],
                "responsavel": dados[
                    "responsavel"
                ],
                "descricao_responsavel": dados[
                    "descricao_responsavel"
                ],
                "missao_id": missao_id
            }
        )

    print(
        f"[REPROCESSAR] "
        f"{dados['chave_missao']}"
    )

    return {
        "acao": "PROCESSAR",
        "status": "PROCESSANDO",
        "era_reprocessamento": True,
        "missao_id": missao_id,
        **dados
    }


def marcar_concluida(chave_missao):

    sql = text("""
        UPDATE ATVOSPUBLICADOR.MISSOES_PROCESSADAS
        SET
            STATUS = 'CONCLUIDO',
            PROCESSADO_EM = SYSDATETIME(),
            ATUALIZADO_EM = SYSDATETIME()
        WHERE
            CHAVE_MISSAO = :chave_missao
    """)

    with engine.begin() as connection:

        connection.execute(
            sql,
            {
                "chave_missao": chave_missao
            }
        )

    print(
        f"[CONCLUIDA] "
        f"{chave_missao}"
    )


def marcar_erro(chave_missao):

    sql = text("""
        UPDATE ATVOSPUBLICADOR.MISSOES_PROCESSADAS
        SET
            STATUS = 'ERRO',
            ATUALIZADO_EM = SYSDATETIME()
        WHERE
            CHAVE_MISSAO = :chave_missao
    """)

    with engine.begin() as connection:

        connection.execute(
            sql,
            {
                "chave_missao": chave_missao
            }
        )

    print(
        f"[ERRO] "
        f"{chave_missao}"
    )


def marcar_talhao_nao_encontrado(chave_missao):

    sql = text("""
        UPDATE ATVOSPUBLICADOR.MISSOES_PROCESSADAS
        SET
            STATUS = 'TALHAO_NAO_ENCONTRADO',
            ATUALIZADO_EM = SYSDATETIME()
        WHERE
            CHAVE_MISSAO = :chave_missao
    """)

    with engine.begin() as connection:

        connection.execute(
            sql,
            {
                "chave_missao": chave_missao
            }
        )

    print(
        f"[TALHÃO NÃO ENCONTRADO] "
        f"{chave_missao}"
    )