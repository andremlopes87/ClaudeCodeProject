"""
tests/test_canal_email_assistido.py

Valida o canal de email assistido (v0.40).

Testa:
  1. validar_identidade_para_email: identidade válida → ok
  2. validar_identidade_para_email: identidade inativa → bloqueado
  3. validar_identidade_para_email: sem email_remetente → bloqueado
  4. montar_assunto_email: templates por abordagem
  5. montar_corpo_email_texto: corpo exploratória com assinatura
  6. preparar_email_para_execucao: email preparado completo
  7. preparar_email_para_execucao: bloqueado sem email_destino
  8. integrador_email.executar: canal desativado → sem preparação
  9. integrador_email.executar: com execuções elegíveis → emails preparados
  10. integrador_email.respeitar_governanca_e_politicas: pausa correto
"""

import sys
import io
import json
from pathlib import Path
from copy import deepcopy

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
from conectores.canal_email_assistido import (
    validar_identidade_para_email,
    montar_assunto_email,
    montar_corpo_email_texto,
    preparar_email_para_execucao,
    registrar_historico_email,
)
from core.integrador_email import (
    carregar_execucoes_email_elegiveis,
    carregar_config_canal_email,
    atualizar_estado_canal_email,
    respeitar_governanca_e_politicas,
    executar as executar_integrador_email,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

_IDENTIDADE_OK = {
    "ativa": True,
    "nome_oficial": "PresençaDigital Soluções Ltda",
    "nome_exibicao": "PresençaDigital",
    "descricao_curta": "Presença digital para pequenos negócios.",
}

_CANAIS_OK = {
    "email_comercial_planejado": "comercial@presencadigital.com.br",
    "email_principal_planejado": "contato@presencadigital.com.br",
    "whatsapp_oficial": "+5511999990000",
}

_CONFIG_CANAL_OK = {
    "modo": "assistido",
    "habilitado": True,
    "nome_remetente": "Equipe PresençaDigital",
    "email_remetente_planejado": "comercial@presencadigital.com.br",
    "assunto_prefixo": "",
    "assinatura_tipo_padrao": "comercial",
    "usar_html": False,
    "exigir_email_destino": True,
    "limite_preparos_por_ciclo": 50,
}

_GUIA_OK = {
    "estilo_abertura": "direto ao ponto",
    "estilo_fechamento": "ação clara",
    "tom_voz": "consultivo",
}

_ASSINATURAS_OK = {
    "nome_remetente_padrao": "Equipe PresençaDigital",
    "cargo_remetente_padrao": "Consultoria Digital",
}

def _execucao_email(
    exec_id="exec_001",
    contraparte="Barbearia do João",
    oportunidade_id="op_001",
    abordagem="exploratoria",
    email_destino="joao@barbearia.com",
):
    return {
        "id": exec_id,
        "oportunidade_id": oportunidade_id,
        "contraparte": contraparte,
        "canal": "email",
        "abordagem_inicial_tipo": abordagem,
        "linha_servico_sugerida": "marketing_presenca_digital",
        "status": "aguardando_integracao_canal",
        "pronto_para_integracao": True,
        "payload_execucao": {
            "canal": "email",
            "contato_destino": email_destino,
            "contexto_oportunidade": {
                "contraparte": contraparte,
                "cidade": "São Paulo",
                "categoria": "barbearia",
            },
        },
    }


# ─── Teste 1: identidade válida ───────────────────────────────────────────────

def test_validar_identidade_ok():
    print("\n=== Teste 1: Validar identidade válida ===")
    ok, motivo = validar_identidade_para_email(_IDENTIDADE_OK, _CANAIS_OK, _CONFIG_CANAL_OK)
    check(ok, "identidade válida retorna ok=True")
    check(motivo == "", "motivo vazio quando ok")
    print(f"    ok={ok} | motivo='{motivo}'")


# ─── Teste 2: identidade inativa ──────────────────────────────────────────────

def test_validar_identidade_inativa():
    print("\n=== Teste 2: Identidade inativa bloqueada ===")
    ident = dict(_IDENTIDADE_OK, ativa=False)
    ok, motivo = validar_identidade_para_email(ident, _CANAIS_OK, _CONFIG_CANAL_OK)
    check(not ok, "identidade inativa retorna ok=False")
    check("ativa" in motivo, f"motivo menciona 'ativa': {motivo}")
    print(f"    ok={ok} | motivo='{motivo}'")


# ─── Teste 3: sem email_remetente ─────────────────────────────────────────────

def test_validar_sem_email_remetente():
    print("\n=== Teste 3: Sem email_remetente bloqueado ===")
    canais_vazios = {"whatsapp_oficial": "+5511999990000"}
    config_sem_rem = dict(_CONFIG_CANAL_OK, email_remetente_planejado="")
    ok, motivo = validar_identidade_para_email(_IDENTIDADE_OK, canais_vazios, config_sem_rem)
    check(not ok, "sem remetente retorna ok=False")
    check("email_remetente" in motivo.lower() or "email_comercial" in motivo.lower(),
          f"motivo menciona email: {motivo}")
    print(f"    ok={ok} | motivo='{motivo}'")


# ─── Teste 4: assuntos por abordagem ─────────────────────────────────────────

def test_montar_assunto():
    print("\n=== Teste 4: Assuntos por abordagem ===")
    abordagens = [
        ("exploratoria", "aparecer melhor no Google"),
        ("consultiva_diagnostica", "Diagnóstico"),
        ("followup_sem_resposta", "Seguimento"),
        ("reengajamento", "Retomando"),
        ("padrao", "Oportunidade"),
    ]
    for abordagem, esperado in abordagens:
        exec_ = _execucao_email(abordagem=abordagem)
        payload = exec_["payload_execucao"]
        assunto = montar_assunto_email(exec_, payload, _IDENTIDADE_OK, _CONFIG_CANAL_OK)
        check(bool(assunto), f"assunto não vazio para abordagem={abordagem}")
        check(esperado.lower() in assunto.lower() or "Barbearia" in assunto,
              f"assunto contém '{esperado}' ou contraparte: got '{assunto}'")
        print(f"    [{abordagem}] → '{assunto}'")

    # Com prefixo
    cfg_prefixo = dict(_CONFIG_CANAL_OK, assunto_prefixo="TESTE")
    exec_ = _execucao_email(abordagem="exploratoria")
    payload = exec_["payload_execucao"]
    assunto = montar_assunto_email(exec_, payload, _IDENTIDADE_OK, cfg_prefixo)
    check("[TESTE]" in assunto, f"prefixo no assunto: '{assunto}'")
    print(f"    Com prefixo: '{assunto}'")


# ─── Teste 5: corpo com assinatura ────────────────────────────────────────────

def test_montar_corpo():
    print("\n=== Teste 5: Corpo email com assinatura ===")
    exec_ = _execucao_email(abordagem="exploratoria")
    payload = exec_["payload_execucao"]
    corpo = montar_corpo_email_texto(
        exec_, payload, _IDENTIDADE_OK, _GUIA_OK, _ASSINATURAS_OK, _CANAIS_OK, _CONFIG_CANAL_OK
    )
    check(bool(corpo), "corpo não vazio")
    check("Barbearia do João" in corpo or "Olá" in corpo, "contraparte ou saudação no corpo")
    check("PresençaDigital" in corpo, "nome empresa na assinatura")
    check("---" in corpo, "separador de assinatura presente")
    print(f"    Corpo (primeiros 200 chars):\n    {corpo[:200]!r}")


# ─── Teste 6: email preparado completo ───────────────────────────────────────

def test_preparar_email_ok():
    print("\n=== Teste 6: Email preparado completo ===")
    exec_ = _execucao_email()
    email = preparar_email_para_execucao(
        exec_, _IDENTIDADE_OK, _GUIA_OK, _ASSINATURAS_OK, _CANAIS_OK, _CONFIG_CANAL_OK
    )
    check(email["status"] == "preparado", f"status='preparado' (got {email['status']})")
    check(email["pronto_para_envio"] is True, "pronto_para_envio=True")
    check(email["simulado"] is True, "simulado=True sempre")
    check(bool(email["assunto"]), "assunto preenchido")
    check(bool(email["corpo_texto"]), "corpo_texto preenchido")
    check(email["email_destino"] == "joao@barbearia.com", "email_destino correto")
    check(email["motivo_bloqueio"] is None, "motivo_bloqueio=None quando ok")
    check(email["modo_canal"] == "assistido", "modo_canal=assistido")
    print(f"    id={email['id']} | assunto='{email['assunto'][:50]}'")
    print(f"    destino={email['email_destino']} | simulado={email['simulado']}")


# ─── Teste 7: bloqueado sem email_destino ────────────────────────────────────

def test_preparar_email_bloqueado():
    print("\n=== Teste 7: Email bloqueado sem destino ===")
    exec_ = _execucao_email(email_destino="")
    exec_["payload_execucao"]["contato_destino"] = ""
    email = preparar_email_para_execucao(
        exec_, _IDENTIDADE_OK, _GUIA_OK, _ASSINATURAS_OK, _CANAIS_OK, _CONFIG_CANAL_OK
    )
    check(email["status"] == "bloqueado", f"status='bloqueado' (got {email['status']})")
    check(email["pronto_para_envio"] is False, "pronto_para_envio=False")
    check(email["simulado"] is True, "simulado=True mesmo bloqueado")
    check(bool(email["motivo_bloqueio"]), f"motivo_bloqueio preenchido: {email['motivo_bloqueio']}")
    print(f"    status={email['status']} | motivo={email['motivo_bloqueio']}")


# ─── Teste 8: integrador — canal desativado ───────────────────────────────────

def test_integrador_canal_desativado():
    print("\n=== Teste 8: Integrador com canal desativado ===")
    # Garantir que config_canal_email.json existe com modo=desativado
    arq_config = config.PASTA_DADOS / "config_canal_email.json"
    cfg_backup = None
    if arq_config.exists():
        with open(arq_config, "r", encoding="utf-8") as f:
            cfg_backup = json.load(f)

    cfg_desativado = {
        "modo": "desativado", "habilitado": False,
        "email_remetente_planejado": "", "limite_preparos_por_ciclo": 10,
    }
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(arq_config, "w", encoding="utf-8") as f:
        json.dump(cfg_desativado, f, ensure_ascii=False, indent=2)

    try:
        resultado = executar_integrador_email()
        check(resultado["preparados"] == 0, f"0 preparados com canal desativado (got {resultado['preparados']})")
        check(resultado["modo"] == "desativado", f"modo=desativado (got {resultado['modo']})")
        print(f"    preparados={resultado['preparados']} | modo={resultado['modo']}")
    finally:
        # Restaurar config
        if cfg_backup:
            with open(arq_config, "w", encoding="utf-8") as f:
                json.dump(cfg_backup, f, ensure_ascii=False, indent=2)
        else:
            arq_config.unlink(missing_ok=True)


# ─── Teste 9: integrador com execuções elegíveis ──────────────────────────────

def test_integrador_com_execucoes():
    print("\n=== Teste 9: Integrador prepara emails elegíveis ===")

    arq_config    = config.PASTA_DADOS / "config_canal_email.json"
    arq_fila_exec = config.PASTA_DADOS / "fila_execucao_contato.json"
    arq_fila_eml  = config.PASTA_DADOS / "fila_envio_email.json"
    arq_historico = config.PASTA_DADOS / "historico_email.json"
    arq_estado    = config.PASTA_DADOS / "estado_canal_email.json"

    # Guardar backups
    def _ler(arq):
        return json.loads(arq.read_text("utf-8")) if arq.exists() else None

    bkp_config    = _ler(arq_config)
    bkp_fila_exec = _ler(arq_fila_exec)
    bkp_fila_eml  = _ler(arq_fila_eml)
    bkp_hist      = _ler(arq_historico)
    bkp_estado    = _ler(arq_estado)

    try:
        # Config: canal assistido habilitado
        cfg = dict(_CONFIG_CANAL_OK)
        with open(arq_config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        # Identidade mínima via identidade_empresa
        from core.identidade_empresa import (
            carregar_identidade, salvar_identidade,
            carregar_canais, salvar_canais,
        )
        ident = carregar_identidade()
        ident.update({"nome_oficial": "PresençaDigital Ltda", "nome_exibicao": "PresençaDigital", "ativa": True})
        salvar_identidade(ident, origem="teste_email")
        canais = carregar_canais()
        canais["email_comercial_planejado"] = "comercial@presencadigital.com.br"
        salvar_canais(canais, origem="teste_email")

        # Fila de execuções com 2 elegíveis (email) + 1 não elegível (whatsapp)
        exec1 = _execucao_email("exec_email_001", "Padaria Central", "op_001", "exploratoria", "padaria@central.com")
        exec2 = _execucao_email("exec_email_002", "Restaurante Silva", "op_002", "consultiva_diagnostica", "silva@rest.com")
        exec_wa = {
            "id": "exec_wa_001",
            "canal": "whatsapp",
            "status": "aguardando_integracao_canal",
            "pronto_para_integracao": True,
            "contraparte": "Oficina Boa",
            "oportunidade_id": "op_003",
            "payload_execucao": {},
        }
        # Limpar fila anterior + escrever novas execuções
        with open(arq_fila_exec, "w", encoding="utf-8") as f:
            json.dump([exec1, exec2, exec_wa], f, ensure_ascii=False, indent=2)

        # Limpar fila email anterior
        arq_fila_eml.write_text("[]", encoding="utf-8")
        arq_historico.write_text("[]", encoding="utf-8")

        resultado = executar_integrador_email()

        check(resultado["execucoes_lidas"] == 2, f"2 execucoes email lidas (got {resultado['execucoes_lidas']})")
        check(resultado["preparados"] >= 1, f"pelo menos 1 email preparado (got {resultado['preparados']})")
        check(resultado["modo"] == "assistido", f"modo=assistido (got {resultado['modo']})")

        fila_email = json.loads(arq_fila_eml.read_text("utf-8"))
        check(len(fila_email) >= 1, f"fila_envio_email com ao menos 1 item (got {len(fila_email)})")

        preparados_na_fila = [e for e in fila_email if e.get("status") == "preparado"]
        check(len(preparados_na_fila) >= 1, f"ao menos 1 com status=preparado (got {len(preparados_na_fila)})")

        for e in preparados_na_fila:
            check(e.get("simulado") is True, f"simulado=True em {e['id']}")
            check(bool(e.get("assunto")), f"assunto preenchido em {e['id']}")

        historico = json.loads(arq_historico.read_text("utf-8"))
        check(len(historico) >= 1, f"historico_email com ao menos 1 evento (got {len(historico)})")

        estado = json.loads(arq_estado.read_text("utf-8"))
        check("contadores" in estado, "estado tem contadores")
        check(estado.get("modo") == "assistido", "estado.modo=assistido")

        print(f"    preparados={resultado['preparados']} | bloqueados={resultado['bloqueados']}")
        print(f"    fila_email={len(fila_email)} itens | historico={len(historico)} eventos")

    finally:
        # Restaurar todos os arquivos
        def _restaurar(arq, bkp):
            if bkp is None:
                arq.unlink(missing_ok=True)
            else:
                with open(arq, "w", encoding="utf-8") as f:
                    json.dump(bkp, f, ensure_ascii=False, indent=2)

        _restaurar(arq_config, bkp_config)
        _restaurar(arq_fila_exec, bkp_fila_exec)
        _restaurar(arq_fila_eml, bkp_fila_eml)
        _restaurar(arq_historico, bkp_hist)
        _restaurar(arq_estado, bkp_estado)


# ─── Teste 10: respeitar_governanca_e_politicas ───────────────────────────────

def test_governanca_politicas():
    print("\n=== Teste 10: Governança e políticas ===")

    cfg_ok = dict(_CONFIG_CANAL_OK)

    ok, motivo = respeitar_governanca_e_politicas(cfg_ok, {})
    check(ok, f"canal habilitado + sem pausa → ok (motivo={motivo})")

    _, motivo = respeitar_governanca_e_politicas(cfg_ok, {"agentes_pausados": ["integrador_email"]})
    check("integrador_email" in motivo, f"pause de agente refletida: {motivo}")

    _, motivo = respeitar_governanca_e_politicas(cfg_ok, {"areas_pausadas": ["comercial"]})
    check("comercial" in motivo, f"pause de area refletida: {motivo}")

    cfg_desab = dict(_CONFIG_CANAL_OK, habilitado=False)
    ok_desab, motivo_desab = respeitar_governanca_e_politicas(cfg_desab, {})
    check(not ok_desab, f"habilitado=False → bloqueado: {motivo_desab}")

    print(f"    Todos os cenários de governança validados.")


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        test_validar_identidade_ok,
        test_validar_identidade_inativa,
        test_validar_sem_email_remetente,
        test_montar_assunto,
        test_montar_corpo,
        test_preparar_email_ok,
        test_preparar_email_bloqueado,
        test_integrador_canal_desativado,
        test_integrador_com_execucoes,
        test_governanca_politicas,
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

    print("\n" + "=" * 60)
    print(f"Resultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
