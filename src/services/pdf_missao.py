import hashlib
import json
import math
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import FILL_EVEN_ODD

from dotenv import load_dotenv
import os

load_dotenv()


PDF_OUTPUT_DIR = Path(
    os.getenv(
        "PDF_OUTPUT",
        str(Path(__file__).resolve().parents[2] / "RELATORIO_OPERACIONAL")
    )
).expanduser()

# Nome da pasta da unidade. Se a unidade não estiver aqui, usa o próprio código.
# Ex.: {"UCR": "Costa Rica", "UAT": "Alto Taquari"}
NOME_PASTA_UNIDADE = {}

# Talhões "genéricos" (final 0999 no CHAVESIG) que não entram no PDF:
# nem na tabela, nem no mapa, nem na contagem de talhões sem geometria.
TALHOES_IGNORADOS = {999}

TABELA_TALHOES = ("ATVOSPUBLICADOR", "BASE_TALHOES_ATVOS")
TABELA_MISSOES = "ATVOSPUBLICADOR.MISSOES_PROCESSADAS"

TENTATIVAS_TROCA = 3
ESPERA_TENTATIVA_S = 0.4
MAX_VERSOES_ALTERNATIVAS = 9

PAGINA = landscape(A4)           # 842 x 595 pt (horizontal)
LOGO_PATH = Path(__file__).resolve().parents[2] / "logo.png"

COLUNAS_OCULTAS = {"OBJECTID", "GLOBALID", "SHAPE", "SHAPE_LENGTH", "SHAPE_AREA"}

# nomes prováveis das colunas da base (maiúsculo). Pode forçar por variável de
# ambiente, ex.: PDF_COL_FAZENDA=NM_FAZENDA
CANDIDATOS = {
    "fazenda": ["FAZENDA", "NM_FAZENDA", "NOME_FAZENDA", "DE_FAZENDA",
                "DS_FAZENDA", "NOME_FAZ", "PROPRIEDADE"],
    "codigo": ["CODIGO", "COD", "CD_FAZENDA", "COD_FAZENDA", "CODFAZENDA"],
    "setor": ["SETOR", "DE_SETOR", "CD_SETOR", "NM_SETOR", "GLEBA"],
    "talhao": ["TALHAO", "NM_TALHAO", "CD_TALHAO", "DE_TALHAO", "TALH"],
}


# Colunas da tabela por talhão (ordem do PDF)
COLUNAS_TABELA = ["CODIGO", "SETOR", "TALHÃO", "SAFRA", "VARIEDADE", "ESTAGIO",
                  "AMBIENTE", "ADMIN", "AREA_OS", "AREA_REALIZADA"]
COLUNAS_NUMERICAS = {"AREA_OS", "AREA_REALIZADA"}

# Nomes possíveis dos campos (comparados sem acento, sem "_" e em maiúsculo),
# procurados nos dados do Power Automate e na base de talhões.
# Para forçar o nome real de um campo: PDF_COL_<NOME>=<campo>, ex.: PDF_COL_SAFRA=NM_SAFRA
ALIASES = {
    "SAFRA": ["SAFRA", "DESAFRA", "NMSAFRA", "CDSAFRA"],
    "VARIEDADE": ["VARIEDADE", "DEVARIEDADE", "NMVARIEDADE", "CDVARIEDADE"],
    "ESTAGIO": ["ESTAGIO", "DEESTAGIO", "NMESTAGIO", "ESTAGIOCORTE", "NOESTAGIO"],
    "AMBIENTE": ["AMBIENTE", "DEAMBIENTE", "NMAMBIENTE", "AMBIENTEPRODUCAO"],
    "ADMIN": ["ADMIN", "DEADMIN", "ADMINISTRACAO", "ADM", "TIPOADMIN"],
    "AREA_OS": ["AREAOS", "AREAORDEMSERVICO", "AREAPLANEJADA", "QTAREAOS", "AREAPLAN"],
    "AREA_REALIZADA": ["AREAREALIZADA", "AREAREAL", "AREAAPLICADA",
                       "AREAEXECUTADA", "QTAREAREALIZADA"],
    "DATA_FINAL": ["DATAFINAL", "DTFINAL", "DATAFIM", "DTFIM", "DATATERMINO",
                   "DTTERMINO", "DATAFINALOS", "DTFIMOS"],
}

_E_DATA = lambda n: "DT" in n or "DATA" in n
FALLBACK = {
    "SAFRA": lambda n: "SAFRA" in n,
    "VARIEDADE": lambda n: "VARIEDADE" in n,
    "ESTAGIO": lambda n: "ESTAGIO" in n,
    "AMBIENTE": lambda n: "AMBIENTE" in n,
    "ADMIN": lambda n: n.startswith("ADMIN"),
    "DATA_FINAL": lambda n: _E_DATA(n) and any(
        s in n for s in ("FINAL", "FIM", "TERMIN", "ENCERR")),
}

# Paleta Atvos (extraída do site)
LARANJA = colors.HexColor("#EE7202")
AZUL = colors.HexColor("#005A7D")
AMARELO = colors.HexColor("#F7A600")
CINZA = colors.HexColor("#5F6B73")
LINHA = colors.HexColor("#D5DEE3")
FUNDO_ZEBRA = colors.HexColor("#F1F6F8")

_lock_geracao = threading.Lock()
_ultimas_geracoes = {}   # caminho final -> fingerprint
_colunas_cache = {}
_raw_cache = {}          # (unidade, os, chavesig) -> dados brutos do Power Automate


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL",
               *{f"COM{i}" for i in range(1, 10)},
               *{f"LPT{i}" for i in range(1, 10)}}


def limpar_nome(valor, padrao="SEM_INFO", limite=80):
    """Torna um texto seguro para nome de pasta/arquivo no Windows."""
    texto = "" if valor is None else str(valor).strip()
    texto = _INVALIDOS.sub("-", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    if not texto:
        return padrao
    if texto.split(".")[0].upper() in _RESERVADOS:
        texto = f"_{texto}"
    return texto[:limite].rstrip(" .") or padrao


def _fmt(valor):
    if valor is None:
        return ""
    if isinstance(valor, (float, Decimal)):
        s = f"{valor:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    return str(valor).strip()


def decompor_chavesig(chavesig):
    """CHAVESIG = COD. FAZENDA (6) + SETOR (4) + TALHÃO (4). Ex.: 43018600010999"""
    cs = re.sub(r"\s+", "", str(chavesig or ""))
    if re.fullmatch(r"\d{14}", cs):
        return {"codigo": cs[:6], "setor": cs[6:10], "talhao": cs[10:14]}
    return {"codigo": "", "setor": "", "talhao": ""}


def _achar_atributo(atributos, chave):
    forcado = os.getenv(f"PDF_COL_{chave.upper()}")
    mapa = {str(k).upper(): k for k in atributos}
    if forcado and forcado.upper() in mapa:
        k = mapa[forcado.upper()]
        return k, _fmt(atributos[k])
    for nome in CANDIDATOS[chave]:
        if nome in mapa and _fmt(atributos[mapa[nome]]):
            k = mapa[nome]
            return k, _fmt(atributos[k])
    if chave == "fazenda":
        for up, k in mapa.items():
            if "FAZENDA" in up and _fmt(atributos[k]):
                return k, _fmt(atributos[k])
    return None, ""


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _nome_interno(chave):
    """'Aplicacao[AREA_OS]' -> 'AREA_OS'"""
    return re.sub(r"^[^\[]*\[|\]$", "", str(chave))


def _procurar(nome_logico, *fontes):
    """Valor (texto) do primeiro campo compatível com o nome lógico, nas fontes dadas."""
    forcado = os.getenv(f"PDF_COL_{nome_logico}")
    alvos = ({_norm(forcado)} if forcado
             else {_norm(a) for a in ALIASES.get(nome_logico, [])} | {_norm(nome_logico)})
    for fonte in fontes:
        for k, v in (fonte or {}).items():
            if _norm(_nome_interno(k)) in alvos and _fmt(v):
                return _fmt(v)
    fb = None if forcado else FALLBACK.get(nome_logico)
    if fb:
        for fonte in fontes:
            for k, v in (fonte or {}).items():
                if fb(_norm(_nome_interno(k))) and _fmt(v):
                    return _fmt(v)
    return ""


def _num_br(texto):
    """'1234.5' / '1.234,5' -> '1.234,50'"""
    if not texto:
        return ""
    try:
        v = float(texto.replace(".", "").replace(",", ".")) if "," in texto else float(texto)
    except ValueError:
        return texto
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_data(texto):
    if not texto:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", str(texto).strip()).replace("Z", "")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _fmt_data(dt):
    return dt.strftime("%d/%m/%Y") + (f" {dt:%H:%M}" if (dt.hour or dt.minute) else "")


def _talhao_ignorado(chavesig):
    talhao = decompor_chavesig(chavesig)["talhao"]
    return talhao.isdigit() and int(talhao) in TALHOES_IGNORADOS


def pasta_unidade(unidade):
    return NOME_PASTA_UNIDADE.get(str(unidade).strip(), str(unidade).strip())


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------

def _colunas_talhao(engine):
    from sqlalchemy import text
    if "cols" in _colunas_cache:
        return _colunas_cache["cols"]
    sql = text("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :tabela
          AND DATA_TYPE NOT IN ('geometry','geography','varbinary','binary',
                                'image','hierarchyid','xml')
        ORDER BY ORDINAL_POSITION
    """)
    with engine.connect() as conn:
        cols = [r[0] for r in conn.execute(
            sql, {"schema": TABELA_TALHOES[0], "tabela": TABELA_TALHOES[1]})]
    _colunas_cache["cols"] = cols
    return cols


def buscar_missoes_os(unidade, numero_os, cd_operacao, codigo_fazenda):
    """Todas as missões (talhões) da O.S., de qualquer status."""
    from sqlalchemy import text
    from config.database import engine

    filtros = ["UNIDADE = :u", "NUMERO_OS = :os"]
    params = {"u": unidade, "os": numero_os}
    if cd_operacao is None:
        filtros.append("CD_OPERACAO IS NULL")
    else:
        filtros.append("CD_OPERACAO = :cd")
        params["cd"] = cd_operacao
    if codigo_fazenda:
        filtros.append("CHAVESIG LIKE :pref")
        params["pref"] = f"{codigo_fazenda}%"

    sql = text(f"""
        SELECT CHAVESIG, CD_OPERACAO, DE_OPERACAO, RESPONSAVEL,
               DESCRICAO_RESPONSAVEL, STATUS
        FROM {TABELA_MISSOES}
        WHERE {' AND '.join(filtros)}
        ORDER BY CHAVESIG
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [
        {
            "chavesig": str(r["CHAVESIG"]).strip(),
            "cd_operacao": r["CD_OPERACAO"],
            "de_operacao": r["DE_OPERACAO"],
            "responsavel": r["RESPONSAVEL"],
            "descricao_responsavel": r["DESCRICAO_RESPONSAVEL"],
            "status": r["STATUS"],
        }
        for r in rows
    ]


def buscar_talhoes_base(chavesigs):
    """{chavesig: {"wkt","srid","atributos"}} (versão mais recente de cada talhão)."""
    from sqlalchemy import bindparam, text
    from config.database import engine

    if not chavesigs:
        return {}
    cols = _colunas_talhao(engine)
    selecao = ", ".join(f"[{c.replace(']', ']]')}]" for c in cols)
    selecao = (selecao + ", " if selecao else "") + \
        "Shape.STAsText() AS __WKT, Shape.STSrid AS __SRID"
    sql = text(f"""
        WITH T AS (
            SELECT {selecao},
                   CAST(Chavesig AS NVARCHAR(50)) AS __CHAVE,
                   ROW_NUMBER() OVER (
                       PARTITION BY CAST(Chavesig AS NVARCHAR(50))
                       ORDER BY GDB_FROM_DATE DESC) AS __RN
            FROM {TABELA_TALHOES[0]}.{TABELA_TALHOES[1]}
            WHERE CAST(Chavesig AS NVARCHAR(50)) IN :lista
              AND Shape IS NOT NULL
        )
        SELECT * FROM T WHERE __RN = 1
    """).bindparams(bindparam("lista", expanding=True))

    resultado = {}
    lista = list(dict.fromkeys(str(c).strip() for c in chavesigs))
    with engine.connect() as conn:
        for i in range(0, len(lista), 500):
            for row in conn.execute(sql, {"lista": lista[i:i + 500]}).mappings():
                row = dict(row)
                chave = str(row.pop("__CHAVE")).strip()
                row.pop("__RN", None)
                resultado[chave] = {
                    "wkt": row.pop("__WKT", None),
                    "srid": row.pop("__SRID", None),
                    "atributos": row,
                }
    return resultado


# ---------------------------------------------------------------------------
# Geometria e mapa
# ---------------------------------------------------------------------------

def parse_wkt_aneis(wkt):
    """Anéis [(x, y), ...] de POLYGON / MULTIPOLYGON (ignora Z/M)."""
    if not wkt:
        return []
    aneis = []
    for bloco in re.findall(r"\(([^()]+)\)", wkt):
        pts = []
        for par in bloco.split(","):
            nums = par.split()
            if len(nums) >= 2:
                try:
                    pts.append((float(nums[0]), float(nums[1])))
                except ValueError:
                    pass
        if len(pts) >= 3:
            aneis.append(pts)
    return aneis


def _centroide(anel):
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1]):
        f = x0 * y1 - x1 * y0
        area += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(area) < 1e-12:
        xs, ys = [p[0] for p in anel], [p[1] for p in anel]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * area), cy / (3 * area), abs(area / 2)


def _desenhar_mapa(c, talhoes, x, y, w, h):
    """talhoes: lista de {'rotulo': str, 'aneis': [...]}"""
    c.setStrokeColor(LINHA)
    c.setFillColor(colors.white)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h, stroke=1, fill=1)

    todos = [a for t in talhoes for a in t["aneis"]]
    if not todos:
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 10)
        c.drawCentredString(x + w / 2, y + h / 2, "Geometria dos talhões indisponível")
        return

    xs = [p[0] for a in todos for p in a]
    ys = [p[1] for a in todos for p in a]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    geografico = max(abs(minx), abs(maxx)) <= 180 and max(abs(miny), abs(maxy)) <= 90
    fx = math.cos(math.radians((miny + maxy) / 2)) if geografico else 1.0

    dx = max((maxx - minx) * fx, 1e-12)
    dy = max(maxy - miny, 1e-12)
    pad = 30
    esc = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
    ox = x + (w - dx * esc) / 2
    oy = y + (h - dy * esc) / 2

    def tr(px, py):
        return ox + (px - minx) * fx * esc, oy + (py - miny) * esc

    c.setLineWidth(1.2)
    for t in talhoes:
        if not t["aneis"]:
            continue
        path = c.beginPath()
        for anel in t["aneis"]:
            x0, y0 = tr(*anel[0])
            path.moveTo(x0, y0)
            for px, py in anel[1:]:
                path.lineTo(*tr(px, py))
            path.close()
        c.setFillColor(LARANJA, alpha=0.35)
        c.setStrokeColor(AZUL)
        c.drawPath(path, stroke=1, fill=1, fillMode=FILL_EVEN_ODD)

    # rótulo (nº do talhão) no centro do maior anel de cada talhão
    for t in talhoes:
        if not t["aneis"] or not t.get("rotulo"):
            continue
        maior = max(t["aneis"], key=lambda a: _centroide(a)[2])
        cx, cy, _ = _centroide(maior)
        px, py = tr(cx, cy)
        bx = [tr(*p)[0] for p in maior]
        largura_poligono = max(bx) - min(bx)
        for tam in (9, 7.5, 6.5):
            if stringWidth(t["rotulo"], "Helvetica-Bold", tam) + 4 <= largura_poligono:
                c.setFillColor(AZUL)
                c.setFont("Helvetica-Bold", tam)
                c.drawCentredString(px, py - tam / 3, t["rotulo"])
                break

    # seta norte
    nx, ny = x + w - 24, y + h - 20
    c.setFillColor(AZUL)
    c.setStrokeColor(AZUL)
    c.setLineWidth(0.8)
    p = c.beginPath()
    p.moveTo(nx, ny)
    p.lineTo(nx - 5, ny - 14)
    p.lineTo(nx, ny - 10)
    p.lineTo(nx + 5, ny - 14)
    p.close()
    c.drawPath(p, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(nx, ny + 3, "N")

    # barra de escala (coordenadas projetadas, em metros)
    if not geografico:
        alvo = (w * 0.25) / esc
        nice = 10000
        for cand in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
            if cand >= alvo * 0.5:
                nice = cand
                break
        comp = nice * esc
        bx0, by0 = x + 14, y + 14
        c.setStrokeColor(AZUL)
        c.setLineWidth(2)
        c.line(bx0, by0, bx0 + comp, by0)
        c.setLineWidth(0.8)
        c.line(bx0, by0 - 3, bx0, by0 + 3)
        c.line(bx0 + comp, by0 - 3, bx0 + comp, by0 + 3)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(AZUL)
        c.drawString(bx0, by0 + 5, f"{nice:,} m".replace(",", "."))


# ---------------------------------------------------------------------------
# Desenho: cabeçalho, rodapé, listas, tabela
# ---------------------------------------------------------------------------

def _truncar(texto, fonte, tam, largura):
    texto = str(texto)
    if stringWidth(texto, fonte, tam) <= largura:
        return texto
    while texto and stringWidth(texto + "…", fonte, tam) > largura:
        texto = texto[:-1]
    return texto + "…"


ALTURA_CABECALHO = 80


def _cabecalho(c, titulo, subtitulo, agora):
    larg, alt = PAGINA
    # faixa branca com logo + título
    x_texto = 28
    if LOGO_PATH.exists():
        try:
            c.drawImage(str(LOGO_PATH), 24, alt - 52, 100, 44,
                        preserveAspectRatio=True, anchor="w", mask="auto")
            x_texto = 140
        except Exception:
            pass
    c.setFillColor(AZUL)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(x_texto, alt - 34, _truncar(titulo, "Helvetica-Bold", 17, larg - x_texto - 24))

    # faixa laranja + bloco azul (como o site)
    y_faixa = alt - ALTURA_CABECALHO
    c.setFillColor(LARANJA)
    c.rect(0, y_faixa, larg, 26, stroke=0, fill=1)
    larg_bloco = 200
    c.setFillColor(AZUL)
    c.rect(larg - larg_bloco, y_faixa, larg_bloco, 26, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(28, y_faixa + 9,
                 _truncar(subtitulo, "Helvetica-Bold", 10, larg - larg_bloco - 56))
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(larg - larg_bloco / 2, y_faixa + 9,
                        f"Processado em {agora.strftime('%d/%m/%Y %H:%M')}")


def _rodape(c, chave, pagina):
    larg, _ = PAGINA
    c.setStrokeColor(AMARELO)
    c.setLineWidth(1.2)
    c.line(24, 28, larg - 24, 28)
    c.setFillColor(CINZA)
    c.setFont("Helvetica", 7)
    c.drawString(24, 16, f"O.S.: {chave}")
    c.setFillColor(AZUL)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(larg / 2, 16, "Equipe Geotecnologias")
    c.setFillColor(CINZA)
    c.setFont("Helvetica", 7)
    c.drawRightString(larg - 24, 16, f"Página {pagina}")


def _titulo_secao(c, texto, x, y):
    c.setFillColor(AZUL)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x, y, texto)
    c.setStrokeColor(LARANJA)
    c.setLineWidth(1.5)
    c.line(x, y - 3, x + stringWidth(texto, "Helvetica-Bold", 8.5), y - 3)


def _lista(c, itens, x, y_topo, largura, tam=9, max_linhas=4):
    """Lista vertical rótulo/valor com quebra de linha."""
    y = y_topo
    for rotulo, valor in itens:
        linhas = simpleSplit(valor or "-", "Helvetica-Bold", tam, largura - 10)[:max_linhas] or ["-"]
        altura = 12 + tam + (len(linhas) - 1) * (tam + 1.5) + 7
        c.setStrokeColor(LINHA)
        c.setLineWidth(0.6)
        c.rect(x, y - altura, largura, altura, stroke=1, fill=0)
        c.setFillColor(LARANJA)
        c.rect(x, y - altura, 2.5, altura, stroke=0, fill=1)
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 7, y - 8.5, rotulo.upper())
        c.setFillColor(AZUL)
        c.setFont("Helvetica-Bold", tam)
        for k, linha in enumerate(linhas):
            c.drawString(x + 7, y - 12 - tam - k * (tam + 1.5), linha)
        y -= altura
    return y


def _paginas_talhoes(c, linhas, titulo, agora, chave, pagina):
    larg, alt = PAGINA
    margem = 24
    util = larg - 2 * margem
    base = 36
    topo = alt - ALTURA_CABECALHO - 16
    h_cab, h_lin = 20, 17
    cols = COLUNAS_TABELA

    # larguras: conteúdo natural, depois ajustadas para ocupar exatamente a página
    nat = {}
    for col in cols:
        mx = stringWidth(col, "Helvetica-Bold", 7) + 12
        for lin in linhas:
            mx = max(mx, stringWidth(lin.get(col, ""), "Helvetica", 7.5) + 12)
        nat[col] = max(40, min(mx, 220))
    fator = util / sum(nat.values())
    larguras = {k: v * fator for k, v in nat.items()}

    por_pagina = max(int((topo - 30 - base - h_cab) // h_lin), 1)
    tem_sem_geom = any(l["__semgeom"] for l in linhas)

    for ini in range(0, len(linhas), por_pagina):
        bloco = linhas[ini:ini + por_pagina]
        c.showPage()
        pagina += 1
        _cabecalho(c, titulo, "Informações por talhão", agora)
        _titulo_secao(
            c, f"INFORMAÇÕES POR TALHÃO   |   talhões {ini + 1}–{ini + len(bloco)} de {len(linhas)}",
            margem, topo)
        if tem_sem_geom:
            c.setFillColor(LARANJA)
            c.setFont("Helvetica", 7.5)
            c.drawRightString(larg - margem, topo, "Linhas em laranja: talhão sem geometria na base")

        y = topo - 14
        c.setFillColor(AZUL)
        c.rect(margem, y - h_cab, util, h_cab, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        x = margem
        for k in cols:
            if k in COLUNAS_NUMERICAS:
                c.drawRightString(x + larguras[k] - 5, y - 13, k)
            else:
                c.drawString(x + 5, y - 13, _truncar(k, "Helvetica-Bold", 7, larguras[k] - 8))
            x += larguras[k]
        y -= h_cab

        for n, lin in enumerate(bloco):
            if n % 2 == 1:
                c.setFillColor(FUNDO_ZEBRA)
                c.rect(margem, y - h_lin, util, h_lin, stroke=0, fill=1)
            c.setFillColor(LARANJA if lin["__semgeom"] else colors.black)
            c.setFont("Helvetica", 7.5)
            x = margem
            for k in cols:
                txt = _truncar(lin.get(k, ""), "Helvetica", 7.5, larguras[k] - 8)
                if k in COLUNAS_NUMERICAS:
                    c.drawRightString(x + larguras[k] - 5, y - 12, txt)
                else:
                    c.drawString(x + 5, y - 12, txt)
                x += larguras[k]
            c.setStrokeColor(LINHA)
            c.setLineWidth(0.4)
            c.line(margem, y - h_lin, margem + util, y - h_lin)
            y -= h_lin
        _rodape(c, chave, pagina)
    return pagina


# ---------------------------------------------------------------------------
# Montagem do PDF
# ---------------------------------------------------------------------------

def _preparar(unidade, numero_os, cod_fazenda, missoes, talhoes_base, raws):
    """Estrutura única com tudo que o PDF precisa."""
    linhas, mapa, operadores, vistos = [], [], [], set()
    fazenda_nome = ""
    datas_fim = []
    texto_fim = ""
    exemplo_campos = []

    for m in missoes:
        ch = m["chavesig"]
        base = talhoes_base.get(ch)
        dec = decompor_chavesig(ch)
        atrib = (base or {}).get("atributos", {}) or {}
        raw = raws.get((unidade, numero_os, ch)) or {}
        fontes = (raw, atrib)

        _, nome_faz = _achar_atributo(atrib, "fazenda")
        fazenda_nome = fazenda_nome or nome_faz

        nome_op = _fmt(m.get("descricao_responsavel"))
        cod_op = _fmt(m.get("responsavel"))
        operador = f"{nome_op} (cód. {cod_op})" if nome_op and cod_op else (nome_op or cod_op)
        if operador and operador not in vistos:
            vistos.add(operador)
            operadores.append(operador)

        df = _procurar("DATA_FINAL", *fontes)
        dt = _parse_data(df)
        if dt:
            datas_fim.append(dt)
        texto_fim = texto_fim or df

        if not exemplo_campos and (raw or atrib):
            exemplo_campos = sorted(
                {_nome_interno(k) for k in raw} | {str(k) for k in atrib
                 if str(k).upper() not in COLUNAS_OCULTAS and not str(k).upper().startswith("GDB_")}
            )

        aneis = parse_wkt_aneis((base or {}).get("wkt"))
        linha = {
            "CODIGO": dec["codigo"] or _achar_atributo(atrib, "codigo")[1],
            "SETOR": dec["setor"] or _achar_atributo(atrib, "setor")[1],
            "TALHÃO": dec["talhao"] or _achar_atributo(atrib, "talhao")[1],
            "SAFRA": _procurar("SAFRA", *fontes),
            "VARIEDADE": _procurar("VARIEDADE", *fontes),
            "ESTAGIO": _procurar("ESTAGIO", *fontes),
            "AMBIENTE": _procurar("AMBIENTE", *fontes),
            "ADMIN": _procurar("ADMIN", *fontes),
            "AREA_OS": _num_br(_procurar("AREA_OS", *fontes)),
            "AREA_REALIZADA": _num_br(_procurar("AREA_REALIZADA", *fontes)),
            "__semgeom": not aneis,
        }
        linhas.append(linha)
        mapa.append({"chavesig": ch, "setor": linha["SETOR"], "talhao": linha["TALHÃO"], "aneis": aneis})

    setores = {t["setor"] for t in mapa if t["setor"]}
    for t in mapa:
        t["rotulo"] = (f"{t['setor']}/{t['talhao']}" if len(setores) > 1 else t["talhao"]) or ""

    data_final = _fmt_data(max(datas_fim)) if datas_fim else texto_fim

    operacao = ""
    for m in missoes:
        operacao = " - ".join(p for p in (_fmt(m.get("cd_operacao")), _fmt(m.get("de_operacao"))) if p)
        if operacao:
            break

    # avisos: campos que não foram achados em nenhum talhão
    avisos = []
    faltando = [c for c in COLUNAS_TABELA[3:] if not any(l[c] for l in linhas)]
    if not data_final:
        faltando.append("DATA_FINAL")
    if faltando:
        avisos.append(
            "Campos não encontrados nos dados: " + ", ".join(faltando) +
            ". Defina PDF_COL_<NOME>=<nome do campo> no .env. Campos disponíveis: " +
            (", ".join(exemplo_campos[:80]) or "(nenhum)")
        )

    return {
        "unidade": unidade, "numero_os": numero_os, "cod_fazenda": cod_fazenda,
        "fazenda_nome": fazenda_nome, "operacao": operacao, "operadores": operadores,
        "data_final": data_final,
        "linhas": linhas, "mapa": mapa, "avisos": avisos,
        "sem_geom": sum(1 for l in linhas if l["__semgeom"]),
    }


def _construir_pdf(caminho, d, agora):
    larg, alt = PAGINA
    margem = 24
    chave = f"{d['unidade']}_{d['numero_os']}"
    titulo = f"Ordem de Serviço Nº {d['numero_os']}"
    subtitulo = (f"{d['operacao'] or 'Operação não informada'}   |   Unidade {d['unidade']}"
                 f"   |   Fazenda {d['cod_fazenda'] or '-'}")

    c = canvas.Canvas(str(caminho), pagesize=PAGINA)
    c.setTitle(f"O.S. {d['numero_os']} - {d['unidade']}")
    c.setAuthor("Equipe Geotecnologias")
    c.setSubject(d["operacao"])

    _cabecalho(c, titulo, subtitulo, agora)

    topo = alt - ALTURA_CABECALHO - 16
    base = 36
    larg_info = 225
    x_mapa = margem + larg_info + 12
    larg_mapa = larg - margem - x_mapa

    _titulo_secao(c, "DADOS DA ORDEM DE SERVIÇO", margem, topo)
    itens = [
        ("Unidade", d["unidade"]),
        ("Código da fazenda", d["cod_fazenda"]),
        ("Fazenda", d["fazenda_nome"]),
        ("Ordem de serviço", str(d["numero_os"])),
        ("Operação", d["operacao"]),
        ("Operador" if len(d["operadores"]) <= 1 else "Operadores", "; ".join(d["operadores"])),
        ("Data final da O.S.", d["data_final"]),
        ("Talhões na O.S.", str(len(d["linhas"]))),
    ]
    if d["sem_geom"]:
        itens.append(("Talhões sem geometria na base", str(d["sem_geom"])))
    _lista(c, itens, margem, topo - 10, larg_info, tam=9, max_linhas=4)

    _titulo_secao(c, "MAPA DOS TALHÕES", x_mapa, topo)
    _desenhar_mapa(c, d["mapa"], x_mapa, base, larg_mapa, topo - 10 - base)
    _rodape(c, chave, 1)

    _paginas_talhoes(c, d["linhas"], titulo, agora, chave, 1)

    c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# Gravação segura
# ---------------------------------------------------------------------------

def _pdf_valido(caminho):
    try:
        tam = os.path.getsize(caminho)
        if tam < 500:
            return False
        with open(caminho, "rb") as f:
            inicio = f.read(5)
            f.seek(max(tam - 64, 0))
            fim = f.read()
        return inicio == b"%PDF-" and b"%%EOF" in fim
    except OSError:
        return False


def _trocar(tmp, destino):
    for i in range(TENTATIVAS_TROCA):
        try:
            os.replace(tmp, destino)
            return True
        except PermissionError:
            time.sleep(ESPERA_TENTATIVA_S * (i + 1))
    return False


def _alternativo(destino, n):
    return destino.with_name(f"{destino.stem}_v{n}{destino.suffix}")


def _limpar_antigos(destino, prefixo_os):
    """Remove versões _vN do arquivo e PDFs antigos da mesma O.S. (nome diferente)."""
    try:
        for f in destino.parent.glob(f"{prefixo_os}*.pdf"):
            if f.stem == destino.stem:
                continue
            try:
                f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _gravar_seguro(destino, d, agora, prefixo_os):
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(f".~{destino.stem}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        _construir_pdf(tmp, d, agora)
        if not _pdf_valido(tmp):
            raise RuntimeError("PDF gerado ficou inválido/corrompido")

        if _trocar(tmp, destino):
            _limpar_antigos(destino, prefixo_os)
            return destino, False

        for n in range(2, MAX_VERSOES_ALTERNATIVAS + 1):
            alt = _alternativo(destino, n)
            if _trocar(tmp, alt):
                return alt, True
        raise PermissionError("Arquivo e versões alternativas estão abertos/bloqueados")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def gerar_pdf_os(unidade, numero_os, cd_operacao, cod_fazenda,
                 raws=None, missoes=None, talhoes=None):
    """
    Gera (ou regera) o PDF de UMA ordem de serviço. NUNCA levanta exceção.
    missoes / talhoes: opcionais (testes); normalmente vêm do banco.
    """
    try:
        with _lock_geracao:
            agora = datetime.now()
            for ch, bruto in (raws or {}).items():
                if bruto:
                    _raw_cache.setdefault((unidade, numero_os, ch), {}).update(bruto)

            if missoes is None:
                missoes = buscar_missoes_os(unidade, numero_os, cd_operacao, cod_fazenda)
            if not missoes:
                raise ValueError("Nenhuma missão encontrada para a O.S.")
            missoes = [m for m in missoes if not _talhao_ignorado(m["chavesig"])]
            if not missoes:
                return {"status": "IGNORADO", "arquivo": None, "erro": None,
                        "os": f"{unidade}_{numero_os}"}
            if talhoes is None:
                talhoes = buscar_talhoes_base([m["chavesig"] for m in missoes])

            d = _preparar(unidade, numero_os, cod_fazenda, missoes, talhoes, _raw_cache)
            if all(l["__semgeom"] for l in d["linhas"]):
                return {"status": "SEM_GEOMETRIA", "arquivo": None, "erro": None,
                        "os": f"{unidade}_{numero_os}"}

            primeira = min(m["chavesig"] for m in missoes)
            pasta = (PDF_OUTPUT_DIR
                     / limpar_nome(pasta_unidade(unidade), "SEM_UNIDADE")
                     / limpar_nome(cod_fazenda, "SEM_CODIGO")
                     / limpar_nome(d["operacao"], "SEM_OPERACAO"))
            prefixo = f"{limpar_nome(unidade, 'SEMUN', 20)}_{limpar_nome(numero_os, 'SEMOS', 20)}_"
            destino = pasta / f"{prefixo}{limpar_nome(primeira, 'SEMCHAVE', 60)}.pdf"
            pasta.mkdir(parents=True, exist_ok=True)

            fingerprint = hashlib.sha1(json.dumps(
                {k: d[k] for k in ("unidade", "numero_os", "cod_fazenda", "fazenda_nome",
                                   "operacao", "operadores", "data_final")}
                | {"linhas": d["linhas"],
                   "mapa": [[t["chavesig"], t["aneis"]] for t in d["mapa"]]},
                default=str, sort_keys=True).encode("utf-8")).hexdigest()

            if _ultimas_geracoes.get(str(destino)) == fingerprint and destino.exists():
                return {"status": "SEM_ALTERACAO", "arquivo": str(destino), "erro": None,
                        "os": f"{unidade}_{numero_os}"}

            final, alternativo = _gravar_seguro(destino, d, agora, prefixo)
            if alternativo:
                _ultimas_geracoes.pop(str(destino), None)
                return {"status": "GERADO_ALTERNATIVO", "arquivo": str(final),
                        "erro": "PDF original estava aberto; gerado nome alternativo.",
                        "avisos": d["avisos"], "os": f"{unidade}_{numero_os}"}
            _ultimas_geracoes[str(destino)] = fingerprint
            return {"status": "GERADO", "arquivo": str(final), "erro": None,
                    "avisos": d["avisos"], "os": f"{unidade}_{numero_os}"}

    except Exception as e:
        return {"status": "ERRO", "arquivo": None,
                "erro": f"{type(e).__name__}: {e}", "os": f"{unidade}_{numero_os}"}


def gerar_pdfs_ordens_servico(missoes):
    """
    Recebe as missões (talhões) processadas, agrupa por O.S. e gera UM PDF por
    (unidade, O.S., operação, fazenda).

    É um GERADOR: devolve cada resultado assim que o PDF daquela O.S. fica pronto,
    para quem chamou poder marcar as missões como CONCLUIDO na hora.
    Cada resultado traz "chaves_missao" (as missões daquele grupo).
    """
    grupos = {}
    for m in missoes:
        cod = decompor_chavesig(m["chavesig"])["codigo"]
        chave = (m["unidade"], m["numero_os"], m.get("cd_operacao"), cod)
        grupos.setdefault(chave, []).append(m)

    for (unidade, numero_os, cd_op, cod), ms in grupos.items():
        raws = {m["chavesig"]: m.get("registro_bruto") for m in ms}
        resultado = gerar_pdf_os(unidade, numero_os, cd_op, cod, raws=raws)
        resultado["chaves_missao"] = [m["chave_missao"] for m in ms]
        yield resultado