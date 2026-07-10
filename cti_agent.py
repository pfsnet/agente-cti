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
from dotenv import load_dotenv

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
MODELO = "gemini-2.5-pro-002"  # versão fixa — evite tags "-latest" em produção
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
    "Reuters": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best-topics&term=technology",
    "MIT": "https://www.technologyreview.com/feed/",
    "Forbes": "https://www.forbes.com/innovation/feed/",
    # Fontes especializadas — menos mainstream, foco em segurança/alinhamento,
    # agentes e modelos, com forte credibilidade dentro da comunidade técnica.
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "AI Alignment Forum": "https://www.alignmentforum.org/feed.xml",
    "Zvi Mowshowitz": "https://thezvi.substack.com/feed",
}

# --------------------------------------------------------------------------
# Inicialização e validação de ambiente
# --------------------------------------------------------------------------
load_dotenv()

VARS_OBRIGATORIAS = ["SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY"]


def validar_variaveis_ambiente():
    faltando = [v for v in VARS_OBRIGATORIAS if not os.getenv(v)]
    if faltando:
        raise EnvironmentError(
            f"Variáveis de ambiente ausentes: {', '.join(faltando)}. "
            "Verifique o .env ou os secrets do GitHub Actions."
        )


validar_variaveis_ambiente()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
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


def ler_feeds() -> str:
    noticias = []
    for nome, url in FEEDS.items():
        feed = buscar_feed(nome, url)
        if not feed:
            continue

        contador = 0
        for entry in feed.entries:
            if contador >= ITENS_POR_FEED:
                break
            if not dentro_da_janela(entry):
                continue

            titulo = limpar_html(getattr(entry, "title", ""))
            resumo = limpar_html(getattr(entry, "summary", ""))
            link = getattr(entry, "link", "")

            if not titulo or not link:
                continue

            noticias.append(
                f"Fonte: {nome} | Titulo: {titulo} | Link: {link} | Resumo: {resumo[:500]}"
            )
            contador += 1

        logger.info(
            f"[{nome}] {contador} notícia(s) coletada(s) dentro da janela de "
            f"{JANELA_HORAS}h."
        )

    return "\n".join(noticias)


# --------------------------------------------------------------------------
# Histórico (dedup) e expurgo
# --------------------------------------------------------------------------
def buscar_historico_recente(dias: int = DIAS_DEDUP) -> str:
    try:
        data_recente = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        resposta = (
            supabase.table("relatorios_cti")
            .select("conteudo_markdown")
            .gte("data_criacao", data_recente)
            .execute()
        )
        if resposta.data:
            return "\n".join(item["conteudo_markdown"] for item in resposta.data)
        return "Nenhum histórico."
    except Exception as e:
        logger.warning(f"Falha ao buscar histórico recente: {e}")
        return "Nenhum histórico."


def limpar_historico_antigo(dias: int = DIAS_RETENCAO):
    data_limite = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    logger.info(f"Expurgando relatórios anteriores a {data_limite}...")
    try:
        supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
        logger.info("Expurgo concluído.")
    except Exception as e:
        logger.warning(f"Falha ao expurgar histórico antigo: {e}")


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

    FORMATO OBRIGATÓRIO PARA CADA NOTÍCIA:
    ### [Manchete traduzida para português](LINK_ORIGINAL_SEM_ALTERAR)
    Resumo executivo em português (máximo 3 linhas).

    REGRAS DE SELEÇÃO E PRIORIZAÇÃO (siga nesta ordem):
    - Cada item dos dados brutos vem marcado com "Fonte: <nome>".
    - FONTES PRIORITÁRIAS (segurança/alinhamento de IA, agentes, modelos —
      sempre entram primeiro quando houver conteúdo relevante disponível):
      Simon Willison, AI Alignment Forum, Zvi Mowshowitz.
    - FONTES DE IMPRENSA GERAL (usadas para completar a lista, nunca para
      substituir uma notícia prioritária disponível): TechCrunch, Reuters,
      Forbes, MIT.
    - Monte a lista final nesta ordem de prioridade: primeiro TODAS as
      notícias relevantes disponíveis das fontes prioritárias, depois
      complete com as notícias mais relevantes da imprensa geral até o
      limite abaixo.
    - Selecione NO MÁXIMO 7 notícias. NÃO existe mínimo fixo: inclua somente
      itens genuinamente relevantes sobre Inteligência Artificial. Se houver
      poucos itens relevantes nos dados brutos (2, 3, 4...), entregue apenas
      esses — é proibido completar a lista com itens fracos, repetitivos ou
      fora do tema só para atingir um número maior.
    - Ignore qualquer item que não seja sobre Inteligência Artificial (ex:
      jogos, entretenimento, cultura pop).
    - NÃO repita temas já cobertos no histórico recente (compare por
      assunto, não apenas pelo texto literal do título).

    HISTÓRICO RECENTE PARA NÃO REPETIR:
    {textos_antigos}

    DADOS BRUTOS (em inglês):
    {conteudo_feeds}

    Ao final do relatório, adicione a seção:
    ## 🧠 Insights Estratégicos (Perspectiva Gartner)
    """


def gerar_relatorio():
    logger.info("Lendo feeds RSS...")
    conteudo_feeds = ler_feeds()

    if not conteudo_feeds.strip():
        logger.error(
            "Nenhuma notícia coletada dos feeds dentro da janela definida. "
            "Abortando geração para não gastar chamada de API à toa."
        )
        return

    logger.info("Buscando histórico recente para evitar repetição de temas...")
    textos_antigos = buscar_historico_recente()

    prompt = montar_prompt(conteudo_feeds, textos_antigos)

    logger.info(f"Gerando relatório com o modelo {MODELO}...")
    try:
        response = client.models.generate_content(
            model=MODELO,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
    except Exception as e:
        logger.error(f"Falha ao chamar a API do Gemini: {e}")
        return

    conteudo_final = getattr(response, "text", None)
    if not conteudo_final or not conteudo_final.strip():
        logger.error("Resposta do modelo veio vazia. Abortando salvamento.")
        return

    logger.info("Salvando relatório no Supabase...")
    try:
        supabase.table("relatorios_cti").insert(
            {
                "data_criacao": datetime.now().strftime("%Y-%m-%d"),
                "conteudo_markdown": conteudo_final,
            }
        ).execute()
    except Exception as e:
        logger.error(f"Falha ao salvar relatório no Supabase: {e}")
        return

    limpar_historico_antigo()

    logger.info("Processo finalizado com sucesso.")


if __name__ == "__main__":
    gerar_relatorio()
