"""
core/llm_router.py

Cérebro LLM central da plataforma de agentes Vetor.

Dá acesso a modelos de linguagem para todos os agentes sem que cada um
precise saber qual modelo chamar, como autenticar ou como tratar erros.

Modos de operação:
  dry-run (padrão) — custo zero, sem chamada real, respostas simuladas
  real            — chamadas reais à API Anthropic (requer ANTHROPIC_API_KEY)

Uso básico:
  from core.llm_router import LLMRouter
  router = LLMRouter()
  resposta = router.redigir({
      "agente": "agente_comercial",
      "tarefa": "redigir_email_proposta",
      "dados": {"empresa": "Padaria X", "oferta": "Diagnóstico Digital"},
  })

Controle de modo em config.py:
  LLM_MODO = "dry-run"   # padrão — custo zero
  LLM_MODO = "real"      # ativa quando empresa estiver operacional
"""

import json
import logging
import os
from pathlib import Path

import config

log = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────

_MODELO_RAPIDO   = getattr(config, "LLM_MODELO_RAPIDO",   "claude-haiku-4-5-20251001")
_MODELO_COMPLETO = getattr(config, "LLM_MODELO_COMPLETO", "claude-sonnet-4-6")

_TIMEOUT         = getattr(config, "LLM_TIMEOUT", 30)
_MAX_TOK_RAPIDO  = getattr(config, "LLM_MAX_TOKENS_RAPIDO",   1024)
_MAX_TOK_COMPL   = getattr(config, "LLM_MAX_TOKENS_COMPLETO", 2048)

# Custo estimado por 1 000 tokens (USD) — referência para estimativas
_CUSTO_HAIKU_INPUT  = 0.00080  # $0.80 / 1M tokens
_CUSTO_HAIKU_OUTPUT = 0.00400  # $4.00 / 1M tokens
_CUSTO_SONNET_INPUT  = 0.00300  # $3.00 / 1M tokens
_CUSTO_SONNET_OUTPUT = 0.01500  # $15.00 / 1M tokens


# ─── Classe principal ─────────────────────────────────────────────────────────

class LLMRouter:
    """
    Router central de LLM para os agentes da Vetor.

    Abstrai modelo, autenticação e tratamento de erros.
    Em dry-run, opera completamente sem API key e sem custo.
    """

    def __init__(self):
        self._modo = self._detectar_modo()
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None
        self._contexto_empresa = self._carregar_contexto_empresa()
        self._imprimir_modo()

    # ─── Interface pública ────────────────────────────────────────────────────

    def classificar(self, contexto: dict, empresa_id: str = None) -> dict:
        """
        Triagem e categorização de entidades ou sinais.
        Modelo rápido (Haiku). Baixo custo quando em modo real.

        Exemplo de uso:
          router.classificar({
              "agente": "agente_prospeccao",
              "tarefa": "classificar_empresa",
              "dados": {"nome": "Barbearia Central", "sinais": [...]},
          })
        """
        if empresa_id:
            self._enriquecer_com_memoria(contexto, empresa_id)
        if self._modo == "dry-run":
            return self._resposta_dry_run("classificar", contexto, {
                "classificacao": "simulado",
                "confianca": "dry-run",
                "nota": "Resposta simulada — ativar modo real para classificação via LLM",
            }, modelo_simulado=_MODELO_RAPIDO)
        return self._chamar_real(
            metodo="classificar",
            contexto=contexto,
            modelo=_MODELO_RAPIDO,
            max_tokens=_MAX_TOK_RAPIDO,
            instrucao_sistema="Classifique o objeto descrito. Retorne JSON com classificacao, confianca (0.0-1.0) e justificativa.",
        )

    def redigir(self, contexto: dict, empresa_id: str = None) -> dict:
        """
        Redação de emails, propostas e mensagens personalizadas.
        Modelo completo (Sonnet).

        Para tarefas de comunicação comercial (abordagem, email, proposta),
        injeta automaticamente o guia de tom e exemplos por categoria.
        """
        if empresa_id:
            self._enriquecer_com_memoria(contexto, empresa_id)

        # Injetar guia de tom em tarefas de comunicação comercial
        _tarefas_comunicacao = (
            "redigir_email", "redigir_abordagem", "redigir_proposta",
            "redigir_mensagem", "abordagem", "email", "copy",
        )
        agente = contexto.get("agente", "")
        tarefa = contexto.get("tarefa", "conteúdo solicitado")
        _eh_comunicacao = (
            agente in ("agente_comercial", "agente_marketing", "agente_executor_contato")
            or any(t in tarefa.lower() for t in _tarefas_comunicacao)
        )

        if _eh_comunicacao:
            self._injetar_guia_tom(contexto)

        if self._modo == "dry-run":
            # Em dry-run, mostrar preview do padrão storytelling se tiver guia
            guia = contexto.get("contexto_extra", {}).get("guia_tom", {})
            categoria = contexto.get("dados", {}).get("categoria", "")
            exemplo = contexto.get("contexto_extra", {}).get("exemplo_tom_categoria", {})
            if guia and exemplo:
                preview = (
                    f"[DRY-RUN] Seguiria padrão storytelling — "
                    f"cena: {exemplo.get('cena_problema', '?')[:80]} | "
                    f"perda: {exemplo.get('perda_concreta', '?')[:80]}"
                )
            else:
                preview = (
                    f"[DRY-RUN] Texto simulado para: {tarefa}. "
                    "Em modo real, o LLM redigiria uma mensagem personalizada baseada no contexto."
                )
            return self._resposta_dry_run("redigir", contexto, {
                "texto": preview,
                "canal": "simulado",
            }, modelo_simulado=_MODELO_COMPLETO)

        instrucao = (
            "Redija o conteúdo solicitado em português brasileiro seguindo RIGOROSAMENTE "
            "o guia de tom e o modelo de referência injetados no contexto. "
            "Tom: formal mas simples, sem buzzwords, do ponto de vista do cliente. "
            "Retorne JSON com texto e canal."
        )
        return self._chamar_real(
            metodo="redigir",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema=instrucao,
        )

    def decidir(self, contexto: dict, empresa_id: str = None) -> dict:
        """
        Decisão em situações ambíguas com justificativa estruturada.
        Modelo completo (Sonnet).

        Exemplo de uso:
          router.decidir({
              "agente": "agente_secretario",
              "tarefa": "decidir_escalamento_oportunidade",
              "dados": {"opp_id": "opp_xxx", "sinais": [...]},
          })
        """
        if empresa_id:
            self._enriquecer_com_memoria(contexto, empresa_id)
        if self._modo == "dry-run":
            return self._resposta_dry_run("decidir", contexto, {
                "decisao": "pendente_revisao_humana",
                "justificativa": "Modo dry-run — decisão requer ativação do LLM ou revisão manual",
                "confianca": "dry-run",
            }, modelo_simulado=_MODELO_COMPLETO)
        return self._chamar_real(
            metodo="decidir",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema="Analise o cenário e tome uma decisão clara. Retorne JSON com decisao, justificativa e confianca (0.0-1.0).",
        )

    def analisar(self, contexto: dict, empresa_id: str = None) -> dict:
        """
        Análise de risco, diagnóstico operacional e leitura de sinais.
        Modelo completo (Sonnet).

        Exemplo de uso:
          router.analisar({
              "agente": "agente_financeiro",
              "tarefa": "analisar_risco_caixa",
              "dados": {"saldo": 1200.0, "despesas_previstas": [...]},
          })
        """
        if empresa_id:
            self._enriquecer_com_memoria(contexto, empresa_id)
        if self._modo == "dry-run":
            return self._resposta_dry_run("analisar", contexto, {
                "analise": "simulada",
                "riscos": [],
                "nota": "Análise simulada — ativar modo real para diagnóstico via LLM",
            }, modelo_simulado=_MODELO_COMPLETO)
        return self._chamar_real(
            metodo="analisar",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema="Analise os dados fornecidos. Retorne JSON com analise (texto), riscos (lista) e recomendacoes (lista).",
        )

    def resumir(self, contexto: dict, empresa_id: str = None) -> dict:
        """
        Resumos e consolidações de dados estruturados.
        Modelo rápido (Haiku). Baixo custo quando em modo real.

        Exemplo de uso:
          router.resumir({
              "agente": "agente_secretario",
              "tarefa": "resumir_ciclo_operacional",
              "dados": {"ciclo": {...}},
          })
        """
        if empresa_id:
            self._enriquecer_com_memoria(contexto, empresa_id)
        dados = contexto.get("dados", {})
        if self._modo == "dry-run":
            return self._resposta_dry_run("resumir", contexto, {
                "resumo": f"[DRY-RUN] Resumo simulado. Dados recebidos: {len(dados)} chave(s).",
                "nota": "dry-run",
            }, modelo_simulado=_MODELO_RAPIDO)
        return self._chamar_real(
            metodo="resumir",
            contexto=contexto,
            modelo=_MODELO_RAPIDO,
            max_tokens=_MAX_TOK_RAPIDO,
            instrucao_sistema="Resuma os dados fornecidos de forma concisa. Retorne JSON com resumo (texto) e pontos_principais (lista).",
        )

    # ─── Dry-run ──────────────────────────────────────────────────────────────

    def _resposta_dry_run(
        self,
        metodo: str,
        contexto: dict,
        resultado: dict,
        modelo_simulado: str = "",
    ) -> dict:
        agente = contexto.get("agente", "desconhecido")
        tarefa = contexto.get("tarefa", "—")
        print(
            f"[LLM Router] dry-run | {metodo} | agente={agente} | tarefa={tarefa}"
        )
        resp = {
            "sucesso":            True,
            "resultado":          resultado,
            "modelo_usado":       "dry-run",
            "tokens_entrada":     0,
            "tokens_saida":       0,
            "custo_estimado_usd": 0.0,
            "fallback_usado":     False,
            "modo":               "dry-run",
            "erro":               None,
        }
        try:
            from core.llm_log import registrar_chamada_llm
            registrar_chamada_llm({
                **resp,
                "agente":          agente,
                "tipo_tarefa":     metodo,
                "payload_chars":   len(json.dumps(contexto, ensure_ascii=False)),
                "modelo_simulado": modelo_simulado,
                "ciclo_id":        contexto.get("ciclo_id"),
            })
        except Exception as _exc:
            log.warning(f"[llm_router] falha ao registrar log dry-run: {_exc}")
        return resp

    # ─── Modo real ────────────────────────────────────────────────────────────

    def _chamar_real(
        self,
        metodo: str,
        contexto: dict,
        modelo: str,
        max_tokens: int,
        instrucao_sistema: str,
    ) -> dict:
        """Faz chamada real à API Anthropic. Nunca lança exceção."""
        agente = contexto.get("agente", "desconhecido")
        tarefa = contexto.get("tarefa", "—")
        print(
            f"[LLM Router] REAL | {metodo} | modelo={modelo} | agente={agente} | tarefa={tarefa}"
        )

        try:
            client = self._obter_client()
            prompt = self._montar_prompt(contexto)
            system_prompt = self._montar_system_prompt(instrucao_sistema)

            resposta = client.messages.create(
                model=modelo,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                timeout=_TIMEOUT,
            )

            conteudo = resposta.content[0].text if resposta.content else ""
            tok_in   = resposta.usage.input_tokens  if resposta.usage else 0
            tok_out  = resposta.usage.output_tokens if resposta.usage else 0

            # Tentar parsear JSON; se não conseguir, retorna como texto
            resultado = self._parsear_resultado(conteudo)
            custo     = self._estimar_custo(modelo, tok_in, tok_out)

            resp = {
                "sucesso":            True,
                "resultado":          resultado,
                "modelo_usado":       modelo,
                "tokens_entrada":     tok_in,
                "tokens_saida":       tok_out,
                "custo_estimado_usd": custo,
                "fallback_usado":     False,
                "modo":               "real",
                "erro":               None,
            }
            try:
                from core.llm_log import registrar_chamada_llm
                registrar_chamada_llm({
                    **resp,
                    "agente":          agente,
                    "tipo_tarefa":     metodo,
                    "payload_chars":   0,
                    "modelo_simulado": "",
                    "ciclo_id":        contexto.get("ciclo_id"),
                })
            except Exception as _exc:
                log.warning(f"[llm_router] falha ao registrar log real: {_exc}")
            return resp

        except Exception as exc:
            log.warning(f"[llm_router] falha em {metodo} ({agente}): {exc}")
            print(f"[LLM Router] ERRO em {metodo}: {exc} — retornando fallback")
            resp_err = {
                "sucesso":            False,
                "resultado":          {},
                "modelo_usado":       modelo,
                "tokens_entrada":     0,
                "tokens_saida":       0,
                "custo_estimado_usd": 0.0,
                "fallback_usado":     True,
                "modo":               "real",
                "erro":               str(exc),
            }
            try:
                from core.llm_log import registrar_chamada_llm
                registrar_chamada_llm({
                    **resp_err,
                    "agente":          agente,
                    "tipo_tarefa":     metodo,
                    "payload_chars":   0,
                    "modelo_simulado": "",
                    "ciclo_id":        contexto.get("ciclo_id"),
                })
            except Exception:
                pass
            return resp_err

    # ─── Auxiliares ──────────────────────────────────────────────────────────

    def _injetar_guia_tom(self, contexto: dict) -> None:
        """
        Injeta guia_tom_comunicacao.json e exemplo_tom por categoria no contexto.
        Não lança exceção — é auxiliar.
        """
        try:
            extra = contexto.setdefault("contexto_extra", {})
            if extra.get("guia_tom"):
                return  # já injetado

            guia = self._carregar_guia_tom()
            if guia:
                extra["guia_tom"] = {
                    "principios": guia.get("principios", []),
                    "proibido": guia.get("proibido", []),
                    "estrutura_abordagem": guia.get("estrutura_abordagem", {}),
                    "modelo_referencia_texto": guia.get("modelo_referencia", {}).get("texto", ""),
                }

            categoria = (
                contexto.get("dados", {}).get("categoria_id")
                or contexto.get("dados", {}).get("categoria")
                or contexto.get("categoria")
                or ""
            )
            if categoria:
                exemplo = self._carregar_exemplo_tom(categoria)
                if exemplo:
                    extra["exemplo_tom_categoria"] = exemplo
        except Exception as exc:
            log.warning(f"[llm_router] falha ao injetar guia_tom: {exc}")

    def _carregar_guia_tom(self) -> dict:
        """Carrega guia_tom_comunicacao.json com cache simples."""
        if not hasattr(self, "_guia_tom_cache"):
            arq = config.PASTA_DADOS / "guia_tom_comunicacao.json"
            try:
                if arq.exists():
                    with open(arq, encoding="utf-8") as f:
                        self._guia_tom_cache = json.load(f)
                else:
                    self._guia_tom_cache = {}
            except Exception:
                self._guia_tom_cache = {}
        return self._guia_tom_cache

    def _carregar_exemplo_tom(self, categoria: str) -> dict:
        """Carrega exemplo de tom para a categoria do negócio."""
        arq = config.PASTA_DADOS / "exemplos_tom_por_categoria.json"
        try:
            if arq.exists():
                with open(arq, encoding="utf-8") as f:
                    dados = json.load(f)
                for nicho in dados.get("nichos", []):
                    if (nicho.get("nicho") == categoria
                            or categoria in nicho.get("categoria_ids", [])):
                        return nicho
        except Exception as exc:
            log.warning(f"[llm_router] falha ao carregar exemplo_tom ({categoria}): {exc}")
        return {}

    def _enriquecer_com_memoria(self, contexto: dict, empresa_id: str) -> None:
        """
        Carrega memória da conta e injeta em contexto_extra.
        Não lança exceção — memória é auxiliar, nunca bloqueante.
        Funciona em dry-run (monta contexto para debug) e em modo real.
        """
        try:
            from core.llm_memoria import gerar_contexto_llm
            ctx_mem = gerar_contexto_llm(empresa_id=empresa_id)
            if ctx_mem:
                extra = contexto.setdefault("contexto_extra", {})
                extra["memoria_conta"] = ctx_mem
        except Exception as exc:
            log.warning(f"[llm_router] falha ao carregar memória ({empresa_id}): {exc}")

    def _detectar_modo(self) -> str:
        """
        Resolve o modo de operação em três camadas:
        1. Variável de ambiente LLM_MODO
        2. config.LLM_MODO
        3. Padrão: "dry-run"
        Guarda de segurança: se modo="real" mas sem API key → "dry-run" com alerta.
        """
        modo = (
            os.getenv("LLM_MODO")
            or getattr(config, "LLM_MODO", "dry-run")
            or "dry-run"
        ).strip().lower()

        if modo == "real":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key or api_key.startswith("sk-ant-..."):
                print(
                    "[LLM Router] ALERTA: LLM_MODO=real mas ANTHROPIC_API_KEY nao "
                    "configurada. Operando como dry-run."
                )
                return "dry-run"

        return modo if modo in ("dry-run", "real") else "dry-run"

    def _imprimir_modo(self) -> None:
        if self._modo == "dry-run":
            print("[LLM Router] Modo: dry-run — sem custo")
        else:
            modelo_r = _MODELO_RAPIDO
            modelo_c = _MODELO_COMPLETO
            print(
                f"[LLM Router] Modo: REAL — chamadas com custo ativo | "
                f"rapido={modelo_r} | completo={modelo_c}"
            )

    def _obter_client(self):
        """Inicializa cliente Anthropic com lazy loading."""
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "Biblioteca 'anthropic' não instalada. "
                    "Execute: pip install anthropic>=0.40.0"
                )
        return self._client

    def _carregar_contexto_empresa(self) -> dict:
        """Carrega contexto da empresa para injetar em system prompts."""
        ctx = {}
        arquivos = {
            "identidade": config.PASTA_DADOS / "identidade_empresa.json",
            "politicas":  config.PASTA_DADOS / "politicas_operacionais.json",
            "governanca": config.PASTA_DADOS / "estado_governanca_conselho.json",
        }
        for chave, caminho in arquivos.items():
            try:
                if caminho.exists():
                    with open(caminho, encoding="utf-8") as f:
                        ctx[chave] = json.load(f)
            except Exception:
                pass
        return ctx

    def _montar_system_prompt(self, instrucao_tarefa: str) -> str:
        """Monta system prompt com contexto da empresa + instrução da tarefa."""
        partes = []

        if self._contexto_empresa.get("identidade"):
            ident = self._contexto_empresa["identidade"]
            nome = ident.get("nome_exibicao") or ident.get("nome_oficial", "Empresa")
            desc = ident.get("descricao_curta", "")
            partes.append(f"Você está auxiliando a empresa {nome}. {desc}")

        if self._contexto_empresa.get("politicas"):
            pol = self._contexto_empresa["politicas"]
            if isinstance(pol, dict):
                partes.append(
                    "Políticas operacionais ativas: "
                    + json.dumps(pol, ensure_ascii=False)
                )

        partes.append(instrucao_tarefa)
        partes.append("Responda sempre em JSON válido, sem texto fora do objeto JSON.")
        return "\n\n".join(partes)

    def _montar_prompt(self, contexto: dict) -> str:
        """Converte o dict de contexto em prompt de usuário."""
        agente = contexto.get("agente", "agente")
        tarefa = contexto.get("tarefa", "tarefa")
        dados  = contexto.get("dados", {})
        extra  = contexto.get("contexto_extra", {})

        partes = [
            f"Agente: {agente}",
            f"Tarefa: {tarefa}",
            f"Dados:\n{json.dumps(dados, ensure_ascii=False, indent=2)}",
        ]
        if extra:
            partes.append(
                f"Contexto adicional:\n{json.dumps(extra, ensure_ascii=False, indent=2)}"
            )
        return "\n\n".join(partes)

    def _parsear_resultado(self, texto: str) -> dict:
        """Tenta parsear JSON; retorna dict com texto bruto se falhar."""
        texto = texto.strip()
        # Remover markdown code blocks se presentes
        if texto.startswith("```"):
            linhas = texto.split("\n")
            texto  = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
        try:
            return json.loads(texto)
        except Exception:
            return {"texto": texto, "parse_error": True}

    def _estimar_custo(self, modelo: str, tok_in: int, tok_out: int) -> float:
        """Estima custo em USD baseado no modelo e tokens usados."""
        if _MODELO_RAPIDO in modelo:
            return (tok_in * _CUSTO_HAIKU_INPUT + tok_out * _CUSTO_HAIKU_OUTPUT) / 1000
        return (tok_in * _CUSTO_SONNET_INPUT + tok_out * _CUSTO_SONNET_OUTPUT) / 1000

    @property
    def modo(self) -> str:
        """Modo de operação atual: 'dry-run' ou 'real'."""
        return self._modo

    @property
    def contexto_empresa(self) -> dict:
        """Contexto da empresa carregado (para debug em dry-run)."""
        return self._contexto_empresa
