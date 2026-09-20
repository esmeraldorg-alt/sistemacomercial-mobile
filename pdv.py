"""
PDV (Frente de Caixa) — equivalente a PDVWindow (modulo_pdv.py original).

Escopo desta Fase 3: adicionar produto (código/nome/fracionado), carrinho,
desconto, seleção de cliente, pagamento (simples, múltiplo, a prazo, saldo
crédito, vale crédito) e finalização da venda — batendo com a mesma lógica
de `concluir_gravacao_venda` do original.

Ainda NÃO incluído (fica pra uma próxima fase, como combinamos):
- Salvar/recuperar Orçamentos
- Histórico de vendas / reimpressão de comprovante
- Configuração de impressora (não se aplica da mesma forma no Android)
"""
from datetime import datetime, timedelta

from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp

import utils_mobile as utils
from components import (
    TabelaDados, criar_bloco_tabela, criar_cabecalho, label_esquerda,
    mostrar_popup, confirmar_popup,
    COR_VERDE, COR_AZUL, COR_LARANJA, COR_VERMELHO, COR_CINZA,
)

from database import (
    criar_conexao, registrar_auditoria, obter_caixa_aberto,
    registrar_movimentacao_estoque, obter_total_fiados_abertos_cliente,
    obter_formas_pagamento, obter_credito_cliente, usar_credito_cliente,
    obter_saldo_vale_credito, usar_vale_credito, obter_promocao_vigente,
)

FORMAS_PAGAMENTO_MODAL = [
    "DINHEIRO", "PIX", "DEBITO", "CREDITO", "A PRAZO",
    "SALDO CREDITO", "VALE CREDITO",
]


def _resolver_preco_promocional(produto_id, preco_base):
    try:
        promo = obter_promocao_vigente(produto_id)
    except Exception as e:
        utils.logger.exception(f"Erro ao verificar promoção do produto {produto_id}: {e}")
        promo = None
    if promo:
        return promo["preco_promocional"], {
            "promocao_id": promo["id"],
            "preco_original": preco_base,
            "data_fim": promo["data_fim"],
        }
    return preco_base, None


# ==========================================
# BUSCA DE PRODUTO (F6)
# ==========================================
class BuscaProdutoPopup(Popup):
    def __init__(self, ao_selecionar, **kwargs):
        kwargs.setdefault("title", "Pesquisa de Produtos")
        kwargs.setdefault("size_hint", (0.92, 0.9))
        super().__init__(**kwargs)
        self.ao_selecionar = ao_selecionar
        self._montar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        self.e_filtro = TextInput(hint_text="Filtrar por nome ou código...",
                                   multiline=False, size_hint_y=None, height=dp(44))
        self.e_filtro.bind(text=lambda inst, val: self._carregar(val))
        raiz.add_widget(self.e_filtro)

        titulos = ["Código", "Nome", "Preço", "Estoque"]
        larguras = [1, 3, 1, 1]
        raiz.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, selecionavel=True,
                                   callback_selecao=self._selecionou)
        raiz.add_widget(self.tabela)
        self.content = raiz
        self._carregar("")

    def _carregar(self, filtro):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            if filtro:
                cursor.execute(
                    "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                    "FROM produtos WHERE (nome LIKE ? OR codigo_barras LIKE ?) "
                    "AND ativo = 1 LIMIT 200",
                    (f"%{filtro}%", f"%{filtro}%"))
            else:
                cursor.execute(
                    "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                    "FROM produtos WHERE ativo = 1 LIMIT 200")
            linhas, extra = [], []
            for row in cursor.fetchall():
                linhas.append([row["codigo_barras"] or "-", row["nome"],
                                utils.formatar_moeda(row["preco_venda"]),
                                f"{row['estoque']:.2f}"])
                extra.append(dict(row))
            self.tabela.set_dados(linhas, "Nenhum produto encontrado.", dados_extra=extra)
        except Exception as e:
            utils.logger.exception(f"Erro ao buscar produtos: {e}")
        finally:
            if conn:
                conn.close()

    def _selecionou(self, produto):
        self.dismiss()
        self.ao_selecionar(produto)


# ==========================================
# SELEÇÃO DE CLIENTE (F9)
# ==========================================
class SelecaoClientePopup(Popup):
    def __init__(self, ao_selecionar, **kwargs):
        kwargs.setdefault("title", "Selecionar Cliente")
        kwargs.setdefault("size_hint", (0.9, 0.85))
        super().__init__(**kwargs)
        self.ao_selecionar = ao_selecionar
        self._montar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        e_filtro = TextInput(hint_text="Filtrar por nome...", multiline=False,
                              size_hint_y=None, height=dp(44))
        e_filtro.bind(text=lambda inst, val: self._carregar(val))
        raiz.add_widget(e_filtro)

        titulos = ["Nome", "Telefone", "Limite Créd.", "Saldo Créd."]
        larguras = [2.2, 1.2, 1, 1]
        raiz.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, selecionavel=True,
                                   callback_selecao=self._selecionou)
        raiz.add_widget(self.tabela)
        self.content = raiz
        self._carregar("")

    def _carregar(self, filtro):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            if filtro:
                cursor.execute(
                    "SELECT id, nome, telefone, limite_credito, credito_saldo "
                    "FROM clientes WHERE nome LIKE ? LIMIT 200", (f"%{filtro}%",))
            else:
                cursor.execute(
                    "SELECT id, nome, telefone, limite_credito, credito_saldo "
                    "FROM clientes LIMIT 200")
            linhas, extra = [], []
            for row in cursor.fetchall():
                linhas.append([row["nome"], row["telefone"] or "N/D",
                                utils.formatar_moeda(row["limite_credito"]),
                                utils.formatar_moeda(row["credito_saldo"] or 0.0)])
                extra.append(dict(row))
            self.tabela.set_dados(linhas, "Nenhum cliente encontrado.", dados_extra=extra)
        except Exception as e:
            utils.logger.exception(f"Erro ao buscar clientes: {e}")
        finally:
            if conn:
                conn.close()

    def _selecionou(self, cliente):
        self.dismiss()
        self.ao_selecionar(cliente)


# ==========================================
# PRODUTO FRACIONADO (peso x valor)
# ==========================================
class ProdutoFracionadoPopup(Popup):
    def __init__(self, produto, unidade, preco, promo_info, ao_confirmar, **kwargs):
        kwargs.setdefault("title", "Produto Fracionado")
        kwargs.setdefault("size_hint", (0.85, None))
        kwargs.setdefault("height", dp(420))
        super().__init__(**kwargs)
        self.produto, self.unidade, self.preco = produto, unidade, preco
        self.promo_info, self.ao_confirmar = promo_info, ao_confirmar
        self._sincronizando = False
        self._montar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        raiz.add_widget(label_esquerda(self.produto["nome"], bold=True,
                                        font_size="15sp", halign="center",
                                        size_hint_y=None, height=dp(44)))
        texto_preco = f"Preço: {utils.formatar_moeda(self.preco)} / {self.unidade}"
        if self.promo_info:
            texto_preco += "  (PROMOÇÃO)"
        raiz.add_widget(label_esquerda(
            texto_preco, halign="center", size_hint_y=None, height=dp(22),
            color=COR_LARANJA if self.promo_info else COR_CINZA))

        raiz.add_widget(label_esquerda(
            f"Peso / Quantidade ({self.unidade}):", size_hint_y=None, height=dp(20)))
        self.e_peso = TextInput(text="1.000", multiline=False, input_filter="float",
                                 size_hint_y=None, height=dp(46), font_size="16sp")
        raiz.add_widget(self.e_peso)

        raiz.add_widget(label_esquerda("Valor (R$):", size_hint_y=None, height=dp(20)))
        self.e_valor = TextInput(multiline=False, input_filter="float",
                                  size_hint_y=None, height=dp(46), font_size="16sp")
        raiz.add_widget(self.e_valor)

        self.e_peso.bind(text=self._por_peso)
        self.e_valor.bind(text=self._por_valor)
        self._por_peso(self.e_peso, self.e_peso.text)

        btn = Button(text="Adicionar ao Carrinho", size_hint_y=None, height=dp(48),
                     background_color=COR_VERDE)
        btn.bind(on_release=self._confirmar)
        raiz.add_widget(btn)
        self.content = raiz

    def _por_peso(self, inst, valor):
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            peso = float((valor or "0").replace(",", "."))
        except ValueError:
            peso = 0.0
        self.e_valor.text = f"{peso * self.preco:.2f}"
        self._sincronizando = False

    def _por_valor(self, inst, valor):
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            v = float((valor or "0").replace(",", "."))
        except ValueError:
            v = 0.0
        peso = (v / self.preco) if self.preco > 0 else 0.0
        self.e_peso.text = f"{peso:.3f}"
        self._sincronizando = False

    def _confirmar(self, *_):
        try:
            peso = float((self.e_peso.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Peso/quantidade inválido.")
            return
        if peso <= 0:
            mostrar_popup("Erro", "Informe um peso/quantidade maior que zero.")
            return
        self.dismiss()
        self.ao_confirmar(peso)


# ==========================================
# DESCONTO (F7)
# ==========================================
class DescontoPopup(Popup):
    def __init__(self, subtotal, desconto_atual, ao_confirmar, **kwargs):
        kwargs.setdefault("title", "Aplicar Desconto")
        kwargs.setdefault("size_hint", (0.85, None))
        kwargs.setdefault("height", dp(380))
        super().__init__(**kwargs)
        self.subtotal = subtotal
        self.ao_confirmar = ao_confirmar
        self._sincronizando = False
        self._montar(desconto_atual)

    def _montar(self, desconto_atual):
        raiz = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        raiz.add_widget(label_esquerda(
            f"Subtotal: {utils.formatar_moeda(self.subtotal)}", bold=True,
            halign="center", size_hint_y=None, height=dp(26)))

        raiz.add_widget(label_esquerda("Desconto em R$:", size_hint_y=None, height=dp(20)))
        self.e_valor = TextInput(text=f"{desconto_atual:.2f}", multiline=False,
                                  input_filter="float", size_hint_y=None, height=dp(44))
        raiz.add_widget(self.e_valor)

        raiz.add_widget(label_esquerda("Desconto em %:", size_hint_y=None, height=dp(20)))
        pct_inicial = (desconto_atual / self.subtotal * 100.0) if self.subtotal > 0 else 0.0
        self.e_pct = TextInput(text=f"{pct_inicial:.2f}", multiline=False,
                                input_filter="float", size_hint_y=None, height=dp(44))
        raiz.add_widget(self.e_pct)

        self.lbl_calc = label_esquerda(
            f"Total com desconto: {utils.formatar_moeda(self.subtotal - desconto_atual)}",
            halign="center", color=COR_VERDE, bold=True,
            size_hint_y=None, height=dp(26))
        raiz.add_widget(self.lbl_calc)

        atalhos = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        for p in (5, 10, 15, 20):
            b = Button(text=f"{p}%")
            b.bind(on_release=lambda _b, pp=p: self._set_pct(pp))
            atalhos.add_widget(b)
        raiz.add_widget(atalhos)

        self.e_valor.bind(text=self._por_valor)
        self.e_pct.bind(text=self._por_pct)

        linha_btn = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        btn_ok = Button(text="Confirmar", background_color=COR_VERDE)
        btn_ok.bind(on_release=self._confirmar)
        btn_zerar = Button(text="Zerar", background_color=COR_CINZA)
        btn_zerar.bind(on_release=self._zerar)
        linha_btn.add_widget(btn_zerar)
        linha_btn.add_widget(btn_ok)
        raiz.add_widget(linha_btn)
        self.content = raiz

    def _set_pct(self, p):
        self.e_pct.text = f"{p:.2f}"

    def _por_valor(self, inst, valor):
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            v = max(0.0, min(float((valor or "0").replace(",", ".")), self.subtotal))
        except ValueError:
            v = 0.0
        pct = (v / self.subtotal * 100.0) if self.subtotal > 0 else 0.0
        self.e_pct.text = f"{pct:.2f}"
        self.lbl_calc.text = f"Total com desconto: {utils.formatar_moeda(self.subtotal - v)}"
        self._sincronizando = False

    def _por_pct(self, inst, valor):
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            p = max(0.0, min(float((valor or "0").replace(",", ".")), 100.0))
        except ValueError:
            p = 0.0
        v = self.subtotal * (p / 100.0)
        self.e_valor.text = f"{v:.2f}"
        self.lbl_calc.text = f"Total com desconto: {utils.formatar_moeda(self.subtotal - v)}"
        self._sincronizando = False

    def _confirmar(self, *_):
        try:
            d = float((self.e_valor.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Valor inválido.")
            return
        if d < 0 or d > self.subtotal + 0.001:
            mostrar_popup("Erro", "Desconto inválido para este subtotal.")
            return
        self.dismiss()
        self.ao_confirmar(d)

    def _zerar(self, *_):
        self.dismiss()
        self.ao_confirmar(0.0)


# ==========================================
# PAGAMENTO (F2)
# ==========================================
class PagamentoPopup(Popup):
    def __init__(self, pdv_screen, **kwargs):
        kwargs.setdefault("title", "Pagamento da Venda")
        kwargs.setdefault("size_hint", (0.92, 0.92))
        kwargs.setdefault("auto_dismiss", False)
        super().__init__(**kwargs)
        self.pdv = pdv_screen
        self.pagamentos = []
        subtotal = sum(i["quantidade"] * i["preco"] for i in self.pdv.carrinho)
        self.total_venda = max(0.0, subtotal - self.pdv.desconto)
        self.subtotal = subtotal
        self._montar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))

        raiz.add_widget(label_esquerda(
            f"Total: {utils.formatar_moeda(self.total_venda)}", bold=True,
            font_size="20sp", color=COR_VERDE, halign="center",
            size_hint_y=None, height=dp(34)))
        if self.pdv.desconto > 0.001:
            raiz.add_widget(label_esquerda(
                f"Subtotal: {utils.formatar_moeda(self.subtotal)}  |  "
                f"Desconto: -{utils.formatar_moeda(self.pdv.desconto)}",
                halign="center", color=COR_LARANJA, font_size="11sp",
                size_hint_y=None, height=dp(20)))

        raiz.add_widget(label_esquerda(
            f"Cliente: {self.pdv.cliente_nome}", size_hint_y=None, height=dp(20),
            color=COR_CINZA))

        raiz.add_widget(label_esquerda("Forma de Pagamento:", bold=True,
                                        size_hint_y=None, height=dp(22)))
        self.spinner_forma = Spinner(text="DINHEIRO", values=FORMAS_PAGAMENTO_MODAL,
                                      size_hint_y=None, height=dp(44))
        raiz.add_widget(self.spinner_forma)

        raiz.add_widget(label_esquerda("Valor a Lançar (R$):", bold=True,
                                        size_hint_y=None, height=dp(22)))
        linha_valor = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.e_valor = TextInput(text=f"{self.total_venda:.2f}", multiline=False,
                                  input_filter="float", font_size="15sp")
        linha_valor.add_widget(self.e_valor)
        btn_lancar = Button(text="Lançar [+]", size_hint_x=None, width=dp(120),
                             background_color=COR_AZUL)
        btn_lancar.bind(on_release=lambda *_: self._lancar())
        linha_valor.add_widget(btn_lancar)
        raiz.add_widget(linha_valor)

        titulos, larguras = ["Forma", "Valor Lançado"], [1, 1]
        raiz.add_widget(criar_cabecalho(titulos, larguras, altura=dp(28)))
        self.tabela_pg = TabelaDados(larguras=larguras, size_hint_y=None, height=dp(140),
                                      selecionavel=True, callback_selecao=self._remover)
        raiz.add_widget(self.tabela_pg)
        raiz.add_widget(label_esquerda(
            "Toque em um lançamento na lista pra remover.", font_size="10sp",
            color=COR_CINZA, halign="center", size_hint_y=None, height=dp(16)))

        self.lbl_status = label_esquerda(
            "", bold=True, font_size="14sp", halign="center", color=COR_LARANJA,
            size_hint_y=None, height=dp(26))
        raiz.add_widget(self.lbl_status)

        btn_finalizar = Button(text="Finalizar Pagamento", size_hint_y=None, height=dp(50),
                                background_color=COR_VERDE, bold=True)
        btn_finalizar.bind(on_release=lambda *_: self._confirmar())
        raiz.add_widget(btn_finalizar)

        btn_cancelar = Button(text="Cancelar", size_hint_y=None, height=dp(40))
        btn_cancelar.bind(on_release=lambda *_: self.dismiss())
        raiz.add_widget(btn_cancelar)

        self.content = raiz
        self._atualizar_resumo()

    def _lancar(self):
        try:
            val_inserido = float((self.e_valor.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Digite um valor numérico válido.")
            return
        if val_inserido <= 0:
            mostrar_popup("Erro", "O valor deve ser maior que zero.")
            return

        forma = self.spinner_forma.text

        if forma == "A PRAZO":
            if not self.pdv.cliente_id:
                mostrar_popup("Aviso", "Selecione um cliente para lançar A Prazo (F9).")
                return
            ja_lancado = sum(p["valor"] for p in self.pagamentos if p["forma"] == "A PRAZO")
            conn = None
            try:
                conn = criar_conexao()
                cur = conn.cursor()
                cur.execute("SELECT nome, limite_credito FROM clientes WHERE id = ?",
                            (self.pdv.cliente_id,))
                cli = cur.fetchone()
                if not cli:
                    mostrar_popup("Erro", "Cliente não encontrado.")
                    return
                limite = cli["limite_credito"] or 0.0
                em_aberto = obter_total_fiados_abertos_cliente(self.pdv.cliente_id)
                disponivel = limite - em_aberto - ja_lancado
                if limite <= 0:
                    mostrar_popup("Sem Limite",
                                  f"O cliente '{cli['nome']}' não tem limite de crédito "
                                  f"cadastrado.")
                    return
                if val_inserido > disponivel + 0.01:
                    mostrar_popup(
                        "Limite Excedido",
                        f"Limite: {utils.formatar_moeda(limite)}\n"
                        f"Já em aberto: {utils.formatar_moeda(em_aberto)}\n"
                        f"Disponível: {utils.formatar_moeda(disponivel)}")
                    return
            except Exception as e:
                utils.logger.exception(f"Erro ao validar limite de credito: {e}")
                mostrar_popup("Erro", str(e))
                return
            finally:
                if conn:
                    conn.close()

        elif forma == "SALDO CREDITO":
            if not self.pdv.cliente_id:
                mostrar_popup("Aviso", "Selecione um cliente para usar saldo de crédito (F9).")
                return
            ja_lancado = sum(p["valor"] for p in self.pagamentos if p["forma"] == "SALDO CREDITO")
            try:
                saldo = obter_credito_cliente(self.pdv.cliente_id)
            except Exception as e:
                mostrar_popup("Erro", str(e))
                return
            disponivel = saldo - ja_lancado
            if val_inserido > disponivel + 0.01:
                mostrar_popup("Saldo Insuficiente",
                              f"Saldo disponível: {utils.formatar_moeda(disponivel)}")
                return

        elif forma == "VALE CREDITO":
            self._pedir_codigo_vale(val_inserido)
            return

        self._adicionar_pagamento(forma, val_inserido)

    def _pedir_codigo_vale(self, valor):
        conteudo = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        conteudo.add_widget(label_esquerda(
            "Código do vale-crédito:", size_hint_y=None, height=dp(22)))
        e_codigo = TextInput(multiline=False, size_hint_y=None, height=dp(44))
        conteudo.add_widget(e_codigo)
        popup = Popup(title="Vale Crédito", content=conteudo,
                       size_hint=(0.8, None), height=dp(220), auto_dismiss=False)

        def confirmar(*_):
            codigo = (e_codigo.text or "").strip().upper()
            if not codigo:
                return
            try:
                saldo_vale = obter_saldo_vale_credito(codigo)
            except Exception as e:
                mostrar_popup("Erro", str(e))
                return
            if saldo_vale <= 0:
                mostrar_popup("Vale Inválido",
                              f"'{codigo}' não encontrado, já usado ou cancelado.")
                return
            if valor > saldo_vale + 0.01:
                mostrar_popup("Saldo Insuficiente",
                              f"Saldo do vale: {utils.formatar_moeda(saldo_vale)}")
                return
            popup.dismiss()
            self.pagamentos.append({"forma": "VALE CREDITO", "valor": valor, "codigo": codigo})
            self._atualizar_resumo()

        btn = Button(text="Confirmar", size_hint_y=None, height=dp(44),
                     background_color=COR_VERDE)
        btn.bind(on_release=confirmar)
        conteudo.add_widget(btn)
        popup.open()

    def _adicionar_pagamento(self, forma, valor):
        for p in self.pagamentos:
            if p["forma"] == forma:
                p["valor"] += valor
                self._atualizar_resumo()
                return
        self.pagamentos.append({"forma": forma, "valor": valor})
        self._atualizar_resumo()

    def _remover(self, pagamento):
        if pagamento in self.pagamentos:
            self.pagamentos.remove(pagamento)
            self._atualizar_resumo()

    def _atualizar_resumo(self):
        linhas = [[p["forma"], utils.formatar_moeda(p["valor"])] for p in self.pagamentos]
        self.tabela_pg.set_dados(linhas, "(nenhum lançamento)", dados_extra=list(self.pagamentos))

        total_lancado = sum(p["valor"] for p in self.pagamentos)
        diferenca = self.total_venda - total_lancado
        if diferenca > 0.01:
            self.lbl_status.text = f"Falta lançar: {utils.formatar_moeda(diferenca)}"
            self.lbl_status.color = COR_LARANJA
            self.e_valor.text = f"{diferenca:.2f}"
        elif diferenca < -0.01:
            self.lbl_status.text = f"Troco: {utils.formatar_moeda(abs(diferenca))}"
            self.lbl_status.color = COR_VERDE
            self.e_valor.text = "0.00"
        else:
            self.lbl_status.text = "Pagamento completo!"
            self.lbl_status.color = COR_VERDE
            self.e_valor.text = "0.00"

    def _confirmar(self):
        if not self.pagamentos:
            self._lancar()
        total_lancado = sum(p["valor"] for p in self.pagamentos)
        if total_lancado < self.total_venda - 0.01:
            mostrar_popup("Erro", f"Valor lançado insuficiente. Falta "
                                   f"{utils.formatar_moeda(self.total_venda - total_lancado)}")
            return

        troco = max(0.0, total_lancado - self.total_venda)
        valor_fiado = sum(p["valor"] for p in self.pagamentos if p["forma"] == "A PRAZO")
        valor_credito_usado = sum(p["valor"] for p in self.pagamentos if p["forma"] == "SALDO CREDITO")

        dados_fiado = None
        if valor_fiado > 0.001:
            if not self.pdv.cliente_id:
                mostrar_popup("Aviso", "Selecione um cliente para o valor A Prazo (F9).")
                return
            vencimento = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            dados_fiado = {"cliente_id": self.pdv.cliente_id, "vencimento": vencimento,
                           "valor": valor_fiado}

        if len(self.pagamentos) == 1:
            forma_principal = ("FIADO" if self.pagamentos[0]["forma"] == "A PRAZO"
                               else self.pagamentos[0]["forma"])
        else:
            forma_principal = "MULTIPLO"

        ok = self.pdv.concluir_gravacao_venda(
            forma_principal, self.total_venda, total_lancado, troco,
            subtotal=self.subtotal, desconto=self.pdv.desconto,
            dados_fiado=dados_fiado, pagamentos=self.pagamentos,
            valor_credito_usado=valor_credito_usado)
        if ok:
            self.dismiss()


# ==========================================
# CARD DE PRODUTO (grade "toque pra adicionar")
# ==========================================
class CartaoProduto(ButtonBehavior, BoxLayout):
    def __init__(self, produto, ao_tocar, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(10))
        kwargs.setdefault("spacing", dp(4))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(88))
        super().__init__(**kwargs)
        self.produto = produto
        self.ao_tocar = ao_tocar

        with self.canvas.before:
            self._cor_fundo = Color(0.14, 0.16, 0.21, 1)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._atualizar, size=self._atualizar)

        lbl_nome = label_esquerda(produto["nome"], halign="center", bold=True,
                                   font_size="12sp", color=(0.92, 0.93, 0.96, 1))
        self.add_widget(lbl_nome)

        sem_estoque = (produto["estoque"] or 0) <= 0
        cor_preco = COR_VERMELHO if sem_estoque else COR_VERDE
        texto_preco = "SEM ESTOQUE" if sem_estoque else utils.formatar_moeda(produto["preco_venda"])
        self.add_widget(label_esquerda(texto_preco, halign="center", bold=True,
                                        font_size="13sp", color=cor_preco,
                                        size_hint_y=None, height=dp(20)))
        if not sem_estoque:
            self.add_widget(label_esquerda(
                f"Disp.: {produto['estoque']:.2f} {(produto.get('unidade') or 'UN')}",
                halign="center", font_size="9sp", color=COR_CINZA,
                size_hint_y=None, height=dp(14)))
        self.disabled = sem_estoque
        if sem_estoque:
            self._cor_fundo.rgba = (0.10, 0.10, 0.12, 1)

    def _atualizar(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def on_release(self):
        self.ao_tocar(self.produto)


# ==========================================
# TELA DO PDV
# equivalente a PDVWindow (modulo_pdv.py)
# ==========================================
class PDVScreen(Screen):
    def on_pre_enter(self, *args):
        app = App.get_running_app()
        if not getattr(self, "_construido", False):
            self._construir(app)
            self._construido = True
        else:
            self.usuario_nome = app.usuario_atual[1] if app.usuario_atual else "desconhecido"
        self._checar_caixa()

    def _construir(self, app):
        self.app_ref = app
        self.usuario_nome = app.usuario_atual[1] if app.usuario_atual else "desconhecido"
        self.carrinho = []
        self.desconto = 0.0
        self.cliente_id = None
        self.cliente_nome = "Consumidor Final"
        self.qtd_pendente = None
        self.caixa_id = None

        try:
            self.formas_rapidas = obter_formas_pagamento(apenas_ativas=True)
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar formas de pagamento: {e}")
            self.formas_rapidas = []

        raiz = BoxLayout(orientation="vertical")

        # ---- topo ----
        topo = BoxLayout(size_hint_y=None, height=dp(70), padding=dp(12), spacing=dp(10))
        info_cli = BoxLayout(orientation="vertical", size_hint_x=2)
        self.lbl_cliente = label_esquerda(
            f"Cliente: {self.cliente_nome}", bold=True, color=(0.25, 0.82, 0.88, 1),
            shorten=True, shorten_from="right", font_size="13sp")
        info_cli.add_widget(self.lbl_cliente)
        btn_trocar_cli = Button(text="Trocar Cliente (F9)", size_hint_y=None, height=dp(30))
        btn_trocar_cli.bind(on_release=lambda *_: self.abrir_selecao_cliente())
        info_cli.add_widget(btn_trocar_cli)
        topo.add_widget(info_cli)

        self.lbl_qtd_pendente = label_esquerda(
            "Qtd padrão: 1.0", halign="center", color=COR_VERDE)
        topo.add_widget(self.lbl_qtd_pendente)

        info_total = BoxLayout(orientation="vertical", size_hint_x=1.4)
        info_total.add_widget(label_esquerda(
            "TOTAL A PAGAR", halign="right", font_size="10sp", color=COR_CINZA,
            size_hint_y=None, height=dp(16)))
        self.lbl_total = label_esquerda(
            "R$ 0,00", halign="right", bold=True, font_size="24sp", color=COR_VERDE)
        info_total.add_widget(self.lbl_total)
        topo.add_widget(info_total)
        raiz.add_widget(topo)

        # ---- barra de código ----
        barra_codigo = BoxLayout(size_hint_y=None, height=dp(50), padding=(dp(10), 0), spacing=dp(8))
        barra_codigo.add_widget(label_esquerda(
            "Código / Qtd*Código:", size_hint_x=None, width=dp(160)))
        self.e_codigo = TextInput(multiline=False, font_size="15sp")
        self.e_codigo.bind(on_text_validate=lambda *_: self.adicionar_produto_por_codigo())
        barra_codigo.add_widget(self.e_codigo)
        btn_buscar = Button(text="Buscar (F6)", size_hint_x=None, width=dp(130),
                             background_color=COR_LARANJA)
        btn_buscar.bind(on_release=lambda *_: self.abrir_busca_produtos())
        barra_codigo.add_widget(btn_buscar)
        raiz.add_widget(barra_codigo)

        # ---- meio: produtos/carrinho + botões ----
        meio = BoxLayout(padding=dp(10), spacing=dp(10))

        abas_esquerda = TabbedPanel(do_default_tab=False, tab_width=dp(130),
                                     size_hint_x=2.6)

        aba_produtos = TabbedPanelItem(text="Produtos")
        aba_produtos.add_widget(self._criar_aba_produtos())
        abas_esquerda.add_widget(aba_produtos)

        aba_carrinho = TabbedPanelItem(text="Carrinho")
        aba_carrinho.add_widget(self._criar_aba_carrinho())
        abas_esquerda.add_widget(aba_carrinho)

        abas_esquerda.default_tab = aba_produtos
        meio.add_widget(abas_esquerda)

        col_botoes = ScrollView(size_hint_x=1.1)
        caixa_botoes = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6),
                                  padding=(dp(4), 0))
        caixa_botoes.bind(minimum_height=caixa_botoes.setter("height"))

        def botao(texto, cor, acao, altura=44):
            b = Button(text=texto, size_hint_y=None, height=dp(altura),
                       background_color=cor)
            b.bind(on_release=lambda *_: acao())
            caixa_botoes.add_widget(b)
            return b

        botao("Pagamentos (F2)", COR_VERDE, self.finalizar_venda_modal, 52)
        for forma in self.formas_rapidas:
            nome = forma["nome"]
            botao(nome, COR_AZUL, lambda f=nome: self.finalizar_venda_rapida(f), 40)
        botao("Remover Item (F4)", COR_VERMELHO, self.remover_item_selecionado)
        botao("Aplicar Desconto (F7)", COR_LARANJA, self.aplicar_desconto)
        botao("Cancelar Venda (F5)", COR_CINZA, self.cancelar_venda_completa)
        botao("Voltar ao Menu", (0.25, 0.27, 0.33, 1), self.voltar_ao_menu)

        col_botoes.add_widget(caixa_botoes)
        meio.add_widget(col_botoes)
        raiz.add_widget(meio)

        self.add_widget(raiz)
        self._atualizar_carrinho()

    def _criar_aba_produtos(self):
        col = BoxLayout(orientation="vertical", spacing=dp(6), padding=(dp(4), dp(6)))
        e_filtro = TextInput(hint_text="Filtrar produtos por nome ou código...",
                              multiline=False, size_hint_y=None, height=dp(42))
        e_filtro.bind(text=lambda inst, val: self._recarregar_grade(val))
        col.add_widget(e_filtro)
        self.scroll_grade = ScrollView()
        self.grade_produtos = GridLayout(cols=3, spacing=dp(8), size_hint_y=None,
                                          padding=(0, dp(4)), col_force_default=True)
        self.grade_produtos.bind(minimum_height=self.grade_produtos.setter("height"))
        self.grade_produtos.bind(width=self._recalcular_largura_colunas)
        self.scroll_grade.add_widget(self.grade_produtos)
        col.add_widget(self.scroll_grade)
        self._recarregar_grade("")
        return col

    def _recalcular_largura_colunas(self, inst, largura):
        n_cols = inst.cols or 1
        espaco = inst.spacing[0] * (n_cols - 1) if inst.spacing else 0
        inst.col_default_width = max(dp(110), (largura - espaco) / n_cols)

    def _criar_aba_carrinho(self):
        col = BoxLayout(orientation="vertical")
        titulos = ["Cód.", "Produto", "Qtd", "Preço", "Subtotal"]
        larguras = [1, 3, 0.8, 1, 1]
        col.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela_carrinho = TabelaDados(larguras=larguras, selecionavel=True,
                                            callback_selecao=self._selecionar_item_remover)
        col.add_widget(self.tabela_carrinho)
        self.lbl_qtd_itens = label_esquerda(
            "Total de Itens: 0,00", size_hint_y=None, height=dp(22), color=COR_LARANJA)
        col.add_widget(self.lbl_qtd_itens)
        return col

    def _recarregar_grade(self, filtro=""):
        self._filtro_grade_atual = filtro
        self.grade_produtos.clear_widgets()
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            if filtro:
                cursor.execute(
                    "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                    "FROM produtos WHERE ativo = 1 AND (nome LIKE ? OR codigo_barras LIKE ?) "
                    "ORDER BY nome LIMIT 300", (f"%{filtro}%", f"%{filtro}%"))
            else:
                cursor.execute(
                    "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                    "FROM produtos WHERE ativo = 1 ORDER BY nome LIMIT 300")
            linhas = cursor.fetchall()
            if not linhas:
                self.grade_produtos.add_widget(label_esquerda(
                    "Nenhum produto cadastrado ainda.\nUse 'Cadastrar Produto Rápido' "
                    "no Menu Principal.", halign="center", color=COR_CINZA,
                    size_hint_y=None, height=dp(60)))
            for row in linhas:
                prod = dict(row)
                ja_no_carrinho = sum(i["quantidade"] for i in self.carrinho if i["id"] == prod["id"])
                prod["estoque"] = max(0.0, prod["estoque"] - ja_no_carrinho)
                self.grade_produtos.add_widget(
                    CartaoProduto(prod, self._tocar_produto_grade))
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar grade de produtos: {e}")
        finally:
            if conn:
                conn.close()

    def _tocar_produto_grade(self, prod):
        p_unidade = (prod["unidade"] or "UN").strip().upper()
        fracionado = p_unidade != "UN"
        qtd = self.qtd_pendente if self.qtd_pendente is not None else 1.0
        qtd_explicita = self.qtd_pendente is not None

        if fracionado and not qtd_explicita:
            preco, promo = _resolver_preco_promocional(prod["id"], prod["preco_venda"])

            def ao_confirmar(peso, p=prod, pr=preco, pm=promo):
                self._inserir_item_carrinho(
                    p["id"], p["codigo_barras"], p["nome"], pr, p["estoque"], peso, pm)
                self._recarregar_grade(getattr(self, "_filtro_grade_atual", ""))

            ProdutoFracionadoPopup(prod, p_unidade, preco, promo, ao_confirmar).open()
            return

        preco, promo = _resolver_preco_promocional(prod["id"], prod["preco_venda"])
        ok = self._inserir_item_carrinho(prod["id"], prod["codigo_barras"], prod["nome"],
                                         preco, prod["estoque"], qtd, promo)
        self.qtd_pendente = None
        self.lbl_qtd_pendente.text = "Qtd padrão: 1.0"
        self.lbl_qtd_pendente.color = COR_VERDE
        if ok:
            self._recarregar_grade(getattr(self, "_filtro_grade_atual", ""))

    def _checar_caixa(self):
        caixa = obter_caixa_aberto()
        self.caixa_id = caixa["id"] if caixa else None
        if not caixa:
            mostrar_popup("Caixa Fechado",
                          "Nenhum caixa aberto. Abra o caixa antes de vender.")

    def voltar_ao_menu(self):
        if self.carrinho:
            confirmar_popup(
                "Sair do PDV",
                "Existe uma venda em andamento. Sair e perder o carrinho?",
                self._voltar_confirmado)
        else:
            self._voltar_confirmado()

    def _voltar_confirmado(self):
        self.carrinho, self.desconto = [], 0.0
        self.cliente_id, self.cliente_nome = None, "Consumidor Final"
        self.qtd_pendente = None
        self.lbl_cliente.text = f"Cliente: {self.cliente_nome}"
        self._atualizar_carrinho()
        self.app_ref.sm.current = "principal"    # ---- adicionar produto ----
    def adicionar_produto_por_codigo(self):
        texto = (self.e_codigo.text or "").strip()
        if not texto:
            return

        if texto.endswith("*") and len(texto) > 1:
            try:
                val_qtd = float(texto[:-1].strip().replace(",", "."))
                if val_qtd > 0:
                    self.qtd_pendente = val_qtd
                    self.lbl_qtd_pendente.text = f"Qtd travada: {val_qtd:.2f}"
                    self.lbl_qtd_pendente.color = COR_LARANJA
                    self.e_codigo.text = ""
                    return
            except ValueError:
                pass

        qtd, termo, qtd_explicita = 1.0, texto, False
        if self.qtd_pendente is not None:
            qtd, qtd_explicita = self.qtd_pendente, True
        if "*" in texto:
            partes = texto.split("*", 1)
            try:
                qtd = float(partes[0].strip().replace(",", "."))
                termo = partes[1].strip()
                qtd_explicita = True
            except ValueError:
                pass

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                "FROM produtos WHERE (codigo_barras = ? OR id = ?) AND ativo = 1",
                (termo, termo))
            prod = cursor.fetchone()
            if not prod:
                cursor.execute(
                    "SELECT id, codigo_barras, nome, preco_venda, estoque, unidade "
                    "FROM produtos WHERE nome LIKE ? AND ativo = 1 LIMIT 1",
                    (f"%{termo}%",))
                prod = cursor.fetchone()
            if not prod:
                mostrar_popup("Aviso", f"Produto '{termo}' não encontrado!")
                self.e_codigo.text = ""
                return

            p_unidade = (prod["unidade"] or "UN").strip().upper()
            fracionado = p_unidade != "UN"

            if fracionado and not qtd_explicita:
                self.e_codigo.text = ""
                preco, promo = _resolver_preco_promocional(prod["id"], prod["preco_venda"])
                produto_dict = dict(prod)

                def ao_confirmar(peso, p=produto_dict, pr=preco, pm=promo):
                    self._inserir_item_carrinho(
                        p["id"], p["codigo_barras"], p["nome"], pr, p["estoque"], peso, pm)

                ProdutoFracionadoPopup(produto_dict, p_unidade, preco, promo,
                                       ao_confirmar).open()
                return

            preco, promo = _resolver_preco_promocional(prod["id"], prod["preco_venda"])
            self._inserir_item_carrinho(prod["id"], prod["codigo_barras"], prod["nome"],
                                        preco, prod["estoque"], qtd, promo)
            self.e_codigo.text = ""
            self.qtd_pendente = None
            self.lbl_qtd_pendente.text = "Qtd padrão: 1.0"
            self.lbl_qtd_pendente.color = COR_VERDE
        except Exception as e:
            utils.logger.exception(f"Erro ao adicionar produto: {e}")
            mostrar_popup("Erro", f"Erro ao adicionar: {e}")
        finally:
            if conn:
                conn.close()

    def _inserir_item_carrinho(self, p_id, p_cod, p_nome, p_preco, p_estoque, qtd, promo_info=None):
        qtd_ja = sum(i["quantidade"] for i in self.carrinho if i["id"] == p_id)
        if (qtd_ja + qtd) > p_estoque:
            mostrar_popup("Estoque Insuficiente",
                          f"'{p_nome}' tem apenas {p_estoque:.2f} em estoque.")
            return False
        for item in self.carrinho:
            if item["id"] == p_id:
                item["quantidade"] += qtd
                self._atualizar_carrinho()
                return True
        novo = {"id": p_id, "codigo": p_cod, "nome": p_nome, "preco": p_preco, "quantidade": qtd}
        if promo_info:
            novo["em_promocao"] = True
            novo["preco_original"] = promo_info["preco_original"]
        self.carrinho.append(novo)
        self._atualizar_carrinho()
        return True

    def abrir_busca_produtos(self):
        def ao_selecionar(produto):
            self.e_codigo.text = produto["codigo_barras"] or str(produto["id"])
            self.adicionar_produto_por_codigo()
        BuscaProdutoPopup(ao_selecionar).open()

    def abrir_selecao_cliente(self):
        def ao_selecionar(cliente):
            self.cliente_id = cliente["id"]
            self.cliente_nome = cliente["nome"]
            self.lbl_cliente.text = f"Cliente: {self.cliente_nome}"
        SelecaoClientePopup(ao_selecionar).open()

    def aplicar_desconto(self):
        if not self.carrinho:
            mostrar_popup("Aviso", "Carrinho vazio!")
            return
        subtotal = sum(i["quantidade"] * i["preco"] for i in self.carrinho)

        def ao_confirmar(valor):
            self.desconto = valor
            self._atualizar_carrinho()

        DescontoPopup(subtotal, self.desconto, ao_confirmar).open()

    def _selecionar_item_remover(self, item):
        confirmar_popup("Remover Item", f"Remover '{item['nome']}' do carrinho?",
                        lambda: self._remover_item(item))

    def _remover_item(self, item):
        if item in self.carrinho:
            self.carrinho.remove(item)
            self._atualizar_carrinho()
            if hasattr(self, "grade_produtos"):
                self._recarregar_grade(getattr(self, "_filtro_grade_atual", ""))

    def remover_item_selecionado(self):
        mostrar_popup("Remover Item", "Toque no item da lista pra removê-lo.")

    def cancelar_venda_completa(self):
        if not self.carrinho:
            return
        confirmar_popup("Cancelar Venda",
                        "Deseja limpar todos os itens e cancelar a venda?",
                        self._cancelar_confirmado)

    def _cancelar_confirmado(self):
        self.carrinho, self.desconto = [], 0.0
        self.cliente_id, self.cliente_nome = None, "Consumidor Final"
        self.qtd_pendente = None
        self.lbl_cliente.text = f"Cliente: {self.cliente_nome}"
        self._atualizar_carrinho()
        if hasattr(self, "grade_produtos"):
            self._recarregar_grade()

    def _atualizar_carrinho(self):
        linhas, extra = [], []
        subtotal, total_itens = 0.0, 0.0
        for item in self.carrinho:
            sub = item["quantidade"] * item["preco"]
            subtotal += sub
            total_itens += item["quantidade"]
            nome = ("[PROMO] " + item["nome"]) if item.get("em_promocao") else item["nome"]
            linhas.append([item["codigo"] or "-", nome, f"{item['quantidade']:.2f}",
                            utils.formatar_moeda(item["preco"]), utils.formatar_moeda(sub)])
            extra.append(item)
        self.tabela_carrinho.set_dados(linhas, "Carrinho vazio", dados_extra=extra)

        self.desconto = max(0.0, min(self.desconto, subtotal))
        total_final = subtotal - self.desconto
        if self.desconto > 0.001:
            self.lbl_total.text = (f"{utils.formatar_moeda(total_final)} "
                                    f"(-{utils.formatar_moeda(self.desconto)})")
        else:
            self.lbl_total.text = utils.formatar_moeda(total_final)
        self.lbl_qtd_itens.text = f"Total de Itens: {total_itens:.2f}"

    def finalizar_venda_modal(self):
        if not self.carrinho:
            mostrar_popup("Aviso", "Carrinho vazio!")
            return
        PagamentoPopup(self).open()

    def finalizar_venda_rapida(self, forma_pagamento):
        if not self.carrinho:
            mostrar_popup("Aviso", "Carrinho vazio!")
            return
        subtotal = sum(i["quantidade"] * i["preco"] for i in self.carrinho)
        total_venda = max(0.0, subtotal - self.desconto)
        self.concluir_gravacao_venda(forma_pagamento, total_venda, total_venda, 0.0,
                                     subtotal=subtotal, desconto=self.desconto)

    def concluir_gravacao_venda(self, forma_pagamento, total_venda, valor_pago=0.0,
                                troco=0.0, subtotal=None, desconto=0.0, dados_fiado=None,
                                pagamentos=None, valor_credito_usado=0.0):
        import json as _json
        if subtotal is None:
            subtotal = total_venda
        if pagamentos is None and forma_pagamento not in ("MULTIPLO", "FIADO"):
            pagamentos = [{"forma": forma_pagamento, "valor": total_venda}]
        elif pagamentos is None:
            pagamentos = []

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            for item in self.carrinho:
                cursor.execute("SELECT estoque FROM produtos WHERE id = ?", (item["id"],))
                res = cursor.fetchone()
                estoque_atual = res["estoque"] if res else 0
                if estoque_atual < item["quantidade"]:
                    raise ValueError(
                        f"Estoque insuficiente para '{item['nome']}' "
                        f"(disponível: {estoque_atual:.2f}, solicitado: "
                        f"{item['quantidade']:.2f}).")

            cursor.execute(
                "INSERT INTO vendas (cliente_id, total, forma_pagamento, usuario, caixa_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.cliente_id, total_venda, forma_pagamento, self.usuario_nome, self.caixa_id))
            venda_id = cursor.lastrowid

            for p in pagamentos:
                cursor.execute(
                    "INSERT INTO vendas_pagamentos (venda_id, forma, valor) VALUES (?, ?, ?)",
                    (venda_id, p["forma"], p["valor"]))

            if dados_fiado:
                valor_fiado = dados_fiado.get("valor", total_venda)
                cursor.execute(
                    "INSERT INTO fiados (cliente_id, valor, vencimento, status) "
                    "VALUES (?, ?, ?, 'ABERTO')",
                    (dados_fiado["cliente_id"], valor_fiado, dados_fiado.get("vencimento")))

            if valor_credito_usado and valor_credito_usado > 0.001:
                usar_credito_cliente(self.cliente_id, valor_credito_usado,
                                     f"Venda #{venda_id}", self.usuario_nome, conn=conn)

            for p in pagamentos:
                if p.get("forma") == "VALE CREDITO" and p.get("codigo"):
                    usar_vale_credito(p["codigo"], p["valor"], self.usuario_nome, conn=conn)

            dados_historico = {
                "itens": self.carrinho, "valor_pago": valor_pago, "troco": troco,
                "subtotal": subtotal, "desconto": desconto, "pagamentos": pagamentos,
            }
            cursor.execute(
                "INSERT INTO vendas_historico "
                "(venda_id, total, desconto, forma_pagamento, carrinho_json, status) "
                "VALUES (?, ?, ?, ?, ?, 'CONCLUIDA')",
                (venda_id, total_venda, desconto, forma_pagamento, _json.dumps(dados_historico)))

            for item in self.carrinho:
                cursor.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?",
                               (item["quantidade"], item["id"]))
            conn.commit()

            for item in self.carrinho:
                registrar_movimentacao_estoque(item["id"], "SAIDA", item["quantidade"],
                                               "VENDA", self.usuario_nome, f"Venda #{venda_id}")

            detalhe = ", ".join(
                f"{p['forma']} {utils.formatar_moeda(p['valor'])}" for p in pagamentos
            ) or forma_pagamento
            registrar_auditoria(
                self.usuario_nome, "VENDA",
                f"Venda #{venda_id} - Total {utils.formatar_moeda(total_venda)} "
                f"(Desc {utils.formatar_moeda(desconto)}) [{detalhe}]")

            mostrar_popup("Sucesso", f"Venda #{venda_id} finalizada!")
            self._cancelar_confirmado()
            return True
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao concluir gravação: {ex}")
            mostrar_popup("Erro", f"Erro ao concluir gravação: {ex}")
            return False
        finally:
            if conn:
                conn.close()
