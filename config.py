"""
config.py — Configuração centralizada do sistema.

Todos os parâmetros ajustáveis ficam aqui.
Nenhum outro arquivo deve conter valores fixos de configuração.
"""

from pathlib import Path

# Diretório raiz do projeto
BASE_DIR = Path(__file__).parent

# Pastas de saída
PASTA_DADOS = BASE_DIR / "dados"
PASTA_LOGS = BASE_DIR / "logs"

# --- Configuração de busca ---

CIDADE = "São José do Rio Preto"
PAIS = "Brazil"  # em inglês para o Nominatim

# Score mínimo para ser considerada candidata (abaixo disso = candidata prioritária)
# Quanto menor o score, menos presença digital foi encontrada nos dados públicos.
# Valor configurável sem necessidade de mudar a lógica do sistema.
LIMITE_SCORE_CANDIDATA = 40

# --- Mapeamento de categorias para tags OSM ---
# Formato: identificador → lista de dicts {chave_osm: valor_osm}
# Cada entrada pode ter mais de um conjunto de tags (ex: salão pode ser beauty ou hairdresser)
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

# --- Configuração de rede ---

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
