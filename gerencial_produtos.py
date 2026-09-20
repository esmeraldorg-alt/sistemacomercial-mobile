"""
Gerencial — Produtos, Clientes e Fornecedores (Fases 4a e 4b). Equivalente a
janela_produto e janela_gerenciar_produtos (produtos), e a janela_cliente,
janela_fornecedor, janela_gerenciar_clientes e janela_gerenciar_fornecedores
(em gerencial_pessoas.py) do modulo_gerencial.py original.

Outras áreas do Gerencial (usuários, relatórios, histórico, devolução/troca,
dívidas/fiados, formas de pagamento) ainda não foram portadas.
"""
from datetime import datetime

from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.metrics import dp

import utils_mobile as utils
from components import (
    TabelaDados, criar_cabecalho, label_esquerda,
    mostrar_popup, confirmar_popup,
    COR_VERDE, COR_AZUL, COR_LARANJA, COR_VERMELHO, COR_CINZA,
)

from database import (
    criar_conexao, registrar_movimentacao_estoque, registrar_auditoria,
    obter_promocao_vigente, criar_promocao, cancelar_promocao,
)

UNIDADES = ["UN", "KG", "G", "L", "ML", "CX", "PCT", "DZ"]
OPERACOES = ["× Multiplicar", "÷ Dividir"]


class PromocaoPopup(Popup):
    def __init__(self, produto_id, nome_produto, usuario_nome, callback_atualizar, **kwargs):
        kwargs.setdefault("title", f"Gerenciar Promoção — {nome_produto}")
        kwargs.setdefault("size_hint", (0.85, None))
        kwargs.setdefault("height", dp(500))
        super().__init__(**kwargs)
        self.produto_id = produto_id
        self.nome_produto = nome_produto
        self.usuario_nome = usuario_nome
        self.callback_atualizar = callback_atualizar
        self._montar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))

        promo = obter_promocao_vigente(self.produto_id)
        if promo:
            de = datetime.strptime(promo["data_inicio"], "%Y-%m-%d").strftime("%d/%m/%Y")
            ate = datetime.strptime(promo["data_fim"], "%Y-%m-%d").strftime("%d/%m/%Y")
            raiz.add_widget(label_esquerda(
                f"Vigente: {utils.formatar_moeda(promo['preco_promocional'])}\n"
                f"De {de} até {ate}", color=COR_LARANJA, bold=False,
                size_hint_y=None, height=dp(46)))
            btn_cancelar = Button(text="Cancelar Promoção Vigente", size_hint_y=None,
                                  height=dp(42), background_color=COR_VERMELHO)

            def _cancelar(*_):
                confirmar_popup("Cancelar Promoção",
                                "Cancelar a promoção vigente deste produto?",
                                self._cancelar_confirmado(promo["id"]))

            btn_cancelar.bind(on_release=_cancelar)
            raiz.add_widget(btn_cancelar)
        else:
            raiz.add_widget(label_esquerda(
                "Nenhuma promoção vigente no momento.", color=COR_CINZA,
                size_hint_y=None, height=dp(30)))

        raiz.add_widget(label_esquerda("Nova Promoção", bold=True, halign="center",
                                        size_hint_y=None, height=dp(26)))
        raiz.add_widget(label_esquerda("Preço Promocional (R$):", size_hint_y=None, height=dp(20)))
        self.e_preco = TextInput(multiline=False, input_filter="float",
                                  size_hint_y=None, height=dp(44))
        raiz.add_widget(self.e_preco)

        raiz.add_widget(label_esquerda("Início (DD/MM/AAAA):", size_hint_y=None, height=dp(20)))
        self.e_ini = TextInput(text=datetime.now().strftime("%d/%m/%Y"), multiline=False,
                                size_hint_y=None, height=dp(44))
        raiz.add_widget(self.e_ini)

        raiz.add_widget(label_esquerda("Fim (DD/MM/AAAA):", size_hint_y=None, height=dp(20)))
        self.e_fim = TextInput(multiline=False, size_hint_y=None, height=dp(44))
        raiz.add_widget(self.e_fim)

        btn_salvar = Button(text="Salvar Promoção", size_hint_y=None, height=dp(48),
                             background_color=COR_AZUL, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        raiz.add_widget(btn_salvar)
        self.content = raiz

    def _cancelar_confirmado(self, promo_id):
        def _fazer():
            cancelar_promocao(promo_id, self.usuario_nome)
            self.dismiss()
            self.callback_atualizar()
        return _fazer

    def _salvar(self, *_):
        try:
            preco = float((self.e_preco.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Preço promocional inválido.")
            return
        if preco <= 0:
            mostrar_popup("Erro", "Preço promocional deve ser maior que zero.")
            return
        try:
            dt_ini = datetime.strptime(self.e_ini.text.strip(), "%d/%m/%Y")
            dt_fim = datetime.strptime(self.e_fim.text.strip(), "%d/%m/%Y")
        except ValueError:
            mostrar_popup("Erro", "Datas inválidas. Use DD/MM/AAAA.")
            return
        if dt_fim < dt_ini:
            mostrar_popup("Erro", "A data final não pode ser antes da inicial.")
            return

        criar_promocao(self.produto_id, preco, dt_ini.strftime("%Y-%m-%d"),
                       dt_fim.strftime("%Y-%m-%d"), self.usuario_nome)
        registrar_auditoria(
            self.usuario_nome, "CRIAR_PROMOCAO",
            f"Produto {self.produto_id} ({self.nome_produto}) - "
            f"{utils.formatar_moeda(preco)} de {self.e_ini.text} até {self.e_fim.text}")
        mostrar_popup("Sucesso", "Promoção salva com sucesso!")
        self.dismiss()
        self.callback_atualizar()


class CadastrarProdutoTab(BoxLayout):
    def __init__(self, usuario_nome, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        super().__init__(**kwargs)
        self.usuario_nome = usuario_nome
        self._montar()

    def _montar(self):
        scroll = ScrollView()
        raiz = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(6),
                          size_hint_y=None)
        raiz.bind(minimum_height=raiz.setter("height"))

        def campo(rotulo, hint="", filtro=None, valor_inicial=""):
            raiz.add_widget(label_esquerda(rotulo, size_hint_y=None, height=dp(20)))
            c = TextInput(text=valor_inicial, hint_text=hint, multiline=False,
                          input_filter=filtro, size_hint_y=None, height=dp(44))
            raiz.add_widget(c)
            return c

        self.e_cod = campo("Código de Barras / Cód Produto:")
        self.e_nome = campo("Nome do Produto:")

        raiz.add_widget(label_esquerda("Unidade de Medida:", size_hint_y=None, height=dp(20)))
        self.spinner_unidade = Spinner(text="UN", values=UNIDADES,
                                        size_hint_y=None, height=dp(44))
        raiz.add_widget(self.spinner_unidade)
        raiz.add_widget(label_esquerda(
            "Use KG/G/L/ML para produtos vendidos fracionados (peso/volume) no PDV.\n"
            "Use UN para itens vendidos por unidade inteira.",
            font_size="10sp", color=COR_CINZA, size_hint_y=None, height=dp(34)))

        self.e_preco = campo("Preço de Venda (R$):", filtro="float")
        self.e_estoque_inicial = campo("Estoque Inicial:", filtro="float", valor_inicial="0")
        self.e_min = campo("Estoque Mínimo (alerta):", filtro="float", valor_inicial="5")

        raiz.add_widget(label_esquerda(
            "Fator de Conversão Padrão (compra → estoque):", size_hint_y=None, height=dp(20)))
        linha_fator = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.e_fator = TextInput(text="1", multiline=False, input_filter="float")
        linha_fator.add_widget(self.e_fator)
        self.spinner_operacao = Spinner(text=OPERACOES[0], values=OPERACOES,
                                         size_hint_x=1.3)
        linha_fator.add_widget(self.spinner_operacao)
        raiz.add_widget(linha_fator)
        raiz.add_widget(label_esquerda(
            "Multiplicar: comprou em unidade MAIOR (ex.: caixa com 12).\n"
            "Dividir: comprou em unidade MENOR (ex.: 480un soltas p/ caixas de 12).",
            font_size="10sp", color=COR_CINZA, size_hint_y=None, height=dp(34)))

        self.e_validade = campo("Validade (opcional, DD/MM/AAAA):", hint="Ex.: 31/12/2026")

        btn_salvar = Button(text="Salvar Produto", size_hint_y=None, height=dp(50),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        raiz.add_widget(btn_salvar)

        scroll.add_widget(raiz)
        self.add_widget(scroll)

    def _salvar(self, *_):
        nome = (self.e_nome.text or "").strip()
        if not nome:
            mostrar_popup("Erro", "Informe o nome do produto.")
            return
        try:
            preco = float((self.e_preco.text or "0").replace(",", "."))
            estoque_inicial = float((self.e_estoque_inicial.text or "0").replace(",", "."))
            minimo = float((self.e_min.text or "0").replace(",", "."))
            fator = float((self.e_fator.text or "1").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Preço/estoque/mínimo/fator precisam ser números.")
            return
        if preco <= 0:
            mostrar_popup("Erro", "O preço de venda deve ser maior que zero.")
            return
        if fator <= 0:
            mostrar_popup("Erro", "Fator de conversão deve ser maior que zero.")
            return

        validade_texto = (self.e_validade.text or "").strip()
        validade_iso = None
        if validade_texto:
            try:
                validade_iso = datetime.strptime(validade_texto, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                mostrar_popup("Erro", "Validade inválida. Use o formato DD/MM/AAAA.")
                return

        operacao = "DIVIDIR" if "Dividir" in self.spinner_operacao.text else "MULTIPLICAR"
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produtos "
                "(codigo_barras, nome, preco_venda, estoque, estoque_minimo, "
                "unidade, fator_conversao_padrao, fator_conversao_operacao, validade) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((self.e_cod.text or "").strip() or None, nome, preco, estoque_inicial,
                 minimo, self.spinner_unidade.text, fator, operacao, validade_iso))
            novo_id = cursor.lastrowid
            conn.commit()

            if estoque_inicial > 0:
                registrar_movimentacao_estoque(
                    novo_id, "ENTRADA", estoque_inicial, "CADASTRO",
                    self.usuario_nome, "Estoque inicial no cadastro")
            registrar_auditoria(self.usuario_nome, "CADASTRO_PRODUTO",
                                f"{nome} | Cód: {self.e_cod.text}")
            mostrar_popup("Sucesso", "Produto cadastrado com sucesso!")

            self.e_cod.text = ""
            self.e_nome.text = ""
            self.e_preco.text = ""
            self.e_estoque_inicial.text = "0"
            self.e_min.text = "5"
            self.e_fator.text = "1"
            self.e_validade.text = ""
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao salvar produto: {ex}")
            mostrar_popup("Erro", f"Erro ao salvar produto: {ex}")
        finally:
            if conn:
                conn.close()


class GerenciarProdutosTab(BoxLayout):
    def __init__(self, app_ref, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(12))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.usuario_nome = app_ref.usuario_atual[1] if app_ref.usuario_atual else "desconhecido"
        self.produto_selecionado = None
        self.mostrar_inativos = False
        self._montar()

    def _montar(self):
        barra_busca = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.e_busca = TextInput(hint_text="Buscar por nome ou código...", multiline=False)
        self.e_busca.bind(text=lambda inst, val: self._carregar(val))
        barra_busca.add_widget(self.e_busca)

        self.check_inativos = CheckBox(size_hint_x=None, width=dp(36))
        self.check_inativos.bind(active=self._alternar_inativos)
        barra_busca.add_widget(self.check_inativos)
        barra_busca.add_widget(label_esquerda("Mostrar inativos", size_hint_x=None,
                                               width=dp(130)))
        self.add_widget(barra_busca)

        titulos = ["Cód.", "Nome", "Preço", "Estoque", "Un.", "Fator", "Validade", "Promo", "Status"]
        larguras = [0.8, 2.4, 1, 1, 0.6, 0.8, 1, 1, 0.9]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, size_hint_y=1.3,
                                   selecionavel=True, callback_selecao=self._selecionar)
        self.add_widget(self.tabela)

        self.painel_edicao = BoxLayout(orientation="vertical", size_hint_y=None,
                                        height=dp(300), padding=dp(10), spacing=dp(4))
        self._montar_painel_edicao()
        self.add_widget(self.painel_edicao)

        self._carregar("")

    def _montar_painel_edicao(self):
        self.painel_edicao.add_widget(label_esquerda(
            "Selecione um produto na tabela pra editar:", bold=True, color=COR_LARANJA,
            size_hint_y=None, height=dp(24)))

        linha1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        linha1.add_widget(label_esquerda("Nome:", size_hint_x=None, width=dp(60)))
        self.e_edit_nome = TextInput(multiline=False)
        linha1.add_widget(self.e_edit_nome)
        linha1.add_widget(label_esquerda("Preço:", size_hint_x=None, width=dp(60)))
        self.e_edit_preco = TextInput(multiline=False, input_filter="float", size_hint_x=0.6)
        linha1.add_widget(self.e_edit_preco)
        self.painel_edicao.add_widget(linha1)

        linha2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        linha2.add_widget(label_esquerda("Estoque:", size_hint_x=None, width=dp(60)))
        self.e_edit_estoque = TextInput(multiline=False, input_filter="float")
        linha2.add_widget(self.e_edit_estoque)
        linha2.add_widget(label_esquerda("Unidade:", size_hint_x=None, width=dp(60)))
        self.spinner_edit_unidade = Spinner(text="UN", values=UNIDADES, size_hint_x=0.6)
        linha2.add_widget(self.spinner_edit_unidade)
        self.painel_edicao.add_widget(linha2)

        linha3 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        linha3.add_widget(label_esquerda("Fator Conv.:", size_hint_x=None, width=dp(90)))
        self.e_edit_fator = TextInput(text="1", multiline=False, input_filter="float")
        linha3.add_widget(self.e_edit_fator)
        self.spinner_edit_operacao = Spinner(text=OPERACOES[0], values=OPERACOES, size_hint_x=1.3)
        linha3.add_widget(self.spinner_edit_operacao)
        self.painel_edicao.add_widget(linha3)

        linha4 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        linha4.add_widget(label_esquerda("Validade:", size_hint_x=None, width=dp(90)))
        self.e_edit_validade = TextInput(hint_text="DD/MM/AAAA (opcional)", multiline=False)
        linha4.add_widget(self.e_edit_validade)
        self.painel_edicao.add_widget(linha4)

        linha_botoes = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        btn_salvar = Button(text="Salvar Alterações", background_color=COR_VERDE)
        btn_salvar.bind(on_release=self._salvar_edicao)
        self.btn_status = Button(text="Desativar Produto", background_color=COR_VERMELHO)
        self.btn_status.bind(on_release=self._alternar_status)
        linha_botoes.add_widget(btn_salvar)
        linha_botoes.add_widget(self.btn_status)
        self.painel_edicao.add_widget(linha_botoes)

        btn_promo = Button(text="🏷️ Gerenciar Promoção", size_hint_y=None, height=dp(42),
                            background_color=(0.51, 0.34, 0.84, 1))
        btn_promo.bind(on_release=self._gerenciar_promocao)
        self.painel_edicao.add_widget(btn_promo)

    def _alternar_inativos(self, inst, valor):
        self.mostrar_inativos = valor
        self._carregar(self.e_busca.text)

    def _carregar(self, filtro):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            condicoes, params = [], []
            if filtro:
                condicoes.append("(nome LIKE ? OR codigo_barras LIKE ?)")
                params += [f"{filtro}%", f"{filtro}%"]
            if not self.mostrar_inativos:
                condicoes.append("ativo = 1")
            where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
            cursor.execute(
                f"SELECT p.id, p.codigo_barras, p.nome, p.preco_venda, p.estoque, "
                f"p.ativo, p.unidade, p.fator_conversao_padrao, "
                f"p.fator_conversao_operacao, p.validade, "
                f"(SELECT preco_promocional FROM promocoes pr "
                f" WHERE pr.produto_id = p.id AND pr.ativo = 1 "
                f" AND date('now','localtime') BETWEEN date(pr.data_inicio) "
                f" AND date(pr.data_fim) ORDER BY pr.id DESC LIMIT 1) AS promo_preco "
                f"FROM produtos p {where} ORDER BY p.nome", params)

            linhas, extra = [], []
            for row in cursor.fetchall():
                d = dict(row)
                validade_txt = "-"
                if d["validade"]:
                    try:
                        validade_txt = datetime.strptime(
                            d["validade"], "%Y-%m-%d").strftime("%d/%m/%Y")
                    except Exception:
                        validade_txt = d["validade"]
                promo_txt = (utils.formatar_moeda(d["promo_preco"])
                            if d["promo_preco"] is not None else "-")
                simbolo = "÷" if (d["fator_conversao_operacao"] or "").upper().startswith("DIV") else "×"
                fator_txt = f"{simbolo}{(d['fator_conversao_padrao'] or 1.0):g}"
                status_txt = "Ativo" if d["ativo"] else "Inativo"
                linhas.append([d["codigo_barras"] or "-", d["nome"],
                                utils.formatar_moeda(d["preco_venda"]), f"{d['estoque']:.2f}",
                                d["unidade"] or "UN", fator_txt, validade_txt, promo_txt,
                                status_txt])
                extra.append(d)
            self.tabela.set_dados(linhas, "Nenhum produto encontrado.", dados_extra=extra)
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar produtos: {e}")
        finally:
            if conn:
                conn.close()

    def _selecionar(self, produto):
        self.produto_selecionado = produto
        self.e_edit_nome.text = produto["nome"]
        self.e_edit_preco.text = f"{produto['preco_venda']:.2f}"
        self.e_edit_estoque.text = f"{produto['estoque']:.2f}"
        self.spinner_edit_unidade.text = produto["unidade"] or "UN"
        self.e_edit_fator.text = f"{(produto['fator_conversao_padrao'] or 1.0):g}"
        self.spinner_edit_operacao.text = (
            OPERACOES[1] if (produto["fator_conversao_operacao"] or "").upper().startswith("DIV")
            else OPERACOES[0])
        if produto["validade"]:
            try:
                self.e_edit_validade.text = datetime.strptime(
                    produto["validade"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                self.e_edit_validade.text = ""
        else:
            self.e_edit_validade.text = ""

        if produto["ativo"]:
            self.btn_status.text = "Desativar Produto"
            self.btn_status.background_color = COR_VERMELHO
        else:
            self.btn_status.text = "Reativar Produto"
            self.btn_status.background_color = COR_VERDE

    def _salvar_edicao(self, *_):
        if not self.app_ref.verificar_permissao("excluir_produto"):
            mostrar_popup("Acesso Negado",
                          "Você não tem permissão para editar produtos (nome, preço, estoque).")
            return
        if not self.produto_selecionado:
            mostrar_popup("Aviso", "Selecione um produto na tabela para editar.")
            return
        try:
            novo_nome = self.e_edit_nome.text.strip()
            novo_preco = float((self.e_edit_preco.text or "0").replace(",", "."))
            novo_estoque = float((self.e_edit_estoque.text or "0").replace(",", "."))
            novo_fator = float((self.e_edit_fator.text or "1").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Preço/estoque/fator precisam ser números.")
            return
        if novo_fator <= 0:
            mostrar_popup("Erro", "Fator de conversão deve ser maior que zero.")
            return

        validade_texto = (self.e_edit_validade.text or "").strip()
        nova_validade_iso = None
        if validade_texto:
            try:
                nova_validade_iso = datetime.strptime(validade_texto, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                mostrar_popup("Erro", "Validade inválida. Use o formato DD/MM/AAAA.")
                return

        nova_operacao = "DIVIDIR" if "Dividir" in self.spinner_edit_operacao.text else "MULTIPLICAR"
        pid = self.produto_selecionado["id"]
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute("SELECT estoque FROM produtos WHERE id = ?", (pid,))
            row = cursor.fetchone()
            estoque_anterior = row["estoque"] if row else 0.0

            cursor.execute(
                "UPDATE produtos SET nome = ?, preco_venda = ?, estoque = ?, unidade = ?, "
                "fator_conversao_padrao = ?, fator_conversao_operacao = ?, validade = ? "
                "WHERE id = ?",
                (novo_nome, novo_preco, novo_estoque, self.spinner_edit_unidade.text,
                 novo_fator, nova_operacao, nova_validade_iso, pid))
            conn.commit()

            dif = novo_estoque - estoque_anterior
            if abs(dif) > 0.001:
                registrar_movimentacao_estoque(
                    pid, "AJUSTE", dif, "EDICAO_MANUAL", self.usuario_nome,
                    f"Estoque {estoque_anterior:.2f} -> {novo_estoque:.2f}")

            registrar_auditoria(self.usuario_nome, "EDICAO_PRODUTO", f"ID {pid} | {novo_nome}")
            mostrar_popup("Sucesso", "Produto atualizado com sucesso!")
            self._carregar(self.e_busca.text)
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao atualizar produto: {ex}")
            mostrar_popup("Erro", f"Erro ao atualizar produto: {ex}")
        finally:
            if conn:
                conn.close()

    def _alternar_status(self, *_):
        if not self.app_ref.verificar_permissao("excluir_produto"):
            mostrar_popup("Acesso Negado", "Sem permissão para ativar/desativar produtos.")
            return
        if not self.produto_selecionado:
            mostrar_popup("Aviso", "Selecione um produto na tabela.")
            return

        ativando = not self.produto_selecionado["ativo"]
        pergunta = ("Deseja realmente reativar este produto?" if ativando else
                    "Deseja realmente desativar este produto?\n\nEle deixará de aparecer "
                    "nas buscas e no PDV, mas o histórico é mantido intacto.")
        confirmar_popup("Confirmação", pergunta, lambda: self._alternar_status_confirmado(ativando))

    def _alternar_status_confirmado(self, ativando):
        pid = self.produto_selecionado["id"]
        nome_produto = self.e_edit_nome.text.strip()
        conn = None
        try:
            conn = criar_conexao()
            conn.execute("UPDATE produtos SET ativo = ? WHERE id = ?",
                        (1 if ativando else 0, pid))
            conn.commit()
            registrar_auditoria(
                self.usuario_nome,
                "REATIVACAO_PRODUTO" if ativando else "DESATIVACAO_PRODUTO",
                f"ID {pid} | {nome_produto}")
            mostrar_popup("Sucesso",
                          f"Produto {'reativado' if ativando else 'desativado'} com sucesso!")
            self.produto_selecionado = None
            self._carregar(self.e_busca.text)
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao alternar status: {ex}")
            mostrar_popup("Erro", str(ex))
        finally:
            if conn:
                conn.close()

    def _gerenciar_promocao(self, *_):
        if not self.produto_selecionado:
            mostrar_popup("Aviso", "Selecione um produto na tabela.")
            return
        PromocaoPopup(self.produto_selecionado["id"], self.e_edit_nome.text.strip(),
                     self.usuario_nome, lambda: self._carregar(self.e_busca.text)).open()


# ==========================================
# TELA GERENCIAL
# ==========================================
class GerencialScreen(Screen):
    def on_pre_enter(self, *args):
        app = App.get_running_app()
        if not getattr(self, "_construido", False):
            self._construir(app)
            self._construido = True
        else:
            self._recarregar_aba_gerenciar(app)

    def _construir(self, app):
        self.app_ref = app
        usuario_nome = app.usuario_atual[1] if app.usuario_atual else "desconhecido"

        raiz = BoxLayout(orientation="vertical")

        topo = BoxLayout(size_hint_y=None, height=dp(50), padding=(dp(12), 0))
        topo.add_widget(label_esquerda("Módulo Gerencial", bold=True,
                                        font_size="15sp"))
        btn_voltar = Button(text="Voltar ao Menu", size_hint=(None, None),
                             size=(dp(150), dp(36)), pos_hint={"center_y": 0.5})
        btn_voltar.bind(on_release=lambda *_: setattr(app.sm, "current", "principal"))
        topo.add_widget(btn_voltar)
        raiz.add_widget(topo)

        self.tabs = TabbedPanel(do_default_tab=False, tab_width=dp(180))

        aba_cadastrar = TabbedPanelItem(text="Cadastrar Produto")
        aba_cadastrar.add_widget(CadastrarProdutoTab(usuario_nome))
        self.tabs.add_widget(aba_cadastrar)

        aba_gerenciar = TabbedPanelItem(text="Gerenciar Produtos")
        self.conteudo_gerenciar = GerenciarProdutosTab(app)
        aba_gerenciar.add_widget(self.conteudo_gerenciar)
        self.tabs.add_widget(aba_gerenciar)

        from gerencial_pessoas import (
            CadastrarClienteTab, GerenciarClientesTab,
            CadastrarFornecedorTab, GerenciarFornecedoresTab,
        )

        aba_cad_cliente = TabbedPanelItem(text="Cadastrar Cliente")
        aba_cad_cliente.add_widget(CadastrarClienteTab(usuario_nome))
        self.tabs.add_widget(aba_cad_cliente)

        aba_ger_cliente = TabbedPanelItem(text="Gerenciar Clientes")
        self.conteudo_gerenciar_clientes = GerenciarClientesTab(app)
        aba_ger_cliente.add_widget(self.conteudo_gerenciar_clientes)
        self.tabs.add_widget(aba_ger_cliente)

        aba_cad_fornecedor = TabbedPanelItem(text="Cadastrar Fornecedor")
        aba_cad_fornecedor.add_widget(CadastrarFornecedorTab(usuario_nome))
        self.tabs.add_widget(aba_cad_fornecedor)

        aba_ger_fornecedor = TabbedPanelItem(text="Gerenciar Fornecedores")
        self.conteudo_gerenciar_fornecedores = GerenciarFornecedoresTab(app)
        aba_ger_fornecedor.add_widget(self.conteudo_gerenciar_fornecedores)
        self.tabs.add_widget(aba_ger_fornecedor)

        from gerencial_relatorios import (
            RelatorioVendasTab, AuditoriaTab, HistoricoEstoqueTab, HistoricoCaixasTab,
        )

        if app.verificar_permissao("ver_relatorios"):
            aba_rel_vendas = TabbedPanelItem(text="Relatório de Vendas")
            aba_rel_vendas.add_widget(RelatorioVendasTab())
            self.tabs.add_widget(aba_rel_vendas)

            aba_auditoria = TabbedPanelItem(text="Auditoria")
            aba_auditoria.add_widget(AuditoriaTab())
            self.tabs.add_widget(aba_auditoria)

            aba_hist_estoque = TabbedPanelItem(text="Histórico Estoque")
            aba_hist_estoque.add_widget(HistoricoEstoqueTab())
            self.tabs.add_widget(aba_hist_estoque)

            aba_hist_caixas = TabbedPanelItem(text="Histórico Caixas")
            aba_hist_caixas.add_widget(HistoricoCaixasTab())
            self.tabs.add_widget(aba_hist_caixas)

        self.tabs.default_tab = aba_cadastrar
        raiz.add_widget(self.tabs)
        self.add_widget(raiz)

    def _recarregar_aba_gerenciar(self, app):
        self.conteudo_gerenciar._carregar(self.conteudo_gerenciar.e_busca.text)
        self.conteudo_gerenciar_clientes._carregar(self.conteudo_gerenciar_clientes.e_busca.text)
        self.conteudo_gerenciar_fornecedores._carregar(
            self.conteudo_gerenciar_fornecedores.e_busca.text)
