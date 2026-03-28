"""
conectores/n8n_api.py — Conector para a API REST do n8n.

Cria, ativa e gerencia workflows no n8n self-hosted via API.
n8n Community Edition é gratuito e disponível na API REST.

Modos:
  dry-run (padrão): zero chamadas externas, respostas simuladas
  real: conecta ao n8n local/remoto via API REST

Autenticação (modo real):
  1. No n8n: Settings → API → Enable API → Gerar API key
  2. Preencher N8N_API_KEY no .env
  3. Alterar modo para "real" via N8N_MODO ou config

Dependência para modo real:
  pip install requests  (já usada em outros conectores)

Referência:
  https://docs.n8n.io/api/api-reference/
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ─── Configuração ─────────────────────────────────────────────────────────────

_DEFAULTS = {
    "url_base": "http://localhost:5678",
    "modo":     "dry-run",
}

_ARQ_CONFIG = config.PASTA_DADOS / "config_n8n.json"


def _carregar_config() -> dict:
    cfg = dict(_DEFAULTS)
    if _ARQ_CONFIG.exists():
        try:
            cfg.update(json.loads(_ARQ_CONFIG.read_text(encoding="utf-8")))
        except Exception:
            pass
    if os.environ.get("N8N_URL"):
        cfg["url_base"] = os.environ["N8N_URL"].rstrip("/")
    if os.environ.get("N8N_API_KEY"):
        cfg["api_key"] = os.environ["N8N_API_KEY"]
    if os.environ.get("N8N_MODO"):
        cfg["modo"] = os.environ["N8N_MODO"]
    return cfg


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id_fake(prefixo: str = "wf") -> str:
    return f"dry-{prefixo}-{uuid.uuid4().hex[:10]}"


# ─── Classe principal ─────────────────────────────────────────────────────────

class N8NConnector:
    """
    Interface com a API REST do n8n self-hosted.

    Em dry-run, todos os métodos retornam respostas simuladas sem
    fazer nenhuma chamada de rede.

    Uso:
        n8n = N8NConnector()
        wf  = n8n.criar_workflow(workflow_json)
        ok  = n8n.ativar_workflow(wf["id"])
    """

    def __init__(self, modo: str = None, url_base: str = None, api_key: str = None):
        cfg = _carregar_config()
        self.modo     = modo     or cfg.get("modo",    "dry-run")
        self.url_base = url_base or cfg.get("url_base", "http://localhost:5678")
        self.api_key  = api_key  or cfg.get("api_key",  "")

        if self.modo == "real" and not self.api_key:
            logger.warning(
                "N8NConnector modo='real' sem api_key — usando dry-run como fallback."
            )
            self.modo = "dry-run"

    # ─── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "X-N8N-API-KEY": self.api_key,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        import requests
        url = f"{self.url_base}/api/v1{path}"
        r = requests.get(url, headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict = None) -> dict:
        import requests
        url = f"{self.url_base}/api/v1{path}"
        r = requests.post(url, headers=self._headers(), json=body or {}, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _put(self, path: str, body: dict) -> dict:
        import requests
        url = f"{self.url_base}/api/v1{path}"
        r = requests.put(url, headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> bool:
        import requests
        url = f"{self.url_base}/api/v1{path}"
        r = requests.delete(url, headers=self._headers(), timeout=30)
        return r.status_code in (200, 204)

    # ─── API pública ───────────────────────────────────────────────────────────

    def criar_workflow(self, workflow_json: dict) -> dict:
        """
        Cria um novo workflow no n8n.

        workflow_json: estrutura completa do workflow (nodes, connections, settings).

        Retorna dict com: id, name, active, createdAt
        """
        logger.info(
            f"[N8N] criar_workflow: '{workflow_json.get('name', '?')}' modo={self.modo}"
        )

        if self.modo == "dry-run":
            wf_id = _id_fake("wf")
            return {
                "id":        wf_id,
                "name":      workflow_json.get("name", "Workflow"),
                "active":    False,
                "createdAt": _agora(),
                "modo":      "dry-run",
            }

        # Garante campos obrigatórios
        payload = {
            "name":        workflow_json.get("name", "Workflow"),
            "nodes":       workflow_json.get("nodes", []),
            "connections": workflow_json.get("connections", {}),
            "settings":    workflow_json.get("settings", {"executionOrder": "v1"}),
            "staticData":  None,
        }

        resp = self._post("/workflows", payload)
        logger.info(f"[N8N] Workflow criado: id={resp.get('id')}")
        return resp

    def ativar_workflow(self, workflow_id: str) -> bool:
        """Ativa um workflow (começa a responder ao trigger)."""
        logger.info(f"[N8N] ativar_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return True

        try:
            self._post(f"/workflows/{workflow_id}/activate")
            return True
        except Exception as exc:
            logger.error(f"[N8N] Erro ao ativar {workflow_id}: {exc}")
            return False

    def desativar_workflow(self, workflow_id: str) -> bool:
        """Desativa um workflow (para de responder ao trigger)."""
        logger.info(f"[N8N] desativar_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return True

        try:
            self._post(f"/workflows/{workflow_id}/deactivate")
            return True
        except Exception as exc:
            logger.error(f"[N8N] Erro ao desativar {workflow_id}: {exc}")
            return False

    def executar_workflow(self, workflow_id: str, dados: dict = None) -> dict:
        """
        Dispara o webhook de teste do workflow com dados simulados.

        Obtém a URL do webhook a partir da definição do workflow e faz POST.
        Útil para verificar se o workflow está respondendo corretamente.

        Retorna dict com: status, workflow_id, resposta
        """
        logger.info(f"[N8N] executar_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return {
                "status":      "success",
                "workflow_id": workflow_id,
                "resposta":    "[DRY-RUN] Execução simulada com sucesso.",
                "modo":        "dry-run",
            }

        try:
            wf = self.obter_workflow(workflow_id)
            webhook_url = self._obter_webhook_url(wf)

            if not webhook_url:
                return {
                    "status": "error",
                    "erro":   "Workflow não possui nó Webhook com URL detectável.",
                }

            import requests
            r = requests.post(
                webhook_url,
                json=dados or {"test": True},
                timeout=30,
            )
            return {
                "status":      "success" if r.ok else "error",
                "workflow_id": workflow_id,
                "http_status": r.status_code,
                "resposta":    r.text[:500],
            }
        except Exception as exc:
            return {"status": "error", "erro": str(exc)}

    def listar_workflows(self) -> list:
        """Retorna lista de workflows do n8n."""
        logger.info(f"[N8N] listar_workflows modo={self.modo}")

        if self.modo == "dry-run":
            return [
                {"id": "dry-wf-000001", "name": "[DRY-RUN] Bot Atendimento Exemplo", "active": True},
                {"id": "dry-wf-000002", "name": "[DRY-RUN] Bot Agendamento Exemplo", "active": True},
            ]

        try:
            resp = self._get("/workflows")
            return resp.get("data", [])
        except Exception as exc:
            logger.error(f"[N8N] Erro ao listar workflows: {exc}")
            return []

    def obter_workflow(self, workflow_id: str) -> dict:
        """Retorna a definição completa de um workflow."""
        logger.info(f"[N8N] obter_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return {
                "id":          workflow_id,
                "name":        "[DRY-RUN] Workflow",
                "active":      True,
                "nodes":       [],
                "connections": {},
                "modo":        "dry-run",
            }

        return self._get(f"/workflows/{workflow_id}")

    def atualizar_workflow(self, workflow_id: str, workflow_json: dict) -> dict:
        """Atualiza a definição de um workflow existente (PUT)."""
        logger.info(f"[N8N] atualizar_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return {"id": workflow_id, "modo": "dry-run", "atualizado_em": _agora()}

        return self._put(f"/workflows/{workflow_id}", workflow_json)

    def deletar_workflow(self, workflow_id: str) -> bool:
        """Remove permanentemente um workflow."""
        logger.info(f"[N8N] deletar_workflow: {workflow_id} modo={self.modo}")

        if self.modo == "dry-run":
            return True

        try:
            return self._delete(f"/workflows/{workflow_id}")
        except Exception as exc:
            logger.error(f"[N8N] Erro ao deletar {workflow_id}: {exc}")
            return False

    # ─── Helpers internos ──────────────────────────────────────────────────────

    def _obter_webhook_url(self, workflow: dict) -> Optional[str]:
        """Extrai a URL do webhook de um workflow (nó do tipo webhook)."""
        nodes = workflow.get("nodes", [])
        for node in nodes:
            if node.get("type") == "n8n-nodes-base.webhook":
                path = node.get("parameters", {}).get("path", "")
                if path:
                    return f"{self.url_base}/webhook/{path}"
        return None


# ─── Factory ──────────────────────────────────────────────────────────────────

def obter_conector(modo: str = None) -> N8NConnector:
    """Retorna instância configurada do conector n8n."""
    return N8NConnector(modo=modo)


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    n8n = obter_conector()
    print(f"\nModo: {n8n.modo} | URL: {n8n.url_base}\n")

    # Criar
    wf_json = {
        "name": "Teste Smoke Test",
        "nodes": [
            {
                "id": "a",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [250, 300],
                "parameters": {"httpMethod": "POST", "path": "teste", "responseMode": "onReceived"},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    wf = n8n.criar_workflow(wf_json)
    print("criar_workflow:", wf)

    ok = n8n.ativar_workflow(wf["id"])
    print("ativar_workflow:", ok)

    lista = n8n.listar_workflows()
    print(f"listar_workflows: {len(lista)} workflows")

    detail = n8n.obter_workflow(wf["id"])
    print("obter_workflow: id =", detail.get("id"))

    exec_r = n8n.executar_workflow(wf["id"], {"mensagem": "oi"})
    print("executar_workflow:", exec_r)

    ok2 = n8n.desativar_workflow(wf["id"])
    print("desativar_workflow:", ok2)

    ok3 = n8n.deletar_workflow(wf["id"])
    print("deletar_workflow:", ok3)
