"""
config.py — Configuração centralizada do sistema.

Todos os parâmetros ajustáveis ficam aqui.
Nenhum outro arquivo deve conter valores fixos de configuração.

Seções:
  [COMPARTILHADO]  Infraestrutura, rede, OSM — usada por ambas as linhas.
  [OPERACIONAL]    Linha local: prospecção, abordagem, histórico.
  [MARKETING]      Linha nacional por nicho: presença digital em escala.
"""

from pathlib import Path

# Diretório raiz do projeto
BASE_DIR = Path(__file__).parent

# Pastas de saída
PASTA_DADOS = BASE_DIR / "dados"
PASTA_LOGS = BASE_DIR / "logs"

# ============================================================
# [COMPARTILHADO] — Tags OSM e infraestrutura de rede
# Usado por ambas as linhas: operacional e marketing.
# ============================================================

# Mapeamento de categorias para tags OSM.
# Formato: identificador → lista de dicts {chave_osm: valor_osm}
# Para adicionar uma categoria nova: basta adicionar um item aqui.
CATEGORIAS = {
    "barbearia": [{"shop": "barber"}],
    "salao_de_beleza": [{"shop": "beauty"}, {"shop": "hairdresser"}],
    "oficina_mecanica": [{"shop": "car_repair"}],
    "borracharia": [{"shop": "tyres"}],
    "acougue": [{"shop": "butcher"}],
    "padaria": [{"shop": "bakery"}],
    "autopecas": [{"shop": "car_parts"}],
}

# Nomes amigáveis para exibição nos resultados
NOMES_CATEGORIAS = {
    "barbearia": "Barbearia",
    "salao_de_beleza": "Salão de Beleza",
    "oficina_mecanica": "Oficina Mecânica",
    "borracharia": "Borracharia / Loja de Pneus",
    "acougue": "Açougue",
    "padaria": "Padaria",
    "autopecas": "Autopeças",
}

# Instâncias públicas da Overpass API — gratuitas, sem chave de API.
# O sistema tenta a primeira; se receber 429 repetido, tenta a próxima.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Pausa entre requisições à Overpass API (segundos) — respeita rate limiting
PAUSA_ENTRE_REQUISICOES = 6

# Pausa extra após receber HTTP 429 (Too Many Requests).
# Precisa ser bem maior que a pausa normal para a API se recuperar.
PAUSA_RATE_LIMIT = 35

# Timeout para requisições HTTP (segundos)
TIMEOUT_REQUISICAO = 45

# Número máximo de tentativas por requisição em caso de falha
MAX_TENTATIVAS = 4

# ============================================================
# [OPERACIONAL] — Linha local: prospecção ativa em uma cidade
# Usada apenas por main.py / core/executor.py
# ============================================================

# Cidade alvo da prospecção operacional
CIDADE = "São José do Rio Preto"
PAIS = "Brazil"  # em inglês para o Nominatim

# Score mínimo para ser considerada candidata
# Quanto menor, menos presença digital foi encontrada nos dados públicos.
LIMITE_SCORE_CANDIDATA = 40

# ============================================================
# [MARKETING] — Linha nacional por nicho: análise de presença digital em escala
# Usada apenas por main_marketing.py / core/executor_marketing.py
# Não inclui abordagem, histórico nem envio de mensagens.
# ============================================================

# Cidades a processar na linha de marketing.
# Adicione ou remova cidades conforme a estratégia de expansão.
CIDADES_MARKETING = [
    "São José do Rio Preto",
    # Exemplos prontos para habilitar:
    # "Ribeirão Preto",
    # "Bauru",
    # "São José dos Campos",
    # "Sorocaba",
]

# Estado inferido por cidade.
# Usado para enriquecer o contexto geográfico na saída.
# Adicione aqui ao incluir novas cidades acima.
ESTADO_POR_CIDADE = {
    "São José do Rio Preto": "SP",
    "Ribeirão Preto": "SP",
    "Bauru": "SP",
    "São José dos Campos": "SP",
    "Sorocaba": "SP",
    "Campinas": "SP",
    "Santos": "SP",
    "Curitiba": "PR",
    "Londrina": "PR",
    "Maringá": "PR",
    "Porto Alegre": "RS",
    "Caxias do Sul": "RS",
    "Florianópolis": "SC",
    "Joinville": "SC",
    "Belo Horizonte": "MG",
    "Uberlândia": "MG",
    "Goiânia": "GO",
    "Brasília": "DF",
    "Salvador": "BA",
    "Fortaleza": "CE",
    "Recife": "PE",
    "Manaus": "AM",
}

# Nichos a processar na linha de marketing.
# Cada nicho é um subconjunto de CATEGORIAS — deve usar os mesmos identificadores.
# Deixe vazio para processar todas as categorias disponíveis em CATEGORIAS.
NICHOS_MARKETING = [
    "barbearia",
    "oficina_mecanica",
    # "salao_de_beleza",
    # "borracharia",
    # "acougue",
    # "padaria",
    # "autopecas",
]

# Limite de empresas aceitas por combinação cidade + nicho.
# Evita sobrecarga em cidades grandes com muitos resultados OSM.
LIMITE_EMPRESAS_POR_CIDADE_NICHO = 100

# Pausa em segundos entre o processamento de cada cidade.
# Respeita o rate limiting da Overpass API em execuções longas.
PAUSA_ENTRE_CIDADES = 5

# ============================================================
# [FINANCEIRO] — Linha financeira interna
# Usada apenas por main_financeiro.py / modulos/financeiro/
# ============================================================

# Saldo inicial do caixa (antes de qualquer evento registrado no sistema).
# Defina aqui o saldo real da conta da empresa no início do período.
FINANCEIRO_SALDO_INICIAL = 0.0

# Valor mínimo (R$) para considerar um atraso ou despesa como relevante.
# Acima deste valor → pode gerar decisão humana.
FINANCEIRO_VALOR_RELEVANTE = 500.0

# Saldo previsto abaixo deste valor dispara risco_caixa = True.
# Zero significa que caixa negativo já é risco.
FINANCEIRO_THRESHOLD_RISCO = 0.0

# Vencimento em até N dias → urgência "imediata"
FINANCEIRO_DIAS_ALERTA_IMEDIATO = 2

# Vencimento em até N dias → urgência "curto_prazo"
FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO = 7

# ============================================================
# [COMERCIAL] — Agente comercial e pipeline de vendas
# ============================================================

# Valor estimado acima deste valor → sobe para deliberação do conselho
COMERCIAL_THRESHOLD_PROPOSTA = 5000.0

# Dias em estagio "aguardando_decisao" sem atividade → escalar para conselho
COMERCIAL_DIAS_LIMITE_DECISAO = 7

# Dias sem atividade → marcar para revisão interna
COMERCIAL_DIAS_SEM_ATIVIDADE_REVISAO = 30

# Número máximo de tentativas antes de sugerir encerramento
COMERCIAL_TENTATIVAS_MAXIMAS = 3

# ============================================================
# [LLM] — Router central de modelos de linguagem
# Controlado por LLM_MODO ou variável de ambiente LLM_MODO.
# ============================================================

# Modo de operação do router LLM.
#   "dry-run" (padrão) — custo zero, sem chamada real, respostas simuladas.
#   "real"             — chamadas à API Anthropic (requer ANTHROPIC_API_KEY).
# Para ativar o modo real: mudar aqui E configurar ANTHROPIC_API_KEY no .env.
LLM_MODO = "dry-run"

# Modelos disponíveis para uso (modo real)
# Haiku: mais rápido e barato — triagem, resumo, classificação
# Sonnet: mais capaz — redação, decisão, análise
LLM_MODELO_RAPIDO   = "claude-haiku-4-5-20251001"
LLM_MODELO_COMPLETO = "claude-sonnet-4-6"

# Timeout das chamadas LLM em segundos
LLM_TIMEOUT = 30

# Limite de tokens por resposta (controla custo)
LLM_MAX_TOKENS_RAPIDO   = 1024
LLM_MAX_TOKENS_COMPLETO = 2048

# ============================================================
# [SCHEDULER] — Loop contínuo de execução dos agentes
# ============================================================

# Habilita o scheduler. False → main_scheduler.py não executa nenhum agente.
SCHEDULER_ATIVO = True

# Agenda por agente.
# horarios: lista de "HH:MM" (24h). dias: lista de abreviaturas PT-BR.
# Dias válidos: seg, ter, qua, qui, sex, sab, dom
AGENDA_AGENTES = {
    "prospeccao":        {"horarios": ["03:00"], "dias": ["seg", "qua", "sex"]},
    "marketing":         {"horarios": ["04:00"], "dias": ["seg", "qua", "sex"]},
    "comercial":         {"horarios": ["08:00", "14:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    "executor_contato":  {"horarios": ["09:00", "15:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    "financeiro":        {"horarios": ["17:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    "secretario":        {"horarios": ["07:30", "12:00", "18:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    "customer_success":  {"horarios": ["10:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    "ciclo_completo":    {"horarios": ["06:00", "19:00"], "dias": ["seg", "ter", "qua", "qui", "sex"]},
    # Auditor de segurança — roda 2x/semana na madrugada (não incluso no ciclo normal)
    "auditor_seguranca": {"horarios": ["02:00"], "dias": ["seg", "qui"]},
}

# Segundos entre cada verificação da agenda
SCHEDULER_INTERVALO_CHECK = 60

# Janela de tolerância: se o horário programado passou há menos de N minutos,
# ainda executa. Evita perder execuções por atrasos do loop.
SCHEDULER_TOLERANCIA_MINUTOS = 5
