"""Funções utilitárias: caminhos, backup, logging, CEP, estilo de tabelas."""
import os
import sys
import shutil
import logging
import urllib.request
import json
from datetime import datetime
from pathlib import Path

# ==========================================
# CAMINHOS
# ==========================================
if getattr(sys, "frozen", False):
    # Rodando como EXE (PyInstaller) — usa a pasta do executável
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # Rodando como .py — usa a pasta do script
    BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "sistema.db"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR = BASE_DIR / "logs"

BACKUP_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# ==========================================
# LOGGING
# ==========================================
def configurar_logging():
    log_file = LOG_DIR / f"sistema_{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("sistema")


logger = configurar_logging()


# ==========================================
# BACKUP
# ==========================================
def fazer_backup_diario(max_backups=15):
    if not DB_PATH.exists():
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
# CEP
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
# FORMATAÇÃO DE MOEDA (padrão brasileiro)
# ==========================================
def formatar_moeda(valor, com_simbolo=True):
    """
    Formata um número no padrão monetário brasileiro: milhar com ponto,
    decimal com vírgula. Ex.: 1234.5 -> "R$ 1.234,50"; -30.92 -> "-R$ 30,92".

    Uso em f-strings: f"Total: {formatar_moeda(total)}"
    """
    try:
        valor = float(valor or 0.0)
    except (TypeError, ValueError):
        valor = 0.0

    negativo = valor < 0
    valor = abs(valor)

    texto = f"{valor:,.2f}"  # "1,234.50" (formato US: vírgula milhar, ponto decimal)
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")  # inverte p/ BR

    prefixo = "-" if negativo else ""
    return f"{prefixo}R$ {texto}" if com_simbolo else f"{prefixo}{texto}"


def desformatar_moeda(texto):
    """
    Converte um texto no formato monetário brasileiro (ex.: "R$ 1.234,56",
    "1.234,56" ou mesmo "1234.56") de volta para float. Complementa
    formatar_moeda(): use ao reaproveitar um valor já exibido/formatado
    (ex.: texto de uma tabela) para preencher um campo editável ou salvar.
    Simples "texto.replace(',', '.')" quebra quando há separador de milhar
    ("1.234,56" viraria "1.234.56"); esta função trata isso corretamente.
    """
    if texto is None:
        return 0.0
    texto = str(texto).strip()
    if not texto:
        return 0.0

    texto = texto.replace("R$", "").replace("r$", "").strip()
    negativo = texto.startswith("-")
    texto = texto.lstrip("-").strip()

    if "," in texto:
        # Formato BR: ponto é milhar, vírgula é decimal -> remove pontos, troca vírgula por ponto
        texto = texto.replace(".", "").replace(",", ".")
    # Se não há vírgula, assume que já está em formato numérico simples (ex.: "15.46")

    try:
        valor = float(texto)
    except ValueError:
        valor = 0.0
    return -valor if negativo else valor


def aplicar_fator_conversao(quantidade, custo_unitario, fator, operacao="MULTIPLICAR"):
    """
    Converte uma quantidade/custo de compra para a quantidade/custo que
    entra no estoque, de acordo com o fator de conversão e a operação:

    - MULTIPLICAR (padrão): comprou em unidades MAIORES que o estoque
      (ex.: comprou 1 caixa com 12 unidades -> estoque recebe 1 x 12 = 12).
      quantidade_final = quantidade x fator
      custo_final      = custo_unitario / fator

    - DIVIDIR: comprou em unidades MENORES que o estoque
      (ex.: comprou 480 unidades soltas mas o estoque controla em caixas
      de 12 -> estoque recebe 480 / 12 = 40 caixas).
      quantidade_final = quantidade / fator
      custo_final      = custo_unitario x fator

    Em ambos os casos o valor total (quantidade x custo) é preservado.
    """
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



def centralizar_janela(janela, largura, altura, deslocar_y=True):
    """
    Define a geometria de uma janela (CTk ou CTkToplevel) já centralizada
    na tela do usuário, com tamanho mínimo igual ao tamanho inicial.

    IMPORTANTE: substitui a chamada a `.geometry("LxA")` — não chame as
    duas. Faz apenas UMA chamada de geometry() com tamanho+posição juntos,
    pois no CustomTkinter chamar `.geometry()` duas vezes em sequência logo
    após criar um CTkToplevel pode fazer a janela renderizar com tamanho
    errado/cortado (a primeira chamada "gruda" antes da segunda ser
    processada). Por isso o cálculo aqui não depende de ler o tamanho atual
    da janela (nada de update_idletasks()/geometry() como leitura).

    Uso:
        top = ctk.CTkToplevel(self)
        top.title("Minha Janela")
        centralizar_janela(top, 500, 400)   # no lugar de top.geometry("500x400")
    """
    tela_largura = janela.winfo_screenwidth()
    tela_altura = janela.winfo_screenheight()

    x = max(0, (tela_largura - largura) // 2)
    # Levemente acima do centro vertical (mais natural que centro exato)
    y = max(0, (tela_altura - altura) // 2 - (40 if deslocar_y else 0))

    janela.geometry(f"{largura}x{altura}+{x}+{y}")
    try:
        janela.minsize(largura, altura)
    except Exception:
        pass

    trazer_janela_para_frente(janela)


def trazer_janela_para_frente(janela):
    """
    Garante que a janela apareça NA FRENTE de todas as outras ao ser aberta.

    Sem isso, algumas CTkToplevel (principalmente no Windows, quando já
    existem outras janelas abertas) podem nascer atrás da janela principal
    em vez de na frente, mesmo com .focus()/.grab_set() chamados. O truque
    de ligar e desligar "-topmost" força o gerenciador de janelas a
    trazê-la pro topo de verdade.

    Já é chamada automaticamente por centralizar_janela(); só use direto
    se precisar reforçar o foco numa janela que não usa centralizar_janela.
    """
    try:
        janela.lift()
        janela.focus_force()
        janela.attributes("-topmost", True)
        janela.after(200, lambda: janela.attributes("-topmost", False))
    except Exception:
        pass



def aplicar_estilo_treeview(widget_treeview=None, nome_estilo="Dark.Treeview",
                            altura_linha=26, fonte_tamanho=11):
    """
    Aplica (ou registra) um estilo escuro consistente para ttk.Treeview.

    Uso:
        # 1) Registrar o estilo uma única vez (ex.: no __init__ da janela):
        aplicar_estilo_treeview(None, "Dark.Treeview")

        # 2) Aplicar na treeview ao criá-la:
        arv = ttk.Treeview(parent, columns=cols, show="headings",
                           style="Dark.Treeview")

    Parâmetros:
        widget_treeview : se passado, já aplica o estilo nele.
                          Passe None apenas para registrar o estilo.
        nome_estilo     : nome do estilo (permite variações, ex.: "DarkSmall.Treeview").
        altura_linha    : altura de cada linha em pixels.
        fonte_tamanho   : tamanho da fonte.
    """
    from tkinter import ttk
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        nome_estilo,
        background="#2b2b2b",
        foreground="white",
        fieldbackground="#2b2b2b",
        rowheight=altura_linha,
        font=("Arial", fonte_tamanho),
        borderwidth=0,
    )
    style.configure(
        f"{nome_estilo}.Heading",
        background="#3a3a3a",
        foreground="white",
        font=("Arial", fonte_tamanho, "bold"),
        relief="flat",
    )
    style.map(
        nome_estilo,
        background=[("selected", "#1f538d")],
        foreground=[("selected", "white")],
    )
    style.map(
        f"{nome_estilo}.Heading",
        background=[("active", "#4a4a4a")],
    )

    if widget_treeview is not None:
        try:
            widget_treeview.configure(style=nome_estilo)
        except Exception:
            pass
    return nome_estilo