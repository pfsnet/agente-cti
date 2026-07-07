import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
# O client não precisa de http_options se estiver usando a versão mais recente
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def gerar_relatorio_executivo():
    # 1. Configuração do modelo e busca
    model_name = 'gemini-1.5-pro'
    
    # Busca histórico para evitar repetições
    resposta = supabase.table("relatorios_cti").select("conteudo_markdown").order("data_criacao", desc=True).limit(3).execute()
    textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta.data]) if resposta.data else "Nenhum histórico."

    prompt = f"Você é um consultor estratégico de IA. Crie um briefing focado em IA (05-07 notícias, fontes reais, links válidos, Insights Gartner). Histórico para ignorar: {textos_antigos}"

    # 2. Execução (SINTAXE CORRETA PARA O SDK NOVO)
    # A ferramenta de busca no SDK novo é declarada dentro de 'tools' como um objeto
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1
        )
    )

    # 3. Salvar e Limpar
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    print("Sucesso! Briefing gerado e salvo.")

if __name__ == "__main__":
    gerar_relatorio_executivo()
