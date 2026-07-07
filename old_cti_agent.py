import os
from google import genai
from google.genai import types
from supabase import create_client
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def gerar_relatorio_executivo():
    print("Buscando histórico...")
    
    try:
        data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        resposta = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta.data]) if resposta.data else "Nenhum histórico."
    except Exception:
        textos_antigos = "Nenhum histórico."

    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia. Crie um briefing executivo focado EXCLUSIVAMENTE em IA.
    REGRAS:
    - Idioma: Português do Brasil.
    - Conteúdo: 05 a 07 notícias MAIS RELEVANTES das últimas 48h (IA Generativa, Agentes, Modelos).
    - Links: Obrigatório incluir o link real e verificável da fonte no formato: ### [Manchete](URL).
    - Insights: Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".
    
    HISTÓRICO PARA IGNORAR:
    {textos_antigos}
    """

    print("Conectando ao modelo Pro 002...")
    
    # UNIÃO DAS CORREÇÕES: Nome exato de produção + Sintaxe correta da ferramenta de busca
    response = client.models.generate_content(
        model='gemini-1.5-pro-002',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1
        )
    )
    
    print("Salvando no banco de dados...")
    
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    print("Processo finalizado com sucesso!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
