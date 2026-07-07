import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Configuração e Inicialização
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
caminho_cofre = os.path.join(diretorio_atual, '.env')
load_dotenv(caminho_cofre)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# 2. Lógica de Autodescoberta do Modelo
def obter_modelo_mais_recente():
    """Consulta a API e retorna o nome do modelo mais recente da família 1.5 Pro"""
    try:
        models = client.models.list()
        # Filtra apenas modelos que contêm 'gemini-1.5-pro' no nome
        pro_models = [m for m in models if 'gemini-1.5-pro' in m.name]
        if not pro_models:
            return 'gemini-1.5-pro-latest' # Fallback de segurança
        # Retorna o último da lista (geralmente a versão mais nova/estável)
        return pro_models[-1].name
    except Exception:
        return 'gemini-1.5-pro-latest'

def gerar_relatorio_executivo():
    print("Iniciando varredura de mercado...")
    
    # Histórico para evitar repetições
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
    
    textos_antigos = "Nenhum histórico recente."
    if resposta_historico.data:
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data])

    modelo_ativo = obter_modelo_mais_recente()
    print(f"Modelo selecionado via autodescoberta: {modelo_ativo}")

    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia. Crie um briefing executivo focado EXCLUSIVAMENTE em IA.
    
    REGRAS DE OURO:
    - Selecione de 05 a 07 notícias MAIS RELEVANTES das últimas 48h (IA Generativa, Agentes, Modelos, IA Embarcada).
    - Fontes: Use a busca web. Só use fontes de alta credibilidade.
    - Links: OBRIGATÓRIO link real no formato: ### [Manchete](URL). Se o link for fake, NÃO cite a notícia.
    - Insights: Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)" com base em dados reais.
    
    HISTÓRICO PARA IGNORAR:
    {textos_antigos}
    """

    # Execução com busca web e alta precisão
    response = client.models.generate_content(
        model=modelo_ativo,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            temperature=0.1
        )
    )
    
    # Persistência
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    # Limpeza
    data_limite = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
    
    print("Sucesso! Relatório atualizado.")

if __name__ == "__main__":
    gerar_relatorio_executivo()
