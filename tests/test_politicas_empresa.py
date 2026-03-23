"""
tests/test_politicas_empresa.py

Valida a camada de políticas operacionais (v0.36).

Testa:
  1. Derivação de políticas por modo (normal / foco_caixa / conservador)
  2. Modulação por diretrizes
  3. Integração com avaliador_fechamento_comercial (score dinâmico)
  4. Integração com agente_financeiro (_deve_escalar_risco)
  5. Limite de prospecção por modo
"""

import sys
import io
import copy
from pathlib import Path

# Encoding para Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.politicas_empresa import (
    derivar_politicas_operacionais,
    aplicar_diretrizes_sobre_politicas,
    _POLITICAS_POR_MODO,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def gov(modo: str, linhas: list = None) -> dict:
    return {
        "modo_empresa": modo,
        "linhas_priorizadas": linhas or [],
        "agentes_pausados": [],
        "areas_pausadas": [],
    }


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


# ─── Testes de derivação por modo ─────────────────────────────────────────────

def test_modo_normal():
    print("\n=== Modo NORMAL ===")
    pol = derivar_politicas_operacionais(gov("normal"))
    check(pol["modo_empresa"] == "normal", "modo_empresa=normal")
    check(pol["fechamento_comercial"]["score_ganho"] == 8, "score_ganho=8")
    check(pol["fechamento_comercial"]["score_pronto"] == 5, "score_pronto=5")
    check("imediata" in pol["financeiro"]["urgencias_escalamento"], "urgencia imediata presente")
    check("alta" in pol["financeiro"]["urgencias_escalamento"], "urgencia alta presente")
    check("media" not in pol["financeiro"]["urgencias_escalamento"], "media NAO escalada no normal")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 0, "sem limite no normal")


def test_modo_foco_caixa():
    print("\n=== Modo FOCO_CAIXA ===")
    pol = derivar_politicas_operacionais(gov("foco_caixa"))
    check(pol["modo_empresa"] == "foco_caixa", "modo_empresa=foco_caixa")
    check("media" in pol["financeiro"]["urgencias_escalamento"],
          "foco_caixa: media deve ser escalada")
    check(pol["fechamento_comercial"]["exigir_escopo_para_ganho"] is True,
          "foco_caixa: exigir_escopo_para_ganho=True")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 5,
          "foco_caixa: limite_novas=5")
    check(pol["marketing"]["rigor_deliberacao"] == "maximo",
          "foco_caixa: rigor_marketing=maximo")
    check(pol["entrega"]["priorizar_desbloqueio"] is True,
          "foco_caixa: priorizar_desbloqueio=True")


def test_modo_conservador():
    print("\n=== Modo CONSERVADOR ===")
    pol = derivar_politicas_operacionais(gov("conservador"))
    check(pol["modo_empresa"] == "conservador", "modo_empresa=conservador")
    check(pol["fechamento_comercial"]["score_ganho"] == 9,
          "conservador: score_ganho=9")
    check(pol["fechamento_comercial"]["score_pronto"] == 6,
          "conservador: score_pronto=6")
    check(pol["fechamento_comercial"]["exigir_escopo_para_ganho"] is True,
          "conservador: exigir_escopo=True")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 10,
          "conservador: limite_novas=10")
    check(pol["marketing"]["rigor_deliberacao"] == "alto",
          "conservador: rigor=alto")


def test_modo_foco_crescimento():
    print("\n=== Modo FOCO_CRESCIMENTO ===")
    pol = derivar_politicas_operacionais(gov("foco_crescimento"))
    check(pol["fechamento_comercial"]["score_ganho"] == 7, "crescimento: score_ganho=7")
    check(pol["fechamento_comercial"]["score_pronto"] == 4, "crescimento: score_pronto=4")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 0, "crescimento: sem limite")
    check("media" not in pol["financeiro"]["urgencias_escalamento"],
          "crescimento: media NAO escalada")


def test_modo_manutencao():
    print("\n=== Modo MANUTENCAO ===")
    pol = derivar_politicas_operacionais(gov("manutencao"))
    check(pol["fechamento_comercial"]["score_ganho"] == 9, "manutencao: score_ganho=9")
    check(pol["fechamento_comercial"]["score_pronto"] == 7, "manutencao: score_pronto=7")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 3, "manutencao: limite_novas=3")
    check(pol["prospeccao"]["ritmo"] == "minimo", "manutencao: ritmo=minimo")


# ─── Testes de modulação por diretrizes ───────────────────────────────────────

def test_diretriz_foco_caixa():
    print("\n=== Diretriz: foco_caixa sobre modo normal ===")
    import copy
    pol = copy.deepcopy(_POLITICAS_POR_MODO["normal"])
    diretrizes = [{"titulo": "Reduzir custo operacional", "descricao": "foco_caixa imediato", "status": "ativa"}]
    pol = aplicar_diretrizes_sobre_politicas(pol, diretrizes, "normal")
    check(pol["fechamento_comercial"]["score_ganho"] == 9, "diretriz foco_caixa: score_ganho elevado para 9")
    check(pol["prospeccao"]["limite_novas_por_ciclo"] == 8, "diretriz foco_caixa: limite_novas=8")


def test_diretriz_crescimento():
    print("\n=== Diretriz: crescimento sobre modo conservador ===")
    import copy
    pol = copy.deepcopy(_POLITICAS_POR_MODO["conservador"])  # score_ganho=9
    diretrizes = [{"titulo": "Acelerar crescimento de clientes", "descricao": "expansao de mercado", "status": "ativa"}]
    pol = aplicar_diretrizes_sobre_politicas(pol, diretrizes, "conservador")
    check(pol["fechamento_comercial"]["score_ganho"] == 8,
          "diretriz crescimento: score_ganho reduzido de 9 para 8")


def test_diretriz_cautela():
    print("\n=== Diretriz: cautela sobre modo foco_crescimento ===")
    import copy
    pol = copy.deepcopy(_POLITICAS_POR_MODO["foco_crescimento"])
    check("media" not in pol["financeiro"]["urgencias_escalamento"], "pre: media nao escalada")
    diretrizes = [{"titulo": "Cautela com novos contratos", "descricao": "risco de credito alto", "status": "ativa"}]
    pol = aplicar_diretrizes_sobre_politicas(pol, diretrizes, "foco_crescimento")
    check("alta" in pol["financeiro"]["urgencias_escalamento"],
          "diretriz cautela: alta adicionada ao financeiro")


# ─── Testes de integração com avaliador_fechamento_comercial ──────────────────

def test_avaliador_score_dinamico():
    print("\n=== Avaliador Fechamento: score dinâmico por modo ===")
    from modulos.comercial.avaliador_fechamento_comercial import decidir_promocao

    # Oportunidade com score=8, linha definida, sem marketing, sem bloqueios
    opp = {"linha_servico_sugerida": "automacao_atendimento", "estagio": "abordagem"}
    sinais = ["pediu_proposta", "respondeu_interesse", "contexto_origem", "ultimo_positivo",
              "escopo_confirmado", "contato_confirmado"]  # score=8
    ins = [{"tipo_insumo": "escopo_confirmado"}, {"tipo_insumo": "contato_confirmado"}]

    # Modo normal: score_ganho=8 → GANHO
    d_normal = decidir_promocao(opp, 8, sinais, ins, score_ganho=8, score_pronto=5)
    check(d_normal["acao"] == "ganho", f"normal: score=8,ganho=8 → ganho (got {d_normal['acao']})")

    # Modo conservador: score_ganho=9 → score=8 não é ganho → PRONTO
    d_conserv = decidir_promocao(opp, 8, sinais, ins, score_ganho=9, score_pronto=6)
    check(d_conserv["acao"] == "pronto_para_entrega",
          f"conservador: score=8,ganho=9 → pronto (got {d_conserv['acao']})")

    # Modo conservador com exigir_escopo=False (escopo presente): score=9 → GANHO
    d_conserv2 = decidir_promocao(opp, 9, sinais + ["objetivo_confirmado"], ins,
                                   score_ganho=9, score_pronto=6, exigir_escopo=False)
    check(d_conserv2["acao"] == "ganho",
          f"conservador sem exigir_escopo: score=9 → ganho (got {d_conserv2['acao']})")

    # Modo conservador com exigir_escopo=True mas SEM escopo → ESCALAR
    ins_sem_escopo = [{"tipo_insumo": "contato_confirmado"}]
    d_escalar = decidir_promocao(opp, 9, sinais, ins_sem_escopo,
                                  score_ganho=9, score_pronto=6, exigir_escopo=True)
    check(d_escalar["acao"] == "escalar",
          f"conservador exigir_escopo=True sem escopo: → escalar (got {d_escalar['acao']})")

    print("  Case financeiro (modo foco_caixa → score_ganho=8, exigir_escopo=True):")
    d_foco = decidir_promocao(opp, 8, sinais, ins_sem_escopo,
                               score_ganho=8, score_pronto=5, exigir_escopo=True)
    check(d_foco["acao"] == "escalar",
          f"foco_caixa exigir_escopo: score=8 sem escopo → escalar (got {d_foco['acao']})")


# ─── Testes de integração com agente_financeiro ───────────────────────────────

def test_financeiro_urgencias_dinamicas():
    print("\n=== Financeiro: urgências dinâmicas por modo ===")
    from agentes.financeiro.agente_financeiro import _deve_escalar_risco

    risco_media = {"urgencia": "media", "tipo": "fluxo_irregular"}
    risco_alta  = {"urgencia": "alta",  "tipo": "vencido_sem_resolucao"}
    posicao = {"risco_caixa": False, "saldo_atual_estimado": 50000.0}
    previsao = {"janelas": {"7_dias": {"houve_buraco_de_caixa": False}}}

    # Modo normal: urgencias={imediata, alta} → media NÃO escala
    urg_normal = {"imediata", "alta"}
    check(not _deve_escalar_risco(risco_media, posicao, previsao, urg_normal),
          "normal: media NAO escalada")
    check(_deve_escalar_risco(risco_alta, posicao, previsao, urg_normal),
          "normal: alta escalada")

    # Modo foco_caixa: urgencias={imediata, alta, media} → media ESCALA
    urg_foco = {"imediata", "alta", "media"}
    check(_deve_escalar_risco(risco_media, posicao, previsao, urg_foco),
          "foco_caixa: media ESCALADA")
    print("  Case: risco urgencia=media → NAO escalado em normal, escalado em foco_caixa [OK]")


# ─── Testes de limite de prospecção ───────────────────────────────────────────

def test_prospeccao_limite():
    print("\n=== Prospecção: limite por ciclo por modo ===")
    pol_normal = derivar_politicas_operacionais(gov("normal"))
    pol_manut  = derivar_politicas_operacionais(gov("manutencao"))
    pol_foco   = derivar_politicas_operacionais(gov("foco_caixa"))

    check(pol_normal["prospeccao"]["limite_novas_por_ciclo"] == 0, "normal: sem limite (0)")
    check(pol_manut["prospeccao"]["limite_novas_por_ciclo"] == 3, "manutencao: limite=3")
    check(pol_foco["prospeccao"]["limite_novas_por_ciclo"] == 5, "foco_caixa: limite=5")

    print("  Diferenca entre modos:")
    print(f"    normal: {pol_normal['prospeccao']['limite_novas_por_ciclo']} (sem limite)")
    print(f"    foco_caixa: {pol_foco['prospeccao']['limite_novas_por_ciclo']}")
    print(f"    manutencao: {pol_manut['prospeccao']['limite_novas_por_ciclo']}")


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        test_modo_normal,
        test_modo_foco_caixa,
        test_modo_conservador,
        test_modo_foco_crescimento,
        test_modo_manutencao,
        test_diretriz_foco_caixa,
        test_diretriz_crescimento,
        test_diretriz_cautela,
        test_avaliador_score_dinamico,
        test_financeiro_urgencias_dinamicas,
        test_prospeccao_limite,
    ]

    falhos = []
    for t in testes:
        try:
            t()
        except AssertionError as e:
            falhos.append(str(e))

    print("\n" + "=" * 60)
    print(f"Resultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
