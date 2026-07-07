import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Configuração e Inicialização
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Força a versão de produção V1 para encontrar o modelo Pro
client = genai.Client(api_key=GEMINI_API_KEY, http_options={'api_version': 'v1'})

def gerar_relatorio_executivo():
    print("Iniciando varredura de mercado...")
    
    # 2. Busca Histórico
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data]) if resposta_historico.data else "Nenhum histórico."
    except:
        textos_antigos = "Nenhum histórico."

    # 3. Prompt
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

    print("Gerando briefing com modelo Pro...")
    
    # 4. Execução (Identificador fixo de produção)
    response = client.models.generate_content(
        model='gemini-1.5-pro-002',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            temperature=0.1
        )
    )
    
    relatorio_markdown = response.text
    
    # 5. Salvar e Limpar
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    supabase.table("relatorios_cti").delete().lt("data_criacao", (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")).execute()
    
    print("Sucesso!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
