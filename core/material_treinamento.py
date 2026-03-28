"""
core/material_treinamento.py

Gera material de treinamento para clientes ao final de uma entrega.
Produz guia escrito (texto) e roteiro de vídeo personalizados por nicho.

Em dry-run: gera conteúdo simulado sem chamar API.
Em real: usa LLMRouter para gerar conteúdo personalizado.
"""

import logging
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter

log = logging.getLogger(__name__)

_PASTA_MATERIAIS = config.PASTA_DADOS / "materiais_treinamento"

# ─── Guias base por tipo de serviço ───────────────────────────────────────────

_GUIAS_BASE: dict[str, str] = {
    "atendimento_whatsapp": """\
GUIA DE USO — BOT DE ATENDIMENTO WHATSAPP

O bot de atendimento está ativo e respondendo automaticamente.

O QUE ELE FAZ:
- Responde dúvidas frequentes em segundos, 24h por dia
- Informa horários de funcionamento automaticamente
- Encaminha casos que precisam de atenção humana para você

COMO FUNCIONA:
Quando um cliente manda mensagem, o bot identifica a pergunta e responde
com base nas informações configuradas. Mensagens fora do padrão são
encaminhadas para o número de atendimento configurado.

COMO ATUALIZAR AS RESPOSTAS:
Entre em contato com a equipe Vetor para atualizar perguntas frequentes,
horários ou informações de preços a qualquer momento.

TESTE AGORA:
Mande uma mensagem para seu próprio número de WhatsApp e veja o bot em ação.
""",

    "agendamento_digital": """\
GUIA DE USO — SISTEMA DE AGENDAMENTO DIGITAL

O sistema de agendamento está configurado e funcionando.

O QUE ELE FAZ:
- Permite que clientes agendem diretamente pelo WhatsApp, sem ligação
- Mostra horários disponíveis em tempo real
- Confirma o agendamento automaticamente na sua agenda Google
- Envia lembrete automático 2 horas antes do horário

COMO FUNCIONA:
Cliente manda "quero agendar" → bot exibe serviços disponíveis → cliente
escolhe serviço, data e horário → agendamento confirmado automaticamente.

GERENCIAR SUA AGENDA:
- Acesse Google Calendar pelo celular ou computador
- Os agendamentos aparecem automaticamente com nome e serviço do cliente
- Para bloquear horários: crie um evento na sua agenda normalmente

CANCELAMENTOS:
O cliente pode cancelar respondendo no WhatsApp. Você também pode
remover o evento diretamente da sua agenda Google.
""",

    "presenca_digital": """\
GUIA DE USO — PERFIL GOOGLE MEU NEGÓCIO

Seu perfil no Google foi criado e está configurado.

O QUE ELE FAZ:
- Seu negócio aparece quando alguém busca no Google Maps
- Clientes encontram telefone, endereço e horários sem precisar de site
- Você pode receber e responder avaliações de clientes

COMO GERENCIAR:
Acesse business.google.com com sua conta Google para:
- Atualizar horários (especialmente em feriados)
- Adicionar fotos reais do seu negócio
- Responder avaliações (positivas e negativas)

AVALIAÇÕES — COMO PEDIR:
Peça pessoalmente para clientes satisfeitos deixarem uma avaliação.
Uma nota alta no Google atrai novos clientes organicamente.

DICA:
Responda TODAS as avaliações, mesmo as negativas. Isso mostra
profissionalismo e é visto por futuros clientes.
""",
}


# ─── Função principal ──────────────────────────────────────────────────────────

def gerar_material_treinamento(
    entrega_id: str,
    nome_negocio: str,
    servicos_entregues: list,
    nicho: str = "",
    modo: str | None = None,
) -> dict:
    """
    Gera guia de uso e roteiro de vídeo para o cliente.

    Args:
        entrega_id:          ID da entrega
        nome_negocio:        Nome do negócio cliente
        servicos_entregues:  Lista de tipos (e.g. ["atendimento_whatsapp", "agendamento_digital"])
        nicho:               Categoria do negócio (e.g. "barbearia", "clinica")
        modo:                "dry-run" ou "real" — None usa config padrão

    Returns:
        {status, guia, roteiro_video, arquivo_salvo, servicos, gerado_em}
    """
    router = LLMRouter()
    agora = datetime.now().isoformat(timespec="seconds")

    # ── Montar guia por serviço ───────────────────────────────────────────────
    secoes = []
    for servico in servicos_entregues:
        base = _GUIAS_BASE.get(servico)
        if not base:
            continue

        resp = router.redigir({
            "agente": "material_treinamento",
            "tarefa": "personalizar_guia_servico",
            "dados": {
                "servico":       servico,
                "nome_negocio":  nome_negocio,
                "nicho":         nicho,
                "guia_base":     base,
            },
        })

        texto_resp = (
            resp.get("resultado", {}).get("texto", "")
            if isinstance(resp, dict)
            else str(resp)
        )
        if texto_resp.startswith("[DRY-RUN]"):
            texto = (
                base
                .replace("O bot de atendimento", f"O bot do {nome_negocio}")
                .replace("O sistema de agendamento", f"O sistema do {nome_negocio}")
                .replace("Seu perfil no Google foi criado", f"O perfil do {nome_negocio} foi criado")
                .replace("Seu negócio aparece", f"{nome_negocio} aparece")
            )
            secoes.append(texto)
        else:
            secoes.append(texto_resp)

    guia = (
        f"MANUAL DE USO — {nome_negocio.upper()}\n"
        f"Entregue por Vetor em {agora[:10]}\n\n"
        + "\n\n---\n\n".join(secoes)
        if secoes
        else f"MANUAL DE USO — {nome_negocio.upper()}\n\nNenhum serviço registrado."
    )

    # ── Roteiro de vídeo ─────────────────────────────────────────────────────
    servicos_str = ", ".join(servicos_entregues) if servicos_entregues else "sistema digital"
    roteiro_base = (
        f"ROTEIRO — COMO USAR SEU SISTEMA DIGITAL\n\n"
        f"[ABERTURA]\n"
        f"Olá {nome_negocio}! Seus serviços digitais estão prontos.\n"
        f"Neste vídeo vou mostrar tudo que foi configurado e como usar no dia a dia.\n\n"
        f"[O QUE FOI ENTREGUE]\n"
        f"Configuramos para você: {servicos_str}.\n"
        f"Isso significa atendimento automático e mais clientes chegando até você.\n\n"
        f"[DEMONSTRAÇÃO]\n"
        f"[Demonstrar cada funcionalidade com exemplos reais do negócio]\n\n"
        f"[PRÓXIMOS PASSOS]\n"
        f"Teste você mesmo — mande uma mensagem para seu número.\n"
        f"Qualquer dúvida, a equipe Vetor está à disposição.\n"
    )

    resp_rot = router.redigir({
        "agente": "material_treinamento",
        "tarefa": "redigir_roteiro_video",
        "dados": {
            "nome_negocio":       nome_negocio,
            "nicho":              nicho,
            "servicos_entregues": servicos_entregues,
            "roteiro_base":       roteiro_base,
        },
    })
    texto_rot = (
        resp_rot.get("resultado", {}).get("texto", "")
        if isinstance(resp_rot, dict)
        else str(resp_rot)
    )
    roteiro_video = roteiro_base if texto_rot.startswith("[DRY-RUN]") else texto_rot

    # ── Salvar em disco ───────────────────────────────────────────────────────
    arquivo_salvo = None
    try:
        pasta = _PASTA_MATERIAIS / entrega_id
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "guia_uso.txt").write_text(guia, encoding="utf-8")
        (pasta / "roteiro_video.txt").write_text(roteiro_video, encoding="utf-8")
        arquivo_salvo = str(pasta)
        log.info(f"[material_treinamento] {entrega_id} → {arquivo_salvo}")
    except Exception as exc:
        log.warning(f"[material_treinamento] erro ao salvar {entrega_id}: {exc}")

    return {
        "status":        "ok",
        "guia":          guia,
        "roteiro_video": roteiro_video,
        "arquivo_salvo": arquivo_salvo,
        "servicos":      servicos_entregues,
        "gerado_em":     agora,
    }
