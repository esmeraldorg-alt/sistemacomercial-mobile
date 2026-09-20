"""
Funções utilitárias para a versão mobile (Kivy) do sistema.

Baseado no utils.py original. Principais diferenças:
- Removidas as funções específicas de Tkinter/CustomTkinter
  (centralizar_janela, trazer_janela_para_frente, aplicar_estilo_treeview),
  que não existem no Kivy.
- BASE_DIR não é mais fixo na pasta do executável: é definido em tempo de
  execução via definir_base_dir(), chamada uma única vez no início do app
  (App.on_start), passando App.user_data_dir. No desktop isso continua
  apontando para a pasta do programa; no Android aponta para a pasta de
  dados privada do app (o único lugar com escrita garantida).
- formatar_moeda, desformatar_moeda, aplicar_fator_conversao e buscar_cep
  são puros (não dependem de UI) e foram mantidos exatamente iguais.
"""
import sys
import shutil
import logging
import urllib.request
import json
from datetime import datetime
from pathlib import Path

# ==========================================
# CAMINHOS (definidos em tempo de execução)
# ==========================================
BASE_DIR = None
DB_PATH = None
BACKUP_DIR = None
LOG_DIR = None
logger = None


def definir_base_dir(caminho: str):
    """
    Deve ser chamada UMA VEZ, no início do app (ex.: em App.build() ou
    App.on_start), passando:
      - Kivy: self.user_data_dir
      - Ainda rodando como script desktop: pode passar None, aí usa a
        pasta do próprio arquivo (comportamento antigo).

    Isso substitui o bloco antigo baseado em sys.frozen / __file__, porque
    no Android não existe "pasta do executável" com permissão de escrita.
    """
    global BASE_DIR, DB_PATH, BACKUP_DIR, LOG_DIR, logger

    if caminho:
        BASE_DIR = Path(caminho)
    elif getattr(sys, "frozen", False):
        BASE_DIR = Path(sys.executable).resolve().parent
    else:
        BASE_DIR = Path(__file__).resolve().parent

    DB_PATH = BASE_DIR / "sistema.db"
    BACKUP_DIR = BASE_DIR / "backups"
    LOG_DIR = BASE_DIR / "logs"

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = _configurar_logging()
    return BASE_DIR


def _configurar_logging():
    log_file = LOG_DIR / f"sistema_{datetime.now().strftime('%Y%m%d')}.log"
    log = logging.getLogger("sistema")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formato)
    log.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(formato)
    log.addHandler(sh)

    return log


# ==========================================
# BACKUP
# ==========================================
def fazer_backup_diario(max_backups=15):
    if not DB_PATH or not DB_PATH.exists():
        return None

    hoje = datetime.now().strftime("%Y%m%d")
    destino = BACKUP_DIR / f"sistema_{hoje}.db"

    if destino.exists():
        return destino

    try:
        shutil.copy2(DB_PATH, destino)
        logger.info(f"Backup criado: {destino}")

        backups = sorted(
            BACKUP_DIR.glob("sistema_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for antigo in backups[max_backups:]:
            try:
                antigo.unlink()
                logger.info(f"Backup antigo removido: {antigo}")
            except Exception as e:
                logger.warning(f"Falha ao remover backup antigo {antigo}: {e}")

        return destino
    except Exception as e:
        logger.error(f"Erro ao criar backup: {e}")
        return None


# ==========================================
# CEP (idêntico ao original — precisa da permissão de INTERNET no Android)
# ==========================================
def buscar_cep(cep: str) -> dict:
    cep_limpo = (cep or "").replace("-", "").replace(".", "").strip()
    if len(cep_limpo) != 8 or not cep_limpo.isdigit():
        raise ValueError("CEP inválido. Digite 8 dígitos.")

    url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
    with urllib.request.urlopen(url, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("erro"):
        raise ValueError("CEP não encontrado.")

    return {
        "logradouro": data.get("logradouro", ""),
        "bairro": data.get("bairro", ""),
        "cidade_uf": f"{data.get('localidade', '')} / {data.get('uf', '')}",
    }


# ==========================================
# FORMATAÇÃO DE MOEDA (idêntico ao original)
# ==========================================
def formatar_moeda(valor, com_simbolo=True):
    try:
        valor = float(valor or 0.0)
    except (TypeError, ValueError):
        valor = 0.0

    negativo = valor < 0
    valor = abs(valor)

    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")

    prefixo = "-" if negativo else ""
    return f"{prefixo}R$ {texto}" if com_simbolo else f"{prefixo}{texto}"


def desformatar_moeda(texto):
    if texto is None:
        return 0.0
    texto = str(texto).strip()
    if not texto:
        return 0.0

    texto = texto.replace("R$", "").replace("r$", "").strip()
    negativo = texto.startswith("-")
    texto = texto.lstrip("-").strip()

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        valor = float(texto)
    except ValueError:
        valor = 0.0
    return -valor if negativo else valor


def aplicar_fator_conversao(quantidade, custo_unitario, fator, operacao="MULTIPLICAR"):
    try:
        fator = float(fator)
    except (TypeError, ValueError):
        fator = 1.0
    if not fator or fator <= 0:
        fator = 1.0

    if (operacao or "MULTIPLICAR").strip().upper().startswith("DIV"):
        quantidade_final = quantidade / fator
        custo_final = custo_unitario * fator
    else:
        quantidade_final = quantidade * fator
        custo_final = custo_unitario / fator

    return quantidade_final, custo_final
