#!/usr/bin/env python3
"""
scripts/setup_auth_painel.py — Configurar autenticação do painel do conselho.

Uso:
  python scripts/setup_auth_painel.py

Cria dados/auth_painel.json com usuário, hash da senha, secret de sessão e
duração da sessão. Se o arquivo já existir, pede confirmação antes de sobrescrever.

Para redefinir a senha: rode este script novamente.
Para desativar a autenticação: apague dados/auth_painel.json (painel volta ao modo dev).
"""

import hashlib
import json
import secrets
import sys
from pathlib import Path

try:
    import getpass
    _HAS_GETPASS = True
except ImportError:
    _HAS_GETPASS = False

_ROOT      = Path(__file__).parent.parent
_AUTH_FILE = _ROOT / "dados" / "auth_painel.json"


def _hash_senha(senha: str) -> str:
    """Retorna 'sha256:<salt_hex>:<hash_hex>'."""
    salt = secrets.token_hex(16)
    h    = hashlib.sha256((senha + salt).encode("utf-8")).hexdigest()
    return f"sha256:{salt}:{h}"


def _ler_senha(prompt: str) -> str:
    if _HAS_GETPASS:
        return getpass.getpass(prompt)
    # Fallback (IDE sem tty)
    return input(prompt)


def main() -> None:
    print("=== Setup de Autenticação — Painel do Conselho ===\n")

    if _AUTH_FILE.exists():
        resp = input("Arquivo de autenticação já existe. Sobrescrever? [s/N] ").strip().lower()
        if resp not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            sys.exit(0)

    # Usuário
    usuario = input("Usuário [conselho]: ").strip() or "conselho"

    # Senha (com confirmação)
    while True:
        senha = _ler_senha("Senha (mínimo 6 caracteres): ")
        if len(senha) < 6:
            print("  Senha deve ter ao menos 6 caracteres. Tente novamente.")
            continue
        confirmar = _ler_senha("Confirmar senha: ")
        if senha != confirmar:
            print("  Senhas não conferem. Tente novamente.\n")
            continue
        break

    # Duração da sessão
    horas_str = input("Duração da sessão em horas [24]: ").strip()
    try:
        sessao_horas = int(horas_str) if horas_str else 24
        if sessao_horas < 1:
            sessao_horas = 24
    except ValueError:
        sessao_horas = 24

    auth = {
        "usuario":      usuario,
        "senha_hash":   _hash_senha(senha),
        "sessao_horas": sessao_horas,
        "secret":       secrets.token_hex(32),
    }

    _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTH_FILE.write_text(json.dumps(auth, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nAutenticação configurada.")
    print(f"  Usuario:  {usuario}")
    print(f"  Sessao:   {sessao_horas}h")
    print(f"  Arquivo:  {_AUTH_FILE}")
    print(f"\nReinicie o painel (main_conselho.py) para ativar a autenticacao.")
    print("Para desativar: apague dados/auth_painel.json")


if __name__ == "__main__":
    main()
