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
        ORDER BY
            GDB_FROM_DATE DESC
    """)

    with engine.connect() as connection:

        resultado = connection.execute(
            sql,
            {
                "chavesig": str(chavesig).strip()
            }
        ).mappings().first()

    if resultado is None:

        return None

    return {
        "chavesig": resultado["CHAVESIG"],
        "wkt": resultado["WKT"],
        "srid": resultado["SRID"]
    }


def salvar_geometrias_talhoes_em_lote(missoes):

    if not missoes:

        return {
            "encontrados": 0,
            "nao_encontrados": 0,
            "missoes_com_geometria": [],
            "missoes_sem_geometria": []
        }

    sql_limpar_temp = text("""
        IF OBJECT_ID('tempdb..#MISSOES_TALHAO') IS NOT NULL
        BEGIN
            DROP TABLE #MISSOES_TALHAO
        END
    """)

    sql_criar_tabela = text("""
        CREATE TABLE #MISSOES_TALHAO (
            MISSAO_ID BIGINT NOT NULL,
            CHAVESIG NVARCHAR(50) NOT NULL
        )
    """)

    sql_inserir_temp = text("""
        INSERT INTO #MISSOES_TALHAO (
            MISSAO_ID,
            CHAVESIG
        )
        VALUES (
            :missao_id,
            :chavesig
        )
    """)

    sql_inserir_geometria = text("""
        WITH TALHOES AS (
            SELECT
                m.MISSAO_ID,
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
            GEOM_TALHAO
        )
        SELECT
            MISSAO_ID,
            Shape
        FROM TALHOES
        WHERE RN = 1
    """)

    sql_missoes_encontradas = text("""
        SELECT DISTINCT
            m.MISSAO_ID
        FROM #MISSOES_TALHAO m
        INNER JOIN ATVOSPUBLICADOR.GEOMETRIAS_MISSAO g
            ON g.MISSAO_ID = m.MISSAO_ID
    """)

    with engine.begin() as connection:

        connection.execute(
            sql_limpar_temp
        )

        connection.execute(
            sql_criar_tabela
        )

        registros = []

        for missao in missoes:

            chavesig = str(
                missao["chavesig"]
            ).strip()

            if not chavesig:

                continue

            registros.append(
                {
                    "missao_id": missao["missao_id"],
                    "chavesig": chavesig
                }
            )

        if not registros:

            connection.execute(
                sql_limpar_temp
            )

            return {
                "encontrados": 0,
                "nao_encontrados": 0,
                "missoes_com_geometria": [],
                "missoes_sem_geometria": []
            }

        connection.execute(
            sql_inserir_temp,
            registros
        )

        connection.execute(
            sql_inserir_geometria
        )

        resultado = connection.execute(
            sql_missoes_encontradas
        )

        ids_encontrados = {
            row[0]
            for row in resultado.fetchall()
        }

        connection.execute(
            sql_limpar_temp
        )

    ids_todas = {
        registro["missao_id"]
        for registro in registros
    }

    ids_nao_encontrados = (
        ids_todas - ids_encontrados
    )

    missoes_com_geometria = [
        missao
        for missao in missoes
        if missao["missao_id"] in ids_encontrados
    ]

    missoes_sem_geometria = [
        missao
        for missao in missoes
        if missao["missao_id"] in ids_nao_encontrados
    ]

    encontrados = len(
        missoes_com_geometria
    )

    nao_encontrados = len(
        missoes_sem_geometria
    )

    print(
        f"[GEOMETRIAS] "
        f"Encontrados: {encontrados}"
    )

    print(
        f"[GEOMETRIAS] "
        f"Não encontrados: {nao_encontrados}"
    )

    return {
        "encontrados": encontrados,
        "nao_encontrados": nao_encontrados,
        "missoes_com_geometria": missoes_com_geometria,
        "missoes_sem_geometria": missoes_sem_geometria
    }