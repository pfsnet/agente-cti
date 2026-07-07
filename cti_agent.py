import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Configuração Robusta
load_dotenv() # Carrega do .env no diretório raiz

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# Inicialização explícita com a chave
# Force a versão v1 explicitamente para evitar a v1beta
client = genai.Client(api_key=GEMINI_API_KEY, http_options={'api_version': 'v1'})

def gerar_relatorio_executivo():
    print("Iniciando varredura de mercado...")
    
    # 2. Histórico
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data]) if resposta_historico.data else "Nenhum histórico."
    except Exception as e:
        textos_antigos = "Nenhum histórico."

    # 3. Prompt Ajustado
    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia. Crie um briefing executivo focado EXCLUSIVAMENTE em IA.
    REGRAS:
    - Idioma: Português do Brasil (pt-BR).
    - Conteúdo: 05 a 07 notícias MAIS RELEVANTES das últimas 48h (IA Generativa, Agentes, Modelos).
    - Fontes: Use a ferramenta de busca para encontrar notícias de ALTA CREDIBILIDADE. 
    - Links: OBRIGATÓRIO link real no formato: ### [Manchete](URL). Se não encontrar o link real, NÃO cite a notícia.
    - Insights: Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)" baseados em fatos.
    
    HISTÓRICO PARA IGNORAR:
    {textos_antigos}
    """

    print("Gerando briefing com modelo gemini-1.5-pro...")

# O nome correto para a API v1 é 'gemini-1.5-pro-002'
response = client.models.generate_content(
    model='gemini-1.5-pro-002', 
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[{"google_search": {}}],
        temperature=0.1
    )
)
    
     relatorio_markdown = response.text
    
    # 5. Persistência
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    # 6. Limpeza
    data_limite = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
    
    print("Sucesso! Relatório gerado e banco limpo.")

if __name__ == "__main__":
    gerar_relatorio_executivo()
