import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Inicialização segura
load_dotenv()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def descobrir_melhor_modelo_disponivel():
    """
    Consulta a API do Google, lista os modelos autorizados para a sua conta
    e seleciona dinamicamente a melhor opção disponível (Pro > Flash).
    """
    print("Mapeando modelos autorizados para esta credencial...")
    try:
        # Puxa a lista real de modelos que a sua chave de API enxerga
        modelos_disponiveis = [m.name for m in client.models.list()]
        
        # Filtra buscando a família 'pro', ignorando versões experimentais ou de visão
        modelos_flash = [m for m in modelos_disponiveis if 'gemini' in m and 'flash' in m and 'vision' not in m and 'latest' not in m]
        
        if modelos_pro:
            # Ordena alfabeticamente e pega o último (a versão mais atualizada)
            melhor_modelo = sorted(modelos_pro)[-1]
            return melhor_modelo.replace('models/', '')
            
        # Se não houver Pro liberado, busca a melhor versão da família 'flash'
        modelos_flash = [m for m in modelos_disponiveis if 'gemini' in m and 'flash' in m and 'latest' not in m]
        
        if modelos_flash:
            melhor_modelo = sorted(modelos_flash)[-1]
            return melhor_modelo.replace('models/', '')
            
        return 'gemini-1.5-pro' # Fallback de emergência
        
    except Exception as e:
        print(f"Aviso na autodescoberta: {e}. Usando fallback.")
        return 'gemini-3.5-flash'

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

    # 1. Seleção Dinâmica: O código descobre sozinho qual modelo usar
    modelo_ideal = descobrir_melhor_modelo_disponivel()
    print(f"Conectando ao modelo validado pela API: {modelo_ideal}")
    
    # 2. Execução com a sintaxe correta e o modelo validado
    response = client.models.generate_content(
        model=modelo_ideal,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1
        )
    )
    
    print("Salvando inteligência gerada no Supabase...")
    
    supabase.table("relatorios_cti").insert({
        "data_criacao": datetime.now().strftime("%Y-%m-%d"),
        "conteudo_markdown": response.text
    }).execute()
    
    print("Processo finalizado com sucesso absoluto!")

if __name__ == "__main__":
    gerar_relatorio_executivo()
