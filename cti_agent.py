"""
=============================================================================
PROJETO: Automação de Briefing Executivo de IA (Migração Claude)
=============================================================================
"""
import os
from anthropic import Anthropic
from duckduckgo_search import DDGS
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Configuração Inicial
load_dotenv()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def buscar_noticias_recentes():
    print("Buscando notícias em tempo real (DuckDuckGo)...")
    try:
        # Busca as 10 notícias mais recentes sobre IA generativa
        resultados = DDGS().news(keywords="Inteligência Artificial AND (Generativa OR Agentes)", timelimit="d", max_results=10)
        textos_noticias = "\n".join([f"- {r['title']}: {r['body']} (Fonte: {r['url']})" for r in resultados])
        return textos_noticias if textos_noticias else "Nenhuma notícia encontrada."
    except Exception as e:
        print(f"Erro na busca: {e}")
        return "Falha ao buscar notícias."

def gerar_relatorio_executivo():
    # 2. Busca histórico no Supabase
    print("Verificando histórico...")
    try:
        data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        resposta = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta.data]) if resposta.data else "Nenhum histórico."
    except Exception:
        textos_antigos = "Nenhum histórico."

    # 3. Executa a Pesquisa Web
    noticias_hoje = buscar_noticias_recentes()

    # 4. Prompt para o Claude
    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia. Crie um briefing executivo focado EXCLUSIVAMENTE em IA.
    
    Abaixo estão as notícias mais recentes coletadas da internet hoje:
    {noticias_hoje}

    REGRAS:
    - Idioma: Português do Brasil.
    - Conteúdo: Selecione de 05 a 07 notícias MAIS RELEVANTES da lista acima.
    - Links: Obrigatório incluir o link da fonte no formato: ### [Manchete](URL).
    - Insights: Termine com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".
    
    HISTÓRICO PARA IGNORAR (não repita estes temas):
    {textos_antigos}
    """

    print("Conectando ao Claude 3.5 Sonnet...")
    
    # 5. Aciona o Claude
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2000,
        temperature=0.1,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    relatorio_markdown = response.content[0].text
    
    # 6. Salvar e Limpar
    print("Salvando no banco de dados...")
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    supabase.table("relatorios_cti").delete().lt("data_criacao", (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")).execute()
    print("Processo finalizado com sucesso!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
