import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Configuração Segura de Caminho
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
caminho_cofre = os.path.join(diretorio_atual, '.env')
load_dotenv(caminho_cofre)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Inicialização de Conexões
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

def gerar_relatorio_executivo():
    print("Buscando histórico recente para curadoria...")
    
    # Busca o que foi publicado nos últimos 3 dias para evitar repetições
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
    
    textos_antigos = "Nenhum histórico recente."
    if resposta_historico.data:
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data])

    # 3. Prompt de Alta Performance (Foco em IA e Precisão)
    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia. Sua tarefa é criar um briefing executivo focado EXCLUSIVAMENTE em Inteligência Artificial.
    
    REGRAS:
    - Idioma: Português do Brasil (pt-BR).
    - Conteúdo: 05 a 07 notícias MAIS RELEVANTES das últimas 48h sobre IA (Generativa, Agentes, Modelos).
    - Fontes: Use a ferramenta de busca para encontrar notícias de ALTA CREDIBILIDADE. 
    - Links: Obrigatório incluir o link real e verificável da fonte no formato: ### [Manchete](URL)
    - Proibição: NUNCA invente links. Se não encontrar o link real, não cite a notícia.
    - Insights: Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".
    
    HISTÓRICO (NÃO REPITA ISSO):
    {textos_antigos}
    """

    print("Gerando briefing com modelo Pro...")
    
    # 4. Execução com Busca Web e Temperatura Rigorosa
    response = client.models.generate_content(
        model='gemini-1.5-pro-latest',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            temperature=0.1
        )
    )
    
    relatorio_markdown = response.text
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    
    # 5. Salvar no Supabase (Usando a chave mestra)
    supabase.table("relatorios_cti").insert({
        "data_criacao": data_hoje,
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    # 6. Limpeza (Manter apenas os últimos 15 dias)
    data_limite = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
    
    print(f"Sucesso! Relatório de {data_hoje} gerado.")

if __name__ == "__main__":
    gerar_relatorio_executivo()
