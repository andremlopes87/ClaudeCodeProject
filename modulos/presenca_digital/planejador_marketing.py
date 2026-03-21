"""
modulos/presenca_digital/planejador_marketing.py — Plano de ação e proposta de serviço.

Transforma a oportunidade detectada pelo consolidador em um plano prático de execução
e em uma proposta de serviço legível para uso interno.

Este módulo NÃO executa nada. NÃO envia nada. NÃO faz anúncios.
Apenas planeja — com base no que foi detectado.

Campos gerados por empresa:
  resumo_oportunidade_marketing    : situação atual em 1-2 frases
  gargalo_principal_marketing      : o que está bloqueando o resultado
  objetivo_principal_marketing     : o que se quer alcançar
  solucao_recomendada_marketing    : o que construir ou configurar
  quick_wins_marketing             : 2-3 ações de resultado rápido
  plano_30_dias_marketing          : roteiro semanal de execução
  entregaveis_sugeridos_marketing  : o que será entregue ao final
  nivel_complexidade_execucao      : baixa / media / alta
  impacto_esperado                 : o que muda para a empresa após execução
  prioridade_execucao_marketing    : alta / media / baixa / sem_dados
  observacoes_execucao_marketing   : ressalvas e limitações dos dados
  proposta_resumida_marketing      : brief interno para entender o que oferecer
  plano_marketing_gerado           : bool — indica se o plano foi gerado com sucesso

O que este módulo NÃO faz:
  - Não executa as ações planejadas
  - Não valida se as informações do OSM estão atualizadas
  - Não analisa concorrência ou mercado
  - Não gera mensagens de abordagem
  - Não decide preço ou forma de entrega do serviço

Documentação: docs/presenca_digital/heuristicas.md
"""

import logging

logger = logging.getLogger(__name__)

_TODOS_CANAIS = ["telefone", "email", "website", "whatsapp", "instagram", "facebook"]

# ---------------------------------------------------------------------------
# Complexidade por gap — base para viabilidade de execução
# ---------------------------------------------------------------------------

_COMPLEXIDADE_POR_GAP = {
    "sem_whatsapp":         "baixa",
    "sem_cta":              "baixa",
    "sem_email":            "baixa",
    "sem_https":            "baixa",
    "sem_facebook":         "baixa",
    "presenca_estruturada": "baixa",
    "sem_website":          "media",
    "site_inacessivel":     "media",
    "sem_instagram":        "media",
    "sem_canais":           "alta",
    "dados_insuficientes":  "alta",
}

# ---------------------------------------------------------------------------
# Gargalo — descrição do problema concreto
# ---------------------------------------------------------------------------

_GARGALO_TEXTO = {
    "sem_website":          "Empresa sem página na internet — não pode ser encontrada ou contatada digitalmente por quem pesquisa no Google",
    "site_inacessivel":     "Site registrado existe, mas não está respondendo — visitantes chegam e não encontram nada",
    "sem_whatsapp":         "Site existe e funciona, mas não tem botão de WhatsApp — perde quem prefere mandar mensagem a ligar",
    "sem_cta":              "Site existe mas não orienta o visitante — sem botão de contato, agendamento ou orçamento em destaque",
    "sem_email":            "Sem e-mail de contato público — dificulta formalização e comunicação por escrito",
    "sem_https":            "Site sem HTTPS — navegadores modernos exibem aviso de 'site não seguro' para visitantes",
    "sem_instagram":        "Sem Instagram identificado — ausência em canal visual com grande alcance local",
    "sem_facebook":         "Sem página no Facebook — canal com boa base de público local ainda ativo",
    "presenca_estruturada": "Presença digital razoavelmente completa — oportunidade de melhoria de visibilidade e conversão",
    "sem_canais":           "Nenhum canal digital identificado nos dados públicos — diagnóstico incompleto",
    "dados_insuficientes":  "Dados públicos insuficientes para diagnóstico confiável",
}

# ---------------------------------------------------------------------------
# Objetivo por gap (o que se quer alcançar)
# ---------------------------------------------------------------------------

_OBJETIVO = {
    "sem_website":          "Criar presença digital básica com página de contato e mapa de localização",
    "site_inacessivel":     "Recuperar o site ou substituir por página funcional com contatos atualizados",
    "sem_whatsapp":         "Adicionar canal de contato imediato ao site para reduzir barreira de conversão",
    "sem_cta":              "Adicionar chamada para ação clara ao site para guiar o visitante ao contato",
    "sem_email":            "Configurar e-mail profissional e formulário de contato no site",
    "sem_https":            "Migrar para HTTPS e eliminar aviso de site inseguro",
    "sem_instagram":        "Criar perfil Instagram com conteúdo visual relevante para a categoria",
    "sem_facebook":         "Criar página Facebook com informações básicas e link para o site",
    "presenca_estruturada": "Melhorar visibilidade local via SEO e gestão de avaliações",
    "sem_canais":           "Mapear e criar canais básicos de contato digital",
    "dados_insuficientes":  "Levantar dados básicos antes de iniciar qualquer execução",
}

# ---------------------------------------------------------------------------
# Solução recomendada por gap + categoria
# ---------------------------------------------------------------------------

_SOLUCAO = {
    "sem_website": {
        "barbearia":        "Página de agendamento com horários, serviços e link direto para WhatsApp",
        "salao_de_beleza":  "Página de agendamento com galeria de trabalhos e link para WhatsApp",
        "oficina_mecanica": "Página de serviços com formulário de orçamento online e WhatsApp",
        "borracharia":      "Página de serviços com mapa de localização e WhatsApp para atendimento",
        "acougue":          "Página com cardápio e horário de funcionamento e WhatsApp para pedidos",
        "padaria":          "Página com cardápio, horários e WhatsApp para encomendas",
        "autopecas":        "Página com catálogo básico e formulário de cotação com WhatsApp",
        "default":          "Página simples com informações de contato, localização e horário",
    },
    "site_inacessivel": {
        "default":          "Diagnóstico de hospedagem, recuperação do site ou reconstrução em nova hospedagem confiável",
    },
    "sem_whatsapp": {
        "barbearia":        "Botão flutuante de WhatsApp com mensagem pré-preenchida para agendamento",
        "salao_de_beleza":  "Botão flutuante de WhatsApp com mensagem pré-preenchida para agendamento",
        "oficina_mecanica": "Botão flutuante de WhatsApp com mensagem pré-preenchida para solicitar orçamento",
        "default":          "Botão flutuante de WhatsApp no site com mensagem de boas-vindas configurada",
    },
    "sem_cta": {
        "barbearia":        "Botão de agendamento em destaque no topo da página com horários disponíveis",
        "salao_de_beleza":  "Botão de agendamento em destaque com opção de envio via WhatsApp",
        "oficina_mecanica": "Formulário de orçamento em destaque com campo para descrição do problema",
        "default":          "Botão de contato em destaque no topo e rodapé da página principal",
    },
    "sem_email": {
        "default":          "E-mail profissional no domínio do site e formulário de contato integrado",
    },
    "sem_https": {
        "default":          "Configuração de certificado SSL gratuito (Let's Encrypt) e redirect HTTP→HTTPS",
    },
    "sem_instagram": {
        "barbearia":        "Perfil Instagram com fotos de cortes, promoções e depoimentos de clientes",
        "salao_de_beleza":  "Perfil Instagram com fotos de resultados antes/depois e agenda de atendimento",
        "oficina_mecanica": "Perfil Instagram com dicas de manutenção e apresentação dos serviços",
        "default":          "Perfil Instagram com conteúdo visual da categoria e contato direto pelo Direct",
    },
    "sem_facebook": {
        "default":          "Página Facebook com informações básicas, link para site e botão de contato",
    },
    "presenca_estruturada": {
        "default":          "Otimização do Google Meu Negócio, gestão de avaliações e melhoria de SEO local",
    },
    "sem_canais": {
        "default":          "Pesquisa manual de canais disponíveis e criação de perfil básico no Google Meu Negócio",
    },
    "dados_insuficientes": {
        "default":          "Pesquisa e mapeamento digital da empresa antes de qualquer execução",
    },
}

# ---------------------------------------------------------------------------
# Quick wins por gap + categoria (ações de resultado rápido)
# ---------------------------------------------------------------------------

_QUICK_WINS = {
    "sem_website": {
        "barbearia":        "Criar perfil no Google Meu Negócio com horários e fotos do espaço\nRegistrar domínio e publicar página simples com WhatsApp para agendamento\nPedir aos clientes atuais avaliação no Google após o atendimento",
        "oficina_mecanica": "Criar perfil no Google Meu Negócio com serviços e formas de pagamento\nRegistrar domínio e publicar página com formulário de orçamento e WhatsApp\nListar serviços com preço médio ou faixa de valor para reduzir barreira de orçamento",
        "default":          "Criar perfil no Google Meu Negócio com horário e localização\nRegistrar domínio e publicar página com telefone e WhatsApp\nSolicitar primeiras avaliações de clientes fiéis no Google",
    },
    "site_inacessivel": {
        "default":          "Verificar se hospedagem ou domínio venceu e renovar\nInstalar página temporária de 'em manutenção' com telefone e WhatsApp\nTestar acessibilidade pelo celular após recuperação",
    },
    "sem_whatsapp": {
        "barbearia":        "Instalar botão flutuante de WhatsApp com mensagem 'Quero agendar um horário'\nAtivar WhatsApp Business e configurar resposta automática fora do horário\nColocar link direto do WhatsApp no cabeçalho da página",
        "oficina_mecanica": "Instalar botão flutuante de WhatsApp com mensagem 'Quero solicitar um orçamento'\nAtivar WhatsApp Business e configurar resposta automática fora do horário\nColocar link direto do WhatsApp no cabeçalho da página",
        "default":          "Instalar botão flutuante de WhatsApp no site\nAtivar WhatsApp Business com resposta automática fora do horário\nColocar link direto do WhatsApp no cabeçalho da página",
    },
    "sem_cta": {
        "default":          "Adicionar botão de contato no topo da página\nAdicionar botão no rodapé com telefone e WhatsApp\nTestar se o botão funciona no celular",
    },
    "sem_email": {
        "default":          "Configurar e-mail profissional no domínio do site\nAdicionar formulário de contato simples na página\nResponder e-mails em até 24h para criar hábito de atendimento digital",
    },
    "sem_https": {
        "default":          "Instalar certificado SSL gratuito (Let's Encrypt) via painel da hospedagem\nConfigurar redirecionamento automático de HTTP para HTTPS\nVerificar se todas as páginas carregam sem aviso após a migração",
    },
    "sem_instagram": {
        "barbearia":        "Criar perfil Instagram com foto do espaço e descrição com localização\nPublicar 3 fotos de cortes com hashtags locais para começar a ter alcance\nAdicionar link do Instagram no site",
        "oficina_mecanica": "Criar perfil Instagram com foto da oficina e descrição de serviços\nPublicar dica de manutenção preventiva para atrair audiência local\nAdicionar link do Instagram no site",
        "default":          "Criar perfil Instagram com foto da empresa e descrição com localização\nPublicar 3 fotos de produtos ou serviços para iniciar presença\nAdicionar link do Instagram no site",
    },
    "sem_facebook": {
        "default":          "Criar página Facebook com nome, categoria e contatos\nAdicionar link da página no site\nCompartilhar publicações do Instagram automaticamente no Facebook",
    },
    "presenca_estruturada": {
        "default":          "Verificar e completar perfil no Google Meu Negócio com fotos e horários\nResponder avaliações do Google — positivas e negativas\nIdentificar 3-5 palavras-chave locais e ajustar textos do site",
    },
    "sem_canais": {
        "default":          "Buscar empresa no Google e catalogar qualquer presença existente\nCriar perfil no Google Meu Negócio como primeiro passo\nContatar empresa para confirmar telefone e horário",
    },
    "dados_insuficientes": {
        "default":          "Pesquisar empresa no Google para confirmar se existe presença digital\nCriar perfil básico no Google Meu Negócio caso não exista\nAtualizar dados no OpenStreetMap caso encontre informações públicas",
    },
}

# ---------------------------------------------------------------------------
# Plano de 30 dias por gap + categoria
# ---------------------------------------------------------------------------

_PLANO_30_DIAS = {
    "sem_website": {
        "barbearia":        "Semana 1: registrar domínio e contratar hospedagem simples\nSemana 2: criar página com serviços, horários, fotos e agendamento via WhatsApp\nSemana 3: ativar Google Meu Negócio e solicitar primeiras avaliações\nSemana 4: ajustes com base no uso real e monitorar contatos recebidos",
        "oficina_mecanica": "Semana 1: registrar domínio e contratar hospedagem simples\nSemana 2: criar página com serviços, orçamento online e WhatsApp\nSemana 3: ativar Google Meu Negócio e listar serviços com faixa de preço\nSemana 4: ajustes com base nos primeiros contatos recebidos",
        "default":          "Semana 1: registrar domínio e contratar hospedagem\nSemana 2: criar página com informações de contato, localização e horário\nSemana 3: ativar Google Meu Negócio\nSemana 4: ajustes e validação com clientes reais",
    },
    "site_inacessivel": {
        "default":          "Semana 1: diagnosticar causa (hospedagem vencida? domínio expirado? erro no servidor?)\nSemana 2: corrigir causa ou migrar para nova hospedagem\nSemana 3: testar disponibilidade e atualizar informações do site\nSemana 4: configurar monitoramento de disponibilidade",
    },
    "sem_whatsapp": {
        "default":          "Semana 1: instalar botão de WhatsApp no site\nSemana 2: ativar WhatsApp Business com resposta automática\nSemana 3: testar fluxo de contato do site ao atendimento\nSemana 4: avaliar volume de contatos recebidos e ajustar mensagens",
    },
    "sem_cta": {
        "barbearia":        "Semana 1: mapear onde o visitante chega no site e o que faz\nSemana 2: adicionar botão de agendamento no topo e rodapé\nSemana 3: testar botão no celular e no computador\nSemana 4: verificar aumento de contatos recebidos",
        "default":          "Semana 1: identificar pontos de saída do site (onde o visitante desiste)\nSemana 2: adicionar botão de contato no topo e rodapé da página\nSemana 3: testar usabilidade no celular\nSemana 4: verificar se aumentou o número de contatos recebidos",
    },
    "sem_email": {
        "default":          "Semana 1: registrar e-mail profissional no domínio do site\nSemana 2: adicionar formulário de contato simples na página\nSemana 3: testar formulário e configurar resposta automática\nSemana 4: avaliar uso e ajustar",
    },
    "sem_https": {
        "default":          "Semana 1: instalar certificado SSL via painel da hospedagem\nSemana 2: configurar redirecionamento HTTP → HTTPS\nSemana 3: verificar se todas as páginas e imagens carregam corretamente\nSemana 4: confirmar que não há mais avisos de 'site inseguro'",
    },
    "sem_instagram": {
        "barbearia":        "Semana 1: criar perfil, adicionar foto de perfil e biografia com localização\nSemana 2: publicar 6 fotos de cortes e espaço da barbearia\nSemana 3: interagir com perfis locais e usar hashtags da cidade\nSemana 4: definir rotina mínima de publicação (2-3x por semana)",
        "oficina_mecanica": "Semana 1: criar perfil, adicionar foto e biografia com localização\nSemana 2: publicar dicas de manutenção e fotos da oficina\nSemana 3: interagir com perfis locais e responder comentários\nSemana 4: definir rotina mínima de publicação (2x por semana)",
        "default":          "Semana 1: criar perfil com foto e biografia completa\nSemana 2: publicar 6 fotos dos produtos ou serviços\nSemana 3: interagir com comunidade local e usar hashtags da cidade\nSemana 4: definir frequência mínima de publicação",
    },
    "sem_facebook": {
        "default":          "Semana 1: criar página com nome, categoria e informações básicas\nSemana 2: adicionar fotos e link para o site\nSemana 3: publicar apresentação da empresa e serviços\nSemana 4: ativar botão de contato e testar",
    },
    "presenca_estruturada": {
        "default":          "Semana 1: auditar Google Meu Negócio — completar informações, horários e fotos\nSemana 2: responder avaliações pendentes, positivas e negativas\nSemana 3: revisar textos do site com palavras-chave de busca local\nSemana 4: solicitar avaliações de clientes recentes",
    },
    "sem_canais": {
        "default":          "Semana 1: pesquisa manual de presença digital existente\nSemana 2: criar perfil no Google Meu Negócio\nSemana 3: criar página básica com informações de contato\nSemana 4: conectar canais e testar funcionamento",
    },
    "dados_insuficientes": {
        "default":          "Semana 1: pesquisar empresa online para confirmar existência e dados básicos\nSemana 2: definir quais canais criar com base no que foi encontrado\nSemana 3: criar canal principal (Google Meu Negócio ou página básica)\nSemana 4: avaliar resultado e planejar próximas ações",
    },
}

# ---------------------------------------------------------------------------
# Entregáveis por gap
# ---------------------------------------------------------------------------

_ENTREGAVEIS = {
    "sem_website":          "Página web publicada, Perfil Google Meu Negócio ativo, Link de WhatsApp integrado",
    "site_inacessivel":     "Site recuperado e funcionando, Monitoramento de disponibilidade configurado",
    "sem_whatsapp":         "Botão WhatsApp integrado ao site, WhatsApp Business configurado com resposta automática",
    "sem_cta":              "Botões de contato no topo e rodapé, Testes de usabilidade no celular",
    "sem_email":            "E-mail profissional ativo, Formulário de contato no site",
    "sem_https":            "Certificado SSL instalado, Redirecionamento HTTP→HTTPS ativo",
    "sem_instagram":        "Perfil Instagram criado e configurado, Primeiras publicações, Frequência de posts definida",
    "sem_facebook":         "Página Facebook criada, Informações completas, Botão de contato ativo",
    "presenca_estruturada": "Google Meu Negócio otimizado, Avaliações respondidas, Textos do site revisados",
    "sem_canais":           "Google Meu Negócio criado, Página básica com contato publicada",
    "dados_insuficientes":  "Relatório de presença digital, Canais prioritários mapeados",
}

# ---------------------------------------------------------------------------
# Impacto esperado por gap
# ---------------------------------------------------------------------------

_IMPACTO = {
    "sem_website":          "Empresa passa a ser encontrada em buscas locais e a receber contatos digitais — reduz dependência de indicação exclusiva",
    "site_inacessivel":     "Site volta a funcionar e visitantes conseguem acessar informações e contatar a empresa",
    "sem_whatsapp":         "Reduz barreira de contato e aumenta chance de converter visitante do site em cliente",
    "sem_cta":              "Visitantes que chegam ao site passam a ter caminho claro para entrar em contato ou agendar",
    "sem_email":            "Facilita comunicação formal e recebimento de pedidos por escrito",
    "sem_https":            "Elimina aviso de site inseguro e melhora confiança do visitante na primeira visita",
    "sem_instagram":        "Amplia alcance para público que busca serviços por indicação visual e recomendação nas redes",
    "sem_facebook":         "Aumenta cobertura em redes sociais e facilita avaliações e recomendações locais",
    "presenca_estruturada": "Melhora posicionamento em buscas locais e reputação baseada em avaliações",
    "sem_canais":           "Empresa passa a ser encontrada digitalmente e pode receber os primeiros contatos online",
    "dados_insuficientes":  "Diagnóstico mais completo permite planejar ações com base em dados reais",
}


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def planejar_marketing(empresas: list) -> list:
    """
    Aplica plano de marketing e proposta de serviço em todas as empresas.

    Entrada: lista de empresas após consolidar_presenca()
    Saída: mesma lista com campos de planejamento adicionados
    """
    logger.info(f"Gerando plano de marketing para {len(empresas)} empresas...")
    resultado = [_planejar(e) for e in empresas]

    gerados = sum(1 for e in resultado if e.get("plano_marketing_gerado"))
    logger.info(f"  Planos gerados: {gerados} de {len(empresas)}")
    return resultado


def gerar_fila_propostas(empresas: list) -> list:
    """
    Gera fila de propostas ordenada por viabilidade de execução.

    Inclui apenas empresas com plano gerado e classificação comercial favorável.
    Exclui complexidade alta (sem dados suficientes para execução segura).

    Ordenação: classificação comercial → prioridade execução → complexidade → score consolidado
    """
    _ORDEM_CLS = {
        "oportunidade_alta_presenca":  0,
        "oportunidade_media_presenca": 1,
        "oportunidade_baixa_presenca": 2,
    }
    _ORDEM_PRIO = {"alta": 0, "media": 1, "baixa": 2, "sem_dados": 3}
    _ORDEM_COMPL = {"baixa": 0, "media": 1, "alta": 2}

    candidatas = [
        e for e in empresas
        if e.get("plano_marketing_gerado") is True
        and e.get("classificacao_presenca_comercial") in (
            "oportunidade_alta_presenca",
            "oportunidade_media_presenca",
        )
        and e.get("nivel_complexidade_execucao") in ("baixa", "media")
    ]
    return sorted(
        candidatas,
        key=lambda e: (
            _ORDEM_CLS.get(e.get("classificacao_presenca_comercial", ""), 9),
            _ORDEM_PRIO.get(e.get("prioridade_execucao_marketing", "sem_dados"), 9),
            _ORDEM_COMPL.get(e.get("nivel_complexidade_execucao", "alta"), 9),
            -e.get("score_presenca_consolidado", 0),
        ),
    )


# ---------------------------------------------------------------------------
# Planejamento por empresa
# ---------------------------------------------------------------------------

def _planejar(empresa: dict) -> dict:
    """Gera campos de planejamento para uma única empresa."""
    cls = empresa.get("classificacao_presenca_comercial", "pouca_utilidade_presenca")

    # Não planeja para empresas sem oportunidade identificada
    if cls == "pouca_utilidade_presenca":
        empresa["plano_marketing_gerado"] = False
        for campo in (
            "resumo_oportunidade_marketing", "gargalo_principal_marketing",
            "objetivo_principal_marketing", "solucao_recomendada_marketing",
            "quick_wins_marketing", "plano_30_dias_marketing",
            "entregaveis_sugeridos_marketing", "nivel_complexidade_execucao",
            "impacto_esperado", "prioridade_execucao_marketing",
            "observacoes_execucao_marketing", "proposta_resumida_marketing",
        ):
            empresa[campo] = None
        return empresa

    gap = _gap_codigo(empresa)
    cat = empresa.get("categoria_id", "default")

    solucao = _get(cat, _SOLUCAO.get(gap, {}))
    empresa["resumo_oportunidade_marketing"]   = _resumo(empresa, gap)
    empresa["gargalo_principal_marketing"]     = _GARGALO_TEXTO.get(gap, gap)
    empresa["objetivo_principal_marketing"]    = _OBJETIVO.get(gap, "")
    empresa["solucao_recomendada_marketing"]   = solucao
    empresa["quick_wins_marketing"]            = _get(cat, _QUICK_WINS.get(gap, {}))
    empresa["plano_30_dias_marketing"]         = _get(cat, _PLANO_30_DIAS.get(gap, {}))
    empresa["entregaveis_sugeridos_marketing"] = _ENTREGAVEIS.get(gap, "")
    empresa["nivel_complexidade_execucao"]     = _COMPLEXIDADE_POR_GAP.get(gap, "media")
    empresa["impacto_esperado"]                = _IMPACTO.get(gap, "")
    empresa["prioridade_execucao_marketing"]   = _prioridade_execucao(empresa, gap)
    empresa["observacoes_execucao_marketing"]  = _observacoes(empresa)
    empresa["proposta_resumida_marketing"]     = _proposta_resumida(empresa, gap, solucao)
    empresa["plano_marketing_gerado"]          = True

    return empresa


# ---------------------------------------------------------------------------
# Helpers de geração de texto
# ---------------------------------------------------------------------------

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


def _get(categoria_id: str, mapa: dict) -> str:
    """Busca texto por categoria com fallback para default."""
    return mapa.get(categoria_id) or mapa.get("default", "")


def _resumo(empresa: dict, gap: str) -> str:
    """Situação atual da empresa em 1-2 frases."""
    nome = empresa.get("nome", "Empresa")
    categoria = empresa.get("categoria", "empresa")
    cidade = empresa.get("cidade", "")
    estado = empresa.get("estado", "")
    loc = f"{cidade}/{estado}" if estado else cidade

    score = empresa.get("score_presenca_consolidado", 0)
    cls_web = empresa.get("classificacao_presenca_web", "dados_insuficientes")

    descricao_situacao = {
        "presenca_boa":          "tem presença digital razoavelmente completa",
        "presenca_razoavel":     "tem presença digital básica mas com lacunas importantes",
        "presenca_basica":       "tem presença digital inicial com vários pontos a melhorar",
        "presenca_fraca":        "tem presença digital muito fraca — site existe mas está incompleto",
        "dados_insuficientes":   "não tem website registrado nos dados públicos",
    }.get(cls_web, "tem presença digital limitada")

    return (
        f"{nome}, {categoria.lower()} em {loc}, {descricao_situacao}. "
        f"Score de presença digital: {score}/100. "
        f"Principal lacuna: {_GARGALO_TEXTO.get(gap, gap).lower().split(' — ')[0]}."
    )


def _prioridade_execucao(empresa: dict, gap: str) -> str:
    """Prioridade de execução baseada em dados disponíveis e complexidade."""
    cls = empresa.get("classificacao_presenca_comercial", "")
    complexidade = _COMPLEXIDADE_POR_GAP.get(gap, "media")

    tem_contato_util = (
        empresa.get("confianca_telefone", "nao_identificado") in ("alta", "media")
        or empresa.get("confianca_email", "nao_identificado") in ("alta", "media")
    )

    if not tem_contato_util:
        return "sem_dados"

    if cls == "oportunidade_alta_presenca" and complexidade in ("baixa", "media"):
        return "alta"

    if cls in ("oportunidade_alta_presenca", "oportunidade_media_presenca") and complexidade == "baixa":
        return "alta"

    if cls == "oportunidade_media_presenca":
        return "media"

    return "baixa"


def _observacoes(empresa: dict) -> str:
    """Ressalvas sobre qualidade dos dados e limitações da análise."""
    notas = []

    if empresa.get("confianca_telefone") == "alta":
        notas.append("Telefone do OSM pode estar desatualizado — confirmar antes de contatar.")

    if empresa.get("site_acessivel") and empresa.get("confianca_whatsapp") == "nao_identificado":
        notas.append("WhatsApp pode existir carregado por JavaScript — não detectável pela análise estática.")

    confianca_diag = empresa.get("confianca_diagnostico_presenca", "")
    if confianca_diag == "sem_dados":
        notas.append("Sem site para analisar — dados baseados apenas no OpenStreetMap.")

    if empresa.get("confianca_website") == "nao_identificado":
        notas.append("Nenhum website identificado nos dados públicos.")

    if not notas:
        notas.append("Dados suficientes para execução direta.")

    return " ".join(notas)


def _proposta_resumida(empresa: dict, gap: str, solucao: str) -> str:
    """Brief interno para entender o que oferecer à empresa."""
    nome = empresa.get("nome", "Empresa")
    categoria = empresa.get("categoria", "empresa").lower()
    cidade = empresa.get("cidade", "")
    estado = empresa.get("estado", "")
    loc = f"{cidade}/{estado}" if estado else cidade

    # Situação de contato
    tel = empresa.get("telefone_confirmado") or empresa.get("contato_principal")
    conf_tel = empresa.get("confianca_telefone", "nao_identificado")
    email = empresa.get("email_confirmado")
    conf_email = empresa.get("confianca_email", "nao_identificado")

    if conf_tel in ("alta", "media") and tel:
        contato_str = f"Tem telefone disponível ({tel}) para abordagem direta."
    elif conf_email in ("alta", "media") and email:
        contato_str = f"Tem e-mail disponível ({email}) para abordagem direta."
    else:
        contato_str = "Sem canal de contato direto identificado — abordagem depende de pesquisa adicional."

    complexidade = _COMPLEXIDADE_POR_GAP.get(gap, "media")
    prio = _prioridade_execucao(empresa, gap)

    return (
        f"{nome} é {categoria} em {loc}. "
        f"{_GARGALO_TEXTO.get(gap, gap)}. "
        f"Solução sugerida: {solucao}. "
        f"Complexidade de execução: {complexidade}. "
        f"Prioridade: {prio}. "
        f"{contato_str}"
    )
