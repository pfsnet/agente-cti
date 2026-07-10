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
    Você é um Analista de Inteligência de Mercado sênior. 
    Compile um briefing executivo baseado nos feeds de tecnologia abaixo.

    REGRAS DE TRADUÇÃO E FORMATO (OBRIGATÓRIO):
    1. TRADUÇÃO: Todos os títulos (Manchetes) e resumos DEVEM ser traduzidos para Português do Brasil de forma profissional.
    2. PRECISÃO: Mantenha o sentido original da fonte. Não altere termos técnicos em inglês que sejam padrão no mercado (ex: "Machine Learning", "LLMs").
    
    FORMATO OBRIGATÓRIO:
    ### [Manchete em Português](LINK_ORIGINAL)
    Resumo executivo em português profissional (máximo 3 linhas).
    
    Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".

    DADOS DOS FEEDS:
    {conteudo_feeds}
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
