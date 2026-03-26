"""
agents/prospeccao/abordagem.py — Gera pacote de abordagem comercial por empresa.

Responsabilidades:
- Gerar mensagens prontas para uso, adaptadas ao canal de contato disponível
- Identificar a oportunidade principal com base na categoria e nos sinais encontrados
- Fornecer orientações práticas para quem vai fazer a abordagem

Regras de tom (v2 — storytelling):
- Nunca buzzwords: "transformação digital", "soluções", "inovação", "potencializar"
- Sempre do ponto de vista do CLIENTE, nunca da Vetor
- Mostrar o problema como CENA do dia a dia do dono
- Conectar problema a PERDA concreta (dinheiro, tempo, cliente perdido)
- Solução como consequência natural, não como venda
- Formal mas simples, sem intimidade forçada, sem exclamação, sem emoji
- Terminar com porta aberta, nunca pressão
- Assinar como "Equipe Vetor"

Referência: dados/guia_tom_comunicacao.json + dados/exemplos_tom_por_categoria.json
Deve ser chamado APÓS calcular_abordabilidade, aplicado apenas a empresas abordáveis.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cenas de abordagem por categoria (tom storytelling v2)
# Cada entrada define: cena, perda, comportamento do consumidor, gancho, assunto
# ---------------------------------------------------------------------------

_CENAS = {
    "barbearia": {
        "oportunidade": "Agendamento pelo WhatsApp",
        "cena_problema": "Cadeira vazia, barbeiro parado no meio da tarde. O cliente entrou no site, viu o telefone, pensou em ligar depois e seguiu o dia.",
        "perda_concreta": "Barbeiro parado mais custos fixos rodando — dinheiro perdido a cada horário vazio.",
        "comportamento_consumidor": "A pessoa entra no site já com a intenção de agendar, vê o telefone, pensa em ligar depois, segue o dia. Algumas esquecem. Outras escolhem outra barbearia onde conseguiram resolver na hora.",
        "gancho_solucao": "agendamento pelo WhatsApp na hora em que o cliente decidiu, sem adiar e sem desistir no caminho",
        "assunto_email": "Como um cliente tenta agendar na {nome}",
        "abertura_contexto": "Encontrei a {nome} pela internet e fui verificar como um cliente faz para marcar um horário. Percebi que, hoje, ele ainda precisa ligar para conseguir agendar.",
        "cena_perda_elaborada": (
            "a perda não está apenas no horário que deixou de ser marcado. "
            "Está no barbeiro que já está ali, pronto para trabalhar, mas fica sem atender naquele momento, "
            "enquanto poderia estar com mais um cliente na cadeira. "
            "E, quando isso se repete, a cadeira fica vazia, o barbeiro fica sem atender, "
            "e a barbearia deixa de ganhar dinheiro justamente enquanto continua pagando "
            "salários, aluguel, luz, internet e todo o resto."
        ),
        "porta_aberta": "Considerei importante escrever porque esse é o tipo de ajuste que pode evitar perdas no dia a dia. Se fizer sentido, posso mostrar como isso funcionaria na {nome}.",
    },
    "salao_de_beleza": {
        "oportunidade": "Confirmação automática de horários",
        "cena_problema": "Profissional esperando na cadeira. Horário marcado por ligação que não confirmou. No final do dia, dois horários vazios que poderiam estar ocupados.",
        "perda_concreta": "Hora de profissional parado é custo direto — salário, aluguel da cabine, produtos que não foram usados.",
        "comportamento_consumidor": "A cliente liga, marca, desliga. Três dias depois esqueceu. Não avisou que não viria. O profissional esperou, atendeu menos, ganhou menos.",
        "gancho_solucao": "confirmação automática pelo WhatsApp no dia anterior, para que a cliente confirme com um clique ou remarque com antecedência",
        "assunto_email": "O horário que o salão reservou mas não foi ocupado",
        "abertura_contexto": "Encontrei o {nome} pela internet e fui verificar como uma cliente faz para marcar um horário. Percebi que, hoje, o processo ainda passa por ligação — e que a confirmação do horário depende de a cliente se lembrar de aparecer.",
        "cena_perda_elaborada": (
            "quando a cliente não aparece e não avisa, a profissional já estava ali, "
            "separou o tempo, talvez tenha recusado outro atendimento. "
            "O horário vazio vira prejuízo direto — e não tem como recuperar aquela hora depois."
        ),
        "porta_aberta": "Considerei importante escrever porque esse tipo de perda acontece silenciosamente toda semana. Se fizer sentido, posso mostrar como funcionaria no {nome}.",
    },
    "oficina_mecanica": {
        "oportunidade": "Aviso automático e follow-up de revisão",
        "cena_problema": "Cliente deixou o carro de manhã, ligou duas vezes perguntando se ficou pronto. O mecânico parou o serviço para responder. No final do dia, o cliente foi embora sem receber um retorno claro sobre quando voltar para a revisão.",
        "perda_concreta": "Mecânico interrompido perde ritmo. Cliente sem follow-up não volta para revisão. Cada revisão que não acontece é uma ordem de serviço a menos no fim do mês.",
        "comportamento_consumidor": "O cliente deixa o carro e fica no escuro. Quando não recebe retorno, começa a ligar. Quando o atendimento parece desorganizado, leva para outra oficina da próxima vez.",
        "gancho_solucao": "aviso automático quando o carro ficar pronto, mais lembrete de revisão no prazo certo — sem ocupar o mecânico com ligações de acompanhamento",
        "assunto_email": "O que acontece quando o cliente não recebe retorno sobre o carro",
        "abertura_contexto": "Encontrei a {nome} pela internet e fui verificar como um cliente acompanha o andamento do serviço do carro. Percebi que, hoje, esse contato ainda depende de o cliente ligar para saber.",
        "cena_perda_elaborada": (
            "quando o cliente precisa ligar para saber se o carro ficou pronto, "
            "ele já começou a perder a confiança no processo. "
            "Sem um aviso claro e um lembrete de revisão no prazo certo, "
            "parte desses clientes não volta — e cada revisão que não acontece é uma receita "
            "que sumiu sem que ninguém percebeu."
        ),
        "porta_aberta": "Considerei importante escrever porque esse tipo de cliente que não retorna quase nunca reclama — ele simplesmente vai embora. Se fizer sentido, posso mostrar como funcionaria na {nome}.",
    },
    "padaria": {
        "oportunidade": "Confirmação de encomendas pelo WhatsApp",
        "cena_problema": "Domingo à tarde, cliente manda mensagem pedindo um bolo para sábado que vem. Ninguém viu a mensagem. Na sexta, o cliente liga perguntando. O bolo não foi feito.",
        "perda_concreta": "Encomenda perdida é receita perdida. E o cliente que encomendava com frequência passou a buscar outra padaria.",
        "comportamento_consumidor": "O cliente manda a encomenda pelo WhatsApp porque é mais fácil do que ligar. Espera uma confirmação. Quando não recebe, assume que está anotado. Descobre na véspera que não está.",
        "gancho_solucao": "confirmação automática de encomenda com prazo e detalhes, para que nenhum pedido se perca no volume de mensagens do dia",
        "assunto_email": "A encomenda que chegou pelo WhatsApp e não foi confirmada",
        "abertura_contexto": "Encontrei a {nome} pela internet e fui verificar como um cliente faz uma encomenda. Percebi que, hoje, o caminho passa pelo WhatsApp — e que a confirmação depende de alguém da equipe ver a mensagem no momento certo.",
        "cena_perda_elaborada": (
            "quando a encomenda não é confirmada, o cliente não sabe se foi registrada. "
            "Às vezes descobre na véspera que não foi. Perde a encomenda, fica sem o produto "
            "que planejou e, dependendo da ocasião, não esquece. "
            "A padaria perde a venda e, em casos de clientes recorrentes, às vezes perde o cliente."
        ),
        "porta_aberta": "Considerei importante escrever porque encomendas perdidas raramente aparecem como reclamação — aparecem como cliente que sumiu. Se fizer sentido, posso mostrar como funcionaria na {nome}.",
    },
    "acougue": {
        "oportunidade": "Pedidos antecipados e confirmação",
        "cena_problema": "Cliente manda lista pelo WhatsApp pedindo cortes específicos para o fim de semana. Ninguém organizou o pedido. O cliente chegou na sexta à tarde, os cortes não estavam separados.",
        "perda_concreta": "Tempo perdido na hora do pico, cliente insatisfeito, e um frequentador que passou a comprar em outro açougue onde resolve com antecedência.",
        "comportamento_consumidor": "O cliente com pedido frequente quer resolver com antecedência para não depender do que tem no momento. Se não encontra essa facilidade, vai para quem oferece.",
        "gancho_solucao": "pedido antecipado pelo WhatsApp com confirmação de disponibilidade, para que o cliente chegue e encontre o que pediu separado",
        "assunto_email": "O cliente que pede pelo WhatsApp mas não recebe confirmação",
        "abertura_contexto": "Encontrei o {nome} pela internet e fui verificar como um cliente com pedido frequente organiza as compras. Percebi que, hoje, o caminho passa pelo WhatsApp — e que a confirmação do pedido nem sempre chega.",
        "cena_perda_elaborada": (
            "quando o pedido pelo WhatsApp não é confirmado, o cliente não sabe se foi anotado. "
            "Chega esperando encontrar o corte separado e muitas vezes não encontra. "
            "Com o tempo, o cliente que comprava toda semana começa a buscar um lugar "
            "onde o processo é mais previsível."
        ),
        "porta_aberta": "Considerei importante escrever porque clientes frequentes que somem raramente reclamam — eles simplesmente vão embora. Se fizer sentido, posso mostrar como funcionaria no {nome}.",
    },
    "autopecas": {
        "oportunidade": "Consulta de disponibilidade por mensagem",
        "cena_problema": "Mecânico liga para consultar se uma peça está disponível. O atendente parou o que estava fazendo, foi verificar, voltou para confirmar. Enquanto isso, o mecânico já havia ligado para o próximo fornecedor.",
        "perda_concreta": "Atendente interrompido várias vezes ao dia. Cliente que não recebeu resposta rápida comprou no concorrente.",
        "comportamento_consumidor": "O mecânico precisa da resposta rápido. Se demorar para ouvir de volta, liga para o próximo fornecedor ou pesquisa online. Quem responde primeiro, vende.",
        "gancho_solucao": "consulta de disponibilidade por mensagem com resposta imediata, sem ocupar o atendente com perguntas repetitivas",
        "assunto_email": "A consulta que chegou e a venda que foi para o concorrente",
        "abertura_contexto": "Encontrei a {nome} pela internet e fui verificar como um mecânico faz para consultar a disponibilidade de uma peça. Percebi que, hoje, esse processo ainda depende de uma ligação — e que a resposta leva um tempo que pode custar a venda.",
        "cena_perda_elaborada": (
            "quando o mecânico precisa de uma peça com urgência e não recebe resposta imediata, "
            "ele não espera — vai para o próximo fornecedor. "
            "Cada vez que isso acontece, é uma venda que foi embora sem fazer barulho. "
            "Com o tempo, o mecânico para de consultar e passa a comprar de quem responde mais rápido."
        ),
        "porta_aberta": "Considerei importante escrever porque essas vendas perdidas não aparecem em lugar nenhum — o cliente simplesmente não ligou mais. Se fizer sentido, posso mostrar como funcionaria na {nome}.",
    },
    "borracharia": {
        "oportunidade": "Presença digital e contato imediato",
        "cena_problema": "Cliente com pneu furado procurou borracharia no Google. Não tinha horário de funcionamento atualizado. Ligou — ninguém atendeu ainda. Foi para outra borracharia que apareceu com o WhatsApp direto.",
        "perda_concreta": "Cliente em emergência não espera. Vai para quem responde primeiro. Sem informação de funcionamento e WhatsApp visível no Google, o cliente em apuros vai para o concorrente.",
        "comportamento_consumidor": "Na emergência, o cliente não tem paciência para descobrir se está aberto. Quer o WhatsApp na tela, manda mensagem e aguarda. Quem aparece com as informações certas no Google, recebe o cliente.",
        "gancho_solucao": "horário de funcionamento correto no Google com WhatsApp direto para que o cliente em emergência encontre e entre em contato na hora",
        "assunto_email": "O cliente que te procurou no Google mas foi para o concorrente",
        "abertura_contexto": "Procurei a {nome} no Google simulando um cliente com pneu furado que precisava de atendimento imediato. Percebi que as informações de funcionamento não estão completas e que não há um caminho direto para contato pelo WhatsApp.",
        "cena_perda_elaborada": (
            "o cliente em emergência não liga duas vezes. "
            "Se não encontra o horário de funcionamento ou um contato imediato, "
            "vai para a próxima opção no Google. "
            "Quem aparece com as informações certas recebe esse cliente. "
            "Quem não aparece, simplesmente não é considerado."
        ),
        "porta_aberta": "Considerei importante escrever porque clientes em emergência são os mais fáceis de perder e os mais difíceis de recuperar — eles não voltam para reclamar. Se fizer sentido, posso mostrar como ficaria na {nome}.",
    },
}

_CENA_PADRAO = {
    "oportunidade": "Atendimento digital organizado",
    "cena_problema": "Cliente tenta entrar em contato, não encontra informações claras e vai buscar a concorrência.",
    "perda_concreta": "Clientes que não conseguem contato fácil simplesmente vão embora sem reclamar.",
    "comportamento_consumidor": "O cliente espera encontrar informações atualizadas e um canal de contato rápido. Se não encontra, vai para quem tem.",
    "gancho_solucao": "informações atualizadas no Google e WhatsApp Business para que o cliente entre em contato na hora que decidiu",
    "assunto_email": "Como um cliente tenta entrar em contato com o {nome}",
    "abertura_contexto": "Encontrei o {nome} pela internet e fui verificar como um cliente faz para entrar em contato. Percebi que hoje esse caminho não está tão claro quanto poderia ser.",
    "cena_perda_elaborada": (
        "quando o cliente não encontra facilidade de contato, ele não reclama — "
        "simplesmente vai buscar outra opção. E raramente volta."
    ),
    "porta_aberta": "Considerei importante escrever porque esse tipo de perda acontece silenciosamente. Se fizer sentido, posso mostrar como ficaria no {nome}.",
}

# Mapeamento legado (compatibilidade com código que usa _OPORTUNIDADES)
_OPORTUNIDADES = {
    k: {
        "oportunidade": v["oportunidade"],
        "problema_tipico": v["cena_problema"],
        "ganho_rapido": v["gancho_solucao"],
        "servico_sugerido": v["gancho_solucao"],
        "pergunta_abertura": v.get("abertura_contexto", "").replace("{nome}", "o estabelecimento"),
    }
    for k, v in _CENAS.items()
}
_OPORTUNIDADE_PADRAO = {
    "oportunidade": _CENA_PADRAO["oportunidade"],
    "problema_tipico": _CENA_PADRAO["cena_problema"],
    "ganho_rapido": _CENA_PADRAO["gancho_solucao"],
    "servico_sugerido": _CENA_PADRAO["gancho_solucao"],
    "pergunta_abertura": _CENA_PADRAO["abertura_contexto"].replace("{nome}", "o estabelecimento"),
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

    Telefone: abertura de conversa respeitosa, sem o nome da Vetor (será dito pessoalmente)
    E-mail: apenas o assunto — direto, sem buzzword, que desperta curiosidade
    """
    categoria_id = _categoria_de_oport(oport)
    cena = _CENAS.get(categoria_id, _CENA_PADRAO)

    if canal == "telefone":
        return (
            f"Boa tarde, tudo bem? Gostaria de falar um momento com o responsável pelo {nome}. "
            f"É sobre o atendimento de clientes pelo WhatsApp."
        )

    if canal == "email":
        assunto = cena.get("assunto_email", "Sobre o atendimento de clientes no {nome}")
        return assunto.replace("{nome}", nome)

    return f"Boa tarde. Gostaria de conversar sobre o atendimento de clientes no {nome}."


def _mensagem_media(nome: str, canal: str, oport: dict, sinais: dict, tem_instagram: bool) -> str:
    """
    Mensagem completa seguindo o padrão storytelling v2.

    Estrutura: contexto → comportamento consumidor → cena da perda → solução → porta aberta
    Assina como "Equipe Vetor". Sem buzzwords. Sem exclamação. Sem emoji.
    """
    categoria_id = _categoria_de_oport(oport)
    cena = _CENAS.get(categoria_id, _CENA_PADRAO)

    abertura = cena.get("abertura_contexto", "Encontrei o {nome} pela internet.").replace("{nome}", nome)
    comportamento = cena.get("comportamento_consumidor", "")
    perda = cena.get("cena_perda_elaborada", cena.get("perda_concreta", ""))
    gancho = cena.get("gancho_solucao", "")
    porta = cena.get("porta_aberta", "Se fizer sentido, posso mostrar como funcionaria no {nome}.").replace("{nome}", nome)

    if canal in ("email", "whatsapp"):
        corpo = (
            f"{abertura}\n\n"
            f"{comportamento}\n\n"
            f"Quando isso acontece, {perda}\n\n"
            f"A Vetor ajuda a resolver isso com {gancho}.\n\n"
            f"{porta}\n\n"
            f"Equipe Vetor"
        )
        return corpo

    if canal == "telefone":
        return (
            f"Boa tarde. Fui verificar como um cliente faz para entrar em contato com o {nome}. "
            f"{cena.get('cena_problema', '')} "
            f"Quando isso acontece, {cena.get('perda_concreta', '')} "
            f"A Vetor tem uma forma de resolver isso sem complicar a rotina. "
            f"Poderia falar dois minutos com o responsável?"
        )

    return (
        f"Boa tarde. Fui verificar o {nome} pela internet. "
        f"{cena.get('cena_problema', '')} "
        f"A Vetor ajuda a resolver isso com {gancho}. "
        f"{porta}"
    )


def _followup(nome: str, canal: str, oport: dict) -> str:
    """Mensagem de follow-up — breve, sem pressão, porta aberta."""
    categoria_id = _categoria_de_oport(oport)
    cena = _CENAS.get(categoria_id, _CENA_PADRAO)

    if canal == "telefone":
        return (
            f"Boa tarde. Entrei em contato alguns dias atrás sobre o atendimento de clientes "
            f"no {nome}. Se tiver um momento, posso explicar o que identificamos. "
            f"Equipe Vetor."
        )

    if canal in ("email", "whatsapp"):
        return (
            f"Boa tarde.\n\n"
            f"Enviei uma mensagem há alguns dias sobre o atendimento de clientes no {nome}. "
            f"Não quero insistir — só queria deixar em aberto caso tenha interesse em ver "
            f"como funcionaria na prática.\n\n"
            f"Equipe Vetor"
        )

    return (
        f"Boa tarde. Entrei em contato dias atrás sobre o {nome}. "
        f"Se tiver interesse, estou à disposição.\n\nEquipe Vetor"
    )


def _categoria_de_oport(oport: dict) -> str:
    """Extrai categoria_id do dict de oportunidade (varios formatos possíveis)."""
    return (
        oport.get("categoria_id")
        or oport.get("categoria")
        or oport.get("nicho")
        or ""
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
