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

    # O NOVO PROMPT: Blindado contra alucinações e focado em credibilidade
    prompt = f"""
    Você é um Analista de Inteligência de Mercado sênior. 
    Sua tarefa é criar um briefing executivo sobre Inteligência Artificial com precisão JORNALÍSTICA absoluta.

    REGRAS DE CREDIBILIDADE E FONTES (INVIOLÁVEIS):
    1. VERACIDADE: Utilize APENAS fatos reais ocorridos nas últimas 48 horas.
    2. FONTES CONFIÁVEIS: Você deve extrair informações prioritariamente de veículos renomados (ex: Reuters, Bloomberg, TechCrunch, Forbes, MIT Technology Review, Valor Econômico).
    3. PROIBIDO INVENTAR LINKS: Você NUNCA deve deduzir, criar ou adivinhar URLs. Utilize EXATAMENTE o link real retornado pela ferramenta de busca. Se uma notícia não possuir um link direto e verificável, NÃO a inclua no relatório.
    
    FORMATO OBRIGATÓRIO:
    - Selecione de 04 a 06 notícias de alto impacto.
    - Estrutura exata: ### [Manchete Clara e Profissional](URL_EXATA_DA_FONTE)
    - Resumo: Máximo de 3 linhas explicando o fato e o impacto estratégico/comercial.
    - Encerramento: Termine obrigatoriamente com "## 🧠 Insights Estratégicos (Perspectiva Gartner)".

    HISTÓRICO PARA IGNORAR (não repita estes temas):
    {textos_antigos}
    """

    modelos_para_tentar = ['gemini-3.5-flash', 'gemini-3.1-pro', 'gemini-3.1-flash-lite']
    response = None
    ultimo_erro = ""

    for modelo in modelos_para_tentar:
        try:
            print(f"Tentando conexão com o modelo: {modelo}...")
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.0 # Temperatura ZERO forçará a IA a ser factual e não criativa
                )
            )
            print(f"Sucesso absoluto utilizando o modelo: {modelo}")
            break  
        except Exception as e:
            print(f"Aviso: O modelo {modelo} apresentou instabilidade. Detalhes: {e}")
            ultimo_erro = str(e)
            time.sleep(5)  
            continue 

    if not response:
        raise Exception(f"Falha geral na esteira de IA. Último log: {ultimo_erro}")

    print("Salvando inteligência gerada no Supabase...")
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    try:
        supabase.table("relatorios_cti").delete().lt("data_criacao", (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")).execute()
    except Exception:
        pass

    print("Processo finalizado com sucesso absoluto!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
