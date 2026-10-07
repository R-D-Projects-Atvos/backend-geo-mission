import asyncio

from routers.aplicacao import (
    enviar_aplicacao,
    enviar_aplicacao_48h
)

from services.controle_missao import (
    registrar_ou_recuperar_missao,
    marcar_erro,
    marcar_talhao_nao_encontrado
)

from services.geometria_missao import (
    salvar_geometrias_talhoes_em_lote
)


def normalizar_dados_48h(dados):

    dados_normalizados = []

    if not isinstance(dados, list):

        dados = [dados]

    for registro in dados:

        if not isinstance(registro, dict):

            dados_normalizados.append(
                registro
            )

            continue

        registro_normalizado = {}

        for chave, valor in registro.items():

            nova_chave = chave.replace(
                "Aplicacao_48[",
                "Aplicacao[",
                1
            )

            registro_normalizado[
                nova_chave
            ] = valor

        dados_normalizados.append(
            registro_normalizado
        )

    return dados_normalizados


def processar_missoes(dados):

    novas = 0
    reprocessadas = 0
    ignoradas = 0
    erros = 0
    talhoes_nao_encontrados = 0

    missoes_processar = []

    if not isinstance(dados, list):

        dados = [dados]

    print("-" * 80)
    print("REGISTRANDO E VALIDANDO MISSÕES")
    print("-" * 80)

    for registro in dados:

        if not isinstance(registro, dict):

            erros += 1

            print(
                "[ERRO] Registro inválido."
            )

            continue

        chave_missao = None

        try:

            resultado = registrar_ou_recuperar_missao(
                registro
            )

            chave_missao = resultado[
                "chave_missao"
            ]

            if resultado["acao"] == "IGNORAR":

                ignoradas += 1

                continue

            if resultado["era_reprocessamento"]:

                reprocessadas += 1

            else:

                novas += 1

            missoes_processar.append(
                resultado
            )

        except Exception as e:

            erros += 1

            print(
                f"[ERRO] Falha na missão "
                f"{chave_missao}: {e}"
            )

            if chave_missao:

                try:

                    marcar_erro(
                        chave_missao
                    )

                except Exception as erro_banco:

                    print(
                        f"[ERRO] Falha ao marcar "
                        f"{chave_missao} como ERRO: "
                        f"{erro_banco}"
                    )

    if not missoes_processar:

        return {
            "novas": novas,
            "reprocessadas": reprocessadas,
            "ignoradas": ignoradas,
            "erros": erros,
            "talhoes_nao_encontrados": 0
        }

    print("-" * 80)
    print("MISSÕES QUE SERÃO PROCESSADAS")
    print("-" * 80)

    print(
        f"Total: {len(missoes_processar)}"
    )

    print("-" * 80)
    print("BUSCANDO TALHÕES EM LOTE")
    print("-" * 80)

    try:

        geometria_resultado = (
            salvar_geometrias_talhoes_em_lote(
                missoes_processar
            )
        )

    except Exception as e:

        print(
            f"[ERRO] Falha na busca em lote "
            f"dos talhões: {e}"
        )

        for missao in missoes_processar:

            try:

                marcar_erro(
                    missao["chave_missao"]
                )

            except Exception as erro_banco:

                print(
                    f"[ERRO] Falha ao marcar "
                    f"{missao['chave_missao']} "
                    f"como ERRO: {erro_banco}"
                )

        return {
            "novas": novas,
            "reprocessadas": reprocessadas,
            "ignoradas": ignoradas,
            "erros": erros + len(
                missoes_processar
            ),
            "talhoes_nao_encontrados": 0
        }

    encontrados = geometria_resultado[
        "encontrados"
    ]

    nao_encontrados = geometria_resultado[
        "nao_encontrados"
    ]

    missoes_com_geometria = (
        geometria_resultado[
            "missoes_com_geometria"
        ]
    )

    missoes_sem_geometria = (
        geometria_resultado[
            "missoes_sem_geometria"
        ]
    )

    print("-" * 80)
    print("RESULTADO DA BUSCA DOS TALHÕES")
    print("-" * 80)

    print(
        f"Talhões encontrados: "
        f"{encontrados}"
    )

    print(
        f"Talhões não encontrados: "
        f"{nao_encontrados}"
    )

    if missoes_sem_geometria:

        print("-" * 80)
        print("TALHÕES NÃO ENCONTRADOS")
        print("-" * 80)

        for missao in missoes_sem_geometria:

            print(
                f"[CHAVESIG NÃO ENCONTRADO] "
                f"{missao['chave_missao']}"
            )

            print(
                f"UNIDADE: "
                f"{missao['unidade']}"
            )

            print(
                f"NUMERO OS: "
                f"{missao['numero_os']}"
            )

            print(
                f"CHAVESIG: "
                f"{missao['chavesig']}"
            )

            print(
                "Possível causa: "
                "o CHAVESIG informado pela O.S. "
                "pode estar desatualizado ou o "
                "talhão pode ter sido alterado "
                "na base."
            )

            try:

                marcar_talhao_nao_encontrado(
                    missao["chave_missao"]
                )

                talhoes_nao_encontrados += 1

            except Exception as erro_banco:

                erros += 1

                print(
                    f"[ERRO] Falha ao marcar "
                    f"{missao['chave_missao']} "
                    f"como TALHAO_NAO_ENCONTRADO: "
                    f"{erro_banco}"
                )

    print("-" * 80)
    print("PROCESSAMENTO DAS MISSÕES")
    print("-" * 80)

    for missao in missoes_com_geometria:

        print("=" * 80)

        print(
            f"PROCESSANDO MISSÃO: "
            f"{missao['chave_missao']}"
        )

        print("=" * 80)

        print(
            f"UNIDADE: "
            f"{missao['unidade']}"
        )

        print(
            f"NUMERO OS: "
            f"{missao['numero_os']}"
        )

        print(
            f"CHAVESIG: "
            f"{missao['chavesig']}"
        )

        print(
            f"CD_OPERACAO: "
            f"{missao['cd_operacao']}"
        )

        print(
            f"DE_OPERACAO: "
            f"{missao['de_operacao']}"
        )

        print(
            f"RESPONSAVEL: "
            f"{missao['responsavel']}"
        )

        print(
            f"DESCRICAO RESPONSAVEL: "
            f"{missao['descricao_responsavel']}"
        )

        print(
            "[GEOM_TALHAO SALVO]"
        )

        print(
            "[AGUARDANDO PRÓXIMA ETAPA "
            "DO PROCESSAMENTO]"
        )

    return {
        "novas": novas,
        "reprocessadas": reprocessadas,
        "ignoradas": ignoradas,
        "erros": erros,
        "talhoes_nao_encontrados":
            talhoes_nao_encontrados
    }


async def executar_consulta_completa():

    print("=" * 80)
    print("EXECUTANDO CONSULTA COMPLETA")
    print("=" * 80)

    try:

        resultado = await asyncio.to_thread(
            enviar_aplicacao
        )

        quantidade = resultado.get(
            "quantidade",
            0
        )

        dados = resultado.get(
            "dados",
            []
        )

        print(
            "Consulta completa finalizada."
        )

        print(
            f"Total de registros: {quantidade}"
        )

        if dados:

            registro = dados[0]

            print("-" * 80)
            print(
                "EXEMPLO DE DADOS DA CONSULTA COMPLETA"
            )
            print("-" * 80)

            print(
                "UNIDADE:",
                registro.get(
                    "Aplicacao[Unidade]"
                )
            )

            print(
                "CHAVESIG:",
                registro.get(
                    "Aplicacao[Chavesig]"
                )
            )

            print(
                "NO_OS:",
                registro.get(
                    "Aplicacao[NO_OS]"
                )
            )

            print(
                "CD_OPERACAO:",
                registro.get(
                    "Aplicacao[CD_OPERACAO]"
                )
            )

            print(
                "DE_OPERACAO:",
                registro.get(
                    "Aplicacao[DE_OPERACAO]"
                )
            )

            print(
                "RESPONSAVEL:",
                registro.get(
                    "Aplicacao[responsavel]"
                )
            )

            print(
                "DESCRICAO:",
                registro.get(
                    "Aplicacao[descricao]"
                )
            )

        controle = await asyncio.to_thread(
            processar_missoes,
            dados
        )

        print("-" * 80)
        print("CONTROLE DAS MISSÕES")
        print("-" * 80)

        print(
            f"Novas: "
            f"{controle['novas']}"
        )

        print(
            f"Reprocessadas: "
            f"{controle['reprocessadas']}"
        )

        print(
            f"Ignoradas: "
            f"{controle['ignoradas']}"
        )

        print(
            f"Talhões não encontrados: "
            f"{controle['talhoes_nao_encontrados']}"
        )

        print(
            f"Erros: "
            f"{controle['erros']}"
        )

    except Exception as e:

        print(
            f"[ERRO] Consulta completa: {e}"
        )


async def executar_consulta_48h():

    print("=" * 80)
    print(
        "CONSULTANDO APLICAÇÕES DAS ÚLTIMAS 48 HORAS"
    )
    print("=" * 80)

    try:

        resultado = await asyncio.to_thread(
            enviar_aplicacao_48h
        )

        quantidade = resultado.get(
            "quantidade",
            0
        )

        dados = resultado.get(
            "dados",
            []
        )

        print(
            "Consulta 48h finalizada."
        )

        print(
            f"Total de registros: {quantidade}"
        )

        print(
            f"Mensagem: "
            f"{resultado.get('mensagem')}"
        )

        if not dados:

            print(
                "Nenhuma aplicação encontrada "
                "nas últimas 48 horas."
            )

            return

        dados = normalizar_dados_48h(
            dados
        )

        registro = dados[0]

        print("-" * 80)
        print("DADOS APÓS NORMALIZAÇÃO")
        print("-" * 80)

        print(
            "UNIDADE:",
            registro.get(
                "Aplicacao[Unidade]"
            )
        )

        print(
            "CHAVESIG:",
            registro.get(
                "Aplicacao[Chavesig]"
            )
        )

        print(
            "NO_OS:",
            registro.get(
                "Aplicacao[NO_OS]"
            )
        )

        print(
            "CD_OPERACAO:",
            registro.get(
                "Aplicacao[CD_OPERACAO]"
            )
        )

        print(
            "DE_OPERACAO:",
            registro.get(
                "Aplicacao[DE_OPERACAO]"
            )
        )

        print(
            "RESPONSAVEL:",
            registro.get(
                "Aplicacao[responsavel]"
            )
        )

        print(
            "DESCRICAO:",
            registro.get(
                "Aplicacao[descricao]"
            )
        )

        controle = await asyncio.to_thread(
            processar_missoes,
            dados
        )

        print("-" * 80)
        print("CONTROLE DAS MISSÕES 48H")
        print("-" * 80)

        print(
            f"Novas: "
            f"{controle['novas']}"
        )

        print(
            f"Reprocessadas: "
            f"{controle['reprocessadas']}"
        )

        print(
            f"Ignoradas: "
            f"{controle['ignoradas']}"
        )

        print(
            f"Talhões não encontrados: "
            f"{controle['talhoes_nao_encontrados']}"
        )

        print(
            f"Erros: "
            f"{controle['erros']}"
        )

    except Exception as e:

        print(
            f"[ERRO] Consulta aplicação 48h: {e}"
        )


async def rotina_aplicacao():

    await executar_consulta_completa()

    while True:

        print("=" * 80)

        print(
            "Próxima consulta 48h em 1 minuto..."
        )

        print("=" * 80)

        await asyncio.sleep(
            60
        )

        await executar_consulta_48h()