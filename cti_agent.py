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
    
    prompt = f"""
    Como Analista Sênior, compile um briefing executivo baseado APENAS nos dados abaixo.
    Não busque na web. Use apenas o que foi fornecido.
    
    DADOS:
    {conteudo_feeds}
    
    FORMATO OBRIGATÓRIO:
    ### [Manchete](LINK_ORIGINAL)
    Resumo executivo profissional (máximo 3 linhas).
    
    Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".
    """

    response = client.models.generate_content(
        model='gemini-3.5-flash',
        contents=prompt
    )
    
    # Salvar no Supabase (código de salvamento igual ao anterior)
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()

if __name__ == "__main__":
    gerar_relatorio()
