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

# Fontes de Alta Credibilidade
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
        for entry in feed.entries[:3]: # Pega as 3 mais recentes de cada
            noticias.append(f"Fonte: {nome}\nManchete: {entry.title}\nLink: {entry.link}\nResumo: {getattr(entry, 'summary', 'Sem resumo')}\n")
    return "\n".join(noticias)

def gerar_relatorio():
    conteudo_feeds = ler_feeds()
    
    # O NOVO PROMPT COM TRADUÇÃO OBRIGATÓRIA
    prompt = f"""
    Você é um Analista de Inteligência Sênior. Sua missão é criar um briefing em PORTUGUÊS (BR).

    REGRAS RÍGIDAS:
    1. TRADUÇÃO INTEGRAL: Traduza TODAS as manchetes e resumos para Português do Brasil.
    2. ESTRUTURA DE LINKS: Para cada notícia, use exatamente este formato:
       ### [MANCHETE TRADUZIDA PARA PORTUGUÊS](LINK_ORIGINAL)
       Resumo executivo em português profissional.
    3. NÃO altere o conteúdo do link (URL). Apenas altere o texto dentro dos colchetes [ ].
    
    DADOS DE ENTRADA (Em Inglês):
    {conteudo_feeds}
    
    Termine com: "## 🧠 Insights Estratégicos (Perspectiva Gartner)"
    """

    response = client.models.generate_content(
        model='gemini-3.1-pro',
        contents=prompt
    )
    
    # Salvar no Supabase (código de salvamento igual ao anterior)
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()

if __name__ == "__main__":
    gerar_relatorio()
