import os
from google import genai
from google.genai import types
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Carregar credenciais
diretorio_atual = os.path.dirname(os.path.abspath(__file__))
caminho_cofre = os.path.join(diretorio_atual, '.env')
load_dotenv(caminho_cofre)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Inicializar conexões
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

def gerar_relatorio_executivo():
    print("Buscando histórico de relatórios recentes para evitar repetições...")
    
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
    
    textos_antigos = "Nenhum histórico recente."
    if resposta_historico.data:
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data])

    print("Iniciando varredura com o Gemini conectado à Internet (Grounding)...")
    
    # 3. O Novo Prompt Focado em IA, Qualidade e Veracidade
    prompt = f"""
    Você é um Consultor Estratégico de Tecnologia e Especialista em Inteligência Artificial.
    
    REGRA MANDATÓRIA 1: O texto gerado DEVE ser estritamente em Português do Brasil (pt-BR).
    REGRA MANDATÓRIA 2: VOCÊ TEM ACESSO À INTERNET. PESQUISE AS INFORMAÇÕES ANTES DE ESCREVER. É TERMINANTEMENTE PROIBIDO INVENTAR LINKS. SÓ USE LINKS REAIS QUE VOCÊ ENCONTRAR NA BUSCA.
    REGRA MANDATÓRIA 3 (ANTI-REPETIÇÃO): Ignore os eventos que já constam no histórico abaixo.
    
    [HISTÓRICO RECENTE PARA VOCÊ IGNORAR]
    {textos_antigos}
    [FIM DO HISTÓRICO]

    Sua tarefa: Criar um briefing executivo focado EXCLUSIVAMENTE em Inteligência Artificial (IA Generativa, Agentes Autônomos, Modelos de Linguagem, IA Embarcada e casos de uso corporativo).
    
    ESTRUTURA:
    1. Selecione rigorosamente de 05 a 07 notícias MAIS RELEVANTES das últimas 24/48 horas. Priorize fontes de alta credibilidade e impacto na indústria.
    2. Cada item DEVE ser formatado como uma manchete clicável em Markdown, contendo OBRIGATORIAMENTE o link REAL da fonte que você pesquisou:
       ### [Escreva a Manchete Aqui](URL_Real_e_Verificada_da_Fonte)
    3. Abaixo da manchete, um parágrafo executivo focando no IMPACTO corporativo e de negócios.
    
    TÓPICO FINAL OBRIGATÓRIO:
    ## 🧠 Insights Estratégicos sobre IA (Perspectiva Gartner)
    Pesquise pelas publicações e tendências mais recentes do Gartner sobre IA. Forneça 2 a 3 bullet points com análises REAIS e VALIDADAS voltadas ao mercado corporativo. Não invente previsões.
    
    Nunca inclua introduções genéricas. Inicie diretamente com as manchetes.
    """

    # 4. GERAR CONTEÚDO COM BUSCA NA WEB E BAIXA TEMPERATURA
    response = client.models.generate_content(
        model='gemini-1.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}], # Conecta a IA à internet em tempo real para validar fatos e links
            temperature=0.1 # Nível de criatividade quase zero para forçar precisão e exatidão
        )
    )
    relatorio_markdown = response.text
    
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    print("Inteligência gerada e verificada. Salvando no banco de dados...")
    
    # 5. Salvar no Supabase
    supabase.table("relatorios_cti").insert({
        "data_criacao": data_hoje,
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    # 6. Manutenção Automática
    print("Executando rotina de limpeza de 15 dias...")
    data_limite = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
    
    print(f"Sucesso! Briefing de {data_hoje} salvo.")

if __name__ == "__main__":
    gerar_relatorio_executivo()
