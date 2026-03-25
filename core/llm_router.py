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

    def classificar(self, contexto: dict) -> dict:
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
        if self._modo == "dry-run":
            return self._resposta_dry_run("classificar", contexto, {
                "classificacao": "simulado",
                "confianca": "dry-run",
                "nota": "Resposta simulada — ativar modo real para classificação via LLM",
            })
        return self._chamar_real(
            metodo="classificar",
            contexto=contexto,
            modelo=_MODELO_RAPIDO,
            max_tokens=_MAX_TOK_RAPIDO,
            instrucao_sistema="Classifique o objeto descrito. Retorne JSON com classificacao, confianca (0.0-1.0) e justificativa.",
        )

    def redigir(self, contexto: dict) -> dict:
        """
        Redação de emails, propostas e mensagens personalizadas.
        Modelo completo (Sonnet).

        Exemplo de uso:
          router.redigir({
              "agente": "agente_comercial",
              "tarefa": "redigir_email_proposta",
              "dados": {"empresa": "X", "oferta": "Y"},
          })
        """
        tarefa = contexto.get("tarefa", "conteúdo solicitado")
        if self._modo == "dry-run":
            return self._resposta_dry_run("redigir", contexto, {
                "texto": f"[DRY-RUN] Texto simulado para: {tarefa}. "
                         "Em modo real, o LLM redigiria uma mensagem personalizada "
                         "baseada no contexto.",
                "canal": "simulado",
            })
        return self._chamar_real(
            metodo="redigir",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema="Redija o conteúdo solicitado em português brasileiro. Tom profissional e direto. Retorne JSON com texto e canal.",
        )

    def decidir(self, contexto: dict) -> dict:
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
        if self._modo == "dry-run":
            return self._resposta_dry_run("decidir", contexto, {
                "decisao": "pendente_revisao_humana",
                "justificativa": "Modo dry-run — decisão requer ativação do LLM ou revisão manual",
                "confianca": "dry-run",
            })
        return self._chamar_real(
            metodo="decidir",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema="Analise o cenário e tome uma decisão clara. Retorne JSON com decisao, justificativa e confianca (0.0-1.0).",
        )

    def analisar(self, contexto: dict) -> dict:
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
        if self._modo == "dry-run":
            return self._resposta_dry_run("analisar", contexto, {
                "analise": "simulada",
                "riscos": [],
                "nota": "Análise simulada — ativar modo real para diagnóstico via LLM",
            })
        return self._chamar_real(
            metodo="analisar",
            contexto=contexto,
            modelo=_MODELO_COMPLETO,
            max_tokens=_MAX_TOK_COMPL,
            instrucao_sistema="Analise os dados fornecidos. Retorne JSON com analise (texto), riscos (lista) e recomendacoes (lista).",
        )

    def resumir(self, contexto: dict) -> dict:
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
        dados = contexto.get("dados", {})
        if self._modo == "dry-run":
            return self._resposta_dry_run("resumir", contexto, {
                "resumo": f"[DRY-RUN] Resumo simulado. Dados recebidos: {len(dados)} chave(s).",
                "nota": "dry-run",
            })
        return self._chamar_real(
            metodo="resumir",
            contexto=contexto,
            modelo=_MODELO_RAPIDO,
            max_tokens=_MAX_TOK_RAPIDO,
            instrucao_sistema="Resuma os dados fornecidos de forma concisa. Retorne JSON com resumo (texto) e pontos_principais (lista).",
        )

    # ─── Dry-run ──────────────────────────────────────────────────────────────

    def _resposta_dry_run(self, metodo: str, contexto: dict, resultado: dict) -> dict:
        agente = contexto.get("agente", "desconhecido")
        tarefa = contexto.get("tarefa", "—")
        print(
            f"[LLM Router] dry-run | {metodo} | agente={agente} | tarefa={tarefa}"
        )
        return {
            "sucesso":             True,
            "resultado":           resultado,
            "modelo_usado":        "dry-run",
            "tokens_entrada":      0,
            "tokens_saida":        0,
            "custo_estimado_usd":  0.0,
            "fallback_usado":      False,
            "modo":                "dry-run",
            "erro":                None,
        }

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

            return {
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

        except Exception as exc:
            log.warning(f"[llm_router] falha em {metodo} ({agente}): {exc}")
            print(f"[LLM Router] ERRO em {metodo}: {exc} — retornando fallback")
            return {
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

    # ─── Auxiliares ──────────────────────────────────────────────────────────

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
