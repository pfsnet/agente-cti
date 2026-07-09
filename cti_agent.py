"""
=============================================================================
PROJETO: Automação de Briefing Executivo de IA (CTI - Cyber Tech Intelligence)
=============================================================================
"""
import os
import time
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Inicialização segura das credenciais
load_dotenv()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def gerar_relatorio_executivo():
    print("Buscando histórico no banco de dados...")
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

    # Fila de prioridade 100% atualizada com os modelos ATUAIS (Geração 3.x)
    modelos_para_tentar = ['gemini-3.5-flash', 'gemini-3.1-pro', 'gemini-3.1-flash-lite']
    response = None
    ultimo_erro = ""

    # Varre a lista até encontrar um modelo disponível no servidor do Google
    for modelo in modelos_para_tentar:
        try:
            print(f"Tentando conexão com o modelo: {modelo}...")
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1
                )
            )
            print(f"Sucesso absoluto utilizando o modelo: {modelo}")
            break  # Interrompe o loop pois conseguiu gerar o relatório
        except Exception as e:
            print(f"Aviso: O modelo {modelo} apresentou instabilidade ou está indisponível. Detalhes: {e}")
            ultimo_erro = str(e)
            time.sleep(5)  # Pausa de segurança antes de tentar o próximo da fila
            continue 

    # Se nenhum modelo da fila funcionar, encerra com segurança reportando a causa
    if not response:
        print("Erro crítico: Todos os modelos da fila falharam devido a instabilidades externas do Google.")
        raise Exception(f"Falha geral na esteira de IA. Último log do servidor: {ultimo_erro}")

    print("Salvando inteligência gerada no Supabase...")
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    # Limpeza automática de histórico antigo (maior que 15 dias)
    try:
        supabase.table("relatorios_cti").delete().lt("data_criacao", (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")).execute()
    except Exception:
        pass

    print("Processo finalizado com sucesso absoluto!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
