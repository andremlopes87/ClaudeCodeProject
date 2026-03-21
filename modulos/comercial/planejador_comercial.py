"""
modulos/comercial/planejador_comercial.py — Plano comercial por empresa.

Transforma oportunidades de marketing/presença em um plano comercial concreto:
qual oferta fazer, por qual canal começar, como qualificar, quando avançar, quando parar.

Duplo uso:
  1. Execução comercial da própria empresa (vender serviços de marketing/presença digital)
  2. Base reaproveitável para estruturar o comercial de clientes no futuro

Este módulo NÃO envia mensagens. NÃO agenda contatos. NÃO executa nada.
Apenas planeja — com base nos dados de presença detectados.

Campos gerados por empresa:
  oferta_principal_comercial     : o que oferecer — da perspectiva do cliente
  motivo_oferta_principal        : por que esta oferta faz sentido para esta empresa
  canal_primeiro_contato         : melhor canal para a primeira abordagem
  canal_contato_secundario       : canal alternativo se o principal não funcionar
  abordagem_comercial_inicial    : ângulo de abertura da conversa (não é script)
  sequencia_followup_comercial   : o que fazer se não houver resposta
  criterios_qualificacao         : como identificar se é um lead real
  sinais_interesse_comercial     : o que indica que vale avançar
  sinais_descarte_comercial      : quando parar e encerrar o contato
  momento_certo_proposta         : quando apresentar proposta formal
  proxima_acao_comercial         : próxima ação concreta com dados reais (canal + número/email)
  status_comercial_sugerido      : identificado / pronto_para_contato / aguardando_dados / descartado
  motivo_status_comercial        : por que este status
  nivel_prioridade_comercial     : alta / media / baixa / sem_dados
  observacoes_comerciais         : ressalvas sobre qualidade dos dados e limitações

O que este módulo NÃO faz:
  - Não valida se os dados de contato estão atualizados
  - Não gera mensagens prontas para envio
  - Não executa a sequência de follow-up automaticamente
  - Não decide preço ou condições comerciais
  - Não rastreia histórico de contatos entre execuções

Documentação: docs/comercial/plano_comercial.md
"""

import logging

logger = logging.getLogger(__name__)

_TODOS_CANAIS = ["telefone", "email", "website", "whatsapp", "instagram", "facebook"]

# ---------------------------------------------------------------------------
# Oferta principal — o que oferecer, da perspectiva do cliente
# ---------------------------------------------------------------------------

_OFERTA = {
    "sem_website": {
        "barbearia":        "Página de agendamento online — clientes encontram a barbearia no Google e agendam pelo WhatsApp",
        "salao_de_beleza":  "Página de agendamento online — clientes encontram o salão, veem os trabalhos e agendam pelo WhatsApp",
        "oficina_mecanica": "Página com formulário de orçamento online — clientes pesquisam, pedem orçamento e recebem retorno pelo WhatsApp",
        "borracharia":      "Página de apresentação com localização e WhatsApp — clientes encontram e ligam ou mandam mensagem na hora",
        "acougue":          "Página com cardápio e horários — clientes veem o que tem, sabem quando abre e pedem pelo WhatsApp",
        "padaria":          "Página com cardápio e WhatsApp para encomendas — clientes pedem sem precisar ligar",
        "autopecas":        "Página com catálogo básico e formulário de cotação — clientes descrevem o que precisam e recebem resposta",
        "default":          "Página simples com informações do negócio — clientes encontram no Google e sabem como contatar",
    },
    "site_inacessivel": {
        "default": "Recuperação do site — clientes voltam a encontrar e acessar as informações que já existiam",
    },
    "sem_whatsapp": {
        "barbearia":        "Botão de WhatsApp no site — clientes chegam na página e mandam mensagem para agendar sem precisar ligar",
        "salao_de_beleza":  "Botão de WhatsApp no site — clientes chegam na página e mandam mensagem para agendar sem precisar ligar",
        "oficina_mecanica": "Botão de WhatsApp no site — clientes chegam na página e mandam mensagem para pedir orçamento sem precisar ligar",
        "default":          "Botão de WhatsApp no site — clientes chegam na página e mandam mensagem diretamente (implementação em 1-3 dias)",
    },
    "sem_cta": {
        "barbearia":        "Botão de agendamento em destaque no site — visitante chega e sabe exatamente o que fazer",
        "oficina_mecanica": "Botão de orçamento em destaque no site — visitante chega e sabe exatamente como pedir orçamento",
        "default":          "Botão de contato em destaque no site — visitante chega e sabe exatamente como entrar em contato",
    },
    "sem_email": {
        "default": "E-mail profissional e formulário de contato — clientes que preferem escrever têm onde enviar",
    },
    "sem_https": {
        "default": "HTTPS no site — aviso de 'site inseguro' desaparece e clientes param de ver esse alerta",
    },
    "sem_instagram": {
        "barbearia":        "Perfil Instagram ativo — novos clientes encontram o trabalho, veem fotos e chegam para agendar",
        "salao_de_beleza":  "Perfil Instagram ativo — novos clientes veem antes/depois e chegam para agendar",
        "oficina_mecanica": "Perfil Instagram ativo — dicas de manutenção atraem clientes e aumentam visibilidade local",
        "default":          "Perfil Instagram ativo — aumenta visibilidade local e facilita indicação entre clientes",
    },
    "sem_facebook": {
        "default": "Página Facebook — avaliações e recomendações locais passam a ter onde aparecer",
    },
    "presenca_estruturada": {
        "default": "Otimização de Google Meu Negócio — empresa aparece melhor em buscas locais e avaliações ficam visíveis",
    },
    "sem_canais": {
        "default": "Perfil Google Meu Negócio e página básica — empresa começa a existir digitalmente",
    },
    "dados_insuficientes": {
        "default": "Diagnóstico de presença digital gratuito — levantamento antes de qualquer oferta paga",
    },
}

# ---------------------------------------------------------------------------
# Motivo da oferta — por que esta oferta faz sentido para esta empresa
# ---------------------------------------------------------------------------

_MOTIVO = {
    "sem_website":          "Empresa sem presença digital própria — não aparece quando clientes pesquisam no Google. Qualquer concorrente que tenha uma página simples aparece primeiro.",
    "site_inacessivel":     "Site existe mas está fora do ar — empresa paga por algo que não funciona e perde clientes que tentam acessar.",
    "sem_whatsapp":         "Site funciona mas não tem WhatsApp — parte dos visitantes desiste quando não encontra canal de mensagem imediato.",
    "sem_cta":              "Site não tem botão de contato visível — visitante chega mas não sabe o que fazer e vai embora.",
    "sem_email":            "Sem e-mail público — clientes que preferem comunicação formal não têm canal disponível.",
    "sem_https":            "Site sem HTTPS — navegadores exibem aviso de 'site inseguro', o que afasta visitantes antes mesmo de lerem o conteúdo.",
    "sem_instagram":        "Sem Instagram — perde clientes que descobrem negócios pela rede social e verificam reputação por fotos antes de ir.",
    "sem_facebook":         "Sem página no Facebook — perde avaliações e recomendações locais que ainda funcionam bem em cidades médias.",
    "presenca_estruturada": "Presença razoavelmente completa — mas posicionamento local pode ser melhorado com SEO e gestão de avaliações.",
    "sem_canais":           "Sem canal digital identificado — empresa invisível online. Qualquer concorrente presente aparece antes.",
    "dados_insuficientes":  "Dados públicos insuficientes para diagnóstico — necessário levantamento antes de oferta concreta.",
}

# ---------------------------------------------------------------------------
# Abordagem inicial — ângulo de abertura da conversa (não é script pronto)
# ---------------------------------------------------------------------------

_ABORDAGEM = {
    "sem_website": {
        "barbearia":        "Mencionar que pesquisou 'barbearia em {cidade}' no Google e {nome} não aparece. Mostrar como ficaria uma página simples com horários e agendamento pelo WhatsApp. Não forçar decisão — objetivo é agendar demonstração rápida.",
        "oficina_mecanica": "Mencionar que pesquisou 'oficina mecânica em {cidade}' no Google e {nome} não aparece. Mostrar como ficaria uma página com formulário de orçamento e WhatsApp. Não forçar decisão — objetivo é mostrar o que é possível.",
        "default":          "Mencionar que pesquisou '{categoria} em {cidade}' no Google e {nome} não aparece nos resultados. Mostrar como ficaria uma página simples com contato e localização. Objetivo: agendar conversa mais detalhada.",
    },
    "site_inacessivel": {
        "default":          "Mencionar que tentou acessar o site e não funcionou. Oferecer diagnóstico rápido da causa sem custo. Abordagem direta — é uma dor concreta e imediata, sem precisar convencer.",
    },
    "sem_whatsapp": {
        "barbearia":        "Mencionar que acessou o site mas não encontrou WhatsApp. Mostrar que clientes que preferem mandar mensagem tendem a desistir. Oferecer implementação rápida — menos de uma semana.",
        "oficina_mecanica": "Mencionar que acessou o site mas não encontrou WhatsApp para pedir orçamento. Mostrar que clientes desistem quando não têm canal imediato. Oferecer implementação rápida.",
        "default":          "Mencionar que acessou o site mas não encontrou botão de WhatsApp. Mostrar que parte dos visitantes desiste quando não tem canal de mensagem. Oferecer implementação em poucos dias.",
    },
    "sem_cta": {
        "default":          "Mencionar que o site existe mas não tem botão de contato visível. Mostrar como visitante atual experiencia o site versus como ficaria com botão em destaque. Serviço rápido — abordagem objetiva.",
    },
    "default": {
        "default":          "Apresentar diagnóstico de presença digital da empresa e a oportunidade identificada. Focar no problema real — não na tecnologia. Objetivo: entender a necessidade antes de proposta formal.",
    },
}

# ---------------------------------------------------------------------------
# Sequência de follow-up por canal principal
# ---------------------------------------------------------------------------

_FOLLOWUP = {
    "whatsapp": (
        "Contato 1: mensagem WhatsApp apresentando o problema identificado de forma curta\n"
        "Contato 2: ligação 3 dias depois se sem resposta\n"
        "Contato 3: mensagem WhatsApp 7 dias depois com proposta de demonstração de 10 minutos\n"
        "Encerrar: sem resposta após 3 tentativas ou recusa explícita"
    ),
    "telefone": (
        "Contato 1: ligação apresentando o problema identificado e perguntando se tem interesse\n"
        "Contato 2: WhatsApp 3 dias depois se sem resposta (se número disponível)\n"
        "Contato 3: nova ligação 7 dias depois em horário diferente\n"
        "Encerrar: sem resposta após 3 tentativas ou recusa explícita"
    ),
    "email": (
        "Contato 1: e-mail curto com o problema identificado e o que é possível melhorar\n"
        "Contato 2: novo e-mail 5 dias depois com exemplo de caso similar\n"
        "Contato 3: ligação se telefone disponível — e-mail tem taxa de resposta baixa\n"
        "Encerrar: após 2 e-mails sem resposta ou recusa explícita"
    ),
    "formulario_site": (
        "Contato 1: formulário do site com mensagem curta e problema identificado\n"
        "Contato 2: tentativa por outro canal disponível 5 dias depois\n"
        "Encerrar: após 2 tentativas sem resposta"
    ),
    "pesquisa_adicional": (
        "Antes de qualquer contato: pesquisar no Google por telefone ou WhatsApp disponível\n"
        "Contato 1: pelo canal encontrado com apresentação curta do problema\n"
        "Encerrar: se nenhum canal útil encontrado após pesquisa de 10 minutos"
    ),
}

# ---------------------------------------------------------------------------
# Critérios de qualificação por gap
# ---------------------------------------------------------------------------

_QUALIFICACAO = {
    "sem_website": (
        "Confirmar que é o responsável pelas decisões do negócio\n"
        "Confirmar abertura para ter presença digital\n"
        "Confirmar disponibilidade de orçamento mínimo para página básica\n"
        "Verificar se já tentou criar site antes e qual foi o resultado"
    ),
    "site_inacessivel": (
        "Confirmar que é o responsável pelo site\n"
        "Confirmar que reconhece o problema e quer resolver\n"
        "Verificar se ainda tem acesso ao painel da hospedagem"
    ),
    "sem_whatsapp": (
        "Confirmar que é o responsável pelo site e pelo atendimento\n"
        "Confirmar que reconhece que clientes tentam contato por WhatsApp\n"
        "Verificar se tem WhatsApp Business ativo"
    ),
    "default": (
        "Confirmar que é o responsável pelas decisões de marketing ou tecnologia\n"
        "Confirmar que reconhece o problema identificado\n"
        "Verificar disponibilidade de orçamento para o serviço\n"
        "Identificar se já tem fornecedor atual e qual o nível de satisfação"
    ),
}

# ---------------------------------------------------------------------------
# Sinais de interesse e descarte (estáticos — válidos para todos os gaps)
# ---------------------------------------------------------------------------

_SINAIS_INTERESSE = (
    "Pergunta sobre prazo de entrega ou implementação\n"
    "Pede para ver exemplos de trabalhos ou páginas similares\n"
    "Menciona o problema atual com suas próprias palavras\n"
    "Agenda conversa, pede orçamento por escrito ou demonstração\n"
    "Demonstra urgência ('tô perdendo clientes', 'meu site tá fora faz tempo')"
)

_SINAIS_DESCARTE = (
    "Não atende após 3 tentativas em canais diferentes\n"
    "Número inexistente, desligado ou sempre ocupado\n"
    "Recusa explícita e sem abertura para nova conversa\n"
    "Empresa fechada, mudou de endereço ou mudou de ramo\n"
    "Já tem fornecedor e está satisfeito\n"
    "Responsável pelo negócio não é quem atende e não quer passar contato"
)

# ---------------------------------------------------------------------------
# Momento certo para proposta formal por gap
# ---------------------------------------------------------------------------

_MOMENTO_PROPOSTA = {
    "sem_website":      "Após confirmar interesse, identificar o decisor e mostrar exemplo de página similar na mesma categoria",
    "site_inacessivel": "Após diagnóstico técnico da causa e confirmação do interesse — proposta pode sair na primeira conversa",
    "sem_whatsapp":     "Na primeira conversa — oferta simples e rápida permite proposta direta se houver interesse",
    "sem_cta":          "Na primeira conversa — serviço técnico padronizado, proposta direta se houver interesse",
    "sem_https":        "Na primeira conversa — serviço técnico padronizado, proposta direta se houver interesse",
    "sem_email":        "Na primeira conversa — serviço simples, proposta direta se houver interesse",
    "sem_instagram":    "Após mostrar exemplos de perfis da categoria e confirmar disponibilidade para gestão de conteúdo",
    "default":          "Após confirmar interesse e identificar o decisor na primeira conversa",
}


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def planejar_comercial(empresas: list) -> list:
    """
    Aplica plano comercial em todas as empresas.

    Entrada: lista de empresas após planejar_marketing()
    Saída: mesma lista com campos de plano comercial adicionados
    """
    logger.info(f"Gerando plano comercial para {len(empresas)} empresas...")
    resultado = [_plano(e) for e in empresas]

    gerados = sum(1 for e in resultado if e.get("plano_comercial_gerado"))
    pronto = sum(1 for e in resultado if e.get("status_comercial_sugerido") == "pronto_para_contato")
    logger.info(f"  Planos comerciais gerados  : {gerados} de {len(empresas)}")
    logger.info(f"  Prontos para contato       : {pronto}")
    return resultado


def gerar_fila_execucao(empresas: list) -> list:
    """
    Gera fila de execução comercial ordenada por viabilidade de contato.

    Inclui: status pronto_para_contato ou identificado + prioridade alta ou media.
    Exclui: aguardando_dados, descartado.

    Ordenação: prioridade → complexidade de execução → score de presença consolidado
    """
    _ORDEM_PRIO = {"alta": 0, "media": 1, "baixa": 2, "sem_dados": 3}
    _ORDEM_STATUS = {"pronto_para_contato": 0, "identificado": 1}
    _ORDEM_COMPL = {"baixa": 0, "media": 1, "alta": 2}

    candidatas = [
        e for e in empresas
        if e.get("status_comercial_sugerido") in ("pronto_para_contato", "identificado")
        and e.get("nivel_prioridade_comercial") in ("alta", "media")
    ]
    return sorted(
        candidatas,
        key=lambda e: (
            _ORDEM_PRIO.get(e.get("nivel_prioridade_comercial", "sem_dados"), 9),
            _ORDEM_STATUS.get(e.get("status_comercial_sugerido", "identificado"), 9),
            _ORDEM_COMPL.get(e.get("nivel_complexidade_execucao", "alta"), 9),
            -e.get("score_presenca_consolidado", 0),
        ),
    )


# ---------------------------------------------------------------------------
# Plano por empresa
# ---------------------------------------------------------------------------

def _plano(empresa: dict) -> dict:
    """Gera campos de plano comercial para uma empresa."""
    cls = empresa.get("classificacao_presenca_comercial", "pouca_utilidade_presenca")

    if cls == "pouca_utilidade_presenca" or not empresa.get("plano_marketing_gerado"):
        empresa["plano_comercial_gerado"] = False
        for campo in (
            "oferta_principal_comercial", "motivo_oferta_principal",
            "canal_primeiro_contato", "canal_contato_secundario",
            "abordagem_comercial_inicial", "sequencia_followup_comercial",
            "criterios_qualificacao", "sinais_interesse_comercial",
            "sinais_descarte_comercial", "momento_certo_proposta",
            "proxima_acao_comercial", "status_comercial_sugerido",
            "motivo_status_comercial", "nivel_prioridade_comercial",
            "observacoes_comerciais",
        ):
            empresa[campo] = None
        empresa["status_comercial_sugerido"] = "descartado"
        empresa["motivo_status_comercial"] = "Empresa sem oportunidade identificada ou dados insuficientes."
        empresa["nivel_prioridade_comercial"] = "sem_dados"
        return empresa

    gap = _gap_codigo(empresa)
    cat = empresa.get("categoria_id", "default")
    canal = _canal_principal(empresa)
    canal_sec = _canal_secundario(empresa, canal)
    prio = _prioridade(empresa, gap, canal)
    status = _status(prio, canal)

    empresa["oferta_principal_comercial"]    = _get(cat, _OFERTA.get(gap, {}))
    empresa["motivo_oferta_principal"]       = _MOTIVO.get(gap, "")
    empresa["canal_primeiro_contato"]        = canal
    empresa["canal_contato_secundario"]      = canal_sec
    empresa["abordagem_comercial_inicial"]   = _abordagem(empresa, gap, cat)
    empresa["sequencia_followup_comercial"]  = _FOLLOWUP.get(canal, _FOLLOWUP["pesquisa_adicional"])
    empresa["criterios_qualificacao"]        = _get(gap, _QUALIFICACAO, fallback_key="default")
    empresa["sinais_interesse_comercial"]    = _SINAIS_INTERESSE
    empresa["sinais_descarte_comercial"]     = _SINAIS_DESCARTE
    empresa["momento_certo_proposta"]        = _MOMENTO_PROPOSTA.get(gap, _MOMENTO_PROPOSTA["default"])
    empresa["proxima_acao_comercial"]        = _proxima_acao(empresa, gap, canal, cat)
    empresa["status_comercial_sugerido"]     = status
    empresa["motivo_status_comercial"]       = _motivo_status(empresa, status, canal, prio)
    empresa["nivel_prioridade_comercial"]    = prio
    empresa["observacoes_comerciais"]        = _observacoes(empresa)
    empresa["plano_comercial_gerado"]        = True

    return empresa


# ---------------------------------------------------------------------------
# Helpers de canal
# ---------------------------------------------------------------------------

def _canal_principal(empresa: dict) -> str:
    """Determina o melhor canal para primeiro contato."""
    wa = empresa.get("whatsapp_confirmado")
    conf_tel = empresa.get("confianca_telefone", "nao_identificado")
    conf_email = empresa.get("confianca_email", "nao_identificado")

    if wa and empresa.get("confianca_whatsapp", "nao_identificado") in ("alta", "media"):
        return "whatsapp"
    if conf_tel in ("alta", "media") and empresa.get("telefone_confirmado"):
        return "telefone"
    if conf_email in ("alta", "media") and empresa.get("email_confirmado"):
        return "email"
    if empresa.get("website_confirmado") and empresa.get("site_acessivel"):
        return "formulario_site"
    return "pesquisa_adicional"


def _canal_secundario(empresa: dict, canal_principal: str) -> str:
    """Canal alternativo se o principal não funcionar."""
    wa = empresa.get("whatsapp_confirmado")
    conf_tel = empresa.get("confianca_telefone", "nao_identificado")
    conf_email = empresa.get("confianca_email", "nao_identificado")

    if canal_principal == "telefone":
        if wa:
            return "whatsapp"
        if conf_email in ("alta", "media"):
            return "email"
        return "pesquisa_adicional"

    if canal_principal == "whatsapp":
        if conf_tel in ("alta", "media"):
            return "telefone"
        if conf_email in ("alta", "media"):
            return "email"
        return "pesquisa_adicional"

    if canal_principal == "email":
        if conf_tel in ("alta", "media"):
            return "telefone"
        if wa:
            return "whatsapp"
        return "pesquisa_adicional"

    return "pesquisa_adicional"


# ---------------------------------------------------------------------------
# Helpers de texto
# ---------------------------------------------------------------------------

def _get(chave: str, mapa: dict, fallback_key: str = "default") -> str:
    """Busca texto por chave com fallback."""
    return mapa.get(chave) or mapa.get(fallback_key, "")


def _abordagem(empresa: dict, gap: str, cat: str) -> str:
    """Gera texto de abordagem com variáveis substituídas."""
    nome = empresa.get("nome", "a empresa")
    cidade = empresa.get("cidade", "sua cidade")
    categoria = empresa.get("categoria", "empresa").lower()

    mapa_gap = _ABORDAGEM.get(gap) or _ABORDAGEM["default"]
    template = mapa_gap.get(cat) or mapa_gap.get("default", "")

    return (
        template
        .replace("{nome}", nome)
        .replace("{cidade}", cidade)
        .replace("{categoria}", categoria)
    )


def _proxima_acao(empresa: dict, gap: str, canal: str, cat: str) -> str:
    """Próxima ação concreta com dados reais de contato."""
    nome = empresa.get("nome", "a empresa")
    tel = empresa.get("telefone_confirmado") or empresa.get("telefone")
    wa = empresa.get("whatsapp_confirmado")
    email = empresa.get("email_confirmado") or empresa.get("email")
    cidade = empresa.get("cidade", "")
    categoria = empresa.get("categoria", "empresa").lower()

    _VERBOS_ACAO = {
        "sem_website":      f"mencionar que {nome} não aparece quando clientes pesquisam {categoria} em {cidade} no Google — perguntar se tem interesse em criar página com formulário e WhatsApp",
        "site_inacessivel": f"mencionar que tentou acessar o site de {nome} e não funcionou — oferecer diagnóstico rápido sem custo",
        "sem_whatsapp":     f"mencionar que o site de {nome} não tem botão de WhatsApp — perguntar se tem interesse em adicionar (implementação em 1-3 dias)",
        "sem_cta":          f"mencionar que o site de {nome} não tem botão de contato em destaque — mostrar como seria com um botão visível",
        "sem_email":        f"mencionar que {nome} não tem e-mail público de contato — oferecer configuração com formulário no site",
        "sem_https":        f"mencionar que o site de {nome} exibe aviso de 'site inseguro' — oferecer solução técnica rápida",
        "sem_instagram":    f"mencionar que {nome} não tem Instagram — mostrar como um perfil simples aumenta visibilidade local",
        "presenca_estruturada": f"mencionar oportunidade de melhorar o posicionamento de {nome} em buscas locais",
        "default":          f"apresentar diagnóstico de presença digital de {nome} e a oportunidade identificada",
    }

    verbo = _VERBOS_ACAO.get(gap) or _VERBOS_ACAO["default"]

    if canal == "whatsapp" and wa:
        return f"Enviar mensagem no WhatsApp ({wa}) para {verbo}"
    if canal == "telefone" and tel:
        return f"Ligar para {tel} e {verbo}"
    if canal == "email" and email:
        return f"Enviar e-mail para {email} e {verbo}"
    return f"Pesquisar canal de contato de {nome} no Google antes de prosseguir"


def _prioridade(empresa: dict, gap: str, canal: str) -> str:
    """Prioridade comercial de execução."""
    cls = empresa.get("classificacao_presenca_comercial", "")
    complexidade = empresa.get("nivel_complexidade_execucao", "media")

    tem_contato_util = canal in ("telefone", "whatsapp", "email")

    if not tem_contato_util:
        return "sem_dados"

    if cls == "oportunidade_alta_presenca" and complexidade in ("baixa", "media"):
        return "alta"

    if cls in ("oportunidade_alta_presenca", "oportunidade_media_presenca") and complexidade == "baixa":
        return "alta"

    if cls == "oportunidade_media_presenca" and tem_contato_util:
        return "media"

    if cls == "oportunidade_alta_presenca" and complexidade == "alta":
        return "media"

    return "baixa"


def _status(prioridade: str, canal: str) -> str:
    """Status comercial sugerido."""
    if canal == "pesquisa_adicional":
        return "aguardando_dados"
    if prioridade in ("alta", "media"):
        return "pronto_para_contato"
    return "identificado"


def _motivo_status(empresa: dict, status: str, canal: str, prio: str) -> str:
    """Texto explicando o status comercial."""
    nome = empresa.get("nome", "Empresa")
    cls = empresa.get("classificacao_presenca_comercial", "")
    gargalo = empresa.get("gargalo_principal_marketing") or empresa.get("principal_gargalo_presenca", "")

    if status == "pronto_para_contato":
        canal_desc = {"telefone": "telefone confirmado", "whatsapp": "WhatsApp confirmado", "email": "e-mail confirmado"}.get(canal, canal)
        return f"{nome} tem {canal_desc}, oportunidade clara ({cls.replace('_presenca', '').replace('_', ' ')}) e {gargalo.lower()}"

    if status == "aguardando_dados":
        return f"{nome} tem oportunidade identificada mas sem canal de contato direto disponível — necessário pesquisar antes de abordar"

    if status == "identificado":
        return f"{nome} identificada com oportunidade mas prioridade baixa — abordar após finalizar leads de alta prioridade"

    return f"{nome} sem dados suficientes para execução comercial no momento"


def _observacoes(empresa: dict) -> str:
    """Ressalvas sobre qualidade dos dados."""
    notas = []

    if empresa.get("confianca_telefone") == "alta":
        notas.append("Telefone do OSM pode estar desatualizado — confirmar na primeira conversa.")

    if empresa.get("site_acessivel") and not empresa.get("whatsapp_confirmado"):
        notas.append("WhatsApp pode existir no site mas não foi detectado (conteúdo JavaScript).")

    if empresa.get("confianca_diagnostico_presenca") == "sem_dados":
        notas.append("Empresa sem site — diagnóstico baseado apenas em OSM.")

    if not notas:
        notas.append("Dados suficientes para abordagem direta.")

    return " ".join(notas)


def _gap_codigo(empresa: dict) -> str:
    """Re-deriva o código do gap principal a partir dos campos da empresa."""
    if empresa.get("classificacao_comercial") == "pouco_util":
        return "dados_insuficientes"
    tem_canal = any(
        empresa.get(f"confianca_{c}", "nao_identificado") != "nao_identificado"
        for c in _TODOS_CANAIS
    )
    if not tem_canal:
        return "sem_canais"
    if not empresa.get("website_confirmado"):
        return "sem_website"
    if empresa.get("tem_site") and not empresa.get("site_acessivel"):
        return "site_inacessivel"
    if not empresa.get("whatsapp_confirmado"):
        return "sem_whatsapp"
    if not empresa.get("tem_cta_clara"):
        return "sem_cta"
    if not empresa.get("email_confirmado"):
        return "sem_email"
    if not empresa.get("usa_https"):
        return "sem_https"
    if not empresa.get("instagram_confirmado"):
        return "sem_instagram"
    if not empresa.get("facebook_confirmado"):
        return "sem_facebook"
    return "presenca_estruturada"
