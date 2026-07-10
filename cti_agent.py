"""
=============================================================================
PROJETO: Automação de Briefing Executivo de IA (CTI - RSS com Tradução Pro)
=============================================================================
"""
import os
import feedparser
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

FEEDS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Reuters": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best-topics&term=technology",
    "MIT": "https://technologyreview.com/feed/",
    "Forbes": "https://www.forbes.com/innovation/feed/"
}

def ler_feeds():
    noticias = []
    for nome, url in FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            noticias.append(f"Fonte: {nome}\nManchete Original: {entry.title}\nLink: {entry.link}\nResumo Original: {getattr(entry, 'summary', 'Sem resumo')}\n")
    return "\n".join(noticias)

def gerar_relatorio():
    conteudo_feeds = ler_feeds()
#def gerar_relatorio():
    # Isso vai listar todos os modelos disponíveis na sua conta
#   for m in client.models.list():
#      print(f"Modelo disponível: {m.name}")
    
    # ... resto do código ...
    
    prompt = f"""
    Você é um Analista de Inteligência Sênior. Sua missão é criar um briefing em PORTUGUÊS (BR) rigoroso.

    REGRAS RÍGIDAS:
    1. TRADUÇÃO INTEGRAL: Traduza TODAS as manchetes e resumos para Português do Brasil de forma natural e executiva.
    2. ESTRUTURA DE LINKS: Para cada notícia, use exatamente este formato de saída:
       ### [MANCHETE TRADUZIDA PARA PORTUGUÊS](LINK_ORIGINAL)
       Resumo executivo em português profissional.
    3. NÃO altere o conteúdo do link (URL). Apenas altere o texto dentro dos colchetes [ ] traduzindo o título.
    
    DADOS DE ENTRADA:
    {conteudo_feeds}
    
    Termine obrigatoriamente com: "## 🧠 Insights Estratégicos (Perspectiva Gartner)"
    """

    # Utilizando o modelo 3.1-pro para seguir com perfeição a regra de tradução estruturada
    response = client.models.generate_content(
        model='gemini-3.5-flash,
        contents=prompt
    )
    
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    try:
        supabase.table("relatorios_cti").delete().lt("data_criacao", (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")).execute()
    except Exception:
        pass

if __name__ == "__main__":
    gerar_relatorio()
