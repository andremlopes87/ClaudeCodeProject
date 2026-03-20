"""
agents/prospeccao/abordagem.py — Gera pacote de abordagem comercial por empresa.

Responsabilidades:
- Gerar mensagens prontas para uso, adaptadas ao canal de contato disponível
- Identificar a oportunidade principal com base na categoria e nos sinais encontrados
- Fornecer orientações práticas para quem vai fazer a abordagem

Regras de tom:
- Profissional, simples e direto
- Sem buzzwords: nada de "IA revolucionária", "transformação digital", "solução inovadora"
- Foco no problema concreto do negócio, não na tecnologia
- Telefone: abertura curta de conversa (20-35 palavras)
- E-mail: assunto + corpo curto (3-4 frases)

Deve ser chamado APÓS calcular_abordabilidade, aplicado apenas a empresas abordáveis.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapeamento de oportunidades por categoria
# ---------------------------------------------------------------------------

_OPORTUNIDADES = {
    "barbearia": {
        "oportunidade": "Agendamento e retenção de clientes",
        "problema_tipico": "Clientes ligam para agendar e às vezes não aparecem. Sem lembretes automáticos, a agenda vira um problema.",
        "ganho_rapido": "Reduzir faltas com confirmação automática de horário",
        "servico_sugerido": "agendamento com confirmação automática",
        "pergunta_abertura": "Como vocês organizam a agenda hoje — é tudo no WhatsApp?",
    },
    "salao_de_beleza": {
        "oportunidade": "Agendamento e confirmação de horários",
        "problema_tipico": "Clientes esquecem horários e o salão perde receita com ausências de última hora.",
        "ganho_rapido": "Confirmar horários automaticamente sem precisar ligar para cada cliente",
        "servico_sugerido": "agendamento com lembrete automático",
        "pergunta_abertura": "Vocês têm muitos cancelamentos de última hora ou clientes que esquecem o horário?",
    },
    "oficina_mecanica": {
        "oportunidade": "Orçamento digital e follow-up pós-serviço",
        "problema_tipico": "Clientes levam o carro e ficam esperando retorno. Sem acompanhamento, muitos não voltam para revisão.",
        "ganho_rapido": "Enviar status do serviço e lembrar o cliente na próxima revisão",
        "servico_sugerido": "acompanhamento de ordem de serviço e follow-up de revisão",
        "pergunta_abertura": "Vocês conseguem avisar o cliente quando o carro fica pronto — ou ainda é tudo no boca a boca?",
    },
    "borracharia": {
        "oportunidade": "Atendimento rápido e consulta de disponibilidade",
        "problema_tipico": "Clientes chegam sem saber se o pneu que precisam está disponível. Atendimento vira correria.",
        "ganho_rapido": "Receber pedidos com antecedência e organizar a fila de atendimento",
        "servico_sugerido": "consulta de disponibilidade e agendamento de serviço",
        "pergunta_abertura": "Vocês recebem muita demanda de cliente que chega sem hora marcada e precisa de atendimento rápido?",
    },
    "acougue": {
        "oportunidade": "Pedido antecipado e fidelização de clientes",
        "problema_tipico": "Clientes querem cortes específicos e precisam ligar para reservar. Sem controle, falta produto ou sobra estoque.",
        "ganho_rapido": "Receber pedidos com antecedência para organizar o corte e reduzir desperdício",
        "servico_sugerido": "pedido antecipado e lista de clientes recorrentes",
        "pergunta_abertura": "Vocês têm clientes que pedem cortes específicos com frequência — isso vocês controlam como hoje?",
    },
    "padaria": {
        "oportunidade": "Encomendas e pedidos antecipados",
        "problema_tipico": "Encomendas de bolo e salgados chegam de última hora. Sem controle, a produção vira improviso.",
        "ganho_rapido": "Receber encomendas com antecedência e organizar a produção do dia",
        "servico_sugerido": "sistema de encomendas com prazo e confirmação",
        "pergunta_abertura": "As encomendas de vocês chegam com antecedência ou sempre de última hora?",
    },
    "autopecas": {
        "oportunidade": "Consulta de peças e orçamento digital",
        "problema_tipico": "Mecânicos e clientes ligam para consultar disponibilidade de peças. Sem sistema, o atendente perde tempo respondendo as mesmas perguntas.",
        "ganho_rapido": "Responder consultas de disponibilidade sem ocupar o telefone o tempo todo",
        "servico_sugerido": "consulta de estoque e orçamento por mensagem",
        "pergunta_abertura": "Vocês recebem muita ligação só para consultar se uma peça está disponível?",
    },
}

_OPORTUNIDADE_PADRAO = {
    "oportunidade": "Organização do atendimento digital",
    "problema_tipico": "Sem canais digitais organizados, o negócio depende de ligações e atendimento presencial para tudo.",
    "ganho_rapido": "Organizar o contato com clientes de forma mais eficiente",
    "servico_sugerido": "organização do atendimento e contato com clientes",
    "pergunta_abertura": "Como vocês organizam o contato com clientes hoje — WhatsApp, telefone ou tudo presencial?",
}

# ---------------------------------------------------------------------------
# Geração de pacote de abordagem
# ---------------------------------------------------------------------------


def preparar_abordagens(empresas: list) -> list:
    """
    Gera pacote de abordagem para cada empresa da lista.

    Deve ser chamado com a lista de candidatas_abordaveis (já filtrada).
    Adiciona campos de abordagem sem remover campos existentes.

    Entrada: lista de empresas com classificação e abordabilidade calculadas
    Saída: mesma lista com campos de abordagem adicionados
    """
    return [_preparar(e) for e in empresas]


def _preparar(empresa: dict) -> dict:
    """Gera e adiciona todos os campos de abordagem para uma empresa."""
    categoria_id = empresa.get("categoria_id", "")
    oport = _OPORTUNIDADES.get(categoria_id, _OPORTUNIDADE_PADRAO)

    nome = empresa.get("nome", "o estabelecimento")
    canal = empresa.get("canal_abordagem_sugerido", "sem_canal_identificado")
    classificacao = empresa.get("classificacao_comercial", "analogica")
    sinais = empresa.get("sinais", {})
    tem_instagram = empresa.get("tem_instagram", False)
    contato = empresa.get("contato_principal", "")
    score = empresa.get("score_prontidao_ia", 0)

    empresa["resumo_empresa"] = _resumo(empresa, oport)
    empresa["oportunidade_principal"] = oport["oportunidade"]
    empresa["motivo_abordagem"] = _motivo(sinais, tem_instagram, classificacao, oport)
    empresa["canal_abordagem_recomendado"] = canal
    empresa["mensagem_inicial_curta"] = _mensagem_curta(nome, canal, oport, contato)
    empresa["mensagem_inicial_media"] = _mensagem_media(nome, canal, oport, sinais, tem_instagram)
    empresa["followup_curto"] = _followup(nome, canal, oport)
    empresa["observacoes_abordagem"] = _observacoes(canal, sinais, tem_instagram, score)
    empresa["risco_abordagem"] = _risco(classificacao, sinais, canal)
    empresa["tom_recomendado"] = _tom(canal, classificacao)

    return empresa


# ---------------------------------------------------------------------------
# Campos individuais
# ---------------------------------------------------------------------------


def _resumo(empresa: dict, oport: dict) -> str:
    """Resumo objetivo da empresa baseado nos dados disponíveis."""
    nome = empresa.get("nome", "Estabelecimento sem nome registrado")
    categoria_nome = empresa.get("categoria_nome", "Estabelecimento comercial")
    sinais = empresa.get("sinais", {})
    tem_instagram = empresa.get("tem_instagram", False)

    sinais_presentes = []
    if sinais.get("tem_telefone"):
        sinais_presentes.append("telefone público")
    if sinais.get("tem_website"):
        sinais_presentes.append("site próprio")
    if sinais.get("tem_horario"):
        sinais_presentes.append("horário de funcionamento")
    if sinais.get("tem_email"):
        sinais_presentes.append("e-mail de contato")
    if tem_instagram:
        sinais_presentes.append("Instagram")

    base = f"{nome} — {categoria_nome}."
    if sinais_presentes:
        base += f" Dados públicos identificados: {', '.join(sinais_presentes)}."
    else:
        base += " Poucos dados digitais identificados nos registros públicos."

    return base


def _motivo(sinais: dict, tem_instagram: bool, classificacao: str, oport: dict) -> str:
    """Por que esta empresa é uma boa oportunidade de abordagem."""
    ausentes = []
    if not sinais.get("tem_website"):
        ausentes.append("site próprio")
    if not sinais.get("tem_horario"):
        ausentes.append("horário online")
    if not tem_instagram:
        ausentes.append("presença em redes sociais")

    if classificacao == "semi_digital_prioritaria":
        base = f"Empresa com presença digital parcial. Oportunidade: {oport['oportunidade'].lower()}."
        if ausentes:
            base += f" Lacunas identificadas nos dados públicos: {', '.join(ausentes)}."
        base += f" {oport['problema_tipico']}"
        return base

    # analogica
    base = f"Empresa com baixa presença digital identificada nos dados públicos."
    base += f" Oportunidade de organizar: {oport['oportunidade'].lower()}."
    base += f" {oport['problema_tipico']}"
    return base


def _mensagem_curta(nome: str, canal: str, oport: dict, contato: str) -> str:
    """
    Mensagem de abertura curta adaptada ao canal.

    Telefone: abertura de conversa (20-35 palavras)
    E-mail: apenas o assunto (Subject:) — corpo fica na média
    """
    if canal == "telefone":
        return (
            f"Olá, tudo bem? Meu nome é [seu nome], trabalho com soluções de atendimento para "
            f"{_tipo_negocio(oport)}. Posso falar um minutinho com o responsável?"
        )

    if canal == "email":
        return f"Assunto: {oport['oportunidade']} para {nome}"

    # fallback para outros canais
    return f"Olá! Tenho interesse em conversar sobre {oport['oportunidade'].lower()} para {nome}."


def _mensagem_media(nome: str, canal: str, oport: dict, sinais: dict, tem_instagram: bool) -> str:
    """
    Mensagem completa adaptada ao canal.

    Telefone: script de abertura mais completo
    E-mail: corpo do e-mail (3-4 frases)
    """
    if canal == "telefone":
        return (
            f"Olá, tudo bem? Meu nome é [seu nome] e trabalho com organização de atendimento "
            f"para {_tipo_negocio(oport)}. {oport['problema_tipico']} "
            f"Desenvolvemos uma forma de {oport['ganho_rapido'].lower()}. "
            f"Teria como falar dois minutinhos com o responsável para eu explicar rapidamente como funciona?"
        )

    if canal == "email":
        return (
            f"Olá,\n\n"
            f"Trabalho com {oport['servico_sugerido']} para estabelecimentos como o {nome}.\n\n"
            f"{oport['problema_tipico']}\n\n"
            f"Desenvolvemos uma forma de {oport['ganho_rapido'].lower()}, sem complicar a rotina de quem já está ocupado.\n\n"
            f"Posso te enviar um exemplo de como funciona? Leva menos de 5 minutos para entender.\n\n"
            f"Att,\n[seu nome]"
        )

    return (
        f"Olá! Trabalho com {oport['servico_sugerido']} para negócios como {nome}. "
        f"{oport['problema_tipico']} "
        f"Posso mostrar como funciona em poucos minutos?"
    )


def _followup(nome: str, canal: str, oport: dict) -> str:
    """Mensagem curta de follow-up para caso não haja resposta inicial."""
    if canal == "telefone":
        return (
            f"Olá, tudo bem? Liguei dias atrás para falar sobre {oport['oportunidade'].lower()} "
            f"para o {nome}. Consegue me dar um retorno rápido?"
        )

    if canal == "email":
        return (
            f"Olá, acompanhando meu e-mail anterior sobre {oport['oportunidade'].lower()} "
            f"para o {nome}. Tem interesse em ver como funciona?"
        )

    return (
        f"Olá! Entrei em contato dias atrás sobre {oport['oportunidade'].lower()}. "
        f"Posso mostrar como funciona?"
    )


def _observacoes(canal: str, sinais: dict, tem_instagram: bool, score: int) -> str:
    """Orientações práticas para quem vai fazer a abordagem."""
    obs = []

    if canal == "telefone":
        obs.append("Ligue em horário comercial (9h-12h ou 14h-17h) para maior chance de falar com o responsável.")
        obs.append("Se não atender, tente no máximo 2 vezes antes de enviar mensagem pelo WhatsApp no mesmo número.")
        obs.append(f"Pergunta sugerida de abertura: \"{_OPORTUNIDADES.get('barbearia', _OPORTUNIDADE_PADRAO)['pergunta_abertura']}\"")

    elif canal == "email":
        obs.append("Envie no início da semana (terça ou quarta) para maior taxa de abertura.")
        obs.append("Se não houver resposta em 3-5 dias úteis, envie o follow-up.")
        obs.append("Assunto curto e direto tem maior taxa de abertura — evite palavras como 'promoção' ou 'grátis'.")

    if score < 30:
        obs.append("Score de prontidão baixo: empresa pode ter pouca familiaridade com serviços digitais. Abordagem pode precisar de mais tempo de explicação.")

    if not sinais.get("tem_website") and not tem_instagram:
        obs.append("Empresa sem presença digital identificada nos dados públicos — pode ser receptiva a uma primeira estruturação, ou completamente avessa. Avaliar na conversa.")

    if sinais.get("tem_website") and not sinais.get("tem_telefone"):
        obs.append("Empresa tem site mas não tem telefone público identificado — pode preferir contato por canais digitais.")

    return " | ".join(obs) if obs else "Nenhuma observação específica identificada para esta empresa."


def _risco(classificacao: str, sinais: dict, canal: str) -> str:
    """Riscos práticos identificados para esta abordagem."""
    riscos = []

    if classificacao == "analogica":
        riscos.append("Empresa com baixa presença digital pode ser resistente a mudanças ou desconhecer o valor dos serviços")

    if not sinais.get("tem_horario"):
        riscos.append("Horário de funcionamento não identificado — risco de ligar ou enviar e-mail fora do expediente")

    if canal == "email" and not sinais.get("tem_email"):
        riscos.append("E-mail obtido indiretamente — pode não ser monitorado com frequência")

    if not riscos:
        return "Nenhum risco crítico identificado com os dados disponíveis."

    return ". ".join(riscos) + "."


def _tom(canal: str, classificacao: str) -> str:
    """Tom recomendado para a abordagem."""
    if canal == "telefone":
        base = "Direto e conversacional. Não leia o script — use-o como guia. Adapte conforme a resposta do interlocutor."
    elif canal == "email":
        base = "Profissional e conciso. Evite parágrafos longos. Uma ideia por frase."
    else:
        base = "Profissional e objetivo."

    if classificacao == "analogica":
        base += " Empresa com menor presença digital — use linguagem simples, sem termos técnicos."

    return base


def _tipo_negocio(oport: dict) -> str:
    """Retorna descrição genérica do tipo de negócio com base na oportunidade."""
    oportunidade = oport.get("oportunidade", "").lower()
    if "agenda" in oportunidade or "horário" in oportunidade:
        return "negócios com agendamento"
    if "orçamento" in oportunidade or "serviço" in oportunidade:
        return "oficinas e serviços"
    if "encomenda" in oportunidade or "pedido" in oportunidade:
        return "estabelecimentos com encomendas"
    if "peça" in oportunidade or "estoque" in oportunidade:
        return "lojas e distribuidoras"
    return "pequenos negócios"
