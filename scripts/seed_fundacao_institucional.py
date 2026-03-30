"""
scripts/seed_fundacao_institucional.py — Fundação institucional mínima (v0.41)

Popula identidade_empresa.json, guia_comunicacao_empresa.json,
assinaturas_empresa.json e canais_empresa.json com os valores
da fundação institucional mínima da Vetor Operações.

Nome recomendado: Vetor (Vetor Operações Ltda)
Domínio planejado: vetorops.com.br

Uso:
  python scripts/seed_fundacao_institucional.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from core.identidade_empresa import (
    carregar_identidade, salvar_identidade,
    carregar_guia_comunicacao, salvar_guia_comunicacao,
    carregar_assinaturas, salvar_assinaturas,
    carregar_canais, salvar_canais,
)


def seed_identidade():
    dados = carregar_identidade()
    dados.update({
        "id_empresa":               "vetor-operacoes",
        "nome_oficial":             "Vetor Operações Ltda",
        "nome_exibicao":            "Vetor",
        "descricao_curta":          "Operamos sua empresa com agentes de IA — do comercial ao financeiro.",
        "descricao_media": (
            "A Vetor é uma plataforma de operações empresariais movida por agentes de IA "
            "em camadas. Ajuda pequenos e médios negócios a prospectar, vender, atender e "
            "gerir o financeiro sem precisar de grandes equipes. Cada área roda com agentes "
            "especializados, supervisionados por um conselho humano."
        ),
        "proposta_valor_resumida": (
            "Operação completa por IA — para negócios que querem crescer sem crescer o time."
        ),
        "quem_somos": (
            "Somos uma empresa de operações empresariais operada por agentes de IA. "
            "Atuamos lado a lado com pequenos negócios para estruturar e automatizar "
            "as funções que mais consomem tempo: prospecção, comercial, atendimento e financeiro."
        ),
        "o_que_fazemos": (
            "Prospectamos clientes em potencial, preparamos abordagens, gerimos o pipeline "
            "comercial, automatizamos atendimentos e acompanhamos o financeiro — tudo com "
            "agentes especializados que trabalham 24h e reportam ao conselho."
        ),
        "para_quem_fazemos": (
            "Pequenos e médios negócios locais que precisam de operação estruturada mas "
            "não têm equipe para isso: barbearias, restaurantes, clínicas, oficinas, "
            "padarias, salões e similares."
        ),
        "como_nos_diferenciamos": (
            "Não somos uma agência de marketing nem um software genérico. "
            "Somos uma operação completa por IA — cada função tem um agente dedicado, "
            "tudo integrado, auditável e supervisionado pelo dono do negócio."
        ),
        "publico_alvo": (
            "Pequenos e médios negócios locais: barbearias, restaurantes, clínicas, "
            "oficinas, padarias, salões."
        ),
        "linhas_servico": [
            "marketing_presenca_digital",
            "automacao_atendimento",
            "gestao_comercial",
            "gestao_financeira",
        ],
        "cidade_base":     "São Paulo",
        "pais_base":       "Brasil",
        "idioma_padrao":   "pt-BR",
        "ativa":           True,

        # Naming — manter finalistas para referência futura
        "_naming_finalistas": ["Vetor", "Cerne", "Escala"],
        "_naming_recomendado": "Vetor",
        "_naming_dominio_sugerido": "vetorops.com.br",
        "_naming_fundacao_em": datetime.now().isoformat(timespec="seconds"),
    })
    salvar_identidade(dados, origem="seed_fundacao_institucional")
    return dados


def seed_guia():
    dados = carregar_guia_comunicacao()
    dados.update({
        "tom_voz":            "claro, objetivo, consultivo, sem floreio",
        "nivel_formalidade":  "medio",
        "postura_comercial": (
            "Diagnóstica — identificar o problema do negócio antes de qualquer oferta. "
            "Mostrar o gap, deixar o cliente decidir."
        ),
        "postura_consultiva": (
            "Escuta ativa, perguntas antes de propostas. "
            "O objetivo é entender o negócio, não empurrar serviço."
        ),
        "postura_financeira": (
            "Transparente e direta. Valores claros, sem letras miúdas. "
            "Firme quando necessário, sem pressão desnecessária."
        ),
        "postura_cobranca":   "Firme, respeitosa e objetiva. Sem constrangimento, sem desculpas.",
        "estilo_abertura": (
            "Direto ao ponto: apresentar o problema identificado antes de qualquer oferta. "
            "Nunca começar com elogios vazios."
        ),
        "estilo_fechamento": (
            "Ação clara: próximo passo concreto, sem pressão. "
            "Deixar sempre uma saída honesta se o momento não for ideal."
        ),
        "palavras_que_usa":   ["resultado", "simples", "prático", "direto", "operacional",
                               "concreto", "claro", "rápido", "estruturado"],
        "palavras_que_evita": ["incrível", "revolucionário", "disruptivo", "inovador",
                               "transformação", "soluções", "ecossistema", "sinergia",
                               "plataforma omnichannel"],
        "observacoes": (
            "Nunca prometer resultado que depende de terceiros. "
            "Nunca usar linguagem de agência criativa. "
            "Nunca soar como vendedor de software enterprise. "
            "A Vetor fala como um sócio operacional pragmático."
        ),
    })
    salvar_guia_comunicacao(dados, origem="seed_fundacao_institucional")
    return dados


def seed_assinaturas():
    dados = carregar_assinaturas()
    dados.update({
        "nome_remetente_padrao":  "Equipe Vetor",
        "cargo_remetente_padrao": "Operações",

        "assinatura_comercial_texto": (
            "\n---\n"
            "{nome_remetente}\n"
            "Comercial | Vetor Operações\n"
            "{email_comercial}"
        ),
        "assinatura_financeiro_texto": (
            "\n---\n"
            "{nome_remetente}\n"
            "Financeiro | Vetor Operações\n"
            "{email_financeiro}"
        ),
        "assinatura_institucional_texto": (
            "\n---\n"
            "Vetor Operações\n"
            "{descricao_curta}\n"
            "{site_oficial}"
        ),

        # Assinaturas por área — neutras, sem dependência de nome pessoal
        "assinatura_operacoes_texto": (
            "\n---\n"
            "Equipe de Operações\n"
            "Vetor Operações\n"
            "{email_comercial}"
        ),
        "assinatura_relacionamento_texto": (
            "\n---\n"
            "Relacionamento Vetor\n"
            "Vetor Operações\n"
            "{email_comercial}"
        ),
    })
    salvar_assinaturas(dados, origem="seed_fundacao_institucional")
    return dados


def seed_canais():
    dados = carregar_canais()
    dados.update({
        "dominio_oficial_planejado":  "vetorops.com.br",
        "email_principal_planejado":  "contato@vetorops.com.br",
        "email_comercial_planejado":  "comercial@vetorops.com.br",
        "email_financeiro_planejado": "financeiro@vetorops.com.br",
        "email_operacoes_planejado":  "operacoes@vetorops.com.br",
        "site_oficial":               "",
        "instagram_oficial":          "",
        "whatsapp_oficial":           "",

        "status_configuracao_email":  "planejado_nao_configurado",
        "status_configuracao_site":   "nao_definido",
        "status_dominio":             "planejado_nao_registrado",

        "observacoes": (
            "Domínio vetorops.com.br planejado — ainda não registrado. "
            "Emails planejados coerentes com o domínio — ainda não configurados. "
            "Próximo passo: registrar domínio e configurar hospedagem de email "
            "(Zoho Mail, Google Workspace ou similar) antes de ativar modo real no canal email."
        ),
    })
    salvar_canais(dados, origem="seed_fundacao_institucional")
    return dados


def seed_prontidao():
    """Cria dados/prontidao_canais_reais.json avaliando o estado atual."""
    agora = datetime.now().isoformat(timespec="seconds")

    prontidao = {
        "identidade_minima_definida":     True,
        "nome_definido":                  True,
        "nome_oficial":                   "Vetor Operações Ltda",
        "nome_exibicao":                  "Vetor",
        "dominio_planejado":              True,
        "dominio_planejado_valor":        "vetorops.com.br",
        "dominio_registrado":             False,
        "emails_planejados":              True,
        "emails_configurados":            False,
        "assinatura_definida":            True,
        "guia_comunicacao_definido":      True,

        # Critério: todos os planejados = True E nenhum real ainda bloqueado
        "pronto_para_configurar_email_real": True,

        "pendencias": [
            "Registrar domínio vetorops.com.br (registro.br ou registrador de confiança)",
            "Configurar hospedagem de email — sugestões: Zoho Mail (gratuito), "
            "Google Workspace (pago), Brevo/SendGrid (marketing)",
            "Atualizar config_canal_email.json: email_remetente_planejado com email real",
            "Alterar modo=real em config_canal_email.json após SMTP configurado",
            "Testar envio real com execução de canal=email antes de produção",
        ],

        "nao_obrigatorio_para_email_real": [
            "Site oficial",
            "Logo ou identidade visual",
            "Instagram oficial",
            "WhatsApp cadastrado",
        ],

        "nota": (
            "pronto_para_configurar_email_real=True significa que a fundação institucional "
            "está definida e o próximo passo técnico pode ser executado. "
            "Não significa que o email real está funcionando — ainda faltam as etapas "
            "operacionais de registro de domínio e configuração de hospedagem."
        ),

        "atualizado_em": agora,
    }

    arq = config.PASTA_DADOS / "prontidao_canais_reais.json"
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(prontidao, f, ensure_ascii=False, indent=2)
    return prontidao


def main():
    print("=" * 60)
    print("SEED — Fundação Institucional Mínima")
    print("Nome: Vetor Operações Ltda | Domínio: vetorops.com.br")
    print("=" * 60)

    print("\n[1/4] Identidade institucional...")
    ident = seed_identidade()
    print(f"     nome_oficial='{ident['nome_oficial']}' | exibicao='{ident['nome_exibicao']}'")

    print("[2/4] Guia de comunicação...")
    guia = seed_guia()
    print(f"     tom_voz='{guia['tom_voz']}'")

    print("[3/4] Assinaturas institucionais...")
    asin = seed_assinaturas()
    print(f"     remetente_padrao='{asin['nome_remetente_padrao']}'")

    print("[4/4] Canais planejados...")
    canais = seed_canais()
    print(f"     dominio='{canais['dominio_oficial_planejado']}' | "
          f"email_comercial='{canais['email_comercial_planejado']}'")

    print("\n[+] Prontidão para canais reais...")
    pront = seed_prontidao()
    status = "PRONTO" if pront["pronto_para_configurar_email_real"] else "NAO PRONTO"
    print(f"     pronto_para_configurar_email_real={pront['pronto_para_configurar_email_real']} [{status}]")

    print("\nPendências:")
    for p in pront["pendencias"]:
        print(f"  - {p}")

    print("\n" + "=" * 60)
    print("FUNDAÇÃO INSTITUCIONAL CONCLUÍDA")
    print("=" * 60)


if __name__ == "__main__":
    main()
