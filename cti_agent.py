"""
=============================================================================
PROJETO: Automação de Briefing Executivo de IA (CTI - Cyber Tech Intelligence)
VERSÃO: RSS + Gemini, com robustez para produção
=============================================================================

Este script lê feeds RSS de fontes de tecnologia, filtra o que foi publicado
nas últimas N horas, envia os dados brutos (em inglês) para o Gemini traduzir
e resumir em Português do Brasil, evita repetir notícias já cobertas nos
últimos dias, salva o relatório no Supabase e expurga histórico antigo.

MELHORIAS APLICADAS EM RELAÇÃO À VERSÃO ANTERIOR:
- Tratamento de erro em toda chamada de rede/API/banco (feed, LLM, Supabase).
- Verificação de `feed.bozo` para detectar feeds malformados/bloqueados.
- Requisição do feed com User-Agent próprio (alguns sites bloqueiam o
  user-agent padrão de bibliotecas Python, ex: Forbes).
- Filtro real de janela de 48h usando `published_parsed`/`updated_parsed`
  (antes o filtro de data era só "confiar no LLM").
- Sanitização de HTML nos resumos (BeautifulSoup) antes de montar o prompt.
- Reintrodução da lógica de histórico/dedup (últimos 3 dias) e do expurgo
  de registros com mais de 15 dias, que existiam na versão anterior baseada
  em busca web e haviam sido perdidas nesta versão RSS.
- Modelo fixo (não usa mais tag "latest", que pode mudar de comportamento
  sem aviso) e `temperature=0.1` para reduzir variação/alucinação.
- Validação de variáveis de ambiente ausentes, com erro claro na inicialização.
- Checagem de conteúdo vazio antes de chamar a LLM (evita gastar chamada de
  API para gerar relatório sem dado real) e antes de salvar no banco.
- Logs estruturados em cada etapa, para depuração via GitHub Actions.
- REGRA DE TRADUÇÃO reforçada no prompt: título, resumo e qualquer texto do
  relatório final devem estar 100% em português, com instrução explícita de
  que copiar o título original em inglês (mesmo que parcialmente) não é
  aceitável.
=============================================================================
"""

import os
import re
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Fuso horário de referência para rotular as datas dos relatórios. O runner
# do GitHub Actions roda em UTC por padrão — sem isso, um relatório gerado
# de madrugada (UTC) pode ficar rotulado com a data de "ontem" no horário de
# Brasília (UTC-3), fazendo o app parecer sempre "um dia atrasado" mesmo
# quando a automação rodou corretamente.
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def hoje_no_brasil() -> datetime:
    return datetime.now(FUSO_BRASIL)

# --------------------------------------------------------------------------
# Configuração de logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cti_briefing")

# --------------------------------------------------------------------------
# Parâmetros
# --------------------------------------------------------------------------
# NOTA IMPORTANTE: o ecossistema de modelos do Gemini tem um ciclo de vida
# curto — versões "-preview" costumam ser desligadas em poucos meses, e
# fixar uma versão exata (ex: "gemini-2.5-pro-002") corre o risco real de
# virar 404 sem aviso, como aconteceu aqui. Por isso, em vez de uma única
# string fixa, usamos uma LISTA de candidatos em ordem de preferência: o
# script tenta o primeiro; se a API retornar erro (ex: 404 de modelo
# descontinuado), tenta o próximo, e loga qual foi realmente usado.
# "-latest" é um alias mantido pela própria Google apontando sempre para a
# versão estável mais recente da família — API muda com menos aviso prévio
# de comportamento, mas não quebra por descontinuação, que é o problema que
# tivemos.
MODELOS_CANDIDATOS = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-pro-latest",
]
JANELA_HORAS = 48
DIAS_RETENCAO = 15
DIAS_DEDUP = 3
ITENS_POR_FEED = 3
TIMEOUT_REQUEST = 15
USER_AGENT = (
    "Mozilla/5.0 (compatible; CTI-Briefing-Bot/1.0; "
    "+https://github.com/) AppleWebKit/537.36"
)

FEEDS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "MIT": "https://www.technologyreview.com/feed/",
    "VentureBeat": "http://feeds.venturebeat.com/VentureBeat",
    # Fontes primárias — os próprios laboratórios de IA, para mudanças de
    # modelo, segurança e alinhamento vindas direto da fonte, não só de
    # cobertura de terceiros sobre eles.
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    # Fontes especializadas — menos mainstream, foco em segurança/alinhamento,
    # agentes e modelos, com forte credibilidade dentro da comunidade técnica.
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "AI Alignment Forum": "https://www.alignmentforum.org/feed.xml",
    "Zvi Mowshowitz": "https://thezvi.substack.com/feed",
    # Fontes de cibersegurança pura — complementam a cobertura de IA com o
    # olhar de segurança da informação (exploits, vulnerabilidades, ataques
    # envolvendo sistemas de IA).
    "The Hacker News": "https://thehackernews.com/feeds/posts/default",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "Ars Technica Security": "https://arstechnica.com/feed/",
    "Bleeping Computer": "https://www.bleepingcomputer.com/feed/",
    "Palo Alto Unit 42": "https://unit42.paloaltonetworks.com/feed/",
}
# NOTA (17/07/2026): "Forbes" foi removida — era a fonte de fit mais fraco
# do pool (cobertura de inovação/negócios em geral, não focada em IA nem
# segurança), substituída por fontes primárias/especializadas de maior
# valor (OpenAI, Google DeepMind, Unit 42).
# ESTRATÉGIA DE REDUNDÂNCIA: mantemos um POOL de 11 fontes (mais do que o
# mínimo de 8 desejado) — não porque todas publiquem todo dia, mas
# justamente para absorver quebras (404, bloqueio 403, feed sem conteúdo na
# janela de 48h) sem que o relatório fique raso. Não existe "fonte reserva"
# separada: todas rodam sempre, e MIN_FONTES_DESEJADO (abaixo) só audita e
# avisa no log quando o número de fontes que renderam alguma notícia no dia
# ficar abaixo do piso desejado — nesse caso, é sinal de que vale investigar
# e, se necessário, adicionar mais uma fonte ao pool.
#
# NOTA: "Reuters" foi removida em 17/07/2026 — a Reuters descontinuou os
# feeds RSS públicos (confirmado: a URL antiga retorna 404 de forma
# permanente, não é uma falha pontual). Não há substituto oficial da Reuters
# com RSS público estável atualmente.
MIN_FONTES_DESEJADO = 8

# --------------------------------------------------------------------------
# Pool de feeds — Mundo Acadêmico
# --------------------------------------------------------------------------
# Pool bem menor e deliberadamente enxuto: fontes de pesquisa acadêmica em
# IA, validadas uma a uma (várias outras universidades testadas foram
# descartadas por estarem com RSS quebrado, abandonado há anos, ou
# bloqueado por robots.txt). Cadência de publicação é irregular por
# natureza (CMU publica ~1x/mês) — isso é esperado, não é bug; por isso o
# layout da página acadêmica omite fontes sem conteúdo no dia, em vez de
# mostrar um card vazio.
FEEDS_ACADEMICO = {
    "arXiv (cs.AI)": "https://rss.arxiv.org/rss/cs.AI",
    "Berkeley (BAIR)": "https://bair.berkeley.edu/blog/feed.xml",
    "MIT (Machine Learning)": "https://news.mit.edu/topic/mitmachine-learning-rss.xml",
    "CMU (Machine Learning Dept)": "https://blog.ml.cmu.edu/feed/",
    "University of Washington (Allen School)": "https://news.cs.washington.edu/feed/",
    # ETH Zurich é feed institucional geral (não filtrado só por IA) — o
    # próprio prompt já descarta itens fora do escopo de IA, então isso não
    # exige tratamento especial, só reduz um pouco o "aproveitamento" do
    # ITENS_POR_FEED nos dias em que a maioria das notícias for de outras
    # áreas (física, biologia etc.).
    "ETH Zurich (ETH News)": "https://www.ethz.ch/en/news-und-veranstaltungen/eth-news/news/_jcr_content.feed.html",
    # NUS é feed institucional geral (mesmo tratamento do ETH Zurich acima:
    # o prompt filtra o que não for IA). Confirmado ativo em 23/07/2026 com
    # item publicado no dia anterior.
    "NUS (Highlights)": "https://news.nus.edu.sg/tagfeed/en-sg/tags/highlights",
    # Fontes de computação quântica — cobrem o tema pedido separadamente de
    # IA, mas usam o mesmo pipeline de coleta/tradução/escopo. O prompt
    # acadêmico já cobre "tendências e novidades técnicas de IA" em termos
    # amplos; computação quântica entra como tema adicional dentro do mesmo
    # escopo de pesquisa/tecnologia de ponta.
    "MIT (Quantum Computing)": "https://news.mit.edu/rss/topic/quantum-computing",
    "QuTech (Delft)": "https://blog.qutech.nl/feed",
    "University of Waterloo (IQC)": "https://uwaterloo.ca/institute-for-quantum-computing/news/news.xml",
}
TABELA_ACADEMICO = "relatorios_academico"

# --------------------------------------------------------------------------
# Inicialização e validação de ambiente
# --------------------------------------------------------------------------
load_dotenv()

VARS_OBRIGATORIAS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE", "GEMINI_API_KEY"]


def validar_variaveis_ambiente():
    faltando = [v for v in VARS_OBRIGATORIAS if not os.getenv(v)]
    if faltando:
        raise EnvironmentError(
            f"Variáveis de ambiente ausentes: {', '.join(faltando)}. "
            "Verifique o .env ou os secrets do GitHub Actions."
        )


validar_variaveis_ambiente()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# --------------------------------------------------------------------------
# Coleta e limpeza dos feeds
# --------------------------------------------------------------------------
def limpar_html(texto: str) -> str:
    """Remove tags HTML e normaliza espaços de um trecho de texto de RSS."""
    if not texto:
        return ""
    texto_limpo = BeautifulSoup(texto, "html.parser").get_text(separator=" ")
    return re.sub(r"\s+", " ", texto_limpo).strip()


def buscar_feed(nome: str, url: str):
    """Baixa e faz parse de um feed, com User-Agent próprio e tratamento
    de erro de rede. Retorna None se falhar ou vier vazio/malformado."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_REQUEST)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"[{nome}] Falha ao baixar feed ({url}): {e}")
        return None

    feed = feedparser.parse(resp.content)

    if feed.bozo:
        logger.warning(f"[{nome}] Feed malformado (bozo=1): {feed.bozo_exception}")

    if not feed.entries:
        logger.warning(f"[{nome}] Nenhuma entrada encontrada no feed.")
        return None

    return feed


def dentro_da_janela(entry, horas: int = JANELA_HORAS) -> bool:
    """
    Verifica se a entrada foi publicada dentro da janela de horas definida.
    Se o feed não fornecer data (alguns não fornecem), a entrada é mantida
    (fail-open) — mas é melhor manter algo do que descartar tudo do feed.
    """
    published = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if not published:
        return True
    data_pub = datetime(*published[:6], tzinfo=timezone.utc)
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    return data_pub >= limite


def coletar_urls_ja_usadas(dias: int = 5, tabela: str = "relatorios_cti") -> set:
    """
    Extrai todos os links já publicados em relatórios dos últimos `dias`
    dias, para exclusão determinística no código — não depende do modelo
    "lembrar" e julgar se algo é repetido (o que se mostrou pouco confiável
    para listas longas, como a de manchetes extras). Um item cujo link já
    apareceu simplesmente nunca chega a ser mostrado ao modelo de novo.
    """
    try:
        data_limite = (hoje_no_brasil() - timedelta(days=dias)).strftime("%Y-%m-%d")
        resposta = (
            supabase.table(tabela)
            .select("conteudo_markdown")
            .gte("data_criacao", data_limite)
            .execute()
        )
        urls = set()
        for item in resposta.data or []:
            urls.update(re.findall(r"\]\((https?://[^)]+)\)", item["conteudo_markdown"]))
        logger.info(f"[{tabela}] {len(urls)} URL(s) já usadas nos últimos {dias} dias (excluídas da coleta).")
        return urls
    except Exception as e:
        logger.warning(f"Falha ao coletar URLs já usadas: {e}. Prosseguindo sem esse filtro.")
        return set()


def ler_feeds(
    feeds: dict = None,
    auditar_piso: bool = True,
    urls_excluir: set = None,
    limite_por_fonte: dict = None,
) -> str:
    feeds = FEEDS if feeds is None else feeds
    urls_excluir = urls_excluir or set()
    noticias = []
    fontes_ativas = 0

    for nome, url in feeds.items():
        feed = buscar_feed(nome, url)
        if not feed:
            continue

        # Teto por fonte: permite reduzir o peso de fontes com volume muito
        # maior que as demais (ex: arXiv publica todo dia; a maioria das
        # universidades tem cadência irregular) — sem isso, a fonte mais
        # prolífica acaba dominando sozinha qualquer lista mais longa.
        teto = (limite_por_fonte or {}).get(nome, ITENS_POR_FEED)

        contador = 0
        excluidos_por_repeticao = 0
        for entry in feed.entries:
            if contador >= teto:
                break
            if not dentro_da_janela(entry):
                continue

            titulo = limpar_html(getattr(entry, "title", ""))
            resumo = limpar_html(getattr(entry, "summary", ""))
            link = getattr(entry, "link", "")

            if not titulo or not link:
                continue
            if link in urls_excluir:
                excluidos_por_repeticao += 1
                continue

            noticias.append(
                f"Fonte: {nome} | Titulo: {titulo} | Link: {link} | Resumo: {resumo[:500]}"
            )
            contador += 1

        log_extra = f" ({excluidos_por_repeticao} descartada(s) por já ter(em) aparecido antes)" if excluidos_por_repeticao else ""
        logger.info(
            f"[{nome}] {contador} notícia(s) coletada(s) dentro da janela de "
            f"{JANELA_HORAS}h{log_extra}."
        )
        if contador > 0:
            fontes_ativas += 1

    # Auditoria do piso mínimo de fontes: só se aplica ao pool principal (o
    # acadêmico é pequeno de propósito, cadência irregular por natureza —
    # não faz sentido auditar um "piso mínimo" nele).
    if auditar_piso:
        if fontes_ativas < MIN_FONTES_DESEJADO:
            logger.warning(
                f"Apenas {fontes_ativas}/{len(feeds)} fontes renderam notícia hoje "
                f"(mínimo desejado: {MIN_FONTES_DESEJADO}). Considere revisar feeds "
                f"quebrados ou ampliar o pool."
            )
        else:
            logger.info(
                f"Piso de fontes atendido: {fontes_ativas}/{len(feeds)} fontes "
                f"ativas hoje (mínimo desejado: {MIN_FONTES_DESEJADO})."
            )
    else:
        logger.info(f"{fontes_ativas}/{len(feeds)} fontes com conteúdo hoje.")

    return "\n".join(noticias)


# --------------------------------------------------------------------------
# Histórico (dedup) e expurgo
# --------------------------------------------------------------------------
def buscar_historico_recente(dias: int = DIAS_DEDUP, tabela: str = "relatorios_cti") -> str:
    try:
        data_recente = (hoje_no_brasil() - timedelta(days=dias)).strftime("%Y-%m-%d")
        resposta = (
            supabase.table(tabela)
            .select("conteudo_markdown")
            .gte("data_criacao", data_recente)
            .execute()
        )
        if resposta.data:
            return "\n".join(item["conteudo_markdown"] for item in resposta.data)
        return "Nenhum histórico."
    except Exception as e:
        logger.warning(f"Falha ao buscar histórico recente ({tabela}): {e}")
        return "Nenhum histórico."


def limpar_historico_antigo(dias: int = DIAS_RETENCAO, tabela: str = "relatorios_cti"):
    data_limite = (hoje_no_brasil() - timedelta(days=dias)).strftime("%Y-%m-%d")
    logger.info(f"Expurgando relatórios anteriores a {data_limite} ({tabela})...")
    try:
        supabase.table(tabela).delete().lt("data_criacao", data_limite).execute()
        logger.info("Expurgo concluído.")
    except Exception as e:
        logger.warning(f"Falha ao expurgar histórico antigo ({tabela}): {e}")


# --------------------------------------------------------------------------
# Geração do relatório
# --------------------------------------------------------------------------
def montar_prompt(conteudo_feeds: str, textos_antigos: str) -> str:
    return f"""
    Você é um Consultor Estratégico de Tecnologia. Analise os dados brutos
    abaixo (em inglês, extraídos de feeds RSS) e crie um briefing executivo
    em Português do Brasil.

    REGRA DE OURO — TRADUÇÃO OBRIGATÓRIA (siga à risca):
    Todo o conteúdo bruto abaixo está em inglês. Você DEVE traduzir
    INTEGRALMENTE para Português do Brasil:
    - As manchetes/títulos: é PROIBIDO copiar o título original em inglês,
      mesmo que parcialmente. Reescreva a manchete inteira em português,
      mantendo o sentido.
    - Os resumos executivos: também 100% em português.
    Exceção: nomes próprios de empresas/produtos (ex: "OpenAI", "ChatGPT",
    "Google DeepMind") permanecem como estão, e a URL do link não deve ser
    alterada.

    PADRÃO DE QUALIDADE (vale para as notícias E para as 4 seções de análise
    mais abaixo):
    - NUNCA invente números, datas, métricas, nomes de pessoas ou detalhes
      técnicos que não estejam presentes nos dados brutos fornecidos. Se o
      resumo original for vago ou incompleto, mantenha a tradução igualmente
      vaga — não complete a lacuna com informação não confirmada.
    - Se o dado bruto contiver um número, métrica, resultado de benchmark ou
      nome específico (ex: "reduziu erro em 12%", "processador de 17
      qubits"), PRIORIZE incluir esse dado concreto no resumo, em vez de
      generalizar (prefira "reduziu o erro em 12%" a "melhorou o
      desempenho").
    - PROIBIDO usar frases de enchimento sem informação real, como "é
      importante destacar que", "representa um avanço significativo no
      cenário atual", "vale ressaltar que", ou variações. Vá direto ao
      fato/achado.

    FORMATO OBRIGATÓRIO PARA CADA NOTÍCIA:
    ### [Manchete traduzida para português](LINK_ORIGINAL_SEM_ALTERAR)
    Resumo executivo em português (máximo 3 linhas).

    ESCOPO OBRIGATÓRIO DO BRIEFING (siga rigorosamente):
    Este briefing cobre EXCLUSIVAMENTE dois temas:
    1. CIBERSEGURANÇA APLICADA A IA: vulnerabilidades, ataques, defesas,
       jailbreaks, red teaming, uso de IA em ataques ou defesas
       cibernéticas, incidentes de segurança envolvendo sistemas de IA,
       políticas/regulação de segurança de IA.
    2. TENDÊNCIAS E NOVIDADES TÉCNICAS DE IA: lançamento de novos modelos,
       avanços de pesquisa, novas capacidades/funcionalidades relevantes,
       mudanças técnicas significativas em produtos de IA, resultados de
       benchmarks relevantes.

    Antes de incluir qualquer notícia, pergunte-se: "O ASSUNTO PRINCIPAL
    desta manchete é cibersegurança de IA OU uma tendência/novidade técnica
    de IA?". Não basta a matéria MENCIONAR ou ter relação indireta com IA
    (ex: infraestrutura de energia para data centers, cabos submarinos,
    chips em geral, política econômica) — se o assunto central não for a
    própria tecnologia de IA ou sua segurança, DESCARTE o item, mesmo que o
    texto cite "inteligência artificial" ou "data centers de IA" em algum
    trecho.

    EXCLUA explicitamente, mesmo que citem IA ou empresas de IA:
    - Notícias de RH/executivos (contratação, saída, reorganização) sem
      mudança técnica ou de segurança relevante por trás.
    - Notícias de negócios/financeiro (IPO, avaliação de mercado, parcerias
      comerciais, resultados financeiros) sem relação direta com segurança
      ou avanço técnico.
    - Notícias de infraestrutura/energia (reatores nucleares, data centers,
      chips, cabos, eletricidade) onde a IA é apenas o motivo de fundo, não
      o assunto central da matéria.
    - Jogos, palavras cruzadas e desafios diários de qualquer veículo (ex:
      Wordle, NYT Strands, NYT Connections, Spangram, sudoku, horóscopo),
      independente do nome específico do jogo.
    - Entretenimento, cultura pop, esportes ou qualquer conteúdo não
      técnico.
    - Notícias genéricas de tecnologia que só citam IA de forma superficial
      ou tangencial.

    REGRAS DE SELEÇÃO E PRIORIZAÇÃO (siga nesta ordem):
    - Cada item dos dados brutos vem marcado com "Fonte: <nome>".
    - FONTES PRIORITÁRIAS (segurança/alinhamento de IA, agentes, modelos —
      sempre entram primeiro quando houver conteúdo relevante disponível):
      OpenAI, Google DeepMind, Simon Willison, AI Alignment Forum, Zvi
      Mowshowitz, The Hacker News, Krebs on Security, Bleeping Computer,
      Palo Alto Unit 42.
    - FONTES DE IMPRENSA GERAL (usadas para completar a lista, nunca para
      substituir uma notícia prioritária disponível): TechCrunch, MIT,
      VentureBeat, Ars Technica Security.
    - Monte a lista final nesta ordem de prioridade: primeiro TODAS as
      notícias relevantes disponíveis das fontes prioritárias, depois
      complete com as notícias mais relevantes da imprensa geral até o
      limite abaixo.
    - Selecione NO MÁXIMO 7 notícias. NÃO existe mínimo fixo: inclua somente
      itens genuinamente relevantes ao escopo acima. Se houver poucos itens
      relevantes nos dados brutos (2, 3, 4...), entregue apenas esses — é
      proibido completar a lista com itens fracos, repetitivos ou fora do
      escopo só para atingir um número maior.
    - NÃO repita temas já cobertos no histórico recente (compare por
      assunto, não apenas pelo texto literal do título).

    HISTÓRICO RECENTE PARA NÃO REPETIR:
    {textos_antigos}

    DADOS BRUTOS (em inglês):
    {conteudo_feeds}

    Depois das notícias, adicione QUATRO seções de análise, NESTA ORDEM, cada
    uma com o cabeçalho exato indicado (não mude o texto do cabeçalho, ele é
    usado para montar o layout da página).

    REGRA OBRIGATÓRIA PARA TODAS AS 4 SEÇÕES: cada ponto da análise deve
    referenciar EXPLICITAMENTE qual notícia do dia está comentando (ex:
    "Como visto na notícia sobre [tema/manchete resumida]: ..."). É PROIBIDO
    escrever um comentário genérico que poderia valer para qualquer dia sem
    conexão clara com o que foi listado acima — a análise deve parecer
    curadoria em cima das notícias específicas de hoje, não um texto solto.

    ## 🛡️ Perspectiva NIST (AI Risk Management Framework)
    Analise as notícias acima sob a ótica do NIST AI Risk Management
    Framework (funções GOVERN, MAP, MEASURE, MANAGE). Escreva 2 a 4 frases
    curtas, no formato "Rótulo curto: explicação", conectando as notícias do
    dia a riscos/controles desse framework. Deixe claro que é uma ANÁLISE
    INSPIRADA no framework do NIST, não uma citação oficial do NIST.

    ## 🔓 Perspectiva OWASP (Top 10 para LLM/GenAI Applications)
    Analise as notícias acima sob a ótica da lista OWASP Top 10 para
    aplicações LLM/GenAI (ex: prompt injection, vazamento de dados
    sensíveis, excesso de autonomia do agente, envenenamento de dados de
    treinamento, roubo de modelo). Escreva 2 a 4 frases curtas, no mesmo
    formato "Rótulo curto: explicação". Deixe claro que é uma ANÁLISE
    INSPIRADA na lista da OWASP, não uma citação oficial da OWASP.

    ## 🎯 Perspectiva MITRE ATLAS
    Analise as notícias acima sob a ótica do MITRE ATLAS (framework de
    táticas e técnicas de ataque e defesa contra sistemas de IA, equivalente
    ao MITRE ATT&CK para modelos de IA — ex: reconhecimento do modelo,
    acesso a recursos de ML, evasão de detecção, exfiltração via modelo,
    envenenamento do pipeline de ML). Escreva 2 a 4 frases curtas, no mesmo
    formato "Rótulo curto: explicação". Deixe claro que é uma ANÁLISE
    INSPIRADA no MITRE ATLAS, não uma citação oficial do MITRE.

    ## 🧠 Insights Estratégicos (Perspectiva Gartner)
    Mantenha exatamente como já é feito hoje: análise executiva/de negócio
    das notícias do dia, no mesmo formato "Rótulo curto: explicação".
    """


def montar_prompt_academico(conteudo_feeds: str, textos_antigos: str) -> str:
    return f"""
    Você é um curador de pesquisa acadêmica em Inteligência Artificial e
    Computação Quântica. Analise os dados brutos abaixo (majoritariamente em
    inglês, extraídos de feeds de universidades, centros de pesquisa e do
    arXiv) e crie um digest em Português do Brasil.

    REGRA DE OURO — TRADUÇÃO OBRIGATÓRIA (siga à risca):
    Todo o conteúdo bruto abaixo está em inglês. Você DEVE traduzir
    INTEGRALMENTE para Português do Brasil:
    - As manchetes/títulos: é PROIBIDO copiar o título original em inglês,
      mesmo que parcialmente. Reescreva a manchete inteira em português,
      mantendo o sentido técnico exato (não simplifique termos técnicos a
      ponto de perder precisão).
    - Os resumos: também 100% em português.
    Exceção: nomes próprios de instituições/produtos/modelos (ex: "arXiv",
    "Stanford", "GPT-4", "BERT", "QuTech") permanecem como estão, e a URL do
    link NUNCA deve ser alterada — o link é a forma de quem ler consultar a
    publicação original, então precisa apontar exatamente para a página do
    artigo/post de origem.

    PADRÃO DE QUALIDADE:
    - NUNCA invente números, datas, métricas, nomes de pesquisadores ou
      detalhes técnicos que não estejam presentes nos dados brutos
      fornecidos. Se o resumo original for vago ou incompleto, mantenha a
      tradução igualmente vaga — não complete a lacuna com informação não
      confirmada.
    - Se o dado bruto contiver um número, métrica, resultado experimental ou
      nome específico (ex: "processador de 17 qubits", "redução de 30% na
      taxa de erro"), PRIORIZE incluir esse dado concreto no resumo, em vez
      de generalizar.
    - PROIBIDO usar frases de enchimento sem informação real, como "é
      importante destacar que", "representa um avanço significativo no
      cenário atual", "vale ressaltar que", ou variações. Vá direto ao
      fato/achado.

    FORMATO OBRIGATÓRIO PARA CADA ITEM (sempre com o link da fonte):
    ### [Manchete traduzida para português](LINK_ORIGINAL_SEM_ALTERAR)
    Resumo em português (máximo 3 linhas), explicando o que foi
    pesquisado/publicado e por que é relevante.

    ESCOPO: pesquisa acadêmica em DOIS temas — trate ambos com o mesmo peso,
    sem priorizar um sobre o outro:
    1. INTELIGÊNCIA ARTIFICIAL — novos modelos, técnicas, resultados
       experimentais, papers relevantes, avanços de métodos (ex: novos
       algoritmos de treinamento, arquiteturas, benchmarks, técnicas de
       segurança/interpretabilidade de modelos).
    2. COMPUTAÇÃO QUÂNTICA — novos processadores/qubits, algoritmos
       quânticos, avanços em correção de erro, redes/internet quântica,
       resultados experimentais relevantes de institutos de pesquisa
       quântica.
    Ignore itens puramente administrativos da instituição (eventos internos,
    prêmios individuais sem conteúdo técnico, notícias de admissão/matrícula,
    captação de recursos sem detalhe técnico do que será pesquisado).

    SELEÇÃO: selecione NO MÁXIMO 6 itens, sem mínimo fixo — inclua somente
    o que for genuinamente relevante nos dados brutos abaixo. Se houver
    poucos itens relevantes (1, 2, 3...), entregue apenas esses.

    REGRA DE DESEMPATE (não é motivo de descarte isolado): se dois ou mais
    itens tratam do mesmo achado/tema e você precisa escolher só um por
    causa do limite de 6, prefira o mais claro/menos técnico-nicho. Mas
    NUNCA descarte um item só por parecer técnico ou de nicho se ele for o
    ÚNICO item relevante disponível no dia — nesse caso, inclua-o mesmo
    assim e apenas capriche no resumo para torná-lo compreensível a um
    público não-especialista. Um dia com 1 notícia bem explicada é sempre
    preferível a um dia sem nenhuma.

    NÃO repita temas já cobertos no histórico recente (compare por
    assunto, não apenas pelo texto literal do título).

    HISTÓRICO RECENTE PARA NÃO REPETIR:
    {textos_antigos}

    DADOS BRUTOS (majoritariamente em inglês):
    {conteudo_feeds}

    Depois dos itens, NÃO adicione nenhuma seção de análise (nada de NIST,
    OWASP, MITRE ou Gartner) — este digest é só a lista curada e traduzida,
    sem camada analítica extra.

    Depois disso, adicione uma seção extra com o cabeçalho exato abaixo:

    ## 📰 Principais Notícias e Tendências Acadêmicas

    Nesta seção, liste TODAS as demais manchetes relevantes dos dados brutos
    que tratam de IA ou Computação Quântica (mesmo escopo de antes) mas que
    NÃO entraram na lista curada acima — sem duplicar nenhuma manchete já
    usada ali. Não há limite de quantidade: inclua todas que se encaixarem
    no escopo. Se não houver nenhuma manchete adicional além das já usadas,
    omita esta seção inteira (não escreva o cabeçalho vazio).

    IMPORTANTE: a mesma regra de NÃO REPETIR o histórico recente (ver
    HISTÓRICO RECENTE PARA NÃO REPETIR, acima) vale também para esta seção —
    não inclua aqui uma manchete cujo tema já foi coberto em dias anteriores,
    mesmo que a redação exata do título seja diferente.

    DIVERSIDADE DE FONTES: não deixe uma única fonte (especialmente o
    arXiv, que publica todos os dias) dominar sozinha esta lista. Priorize
    incluir itens das universidades/centros de pesquisa (Berkeley, MIT,
    CMU, University of Washington, ETH Zurich, NUS, QuTech, University of
    Waterloo) sempre que houver algum disponível nos dados brutos, mesmo
    que em menor quantidade que os itens do arXiv.

    FORMATO OBRIGATÓRIO PARA CADA ITEM DESTA SEÇÃO (diferente do formato das
    notícias curadas acima):
    - [Manchete traduzida para português](LINK_ORIGINAL_SEM_ALTERAR)

    Regras desta seção:
    - APENAS a manchete traduzida, SEM resumo, SEM parágrafo explicativo.
    - Mesma regra de tradução das notícias curadas (proibido copiar o
      título original em inglês, mesmo parcialmente).
    - O link é obrigatório e deve apontar exatamente para a matéria
      original — é assim que quem ler acessa o conteúdo completo, já que
      esta seção não traz resumo.
    """


def diagnosticar_resposta(response, contexto: str = ""):
    """
    Loga sinais de truncamento da resposta — finish_reason == MAX_TOKENS
    indica que a resposta foi cortada antes de terminar (ex: bateu no teto
    de max_output_tokens). Ajuda a diagnosticar rapidamente casos como o de
    17/2026, em que a resposta cortava antes de chegar nas seções de
    análise, sem precisar investigar do zero.
    """
    try:
        candidato = response.candidates[0]
        finish_reason = getattr(candidato, "finish_reason", None)
        uso = getattr(response, "usage_metadata", None)
        if finish_reason and "MAX_TOKENS" in str(finish_reason):
            logger.warning(
                f"{contexto}Resposta possivelmente TRUNCADA (finish_reason="
                f"{finish_reason}). Tokens de saída visível: "
                f"{getattr(uso, 'candidates_token_count', '?')}, tokens de "
                f"'pensamento': {getattr(uso, 'thoughts_token_count', '?')}."
            )
    except Exception:
        pass  # diagnóstico é best-effort, nunca deve interromper o fluxo principal


def gerar_conteudo_resiliente(prompt: str):
    """
    Tenta gerar o conteúdo usando os modelos candidatos em ordem de
    preferência. Passa para o próximo candidato se o atual retornar erro
    (ex: 404 de modelo descontinuado, 429 de limite de cota). Levanta a
    última exceção se TODOS os candidatos falharem — quem chama esta
    função decide o que fazer com a falha (aqui, propagamos para cima).
    """
    ultimo_erro = None
    for modelo in MODELOS_CANDIDATOS:
        try:
            logger.info(f"Tentando gerar relatório com o modelo '{modelo}'...")
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    # thinking_budget=0 desativa o "raciocínio interno" do
                    # Gemini 2.5 Flash. Essa tarefa é estruturada (tradução,
                    # filtro, formatação) — não precisa de raciocínio
                    # profundo, e sem isso os tokens de "pensamento" contam
                    # contra o max_output_tokens (bug documentado do
                    # Gemini 2.5 Flash), cortando a resposta no meio antes de
                    # chegar nas 4 seções de análise, que vêm depois das
                    # notícias no formato pedido.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    # Teto de tokens de saída como margem de segurança real
                    # (não mais um limite apertado, já que thinking_budget=0
                    # elimina o consumo "invisível" que causava o corte) —
                    # ainda protege contra uma resposta anormalmente longa
                    # gerar custo muito acima do esperado.
                    max_output_tokens=8192,
                ),
            )
            logger.info(f"Sucesso com o modelo '{modelo}'.")
            return response
        except Exception as e:
            logger.warning(f"Falha com o modelo '{modelo}': {e}")
            ultimo_erro = e

    raise RuntimeError(
        f"Todos os modelos candidatos falharam ({MODELOS_CANDIDATOS}). "
        f"Último erro: {ultimo_erro}"
    )


def contem_itens_formatados(texto: str) -> bool:
    """
    Verifica se o texto gerado pelo modelo contém ao menos uma notícia no
    formato esperado (### [Título](Link)). Usado para distinguir uma
    resposta real de um "não havia nada novo para reportar" — esse segundo
    caso é uma resposta VÁLIDA do modelo (a regra de anti-repetição
    funcionou), mas não deve ser salva no Supabase: se salvarmos, ela vira
    o registro mais recente do dia (maior id) na próxima execução manual, e
    o front-end passa a exibir "nada" mesmo havendo um relatório bom mais
    cedo no mesmo dia.
    """
    return bool(re.search(r"###\s*\[.+?\]\(.+?\)", texto))


def gerar_relatorio():
    logger.info("Lendo feeds RSS...")
    conteudo_feeds = ler_feeds()

    if not conteudo_feeds.strip():
        raise RuntimeError(
            "Nenhuma notícia coletada dos feeds dentro da janela definida. "
            "Abortando geração para não gastar chamada de API à toa."
        )

    logger.info("Buscando histórico recente para evitar repetição de temas...")
    textos_antigos = buscar_historico_recente()

    prompt = montar_prompt(conteudo_feeds, textos_antigos)

    response = gerar_conteudo_resiliente(prompt)
    diagnosticar_resposta(response)

    conteudo_final = getattr(response, "text", None)
    if not conteudo_final or not conteudo_final.strip():
        raise RuntimeError("Resposta do modelo veio vazia. Abortando salvamento.")

    if not contem_itens_formatados(conteudo_final):
        logger.info(
            "O modelo não encontrou itens novos além do que já está no "
            "histórico recente (provavelmente uma reexecução manual no "
            "mesmo dia). Não é erro — pulando o salvamento para não "
            "sobrescrever o relatório bom já existente hoje."
        )
        return

    logger.info("Salvando relatório no Supabase...")
    try:
        supabase.table("relatorios_cti").insert(
            {
                "data_criacao": hoje_no_brasil().strftime("%Y-%m-%d"),
                "conteudo_markdown": conteudo_final,
            }
        ).execute()
    except Exception as e:
        raise RuntimeError(f"Falha ao salvar relatório no Supabase: {e}") from e

    limpar_historico_antigo()

    logger.info("Processo finalizado com sucesso.")


def gerar_relatorio_academico():
    logger.info("[Acadêmico] Coletando URLs já usadas nos últimos dias...")
    urls_ja_usadas = coletar_urls_ja_usadas(dias=5, tabela=TABELA_ACADEMICO)

    logger.info("[Acadêmico] Lendo feeds de pesquisa acadêmica...")
    conteudo_feeds = ler_feeds(
        feeds=FEEDS_ACADEMICO,
        auditar_piso=False,
        urls_excluir=urls_ja_usadas,
        # Teto reduzido para o arXiv: ele publica todos os dias e tende a
        # dominar sozinho a lista de manchetes extras, "afogando" as
        # universidades/centros de pesquisa (cadência mais irregular). Um
        # teto menor deixa mais espaço relativo para as demais fontes.
        limite_por_fonte={"arXiv (cs.AI)": 2},
    )

    if not conteudo_feeds.strip():
        logger.info(
            "[Acadêmico] Nenhuma publicação nova hoje em nenhuma das fontes "
            "acadêmicas — comportamento esperado (cadência irregular), não é "
            "erro. Pulando a geração deste digest hoje."
        )
        return

    logger.info("[Acadêmico] Buscando histórico recente para evitar repetição...")
    textos_antigos = buscar_historico_recente(tabela=TABELA_ACADEMICO)

    prompt = montar_prompt_academico(conteudo_feeds, textos_antigos)

    response = gerar_conteudo_resiliente(prompt)
    diagnosticar_resposta(response, contexto="[Acadêmico] ")

    conteudo_final = getattr(response, "text", None)
    if not conteudo_final or not conteudo_final.strip():
        raise RuntimeError("[Acadêmico] Resposta do modelo veio vazia. Abortando salvamento.")

    if not contem_itens_formatados(conteudo_final):
        logger.info(
            "[Acadêmico] O modelo não encontrou itens novos além do que já "
            "está no histórico recente. Não é erro — pulando o salvamento."
        )
        return

    logger.info("[Acadêmico] Salvando digest no Supabase...")
    try:
        supabase.table(TABELA_ACADEMICO).insert(
            {
                "data_criacao": hoje_no_brasil().strftime("%Y-%m-%d"),
                "conteudo_markdown": conteudo_final,
            }
        ).execute()
    except Exception as e:
        raise RuntimeError(f"[Acadêmico] Falha ao salvar no Supabase: {e}") from e

    limpar_historico_antigo(tabela=TABELA_ACADEMICO)

    logger.info("[Acadêmico] Processo finalizado com sucesso.")


if __name__ == "__main__":
    import sys

    falhas = []

    try:
        gerar_relatorio()
    except Exception as e:
        logger.error(f"Execução do briefing principal falhou: {e}")
        falhas.append("principal")

    try:
        gerar_relatorio_academico()
    except Exception as e:
        logger.error(f"Execução do digest acadêmico falhou: {e}")
        falhas.append("acadêmico")

    if falhas:
        # Propaga falha real para o GitHub Actions marcar o job como
        # "failed" — mas só depois de tentar os dois pipelines, para que a
        # falha de um não impeça o outro de rodar e salvar seu conteúdo.
        logger.error(f"Pipeline(s) com falha: {', '.join(falhas)}.")
        sys.exit(1)
