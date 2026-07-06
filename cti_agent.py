import os
import google.generativeai as genai
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 1. Mapeamento Cego de Diretório (Blindagem de Caminho)
# Descobre exatamente em qual pasta o script atual está morando
diretorio_atual = os.path.dirname(os.path.abspath(__file__))

# Cria o caminho exato apontando para o arquivo .env nessa mesma pasta
caminho_cofre = os.path.join(diretorio_atual, '.env')

# Abre o cofre usando o endereço exato
load_dotenv(caminho_cofre)

# 2. Carregar credenciais
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Inicializar conexões
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

def gerar_relatorio_executivo():
    print("Buscando histórico de relatórios recentes para evitar repetições...")
    
    # Busca relatórios dos últimos 3 dias para criar a "memória"
    data_recente = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    resposta_historico = supabase.table("relatorios_cti").select("conteudo_markdown").gte("data_criacao", data_recente).execute()
    
    textos_antigos = "Nenhum histórico recente."
    if resposta_historico.data:
        # Junta os textos antigos num único bloco
        textos_antigos = "\n".join([item["conteudo_markdown"] for item in resposta_historico.data])

    print("Iniciando varredura de inteligência inédita com Gemini...")
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    # 3. O Prompt Estratégico com Trava Anti-Repetição
    prompt = f"""
    Você é um Analista Sênior de Cyber Threat Intelligence (CTI) e Consultor Estratégico de Tecnologia.
    
    REGRA MANDATÓRIA 1: O texto gerado DEVE ser estritamente em Português do Brasil (pt-BR).
    
    REGRA MANDATÓRIA 2 (ANTI-REPETIÇÃO): Abaixo está o histórico das notícias reportadas nos últimos dias. VOCÊ É ESTRITAMENTE PROIBIDO de mencionar qualquer incidente, notícia ou tema específico que já conste neste histórico. Traga APENAS eventos inéditos das últimas 24/48 horas.
    
    [HISTÓRICO RECENTE PARA VOCÊ IGNORAR]
    {textos_antigos}
    [FIM DO HISTÓRICO]

    Sua tarefa: Criar um briefing executivo focado em Cibersegurança e IA.
    
    ESTRUTURA:
    1. Máximo de 10 itens inéditos (curadoria de fontes nacionais e internacionais).
    2. Cada item DEVE ser formatado como uma manchete clicável em Markdown:
       ### [Escreva a Manchete Aqui](URL_Real_da_Fonte_Aqui)
    3. Abaixo da manchete, um parágrafo executivo focando no IMPACTO corporativo e de negócios.
    
    TÓPICO FINAL OBRIGATÓRIO:
    ## 🧠 Insights Estratégicos sobre IA (Perspectiva Gartner)
    Forneça 2 a 3 bullet points inéditos com análises voltadas ao mercado corporativo.
    
    Nunca inclua introduções genéricas. Inicie diretamente com as manchetes.
    """

    # 4. Gerar o conteúdo
    response = model.generate_content(prompt)
    relatorio_markdown = response.text
    
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    print("Inteligência gerada. Salvando no banco de dados...")
    
    # 5. Salvar a nova linha no banco
    supabase.table("relatorios_cti").insert({
        "data_criacao": data_hoje,
        "conteudo_markdown": relatorio_markdown
    }).execute()
    
    # 6. Manutenção Automática (Retenção de 15 dias)
    print("Executando rotina de limpeza de 15 dias...")
    data_limite = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    supabase.table("relatorios_cti").delete().lt("data_criacao", data_limite).execute()
    
    print(f"Sucesso! Briefing de {data_hoje} salvo. Dados anteriores a {data_limite} removidos.")

if __name__ == "__main__":
    gerar_relatorio_executivo()