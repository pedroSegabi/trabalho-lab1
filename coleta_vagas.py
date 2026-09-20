#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===============================================================================
 LABORATORIO 1 - COLETA E PREPARACAO DE DADOS
 Web Scraping de um portal de vagas de emprego
===============================================================================
 Portal ......: ProgramaThor  -  https://programathor.com.br
 Area/cargo ..: vagas de desenvolvimento em PYTHON
 Saidas ......: robots_programathor.txt, sitemap_programathor.txt,
                vagas_programathor.csv, vagas_programathor.json
 Bibliotecas .: requests, urllib, BeautifulSoup (bs4), re, selenium,
                pandas, csv/json, time, datetime  (todas vistas em aula)

 ETAPAS
   1) Verificacao de robots.txt e sitemap.xml  (boas praticas - AULA 7)
   2) BUSCA pelo assunto feita pelo proprio codigo, interagindo com o site
      via Selenium (AULA 11): abre o modal "Todos os skills" e clica em "Python"
   3) Navegacao por >= 3 paginas de resultados (paginacao real do site)
   4) Extracao dos dados de cada vaga (BeautifulSoup + seletores CSS + regex)
   5) Limpeza: remocao de duplicatas e tratamento de campos ausentes
   6) Gravacao em arquivo estruturado (CSV e JSON)

 OBS.: nenhuma API e consumida - toda a coleta e feita sobre o HTML das paginas.
===============================================================================
"""

import csv
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

try:
    import pandas as pd
    TEM_PANDAS = True
except ImportError:
    TEM_PANDAS = False

# ----------------------------------------------------------------------------
# CONFIGURACOES
# ----------------------------------------------------------------------------
BASE_URL = "https://programathor.com.br"
URL_LISTAGEM = f"{BASE_URL}/jobs"
TERMO_BUSCA = "Python"          # assunto/area pesquisada pelo programa
URL_FALLBACK = f"{BASE_URL}/jobs-python"   # usada se o Selenium nao estiver disponivel

N_PAGINAS = 3                   # minimo exigido pelo enunciado
ESPERA = 1.5                    # segundos entre requisicoes (nao sobrecarregar o servidor)
TIMEOUT = 20
MAX_TENTATIVAS = 3

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
              "(projeto-academico-web-scraping)")
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"}

ARQ_ROBOTS = "robots_programathor.txt"
ARQ_SITEMAP = "sitemap_programathor.txt"
ARQ_CSV = "vagas_programathor.csv"
ARQ_JSON = "vagas_programathor.json"

CAMPO_VAZIO = "Nao informado"

# Textos que o portal usa quando a informacao NAO foi divulgada pelo anunciante.
# Precisam virar CAMPO_VAZIO, senao a contagem de campos ausentes da sempre zero.
SEM_INFORMACAO = {"nao especificado", "não especificado", "a combinar",
                  "nao informado", "não informado", "-"}

# Expressoes regulares reutilizadas -------------------------------------------
RE_LINK_VAGA = re.compile(r"^/jobs/\d+-[^/?#]+$")            # /jobs/33771-junior-fullstack-developer
RE_EMPRESA = re.compile(r"/companies/\d+")                   # perfil real (ignora /companies/sign_in)
RE_PAGINACAO = re.compile(r"[?&]page=(\d+)")                 # o portal pagina com ?page=N
# Remove o par "page=N" preservando a pontuacao. O sub("") anterior apagava
# tambem o "?" inicial e transformava "?page=2&remoto=1" em "&remoto=1".
RE_PAGINA_PARAM = re.compile(r"([?&])page=\d+&?")
RE_SALARIO = re.compile(r"Sal[aá]rio:\s*([^\n]+)", re.IGNORECASE)
# Exige separador de milhar: sem ele o regex capturava trechos como
# "R$ 50 milhoes" da descricao da empresa e os gravava como faixa salarial.
RE_VALOR_RS = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})+(?:,\d{2})?")
RE_LOCAL = re.compile(r"Localiza[cç][aã]o:\s*([^\n]+)", re.IGNORECASE)
RE_CONTRATO = re.compile(r"\b(CLT|PJ|Est[aá]gio|Freelancer)\b", re.IGNORECASE)
RE_NIVEL = re.compile(r"\b(J[uú]nior|Pleno|S[eê]nior|Est[aá]gio|Trainee)\b", re.IGNORECASE)
RE_SITEMAP_ROBOTS = re.compile(r"^\s*Sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
RE_DISALLOW = re.compile(r"^\s*Disallow:\s*(\S*)", re.IGNORECASE | re.MULTILINE)
RE_LOC_XML = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
RE_ESPACOS = re.compile(r"\s+")
# Marca onde o anuncio acaba: dali para baixo a pagina lista OUTRAS vagas
# ("Veja vagas similares"), cujos titulos contaminavam nivel/contrato/salario.
RE_FIM_VAGA = re.compile(r"Veja vagas similares|N[aã]o perca nenhuma oportunidade",
                         re.IGNORECASE)

sessao = requests.Session()
sessao.headers.update(HEADERS)


# ============================================================================
# FUNCOES AUXILIARES
# ============================================================================
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def salvar_texto(caminho, conteudo):
    """
    Grava um arquivo texto sem deixar erro de E/S escapar (disco cheio, falta
    de permissao, arquivo aberto em outro programa). Devolve True se gravou.
    """
    try:
        with open(caminho, "w", encoding="utf-8") as fp:
            fp.write(conteudo)
        return True
    except OSError as erro:
        log(f"  ! Nao foi possivel gravar '{caminho}': {type(erro).__name__}: {erro}")
        return False


def limpar(texto, padrao=CAMPO_VAZIO, limite=None):
    """Normaliza espacos/quebras de linha e devolve um valor padrao se vier vazio."""
    if texto is None:
        return padrao
    texto = RE_ESPACOS.sub(" ", str(texto)).strip()
    if not texto:
        return padrao
    if limite and len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0] + " [...]"
    return texto


def limpar_opcional(texto, limite=None):
    """
    Igual a limpar(), mas tambem converte em CAMPO_VAZIO os rotulos que o
    proprio portal usa para dizer que o dado nao foi divulgado
    (ex.: "Salario: Nao especificado").
    """
    valor = limpar(texto, limite=limite)
    if valor.lower().strip(" .") in SEM_INFORMACAO:
        return CAMPO_VAZIO
    return valor


# Formas canonicas para o campo "nivel": o regex casa sem diferenciar
# maiusculas/acentos ("Senior", "Senior", "PLENO"), entao o valor bruto
# nao serve como chave de agrupamento.
NIVEIS_CANONICOS = {
    "junior": "Junior",
    "pleno": "Pleno",
    "senior": "Senior",
    "trainee": "Trainee",
    "estagio": "Estagio",
}


def normalizar_nivel(bruto):
    """Reduz 'Senior'/'Senior'/'SENIOR' a uma unica forma canonica."""
    if not bruto or bruto == CAMPO_VAZIO:
        return CAMPO_VAZIO
    chave = (bruto.lower()
             .replace("ú", "u").replace("ê", "e").replace("é", "e")
             .replace("á", "a").replace("ã", "a"))
    return NIVEIS_CANONICOS.get(chave, bruto)


CONTRATOS_CANONICOS = {"clt": "CLT", "pj": "PJ",
                       "estagio": "Estagio", "freelancer": "Freelancer"}


def normalizar_contrato(bruto):
    """RE_CONTRATO passou a ignorar maiusculas, entao 'clt' e 'CLT' sao o mesmo."""
    if not bruto or bruto == CAMPO_VAZIO:
        return CAMPO_VAZIO
    chave = bruto.lower().replace("á", "a").replace("ã", "a")
    return CONTRATOS_CANONICOS.get(chave, bruto)


def baixar_pagina(url, tentativas=MAX_TENTATIVAS):
    """
    Faz GET com requests, tratando timeouts, erros de rede e status != 200.
    Retorna o HTML (str) ou None - nunca levanta excecao para quem chama.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = sessao.get(url, timeout=TIMEOUT)
            if resposta.status_code == 200:
                # So adivinha o encoding quando o servidor nao declara um:
                # sobrescrever um charset correto corrompe acentos, e rodar a
                # deteccao no sitemap de 2 MB e lento sem necessidade.
                tipo = resposta.headers.get("Content-Type", "").lower()
                if resposta.encoding is None or "charset" not in tipo:
                    resposta.encoding = resposta.apparent_encoding or "utf-8"
                return resposta.text
            log(f"  ! HTTP {resposta.status_code} em {url}")
        except requests.exceptions.RequestException as erro:
            log(f"  ! Falha ({tentativa}/{tentativas}) em {url}: {type(erro).__name__}")
        time.sleep(ESPERA * tentativa)
    return None


# ============================================================================
# ETAPA 1 - ROBOTS.TXT E SITEMAP.XML
# ============================================================================
def verificar_robots_e_sitemap():
    """
    Baixa e analisa /robots.txt e o(s) sitemap(s) do portal.
    Salva os dois em disco (evidencia para o relatorio) e devolve um
    RobotFileParser ja carregado para consultar permissoes por URL.
    """
    log("ETAPA 1 - Verificando robots.txt e sitemap.xml")
    parser = RobotFileParser()
    parser.set_url(urljoin(BASE_URL, "/robots.txt"))

    texto_robots = baixar_pagina(urljoin(BASE_URL, "/robots.txt"))
    if texto_robots is None:
        log("  robots.txt nao encontrado/inacessivel -> assumindo coleta permitida")
        parser.parse([])
        return parser

    if salvar_texto(ARQ_ROBOTS, texto_robots):
        log(f"  robots.txt salvo em '{ARQ_ROBOTS}' ({len(texto_robots)} caracteres)")

    parser.parse(texto_robots.splitlines())

    bloqueios = [d for d in RE_DISALLOW.findall(texto_robots) if d]
    log(f"  Regras Disallow encontradas ({len(bloqueios)}): {bloqueios[:15]}")

    # ---- sitemaps declarados no robots.txt (+ tentativa no caminho padrao)
    sitemaps = RE_SITEMAP_ROBOTS.findall(texto_robots) or [urljoin(BASE_URL, "/sitemap.xml")]
    log(f"  Sitemaps declarados: {sitemaps}")

    urls_sitemap = []
    for url_sm in sitemaps[:3]:
        xml = baixar_pagina(url_sm)
        time.sleep(ESPERA)
        if not xml:
            continue
        encontradas = RE_LOC_XML.findall(xml)
        # se for um indice de sitemaps, abre o primeiro sub-sitemap
        if "<sitemapindex" in xml.lower() and encontradas:
            sub = baixar_pagina(encontradas[0])
            time.sleep(ESPERA)
            if sub:
                encontradas = RE_LOC_XML.findall(sub)
        urls_sitemap.extend(encontradas)

    if urls_sitemap:
        salvar_texto(ARQ_SITEMAP, "\n".join(urls_sitemap))
        vagas_no_sitemap = [u for u in urls_sitemap if "/jobs" in u]
        log(f"  Sitemap: {len(urls_sitemap)} URLs listadas "
            f"({len(vagas_no_sitemap)} contendo '/jobs') -> salvo em '{ARQ_SITEMAP}'")
    else:
        log("  Nenhum sitemap XML pode ser lido.")

    return parser


def garantir_permissao(parser, url):
    """
    Confere o robots.txt para a URL que SERA mesmo coletada.

    A checagem era feita sobre URL_LISTAGEM (/jobs), mas a coleta comeca na
    URL de resultados da busca (/jobs-python, ou a que o Selenium devolver):
    podiam ser areas diferentes, com regras diferentes.
    """
    permitido = parser.can_fetch(USER_AGENT, url)
    log(f"  can_fetch('{url}') = {permitido}")
    if not permitido:
        log("  ATENCAO: robots.txt NAO permite coletar essa area. Coleta abortada.")
        sys.exit(1)


# ============================================================================
# ETAPA 2 - BUSCA PELO ASSUNTO INTERAGINDO COM O SITE (SELENIUM)
# ============================================================================
def buscar_com_selenium(termo=TERMO_BUSCA):
    """
    Abre um navegador real, acessa a pagina de vagas, abre o menu
    "Todos os skills" e CLICA no link da tecnologia procurada.
    Retorna a URL de resultados a que o site nos levou, ou None em caso de falha.
    """
    log(f"ETAPA 2 - Buscando '{termo}' no site (Selenium)")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        log("  Selenium nao instalado -> usando navegacao direta (requests)")
        return None

    opcoes = Options()
    opcoes.add_argument("--headless=new")
    opcoes.add_argument("--window-size=1920,1080")
    opcoes.add_argument(f"--user-agent={USER_AGENT}")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--no-sandbox")

    driver = None
    try:
        driver = webdriver.Chrome(options=opcoes)
        driver.get(URL_LISTAGEM)
        espera = WebDriverWait(driver, 15)

        # 2.1 abre o modal com a lista completa de skills
        botao = espera.until(EC.presence_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(text()), 'Todos os skills')]")))
        driver.execute_script("arguments[0].click();", botao)
        time.sleep(1.5)

        # 2.2 clica no link cujo TEXTO EXATO e o termo procurado
        link = espera.until(EC.presence_of_element_located(
            (By.XPATH, f"//a[normalize-space(text())='{termo}']")))
        destino = link.get_attribute("href")
        driver.execute_script("arguments[0].click();", link)

        # Esperar a navegacao de verdade. Com time.sleep() fixo, um clique
        # lento deixava current_url ainda em /jobs e a coleta seguia nas vagas
        # GENERICAS, sem erro nenhum. O "or destino" nao protegia: current_url
        # e uma string nao-vazia mesmo quando nada navegou.
        try:
            espera.until(EC.url_changes(URL_LISTAGEM))
        except Exception:                          # noqa: BLE001
            log("  A URL nao mudou apos o clique - usando o href do proprio link")

        url_resultados = driver.current_url
        if url_resultados.rstrip("/") == URL_LISTAGEM.rstrip("/"):
            url_resultados = destino
        if not url_resultados:
            return None

        log(f"  Busca concluida -> {url_resultados}")
        return url_resultados

    except Exception as erro:                      # noqa: BLE001 (fallback proposital)
        log(f"  Selenium falhou ({type(erro).__name__}) -> usando navegacao direta")
        return None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:                      # noqa: BLE001
                pass


# ============================================================================
# ETAPA 3 - NAVEGACAO PELAS PAGINAS DE RESULTADOS
# ============================================================================
def links_das_vagas(soup):
    """
    Seletor CSS a[href*='/jobs/'] + regex para manter apenas os links de vaga
    (descarta filtros, breadcrumbs e links institucionais).
    """
    achados = []
    for ancora in soup.select("a[href*='/jobs/']"):
        # urlparse().path em vez de split("?"): o seletor tambem casa com
        # hrefs absolutos, e RE_LINK_VAGA (ancorado em "^/jobs/") descartaria
        # TODOS eles em silencio se o portal passasse a emiti-los.
        caminho = urlparse(ancora.get("href") or "").path.rstrip("/")
        if RE_LINK_VAGA.match(caminho):
            achados.append(urljoin(BASE_URL, caminho))
    return achados


# O portal marca o link de avanco com rel="Próx" (e o de volta com
# rel="prev"/"Ante"). Casar o valor exato - e nao um prefixo - evita andar
# para tras, ja que "prev" tambem comeca com "pr".
REL_PROXIMA = {"próx", "prox", "next"}


def proxima_pagina(soup, url_atual, numero):
    """
    Descobre o link da proxima pagina pelo proprio HTML.

    1o criterio: o atributo rel do link de avanco. E semantico e nao depende
       do texto visivel nem das classes CSS do tema.
    2o criterio: o texto do link ("Next ›"), ainda exigindo que o href seja
       mesmo um link de paginacao (?page=N). O texto sozinho NAO basta: o card
       de uma vaga que usa a tecnologia "NextJS" tambem contem "next" e seria
       aceito por engano, desviando a coleta para uma pagina de vaga.
    3o criterio: monta ?page=N sobre a URL atual. Tambem e o caminho usado
       quando soup e None, isto e, quando a pagina nao pode ser baixada.
    """
    if soup is not None:
        for ancora in soup.select("a[rel][href]"):
            rel = " ".join(ancora.get("rel") or []).lower()
            href = ancora.get("href") or ""
            if rel in REL_PROXIMA and RE_PAGINACAO.search(href):
                return urljoin(BASE_URL, href)

        for ancora in soup.select("a[href]"):
            href = ancora.get("href") or ""
            if not RE_PAGINACAO.search(href):
                continue
            texto = ancora.get_text(" ", strip=True).lower()
            if "next" in texto or "›" in texto or "próxima" in texto or "proxima" in texto:
                return urljoin(BASE_URL, href)

    base = RE_PAGINA_PARAM.sub(r"\1", url_atual).rstrip("?&")
    separador = "&" if "?" in base else "?"
    return f"{base}{separador}page={numero}"


def coletar_links(url_inicial, n_paginas=N_PAGINAS):
    """Percorre n paginas de resultados e devolve a lista de URLs de vagas."""
    log(f"ETAPA 3 - Percorrendo {n_paginas} paginas de resultados")
    url = url_inicial
    links, vistos = [], set()

    for pagina in range(1, n_paginas + 1):
        html = baixar_pagina(url)
        if html is None:
            # Nao abortar: um erro transitorio (o portal devolve HTTP 500 de
            # vez em quando) derrubava todas as paginas seguintes e a coleta
            # terminava com menos de 3 paginas.
            log(f"  Pagina {pagina} nao pode ser baixada - tentando a proxima")
            url = proxima_pagina(None, url, pagina + 1)
            time.sleep(ESPERA)
            continue
        soup = BeautifulSoup(html, "html.parser")

        novos = 0
        for link in links_das_vagas(soup):
            if link not in vistos:                 # deduplicacao ja na coleta
                vistos.add(link)
                links.append((link, pagina))
                novos += 1
        log(f"  Pagina {pagina}: {novos} vagas novas  ({url})")

        if pagina < n_paginas:
            url = proxima_pagina(soup, url, pagina + 1)
            if RE_LINK_VAGA.match(urlparse(url).path):
                log("  Link de paginacao invalido (aponta para uma vaga) - parando")
                break
            time.sleep(ESPERA)

    log(f"  Total de links unicos coletados: {len(links)}")
    return links


# ============================================================================
# ETAPA 4 - EXTRACAO DOS DADOS DE CADA VAGA
# ============================================================================
def texto_da_vaga(soup):
    """
    Texto da pagina ATE onde o anuncio termina.

    Abaixo de "Veja vagas similares" o portal lista OUTRAS vagas. Os titulos
    delas ("... Senior ...", "... Pleno ...") eram capturados pelos regex de
    nivel/contrato/salario sempre que a vaga em questao nao declarava o campo,
    gravando o dado de um anuncio alheio em vez do valor padrao.
    """
    texto = soup.get_text("\n", strip=True)
    corte = RE_FIM_VAGA.search(texto)
    return texto[:corte.start()] if corte else texto


def texto_cabecalho(soup, texto_vaga):
    """
    Bloco de informacoes da vaga: empresa, porte, contrato, modalidade,
    localizacao, salario e nivel.

    Vai da ultima ocorrencia do titulo (o fim do breadcrumb, ja depois do menu
    do site) ate o inicio da primeira secao <h3> do anuncio. Delimitar esse
    trecho e o que faz um campo ausente sair como CAMPO_VAZIO em vez de sair
    com o valor de outra parte da pagina.
    """
    h1 = soup.select_one("h1")
    inicio = texto_vaga.rfind(h1.get_text(" ", strip=True)) if h1 else -1
    inicio = max(inicio, 0)
    fim = len(texto_vaga)
    for cabecalho in soup.find_all("h3"):
        posicao = texto_vaga.find(cabecalho.get_text(" ", strip=True), inicio + 1)
        if 0 <= posicao < fim:
            fim = posicao
    return texto_vaga[inicio:fim]


TITULOS = ("h1", "h2", "h3", "h4", "h5")
SEM_TEXTO_UTIL = ("script", "style", "noscript")


def _texto_da_secao(alvo, limite):
    """
    Recolhe os nos de texto que vem depois de `alvo` em ordem de documento,
    parando no proximo titulo.

    Quando `limite` e dado, a varredura nao sai da subarvore dele. E isso que
    impede a secao de vazar para a barra lateral ("Seu perfil combina em ...%",
    "Acesse o perfil da empresa") quando ela e a ULTIMA do anuncio e portanto
    nao ha titulo seguinte servindo de parada.
    """
    proprios = {id(no) for no in alvo.descendants}
    dentro = {id(no) for no in limite.descendants} if limite is not None else None

    partes = []
    for no in alvo.next_elements:
        if id(no) in proprios:              # o texto do proprio titulo
            continue
        if dentro is not None and id(no) not in dentro:
            break                           # saiu do container da secao
        if getattr(no, "name", None) in TITULOS:
            break                           # proxima secao, aninhada ou nao
        if isinstance(no, Comment) or not isinstance(no, NavigableString):
            continue
        if no.parent is not None and no.parent.name in SEM_TEXTO_UTIL:
            continue
        texto = no.strip()
        if not texto:
            continue
        if RE_FIM_VAGA.search(texto):       # nunca passar do fim do anuncio
            break
        partes.append(texto)
    return " ".join(partes)


def extrair_secao(soup, padrao_titulo):
    """
    Localiza um titulo de secao (h2..h5) pelo texto e concatena o conteudo
    ate o proximo titulo. Usado para 'Requisitos', 'Atividades', etc.

    Percorre a arvore em ordem de documento em vez de apenas os irmaos do
    titulo, o que conserta dois casos que find_next_siblings() errava - e como
    'requisitos' e 'descricao' usam esta mesma funcao, os dois campos
    obrigatorios do enunciado erravam juntos:

      1) proximo titulo aninhado numa <div>: o break so olhava irmaos, entao a
         secao VAZAVA para dentro da seguinte;
      2) titulo dentro de um wrapper (<div class="cab"><h3>...</h3></div>): o
         conteudo nao e irmao do titulo, entao o resultado vinha VAZIO.

    A varredura fica presa ao container do titulo; so quando ela nao acha nada
    (caso 2) e que a busca se estende ao resto do documento.
    """
    alvo = None
    for cabecalho in soup.find_all(["h2", "h3", "h4", "h5"]):
        if re.search(padrao_titulo, cabecalho.get_text(" ", strip=True), re.IGNORECASE):
            alvo = cabecalho
            break
    if alvo is None:
        return ""

    conteudo = _texto_da_secao(alvo, alvo.parent)
    if not conteudo:
        conteudo = _texto_da_secao(alvo, None)
    return conteudo


def extrair_tecnologias(soup):
    """
    Tags de tecnologia da vaga: links cujo href comeca com '/jobs-'.
    Exclui '/jobs-city/...' (localidade) e os links do rodape ('Vagas programador X').
    """
    tecnologias = []
    for ancora in soup.select("a[href^='/jobs-']"):
        href = ancora.get("href", "")
        texto = ancora.get_text(" ", strip=True)
        if href.startswith("/jobs-city") or not texto:
            continue
        if texto.lower().startswith("vagas"):
            continue
        if texto not in tecnologias:
            tecnologias.append(texto)
    return ", ".join(tecnologias)


def extrair_vaga(url, pagina_origem):
    """Baixa a pagina da vaga e devolve um dicionario ja tratado (ou None)."""
    html = baixar_pagina(url)
    if html is None:
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        # "texto" para onde o anuncio acaba e "cabecalho" isola o bloco de
        # informacoes da vaga. Antes os regex varriam a pagina inteira.
        texto = texto_da_vaga(soup)
        cabecalho = texto_cabecalho(soup, texto)

        # -- titulo: primeiro <h1> da pagina
        h1 = soup.select_one("h1")
        titulo = limpar(h1.get_text(" ", strip=True) if h1 else None)

        # -- empresa: link para o PERFIL da empresa (/companies/<id>).
        # O filtro por id numerico e essencial: o cabecalho do site tem
        # /companies/sign_in e /companies/sign_up, cujo texto e "Como empresa".
        empresa = CAMPO_VAZIO
        for ancora in soup.select("a[href*='/companies/']"):
            if not RE_EMPRESA.search(ancora.get("href") or ""):
                continue
            nome = limpar(ancora.get_text(" ", strip=True))
            if nome == CAMPO_VAZIO or nome.lower().startswith("conheça"):
                continue
            empresa = nome
            break

        # Empresas sem perfil publico no portal nao tem essa ancora nenhuma;
        # nesses anuncios o nome esta no <h2> logo apos o <h1>.
        if empresa == CAMPO_VAZIO and h1 is not None:
            h2 = h1.find_next("h2")
            empresa = limpar(h2.get_text(" ", strip=True) if h2 else None)

        # -- local: rotulo "Localizacao:" no bloco de informacoes da vaga
        m_local = RE_LOCAL.search(cabecalho)
        local = limpar_opcional(m_local.group(1) if m_local else None)

        # -- faixa salarial: rotulo "Salario:"; se o portal disser
        # "Nao especificado", procura um "R$ ..." no proprio anuncio (nunca no
        # rodape nem nas vagas similares).
        m_sal = RE_SALARIO.search(cabecalho)
        salario = limpar_opcional(m_sal.group(1) if m_sal else None)
        if salario == CAMPO_VAZIO:
            valores = RE_VALOR_RS.findall(texto)
            if len(valores) >= 2:
                salario = f"{valores[0]} a {valores[1]}"
            elif valores:
                salario = valores[0]        # um valor so nao e uma faixa

        # -- metadados extras (buscados no cabecalho, nao na pagina inteira)
        m_contrato = RE_CONTRATO.search(cabecalho)
        contrato = normalizar_contrato(
            limpar(m_contrato.group(1) if m_contrato else None))
        m_nivel = RE_NIVEL.search(titulo) or RE_NIVEL.search(cabecalho)
        nivel = normalizar_nivel(limpar(m_nivel.group(1) if m_nivel else None))

        # -- requisitos e descricao (secoes do anuncio)
        requisitos = limpar(extrair_secao(soup, r"Requisitos|Qualifica"), limite=3000)
        descricao = limpar(
            " ".join(filter(None, [
                extrair_secao(soup, r"Atividades|Responsabilidades|Sobre a vaga"),
                extrair_secao(soup, r"Descri[cç][aã]o da empresa"),
            ])), limite=3000)

        # Se nenhuma secao foi reconhecida, guarda o texto do anuncio a partir
        # do titulo - assim nao entram o menu do site (acima) nem as vagas
        # similares (abaixo, ja cortadas por texto_da_vaga).
        if requisitos == CAMPO_VAZIO and descricao == CAMPO_VAZIO:
            inicio = texto.rfind(titulo) if titulo != CAMPO_VAZIO else -1
            descricao = limpar(texto[max(inicio, 0):], limite=3000)

        return {
            "titulo": titulo,
            "empresa": empresa,
            "local": local,
            "faixa_salarial": salario,
            "tipo_contrato": contrato,
            "nivel": nivel,
            "tecnologias": limpar(extrair_tecnologias(soup)),
            "requisitos": requisitos,
            "descricao": descricao,
            "link": url,
            "pagina_origem": pagina_origem,
            "data_coleta": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as erro:                      # noqa: BLE001
        log(f"  ! Erro ao processar {url}: {type(erro).__name__}: {erro}")
        return None


# ============================================================================
# ETAPA 5 e 6 - LIMPEZA E GRAVACAO
# ============================================================================
COLUNAS = ["titulo", "empresa", "local", "faixa_salarial", "tipo_contrato",
           "nivel", "tecnologias", "requisitos", "descricao", "link",
           "pagina_origem", "data_coleta"]


def remover_duplicatas(registros):
    """
    Deduplicacao UNICA para os dois caminhos de gravacao (com e sem pandas),
    que antes usavam criterios diferentes e geravam arquivos diferentes.

    1) Mesmo link -> mesma vaga.
    2) Mesmo titulo + mesma empresa -> anuncio republicado (o portal de fato
       repete a mesma vaga com ids diferentes). So vale quando a empresa foi
       identificada: com a empresa ausente, duas vagas homonimas de empresas
       DIFERENTES colapsariam numa so.

    Tambem aplica CAMPO_VAZIO aos campos ausentes, garantindo que toda linha
    saia com as 12 colunas preenchidas.
    """
    unicos, links, anuncios = [], set(), set()
    for reg in registros:
        link = reg.get("link")
        if link in links:
            continue
        chave = (reg.get("titulo"), reg.get("empresa"))
        if reg.get("empresa") != CAMPO_VAZIO and chave in anuncios:
            continue
        links.add(link)
        anuncios.add(chave)
        unicos.append({c: (reg.get(c) if reg.get(c) not in (None, "") else CAMPO_VAZIO)
                       for c in COLUNAS})
    return unicos


def tratar_e_salvar(registros):
    log("ETAPA 5 - Tratando os dados (duplicatas e campos ausentes)")
    if not registros:
        log("  Nenhum registro coletado - nada a salvar.")
        return

    unicos = remover_duplicatas(registros)
    log(f"  {len(registros)} registros -> {len(unicos)} apos remocao de duplicatas")
    for coluna in ("empresa", "local", "faixa_salarial", "tipo_contrato", "nivel"):
        ausentes = sum(1 for r in unicos if r[coluna] == CAMPO_VAZIO)
        log(f"  Vagas sem '{coluna}' divulgado: {ausentes}")

    try:
        if TEM_PANDAS:
            df = pd.DataFrame(unicos, columns=COLUNAS).fillna(CAMPO_VAZIO)
            df.to_csv(ARQ_CSV, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL)
            df.to_json(ARQ_JSON, orient="records", force_ascii=False, indent=2)
        else:
            with open(ARQ_CSV, "w", newline="", encoding="utf-8-sig") as fp:
                escritor = csv.DictWriter(fp, fieldnames=COLUNAS, quoting=csv.QUOTE_ALL)
                escritor.writeheader()
                escritor.writerows(unicos)
            with open(ARQ_JSON, "w", encoding="utf-8") as fp:
                json.dump(unicos, fp, ensure_ascii=False, indent=2)
    except OSError as erro:
        # Caso classico: o CSV da execucao anterior aberto no Excel.
        log(f"  ! Falha ao gravar os arquivos: {type(erro).__name__}: {erro}")
        log("    Feche o CSV/JSON se estiverem abertos e rode novamente.")
        return

    log(f"ETAPA 6 - Arquivos gerados: '{ARQ_CSV}' e '{ARQ_JSON}' ({len(unicos)} vagas)")


# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================
def main():
    print("=" * 79)
    print(f" COLETA DE VAGAS - {BASE_URL}  |  termo de busca: '{TERMO_BUSCA}'")
    print("=" * 79)

    robots = verificar_robots_e_sitemap()

    url_resultados = buscar_com_selenium(TERMO_BUSCA)
    if url_resultados is None:
        # Degradacao EXPLICITA: o fallback e uma URL de resultados fixa, ou
        # seja, nao cumpre o requisito de buscar o termo interagindo com o
        # site. Antes isso acontecia em silencio e o CSV saia igual.
        log("  !! A busca interativa falhou; usando a URL fixa de resultados.")
        log("  !! Esta execucao NAO cumpre o requisito 'busca feita pelo codigo'.")
        log("  !! Verifique se o Chrome e o ChromeDriver estao instalados.")
        url_resultados = URL_FALLBACK
    time.sleep(ESPERA)

    garantir_permissao(robots, url_resultados)
    links = coletar_links(url_resultados, N_PAGINAS)

    log("ETAPA 4 - Abrindo a pagina de cada vaga")
    registros = []
    for i, (link, pagina) in enumerate(links, start=1):
        if not robots.can_fetch(USER_AGENT, link):     # respeita o robots.txt vaga a vaga
            log(f"  [{i}/{len(links)}] bloqueado pelo robots.txt: {link}")
            continue
        vaga = extrair_vaga(link, pagina)
        if vaga:
            registros.append(vaga)
            log(f"  [{i}/{len(links)}] {vaga['titulo'][:55]}")
        time.sleep(ESPERA)

    tratar_e_salvar(registros)
    print("=" * 79)


if __name__ == "__main__":
    main()
