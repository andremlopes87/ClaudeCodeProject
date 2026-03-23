"""
tests/test_confiabilidade_empresa.py

Valida a camada de confiabilidade operacional (v0.37).

Testa:
  1. Ciclo normal: lock criado, checkpoints registrados, saúde calculada, lock liberado
  2. Lock stale: detectado, incidente criado, recovery preparado
  3. Falha de etapa: incidente criado, saúde rebaixada
  4. Idempotência: reprocessamento bloqueado
  5. Score de saúde por cenário
"""

import sys
import io
import json
import time
import shutil
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from core.confiabilidade_empresa import (
    adquirir_lock_ciclo,
    liberar_lock_ciclo,
    detectar_lock_stale,
    registrar_checkpoint_etapa,
    finalizar_checkpoint_etapa,
    registrar_incidente_operacional,
    calcular_saude_empresa,
    preparar_recovery_simples,
    marcar_recovery_executado,
    etapa_ja_concluida_neste_ciclo,
    contar_incidentes_abertos,
    _ARQ_LOCK,
    _ARQ_CHECKPOINTS,
    _ARQ_INCIDENTES,
    _ARQ_SAUDE,
    _ARQ_RECOVERY,
    _limpar_lock,
    _salvar,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _limpar_estado_teste():
    """Limpa arquivos de confiabilidade para testes isolados."""
    for arq in [_ARQ_LOCK, _ARQ_CHECKPOINTS, _ARQ_INCIDENTES, _ARQ_SAUDE, _ARQ_RECOVERY]:
        if arq.exists():
            arq.unlink()


# ─── Teste 1: Ciclo normal ────────────────────────────────────────────────────

def test_ciclo_normal():
    print("\n=== Teste 1: Ciclo Normal ===")
    _limpar_estado_teste()

    ciclo_id = "ciclo_teste_001"

    # Adquirir lock
    ok = adquirir_lock_ciclo(ciclo_id)
    check(ok, "lock adquirido com sucesso")

    lock = json.loads(_ARQ_LOCK.read_text(encoding="utf-8"))
    check(lock["lock_ativo"] is True, "lock_ativo=True no arquivo")
    check(lock["ciclo_id"] == ciclo_id, f"ciclo_id correto no lock")
    print(f"    Lock: ciclo_id={lock['ciclo_id']} | pid={lock['pid_ou_identificador']}")

    # Tentar adquirir segundo lock (deve falhar)
    ok2 = adquirir_lock_ciclo("ciclo_outro")
    check(not ok2, "segundo lock rejeitado (exclusividade garantida)")

    # Registrar checkpoints
    for i, nome in enumerate(["agente_financeiro", "agente_comercial", "agente_secretario"], 1):
        registrar_checkpoint_etapa(ciclo_id, nome, f"{i}/3")
        finalizar_checkpoint_etapa(ciclo_id, nome, f"{i}/3", "concluida",
                                    resumo={"itens": i * 10})
        print(f"    Checkpoint: {nome} → concluida")

    chk = json.loads(_ARQ_CHECKPOINTS.read_text(encoding="utf-8"))
    check(chk["ciclo_id"] == ciclo_id, "checkpoints com ciclo_id correto")
    check(len(chk["etapas"]) == 3, f"3 etapas registradas (got {len(chk['etapas'])})")
    check(all(e["status"] == "concluida" for e in chk["etapas"]), "todas etapas concluidas")

    # Liberar lock
    liberar_lock_ciclo(ciclo_id)
    lock_pos = json.loads(_ARQ_LOCK.read_text(encoding="utf-8"))
    check(lock_pos.get("lock_ativo") is False, "lock liberado (lock_ativo=False)")
    print(f"    Lock liberado: lock_ativo={lock_pos['lock_ativo']}")

    # Calcular saúde (ciclo OK, sem incidentes)
    saude = calcular_saude_empresa()
    check(saude["score_saude"] > 0, "score_saude > 0")
    print(f"    Saude: status={saude['status_geral']} | score={saude['score_saude']}")


# ─── Teste 2: Lock stale ──────────────────────────────────────────────────────

def test_lock_stale():
    print("\n=== Teste 2: Lock Stale ===")
    _limpar_estado_teste()

    # Simular lock stale: criar lock com timestamp 40 minutos atrás
    ts_antigo = (datetime.now() - timedelta(minutes=40)).isoformat(timespec="seconds")
    lock_stale = {
        "lock_ativo": True,
        "ciclo_id": "ciclo_antigo_stale",
        "iniciado_em": ts_antigo,
        "hostname_ou_origem": "servidor_anterior",
        "pid_ou_identificador": 99999,
        "etapa_atual": "agente_financeiro[3/13]",
        "atualizado_em": ts_antigo,
    }
    _salvar(_ARQ_LOCK, lock_stale)
    print(f"    Lock stale simulado: iniciado={ts_antigo}")

    # Detectar stale
    stale = detectar_lock_stale()
    check(stale is not None, "lock stale detectado")
    check(stale["ciclo_id"] == "ciclo_antigo_stale", "ciclo_id do stale correto")

    # Novo ciclo deve limpar o stale automaticamente
    ciclo_id_novo = "ciclo_recuperacao_001"
    ok = adquirir_lock_ciclo(ciclo_id_novo)
    check(ok, "lock adquirido após limpeza de stale")

    # Verificar incidente criado
    incidentes = json.loads(_ARQ_INCIDENTES.read_text(encoding="utf-8"))
    inc_stale = [i for i in incidentes if i["tipo_incidente"] == "lock_stale"]
    check(len(inc_stale) > 0, "incidente lock_stale criado")
    check(inc_stale[0]["severidade"] == "alta", "severidade=alta no incidente stale")
    print(f"    Incidente: {inc_stale[0]['titulo'][:60]}")

    # Verificar recovery preparado
    recovery = json.loads(_ARQ_RECOVERY.read_text(encoding="utf-8"))
    check(recovery["ultimo_ciclo_interrompido"] == "ciclo_antigo_stale", "recovery com ciclo correto")
    check(recovery["etapa_interrompida"] == "agente_financeiro[3/13]", "etapa interrompida registrada")
    check(recovery["status"] == "pendente", "recovery status=pendente")
    print(f"    Recovery: ciclo={recovery['ultimo_ciclo_interrompido']} | etapa={recovery['etapa_interrompida']}")

    liberar_lock_ciclo(ciclo_id_novo)


# ─── Teste 3: Falha de etapa + incidente + saúde rebaixada ───────────────────

def test_falha_etapa_e_saude():
    print("\n=== Teste 3: Falha de Etapa + Saúde ===")
    _limpar_estado_teste()

    ciclo_id = "ciclo_com_falha_001"
    adquirir_lock_ciclo(ciclo_id)

    # Registrar etapa que falhou
    registrar_checkpoint_etapa(ciclo_id, "agente_financeiro", "1/3")
    finalizar_checkpoint_etapa(ciclo_id, "agente_financeiro", "1/3", "falhou",
                                erro="ConnectionError: timeout na pipeline financeira")

    # Registrar incidente de falha
    inc = registrar_incidente_operacional(
        tipo_incidente="falha_etapa",
        severidade="alta",
        area="financeiro",
        agente="agente_financeiro",
        titulo="Falha no agente_financeiro [1/3]",
        descricao="ConnectionError: timeout na pipeline financeira",
        ciclo_id=ciclo_id,
        referencia_id="1/3",
        acao_tomada="ciclo_continuou_sem_agente",
    )
    check(inc["tipo_incidente"] == "falha_etapa", "incidente de falha criado")
    check(inc["severidade"] == "alta", "severidade=alta")
    print(f"    Incidente criado: {inc['id']} | {inc['titulo'][:50]}")

    # Registrar segunda etapa com sucesso
    registrar_checkpoint_etapa(ciclo_id, "agente_comercial", "2/3")
    finalizar_checkpoint_etapa(ciclo_id, "agente_comercial", "2/3", "concluida")

    # Liberar lock
    liberar_lock_ciclo(ciclo_id)

    # Calcular saúde — deve ser rebaixada por incidente alta
    saude = calcular_saude_empresa()
    check(saude["score_saude"] < 100, f"score rebaixado por incidente (score={saude['score_saude']})")
    check(saude["incidentes_abertos"]["alta"] >= 1, "incidente alta contado")
    check(saude["status_geral"] in ("atencao", "degradada", "critica"),
          f"status não é saudavel (got {saude['status_geral']})")
    print(f"    Saude rebaixada: score={saude['score_saude']} | status={saude['status_geral']}")
    print(f"    Alertas: {saude['alertas'][:2]}")

    incid = contar_incidentes_abertos()
    check(incid["total"] >= 1, "pelo menos 1 incidente aberto contado")
    print(f"    Incidentes abertos: {incid}")


# ─── Teste 4: Idempotência (reprocessamento bloqueado) ───────────────────────

def test_idempotencia():
    print("\n=== Teste 4: Idempotência ===")
    _limpar_estado_teste()

    ciclo_id = "ciclo_idemp_001"
    adquirir_lock_ciclo(ciclo_id)

    # Registrar e concluir etapa
    registrar_checkpoint_etapa(ciclo_id, "agente_comercial", "4/13")
    finalizar_checkpoint_etapa(ciclo_id, "agente_comercial", "4/13", "concluida")

    # Verificar que etapa já foi concluída
    ja = etapa_ja_concluida_neste_ciclo(ciclo_id, "agente_comercial", "4/13")
    check(ja, "etapa_ja_concluida_neste_ciclo retorna True")
    print(f"    etapa_ja_concluida_neste_ciclo: {ja}")

    # Etapa diferente não está concluída
    nao = etapa_ja_concluida_neste_ciclo(ciclo_id, "agente_financeiro", "1/13")
    check(not nao, "etapa diferente NÃO marcada como concluída")

    # Outro ciclo: não deve ver como concluída
    outro_ciclo = etapa_ja_concluida_neste_ciclo("outro_ciclo_id", "agente_comercial", "4/13")
    check(not outro_ciclo, "outro ciclo: etapa NÃO marcada como concluída")

    liberar_lock_ciclo(ciclo_id)


# ─── Teste 5: Score de saúde por cenário ────────────────────────────────────

def test_score_saude_cenarios():
    print("\n=== Teste 5: Score de Saúde por Cenário ===")
    _limpar_estado_teste()

    # Cenário A: empresa saudável (sem incidentes, sem erros)
    saude_a = calcular_saude_empresa()
    print(f"    Sem incidentes: score={saude_a['score_saude']} | status={saude_a['status_geral']}")

    # Cenário B: adicionar incidente crítico
    registrar_incidente_operacional(
        tipo_incidente="estado_corrompido", severidade="critica", area="operacao",
        agente="orquestrador", titulo="Estado corrompido no ciclo X",
        descricao="Arquivo estado_empresa.json corrompido",
    )
    saude_b = calcular_saude_empresa()
    check(saude_b["score_saude"] < saude_a["score_saude"],
          f"incidente critico rebaixou score ({saude_a['score_saude']} → {saude_b['score_saude']})")
    print(f"    Com incidente critico: score={saude_b['score_saude']} | status={saude_b['status_geral']}")

    # Cenário C: adicionar mais incidentes altos
    for i in range(2):
        registrar_incidente_operacional(
            tipo_incidente="falha_etapa", severidade="alta", area="comercial",
            agente=f"agente_{i}", titulo=f"Falha agente {i}",
            descricao="Erro simulado para teste",
        )
    saude_c = calcular_saude_empresa()
    check(saude_c["score_saude"] <= saude_b["score_saude"],
          f"mais incidentes reduziram score ({saude_b['score_saude']} → {saude_c['score_saude']})")
    print(f"    Com 3 incidentes (1 critico + 2 altos): score={saude_c['score_saude']} | status={saude_c['status_geral']}")

    check(saude_c["incidentes_abertos"]["total"] == 3, "3 incidentes abertos contados")
    check(saude_c["incidentes_abertos"]["critica"] == 1, "1 crítico contado")
    check(saude_c["incidentes_abertos"]["alta"] == 2, "2 altos contados")

    # Recovery
    preparar_recovery_simples("ciclo_stale_cenario", "agente_financeiro[2/13]", "teste_score")
    saude_c2 = calcular_saude_empresa()
    check(saude_c2["ultimo_recovery"] is not None, "ultimo_recovery aparece na saude")
    print(f"    ultimo_recovery: {saude_c2['ultimo_recovery']}")


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        test_ciclo_normal,
        test_lock_stale,
        test_falha_etapa_e_saude,
        test_idempotencia,
        test_score_saude_cenarios,
    ]

    falhos = []
    for t in testes:
        try:
            t()
        except AssertionError as e:
            falhos.append(f"{t.__name__}: {e}")
        except Exception as e:
            falhos.append(f"{t.__name__}: ERRO INESPERADO: {e}")
            import traceback; traceback.print_exc()
        finally:
            # Garantir lock limpo entre testes
            _limpar_lock()

    print("\n" + "=" * 60)
    print(f"Resultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
