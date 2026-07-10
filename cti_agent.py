import os
import feedparser
from google import genai
from supabase import create_client
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
            noticias.append(f"Fonte: {nome} | Titulo: {entry.title} | Link: {entry.link} | Resumo: {getattr(entry, 'summary', '')}")
    return "\n".join(noticias)

def gerar_relatorio():
    conteudo_feeds = ler_feeds()
    
    # Prompt com instrução de tradução de alta prioridade
    prompt = f"""
    Analise os dados abaixo e crie um briefing executivo.
    
    REGRA DE OURO: Traduza TODAS as manchetes para Português do Brasil.
    FORMATO OBRIGATÓRIO:
    ### [MANCHETE EM PORTUGUÊS](LINK_ORIGINAL)
    Resumo executivo (máximo 3 linhas, em português).

    Dados brutos:
    {conteudo_feeds}
    
    ## 🧠 Insights Estratégicos (Perspectiva Gartner)
    """

    # Usando o modelo Pro que confirmamos que está disponível
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt
    )
    
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()

if __name__ == "__main__":
    gerar_relatorio()
