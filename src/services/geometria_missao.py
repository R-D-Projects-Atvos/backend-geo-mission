
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from sqlalchemy import text

from config.database import engine


def buscar_talhao_por_chavesig(chavesig):
    sql = text("""
        SELECT TOP 1
            CAST(Chavesig AS NVARCHAR(50)) AS CHAVESIG,
            Shape.STAsText() AS WKT,
            Shape.STSrid AS SRID
        FROM ATVOSPUBLICADOR.BASE_TALHOES_ATVOS
        WHERE
            CAST(Chavesig AS NVARCHAR(50)) = :chavesig
            AND Shape IS NOT NULL
        ORDER BY GDB_FROM_DATE DESC
    """)

    with engine.connect() as connection:
        resultado = connection.execute(
            sql,
            {"chavesig": str(chavesig).strip()}
        ).mappings().first()

    if resultado is None:
        return None

    return {
        "chavesig": resultado["CHAVESIG"],
        "wkt": resultado["WKT"],
        "srid": resultado["SRID"],
    }


def _normalizar_nome_campo(nome):
    nome = str(nome or "").strip()

    # Converte Aplicacao[SAFRA] em SAFRA.
    if "[" in nome and nome.endswith("]"):
        nome = nome.rsplit("[", 1)[-1][:-1]

    nome = unicodedata.normalize(
        "NFKD", nome
    ).encode("ascii", "ignore").decode()

    return re.sub(r"[^A-Z0-9]", "", nome.upper())


def _valor_com_aliases(registro, nome_logico):
    """
    Procura um campo usando nomes alternativos.
    Aceita diferenças de maiúsculas, acentos e separadores.
    """

    aliases = {
        "SAFRA": [
            "SAFRA", "DESAFRA", "NMSAFRA", "CDSAFRA"
        ],
        "VARIEDADE": [
            "VARIEDADE", "DEVARIEDADE",
            "NMVARIEDADE", "CDVARIEDADE"
        ],
        "ESTAGIO": [
            "ESTAGIO", "DEESTAGIO", "NMESTAGIO",
            "ESTAGIOCORTE", "NOESTAGIO"
        ],
        "AMBIENTE": [
            "AMBIENTE", "DEAMBIENTE",
            "NMAMBIENTE", "AMBIENTEPRODUCAO"
        ],
        "ADMIN": [
            "ADMIN", "DEADMIN", "ADMINISTRACAO",
            "ADM", "TIPOADMIN"
        ],
        "AREA_OS": [
            "AREAOS", "AREAORDEMSERVICO",
            "AREAPLANEJADA", "QTAREAOS", "AREAPLAN"
        ],
        "AREA_REALIZADA": [
            "AREAREALIZADA", "AREAREAL",
            "AREAAPLICADA", "AREAEXECUTADA",
            "QTAREAREALIZADA"
        ],
    }

    if not isinstance(registro, dict):
        return None

    alvos = {
        _normalizar_nome_campo(nome_logico)
    }

    alvos.update(
        _normalizar_nome_campo(alias)
        for alias in aliases.get(nome_logico, [])
    )

    # Primeiro tenta encontrar o nome exato ou um alias.
    for chave, valor in registro.items():
        if (
            _normalizar_nome_campo(chave) in alvos
            and valor is not None
            and str(valor).strip()
        ):
            return valor

    # Depois procura campos descritivos com nomes semelhantes.
    fallbacks = {
        "SAFRA": lambda nome: "SAFRA" in nome,
        "VARIEDADE": lambda nome: "VARIEDADE" in nome,
        "ESTAGIO": lambda nome: "ESTAGIO" in nome,
        "AMBIENTE": lambda nome: "AMBIENTE" in nome,
        "ADMIN": lambda nome: nome.startswith("ADMIN"),
    }

    fallback = fallbacks.get(nome_logico)

    if fallback:
        for chave, valor in registro.items():
            if (
                fallback(_normalizar_nome_campo(chave))
                and valor is not None
                and str(valor).strip()
            ):
                return valor

    return None


def _primeiro_valor(*valores):
    """Retorna o primeiro valor não vazio."""
    for valor in valores:
        if valor is not None and str(valor).strip():
            return valor

    return None


def _decimal_area(valor):
    if valor is None or not str(valor).strip():
        return None

    if isinstance(valor, Decimal):
        return valor

    texto = str(valor).strip()

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return None


def salvar_geometrias_talhoes_em_lote(missoes):
    if not missoes:
        return {
            "encontrados": 0,
            "nao_encontrados": 0,
            "missoes_com_geometria": [],
            "missoes_sem_geometria": [],
        }

    sql_limpar_temp = text("""
        IF OBJECT_ID('tempdb..#MISSOES_TALHAO') IS NOT NULL
            DROP TABLE #MISSOES_TALHAO
    """)

    sql_criar_tabela = text("""
        CREATE TABLE #MISSOES_TALHAO (
            MISSAO_ID BIGINT NOT NULL,
            CHAVESIG NVARCHAR(50) NOT NULL,
            SAFRA NVARCHAR(30) NULL,
            VARIEDADE NVARCHAR(100) NULL,
            ESTAGIO NVARCHAR(50) NULL,
            AMBIENTE NVARCHAR(50) NULL,
            ADMIN NVARCHAR(50) NULL,
            AREA_OS DECIMAL(18,4) NULL,
            AREA_REALIZADA DECIMAL(18,4) NULL
        )
    """)

    sql_inserir_temp = text("""
        INSERT INTO #MISSOES_TALHAO (
            MISSAO_ID,
            CHAVESIG,
            SAFRA,
            VARIEDADE,
            ESTAGIO,
            AMBIENTE,
            ADMIN,
            AREA_OS,
            AREA_REALIZADA
        )
        VALUES (
            :missao_id,
            :chavesig,
            :safra,
            :variedade,
            :estagio,
            :ambiente,
            :admin,
            :area_os,
            :area_realizada
        )
    """)

    # Usa os dados da aplicação quando disponíveis.
    # Quando estiverem vazios, utiliza os atributos da base.
    #
    # A mesma regra é aplicada tanto ao UPDATE quanto ao INSERT.
    sql_upsert_geometria = text("""
        WITH TALHOES AS (
            SELECT
                m.MISSAO_ID,

                COALESCE(
                    NULLIF(m.SAFRA, ''),
                    CAST(b.Safra AS NVARCHAR(30))
                ) AS SAFRA,

                COALESCE(
                    NULLIF(m.VARIEDADE, ''),
                    CAST(b.VARIEDADE AS NVARCHAR(100))
                ) AS VARIEDADE,

                COALESCE(
                    NULLIF(m.ESTAGIO, ''),
                    CAST(b.ESTAGIO AS NVARCHAR(50))
                ) AS ESTAGIO,

                COALESCE(
                    NULLIF(m.AMBIENTE, ''),
                    CAST(b.AMBIENTE AS NVARCHAR(50))
                ) AS AMBIENTE,

                COALESCE(
                    NULLIF(m.ADMIN, ''),
                    CAST(b.ADMIN AS NVARCHAR(50))
                ) AS ADMIN,

                m.AREA_OS,
                m.AREA_REALIZADA,
                b.Shape,

                ROW_NUMBER() OVER (
                    PARTITION BY m.MISSAO_ID
                    ORDER BY b.GDB_FROM_DATE DESC
                ) AS RN

            FROM #MISSOES_TALHAO m

            INNER JOIN ATVOSPUBLICADOR.BASE_TALHOES_ATVOS b
                ON CAST(b.Chavesig AS NVARCHAR(50)) = m.CHAVESIG

            WHERE
                b.Chavesig IS NOT NULL
                AND b.Shape IS NOT NULL
        )

        UPDATE g
        SET
            g.GEOM_TALHAO = t.Shape,

            g.SAFRA = COALESCE(
                NULLIF(t.SAFRA, ''),
                g.SAFRA
            ),

            g.VARIEDADE = COALESCE(
                NULLIF(t.VARIEDADE, ''),
                g.VARIEDADE
            ),

            g.ESTAGIO = COALESCE(
                NULLIF(t.ESTAGIO, ''),
                g.ESTAGIO
            ),

            g.AMBIENTE = COALESCE(
                NULLIF(t.AMBIENTE, ''),
                g.AMBIENTE
            ),

            g.ADMIN = COALESCE(
                NULLIF(t.ADMIN, ''),
                g.ADMIN
            ),

            g.AREA_OS = COALESCE(
                t.AREA_OS,
                g.AREA_OS
            ),

            g.AREA_REALIZADA = COALESCE(
                t.AREA_REALIZADA,
                g.AREA_REALIZADA
            )

        FROM ATVOSPUBLICADOR.GEOMETRIAS_MISSAO g

        INNER JOIN TALHOES t
            ON t.MISSAO_ID = g.MISSAO_ID

        WHERE t.RN = 1;


        WITH TALHOES AS (
            SELECT
                m.MISSAO_ID,

                COALESCE(
                    NULLIF(m.SAFRA, ''),
                    CAST(b.Safra AS NVARCHAR(30))
                ) AS SAFRA,

                COALESCE(
                    NULLIF(m.VARIEDADE, ''),
                    CAST(b.VARIEDADE AS NVARCHAR(100))
                ) AS VARIEDADE,

                COALESCE(
                    NULLIF(m.ESTAGIO, ''),
                    CAST(b.ESTAGIO AS NVARCHAR(50))
                ) AS ESTAGIO,

                COALESCE(
                    NULLIF(m.AMBIENTE, ''),
                    CAST(b.AMBIENTE AS NVARCHAR(50))
                ) AS AMBIENTE,

                COALESCE(
                    NULLIF(m.ADMIN, ''),
                    CAST(b.ADMIN AS NVARCHAR(50))
                ) AS ADMIN,

                m.AREA_OS,
                m.AREA_REALIZADA,
                b.Shape,

                ROW_NUMBER() OVER (
                    PARTITION BY m.MISSAO_ID
                    ORDER BY b.GDB_FROM_DATE DESC
                ) AS RN

            FROM #MISSOES_TALHAO m

            INNER JOIN ATVOSPUBLICADOR.BASE_TALHOES_ATVOS b
                ON CAST(b.Chavesig AS NVARCHAR(50)) = m.CHAVESIG

            WHERE
                b.Chavesig IS NOT NULL
                AND b.Shape IS NOT NULL
        )

        INSERT INTO ATVOSPUBLICADOR.GEOMETRIAS_MISSAO (
            MISSAO_ID,
            GEOM_TALHAO,
            SAFRA,
            VARIEDADE,
            ESTAGIO,
            AMBIENTE,
            ADMIN,
            AREA_OS,
            AREA_REALIZADA
        )
        SELECT
            t.MISSAO_ID,
            t.Shape,
            t.SAFRA,
            t.VARIEDADE,
            t.ESTAGIO,
            t.AMBIENTE,
            t.ADMIN,
            t.AREA_OS,
            t.AREA_REALIZADA

        FROM TALHOES t

        WHERE
            t.RN = 1
            AND NOT EXISTS (
                SELECT 1
                FROM ATVOSPUBLICADOR.GEOMETRIAS_MISSAO g
                WHERE g.MISSAO_ID = t.MISSAO_ID
            )
    """)

    sql_missoes_encontradas = text("""
        SELECT DISTINCT m.MISSAO_ID
        FROM #MISSOES_TALHAO m
        INNER JOIN ATVOSPUBLICADOR.GEOMETRIAS_MISSAO g
            ON g.MISSAO_ID = m.MISSAO_ID
    """)

    with engine.begin() as connection:
        connection.execute(sql_limpar_temp)
        connection.execute(sql_criar_tabela)

        registros = []

        for missao in missoes:
            chavesig = str(
                missao.get("chavesig") or ""
            ).strip()

            if not chavesig:
                continue

            raw = missao.get("registro_bruto") or {}

            # Prioriza os dados do registro da aplicação.
            # Os valores vazios serão complementados pelo SQL
            # com os atributos da BASE_TALHOES_ATVOS.
            safra = _valor_com_aliases(raw, "SAFRA")
            variedade = _valor_com_aliases(raw, "VARIEDADE")
            estagio = _valor_com_aliases(raw, "ESTAGIO")
            ambiente = _valor_com_aliases(raw, "AMBIENTE")
            admin = _valor_com_aliases(raw, "ADMIN")

            area_os = _valor_com_aliases(raw, "AREA_OS")
            area_realizada = _valor_com_aliases(
                raw, "AREA_REALIZADA"
            )

            registros.append({
                "missao_id": missao["missao_id"],
                "chavesig": chavesig,

                "safra": (
                    str(safra) if safra is not None else None
                ),

                "variedade": (
                    str(variedade)
                    if variedade is not None else None
                ),

                "estagio": (
                    str(estagio) if estagio is not None else None
                ),

                "ambiente": (
                    str(ambiente) if ambiente is not None else None
                ),

                "admin": (
                    str(admin) if admin is not None else None
                ),

                "area_os": _decimal_area(area_os),

                "area_realizada": _decimal_area(
                    area_realizada
                ),
            })

        if not registros:
            connection.execute(sql_limpar_temp)

            return {
                "encontrados": 0,
                "nao_encontrados": 0,
                "missoes_com_geometria": [],
                "missoes_sem_geometria": [],
            }

        connection.execute(sql_inserir_temp, registros)
        connection.execute(sql_upsert_geometria)

        ids_encontrados = {
            row[0]
            for row in connection.execute(
                sql_missoes_encontradas
            ).fetchall()
        }

        connection.execute(sql_limpar_temp)

    ids_todas = {
        registro["missao_id"] for registro in registros
    }

    ids_nao_encontrados = ids_todas - ids_encontrados

    com_geom = [
        missao
        for missao in missoes
        if missao["missao_id"] in ids_encontrados
    ]

    sem_geom = [
        missao
        for missao in missoes
        if missao["missao_id"] in ids_nao_encontrados
    ]

    print(f"[GEOMETRIAS] Encontrados: {len(com_geom)}")
    print(f"[GEOMETRIAS] Não encontrados: {len(sem_geom)}")

    return {
        "encontrados": len(com_geom),
        "nao_encontrados": len(sem_geom),
        "missoes_com_geometria": com_geom,
        "missoes_sem_geometria": sem_geom,
    }
