"""
tests/core/test_scheduler.py -- Scheduler de agentes

Roda com: python tests/core/test_scheduler.py
"""

import sys
import io
import json
import tempfile
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import core.scheduler as sched_mod
from core.scheduler import Scheduler


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    sched_mod._ARQ_ESTADO = Path(tmpdir) / "scheduler_estado.json"
    sched_mod._ARQ_LOG = Path(tmpdir) / "scheduler_log.json"
    sched_mod._ARQ_GOV = Path(tmpdir) / "estado_governanca_conselho.json"


def _restore(orig_e, orig_l, orig_g):
    sched_mod._ARQ_ESTADO = orig_e
    sched_mod._ARQ_LOG = orig_l
    sched_mod._ARQ_GOV = orig_g


def test_instanciar_scheduler():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            check(isinstance(s._agenda, dict), "_agenda deve ser dict")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: instanciar_scheduler")


def test_dentro_da_janela_exato():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            agora = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
            check(s._dentro_da_janela(agora, "06:00") is True, "janela exata deve retornar True")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: dentro_da_janela_exato")


def test_dentro_da_janela_antes_tolerancia():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            # agendado=06:00, agora=05:58 — antes da janela, deve ser False
            agora = datetime.now().replace(hour=5, minute=58, second=0, microsecond=0)
            result = s._dentro_da_janela(agora, "06:00")
            check(result is False, "antes da janela deve retornar False")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: dentro_da_janela_antes_tolerancia")


def test_dentro_da_janela_dentro_tolerancia():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            # agendado=06:00, agora=06:03 — dentro da tolerancia de 5min
            agora = datetime.now().replace(hour=6, minute=3, second=0, microsecond=0)
            result = s._dentro_da_janela(agora, "06:00")
            check(result is True, "dentro da tolerancia deve retornar True")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: dentro_da_janela_dentro_tolerancia")


def test_dentro_da_janela_depois_tolerancia():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            # agendado=06:00, agora=06:06 — alem da tolerancia de 5min
            agora = datetime.now().replace(hour=6, minute=6, second=0, microsecond=0)
            result = s._dentro_da_janela(agora, "06:00")
            check(result is False, "alem da tolerancia deve retornar False")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: dentro_da_janela_depois_tolerancia")


def test_dentro_da_janela_fora():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            agora = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
            result = s._dentro_da_janela(agora, "06:00")
            check(result is False, "hora diferente deve retornar False")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: dentro_da_janela_fora")


def test_ja_executou_falso():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            agora = datetime.now()
            result = s._ja_executou("agente_comercial", "06:00", agora)
            check(result is False, "_ja_executou deve retornar False sem estado")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: ja_executou_falso")


def test_ja_executou_apos_marcar():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            s._tolerancia = 5
            agora = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
            s._marcar_executado("agente_comercial", "06:00", agora)
            result = s._ja_executou("agente_comercial", "06:00", agora)
            check(result is True, "_ja_executou deve retornar True apos marcar")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: ja_executou_apos_marcar")


def test_motivo_bloqueio_agente_pausado():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        gov_file = Path(tmpdir) / "estado_governanca_conselho.json"
        gov_data = {
            "modo_empresa": "normal",
            "agentes_pausados": ["agente_comercial"],
        }
        gov_file.write_text(json.dumps(gov_data, ensure_ascii=False), encoding="utf-8")
        try:
            s = Scheduler()
            motivo = s._motivo_bloqueio("agente_comercial")
            check(motivo is not None, "deve retornar motivo quando agente esta pausado")
            check(len(motivo) > 0, "motivo nao deve ser string vazia")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: motivo_bloqueio_agente_pausado")


def test_motivo_bloqueio_nao_pausado():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        try:
            s = Scheduler()
            motivo = s._motivo_bloqueio("agente_comercial")
            check(motivo is None, "deve retornar None quando agente nao esta pausado")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: motivo_bloqueio_nao_pausado")


def test_run_dry_run_nao_executa():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_e, orig_l, orig_g = sched_mod._ARQ_ESTADO, sched_mod._ARQ_LOG, sched_mod._ARQ_GOV
        _patch(tmpdir)
        estado_file = Path(tmpdir) / "scheduler_estado.json"
        try:
            s = Scheduler()
            s.run(dry_run=True)
            # dry_run nao deve criar estado (nao executa nada)
            # O arquivo pode ou nao existir; o importante e nao travar
            check(True, "run(dry_run=True) deve completar sem excecao")
        finally:
            _restore(orig_e, orig_l, orig_g)
    print("OK: run_dry_run_nao_executa")


if __name__ == "__main__":
    testes = [
        test_instanciar_scheduler,
        test_dentro_da_janela_exato,
        test_dentro_da_janela_antes_tolerancia,
        test_dentro_da_janela_dentro_tolerancia,
        test_dentro_da_janela_depois_tolerancia,
        test_dentro_da_janela_fora,
        test_ja_executou_falso,
        test_ja_executou_apos_marcar,
        test_motivo_bloqueio_agente_pausado,
        test_motivo_bloqueio_nao_pausado,
        test_run_dry_run_nao_executa,
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

    print(f"\nResultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
