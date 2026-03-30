"""
core/persistencia.py — Único ponto de leitura e escrita de dados do sistema.

Nenhum outro módulo deve ler ou escrever arquivos JSON diretamente.
Se no futuro trocarmos JSON por banco de dados, só este arquivo muda.

Escrita atômica (v2):
  tmp → fsync → os.replace → .bak
  Garante que o arquivo principal nunca fica corrompido por crash ou Ctrl+C.

Recovery automático:
  Se o principal estiver corrompido, tenta .tmp → .bak → retorna default.
  Incidentes de corrupção são registrados em dados/incidentes_operacionais.json.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ─── Escrita atômica ──────────────────────────────────────────────────────────

def _escrever_atomico(caminho: Path, dados) -> None:
    """
    Escrita atômica: .tmp com fsync → os.replace → rotacionar .bak.

    Fluxo:
      1. Serializar JSON para string
      2. Escrever em <caminho>.tmp + flush + fsync (dados no disco)
      3. Mover principal atual para <caminho>.bak  (1 nível de backup)
      4. os.replace(.tmp, caminho)                 (atômico no OS)

    Crash em qualquer ponto antes do os.replace final:
      - .tmp ficará lá (completo e válido), principal intacto
      - Próxima leitura detecta .tmp e recupera automaticamente

    Crash após os.replace:
      - Arquivo principal está completo (rename é atômico)
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    bak = caminho.with_suffix(caminho.suffix + ".bak")

    # Passo 1 — escrever .tmp com fsync
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())

    # Passo 2 — rotacionar: principal atual → .bak (melhor esforço)
    if caminho.exists():
        try:
            os.replace(caminho, bak)
        except OSError as _err:
            logger.warning("erro ignorado: %s", _err)  # Se falhar, .bak simplesmente não é atualizado; segue

    # Passo 3 — promover .tmp → principal (operação atômica)
    os.replace(tmp, caminho)


# Alias público para uso em outros módulos
salvar_atomico = _escrever_atomico


# ─── Leitura com recuperação ──────────────────────────────────────────────────

def _carregar_com_recuperacao(caminho: Path, padrao):
    """
    Carrega JSON com recuperação em cascata:
      1. Arquivo principal → OK → retornar
      2. Principal corrompido ou ausente → tentar .tmp
      3. .tmp inválido → tentar .bak
      4. Tudo falhou → registrar incidente, retornar padrao

    Nunca lança exceção ao chamador.
    """
    caminho = Path(caminho)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    bak = caminho.with_suffix(caminho.suffix + ".bak")

    # 1. Tentar principal
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("[persistencia] JSON corrompido: %s — %s", caminho.name, e)
            _registrar_incidente(caminho, f"json_corrompido: {e}", "tentando_tmp_bak")
        except Exception as e:
            logger.warning("[persistencia] Erro ao ler %s: %s", caminho.name, e)

    # 2. Tentar .tmp (crash antes do rename final = tmp completo, principal ausente/velho)
    if tmp.exists():
        try:
            dados = json.loads(tmp.read_text(encoding="utf-8"))
            logger.info("[persistencia] Recuperado de .tmp: %s", caminho.name)
            _registrar_incidente(caminho, "principal_ausente_ou_corrompido",
                                 f"recuperado_de_tmp")
            # Promover .tmp a principal para próximas leituras
            try:
                os.replace(tmp, caminho)
            except OSError as _err:
                logger.warning("erro ignorado: %s", _err)
            return dados
        except Exception as _err:
            logger.warning("erro ignorado: %s", _err)

    # 3. Tentar .bak
    if bak.exists():
        try:
            dados = json.loads(bak.read_text(encoding="utf-8"))
            logger.info("[persistencia] Recuperado de .bak: %s", caminho.name)
            _registrar_incidente(caminho, "principal_e_tmp_invalidos",
                                 "recuperado_de_bak")
            return dados
        except Exception as _err:
            logger.warning("erro ignorado: %s", _err)

    # 4. Tudo falhou
    if caminho.exists() or tmp.exists() or bak.exists():
        logger.error("[persistencia] Impossível recuperar %s — retornando default",
                     caminho.name)
        _registrar_incidente(caminho, "tudo_corrompido", "retornado_default")

    return padrao


# ─── Registro de incidentes ───────────────────────────────────────────────────

def _registrar_incidente(caminho: Path, erro: str, acao: str) -> None:
    """Registra incidente em incidentes_operacionais.json sem crashar."""
    try:
        import config
        arq = config.PASTA_DADOS / "incidentes_operacionais.json"

        try:
            incs = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else []
        except Exception:
            incs = []

        incs.append({
            "tipo":      "corrupcao_json",
            "arquivo":   caminho.name,
            "caminho":   str(caminho),
            "erro":      erro,
            "acao":      acao,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

        # Escrita direta sem chamar _escrever_atomico para evitar recursão
        tmp = arq.with_suffix(arq.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(incs, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, arq)
    except Exception as _err:
        logger.warning("erro ignorado: %s", _err)  # Nunca crashar ao registrar um incidente


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _garantir_pasta(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)


# ─── API pública ──────────────────────────────────────────────────────────────

def salvar_resultados(resultados: list, sufixo: str = "", pasta: Path = None) -> Path:
    """
    Salva lista de resultados em arquivo JSON com timestamp.

    Retorna:
        Path do arquivo criado
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    _garantir_pasta(pasta)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    nome = f"resultado_{timestamp}"
    if sufixo:
        nome += f"_{sufixo}"
    nome += ".json"

    caminho = pasta / nome
    _escrever_atomico(caminho, resultados)

    logger.info("Arquivo salvo: %s (%d registros)", caminho, len(resultados))
    return caminho


def salvar_json_fixo(dados, nome_arquivo: str, pasta: Path = None) -> Path:
    """
    Salva dados em arquivo JSON com nome fixo (sem timestamp).

    Usado para arquivos persistentes sobrescritos a cada execução.
    Retorna:
        Path do arquivo salvo
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    _garantir_pasta(pasta)
    caminho = pasta / nome_arquivo

    _escrever_atomico(caminho, dados)

    n = len(dados) if isinstance(dados, (list, dict)) else 1
    logger.info("Arquivo fixo salvo: %s (%s registros)", caminho, n)
    return caminho


def carregar_json_fixo(nome_arquivo: str, pasta: Path = None, padrao=None):
    """
    Carrega arquivo JSON com nome fixo.
    Retorna `padrao` se o arquivo não existir ou não puder ser recuperado.
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    caminho = pasta / nome_arquivo

    if not caminho.exists():
        # Verificar se há .tmp ou .bak antes de desistir
        tmp = caminho.with_suffix(caminho.suffix + ".tmp")
        bak = caminho.with_suffix(caminho.suffix + ".bak")
        if not tmp.exists() and not bak.exists():
            logger.info("Arquivo fixo não encontrado (primeira execução?): %s", caminho)
            return padrao

    dados = _carregar_com_recuperacao(caminho, padrao)
    if dados is not padrao:
        n = len(dados) if isinstance(dados, (list, dict)) else 1
        logger.info("Arquivo fixo carregado: %s (%s registros)", caminho, n)
    return dados


def carregar_resultados(caminho) -> list:
    """
    Carrega resultados de um arquivo JSON.

    Lança:
        FileNotFoundError se o arquivo não existir e não houver recovery
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    dados = _carregar_com_recuperacao(caminho, None)
    if dados is None:
        raise ValueError(f"Arquivo corrompido e sem recovery: {caminho}")

    logger.info("Arquivo carregado: %s (%d registros)", caminho, len(dados))
    return dados
