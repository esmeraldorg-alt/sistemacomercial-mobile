"""
Dashboard e Menu Principal — equivalentes a DashboardFrame e MenuFrame do
main.py original.

PDV, Gerencial, Notas e Financeiro ainda são placeholders (entram nas
Fases 3 e 4) — os botões existem e respeitam permissão, mas por enquanto
avisam que o módulo ainda não foi migrado.
"""
from datetime import datetime

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.metrics import dp

import utils_mobile as utils
from components import (
    CardIndicador, GraficoBarras, criar_bloco_tabela, label_esquerda,
    mostrar_popup, confirmar_popup,
    COR_VERDE, COR_AZUL, COR_LARANJA, COR_VERMELHO, COR_CINZA,
)

from database import (
    obter_resumo_dia, obter_vendas_ultimos_dias, obter_ultimas_vendas,
    obter_produtos_estoque_baixo, obter_produtos_mais_vendidos,
    obter_clientes_top_compradores, obter_produtos_proximos_validade,
    obter_caixa_aberto, abrir_caixa, fechar_caixa, calcular_totais_caixa,
    registrar_movimentacao_caixa, criar_conexao, registrar_movimentacao_estoque,
    registrar_auditoria,
)


# ==========================================
# DASHBOARD
# equivalente a DashboardFrame (main.py)
# ==========================================
class DashboardConteudo(ScrollView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.container = BoxLayout(orientation="vertical", size_hint_y=None,
                                    spacing=dp(10), padding=dp(12))
        self.container.bind(minimum_height=self.container.setter("height"))
        self.add_widget(self.container)
        self.carregar_dados()

    def carregar_dados(self):
        self.container.clear_widgets()

        try:
            resumo = obter_resumo_dia()
        except Exception as e:
            utils.logger.exception(f"Erro ao obter resumo: {e}")
            self.container.add_widget(label_esquerda(
                "Não foi possível carregar o dashboard.", color=COR_VERMELHO))
            return

        # --- Cabeçalho ---
        cabecalho = BoxLayout(size_hint_y=None, height=dp(30))
        cabecalho.add_widget(label_esquerda(
            "Painel de Indicadores", bold=True, font_size="18sp"))
        cabecalho.add_widget(label_esquerda(
            f"Atualizado às {datetime.now().strftime('%H:%M:%S')}",
            color=COR_CINZA, font_size="10sp", halign="right"))
        self.container.add_widget(cabecalho)

        # --- Cards (2 linhas de 3) ---
        grade = GridLayout(cols=2, size_hint_y=None, height=dp(340),
                            spacing=dp(6))
        grade.add_widget(CardIndicador(
            "VENDAS HOJE", utils.formatar_moeda(resumo["vendas_total"]),
            COR_VERDE, f"{resumo['vendas_qtd']} venda(s)"))
        grade.add_widget(CardIndicador(
            "TICKET MÉDIO", utils.formatar_moeda(resumo["ticket_medio"]),
            COR_AZUL, "Média por venda hoje"))
        grade.add_widget(CardIndicador(
            "ESTOQUE BAIXO", str(resumo["estoque_baixo"]),
            COR_LARANJA, "Produtos a repor"))
        grade.add_widget(CardIndicador(
            "FIADOS EM ABERTO", utils.formatar_moeda(resumo["fiados_total"]),
            COR_LARANJA, f"{resumo['fiados_qtd']} dívida(s)"))
        cor_venc = COR_VERMELHO if resumo["vencidos_qtd"] > 0 else COR_CINZA
        grade.add_widget(CardIndicador(
            "FIADOS VENCIDOS", utils.formatar_moeda(resumo["vencidos_total"]),
            cor_venc, f"{resumo['vencidos_qtd']} vencida(s)"))
        if resumo["caixa_id"]:
            caixa_txt = utils.formatar_moeda(resumo["caixa_esperado"])
            cor_caixa = COR_VERDE
            sub_caixa = f"Caixa #{resumo['caixa_id']}"
        else:
            caixa_txt = "FECHADO"
            cor_caixa = COR_VERMELHO
            sub_caixa = "Nenhum caixa aberto"
        grade.add_widget(CardIndicador("CAIXA ATUAL", caixa_txt, cor_caixa, sub_caixa))
        self.container.add_widget(grade)

        # --- Gráfico ---
        try:
            dados_grafico = obter_vendas_ultimos_dias(7)
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar grafico: {e}")
            dados_grafico = []
        grafico = GraficoBarras(size_hint_y=None, height=dp(200))
        grafico.set_dados(dados_grafico)
        self.container.add_widget(grafico)

        # --- Tabelas ---
        self._tabela_produtos_mais_vendidos()
        self._tabela_clientes_top()
        self._tabela_ultimas_vendas()
        self._tabela_estoque_baixo()
        self._tabela_produtos_vencendo()

    def _tabela_produtos_mais_vendidos(self):
        bloco, tabela = criar_bloco_tabela(
            "Produtos Mais Vendidos (30d)", ["Produto", "Qtd", "Total"],
            [3, 1, 1.2])
        try:
            lista = obter_produtos_mais_vendidos(dias=30, limite=5)
            linhas = [[item["nome"][:35], f"{item['quantidade']:.2f}",
                       utils.formatar_moeda(item["total"])] for item in lista]
        except Exception as e:
            utils.logger.exception(f"Erro produtos mais vendidos: {e}")
            linhas = []
        tabela.set_dados(linhas, "(sem vendas)")
        self.container.add_widget(bloco)

    def _tabela_clientes_top(self):
        bloco, tabela = criar_bloco_tabela(
            "Top Clientes (30d)", ["Cliente", "Compras", "Total"],
            [3, 1, 1.2])
        try:
            lista = obter_clientes_top_compradores(dias=30, limite=5)
            linhas = [[c["nome"][:35], str(c["qtd_compras"]),
                       utils.formatar_moeda(c["total"])] for c in lista]
        except Exception as e:
            utils.logger.exception(f"Erro top clientes: {e}")
            linhas = []
        tabela.set_dados(linhas, "(sem compras)")
        self.container.add_widget(bloco)

    def _tabela_ultimas_vendas(self):
        bloco, tabela = criar_bloco_tabela(
            "Últimas Vendas", ["ID", "Data/Hora", "Forma", "Total", "Status"],
            [0.6, 1.6, 1, 1, 1])
        try:
            lista = obter_ultimas_vendas(limite=5)
            linhas = [[str(v["id"]), v["data"] or "", v["forma_pagamento"] or "",
                       utils.formatar_moeda(v["total"]),
                       v["status"] or "CONCLUIDA"] for v in lista]
        except Exception as e:
            utils.logger.exception(f"Erro ultimas vendas: {e}")
            linhas = []
        tabela.set_dados(linhas, "(sem vendas)")
        self.container.add_widget(bloco)

    def _tabela_estoque_baixo(self):
        bloco, tabela = criar_bloco_tabela(
            "Estoque Baixo (alerta)", ["Código", "Produto", "Atual", "Mín."],
            [1, 2.2, 1, 1])
        try:
            lista = obter_produtos_estoque_baixo(limite=8)
            linhas = [[p["codigo_barras"] or "-", p["nome"][:30],
                       f"{p['estoque']:.2f}", f"{p['estoque_minimo']:.2f}"]
                      for p in lista]
        except Exception as e:
            utils.logger.exception(f"Erro estoque baixo: {e}")
            linhas = []
        tabela.set_dados(linhas, "(nenhum alerta)")
        self.container.add_widget(bloco)

    def _tabela_produtos_vencendo(self):
        bloco, tabela = criar_bloco_tabela(
            "⏰ Produtos Próximos do Vencimento (7 dias)",
            ["Código", "Produto", "Estoque", "Validade", "Situação"],
            [1, 2, 1, 1, 1.4], cor_titulo=COR_LARANJA)
        try:
            lista = obter_produtos_proximos_validade(dias=7, limite=10)
            linhas = []
            for p in lista:
                try:
                    validade_txt = datetime.strptime(
                        p["validade"], "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    validade_txt = p["validade"]
                dias_rest = p["dias_restantes"]
                if dias_rest < 0:
                    situacao = f"Vencido há {abs(dias_rest)}d"
                elif dias_rest == 0:
                    situacao = "Vence hoje!"
                else:
                    situacao = f"Vence em {dias_rest}d"
                linhas.append([p["codigo_barras"] or "-", p["nome"][:32],
                                f"{p['estoque']:.2f}", validade_txt, situacao])
        except Exception as e:
            utils.logger.exception(f"Erro produtos vencendo: {e}")
            linhas = []
        tabela.set_dados(linhas, "(nenhum produto próximo do vencimento)")
        self.container.add_widget(bloco)


# ==========================================
# CONTROLE DE CAIXA
# equivalente a JanelaCaixa (main.py)
# ==========================================
class CaixaPopup(Popup):
    def __init__(self, usuario_nome, app_ref=None, callback_atualizar=None, **kwargs):
        kwargs.setdefault("title", "Controle de Caixa")
        kwargs.setdefault("size_hint", (0.9, 0.9))
        kwargs.setdefault("auto_dismiss", False)
        super().__init__(**kwargs)
        self.usuario_nome = usuario_nome
        self.app_ref = app_ref
        self.callback_atualizar = callback_atualizar
        self.caixa_atual = obter_caixa_aberto()
        self.entradas_forma = {}
        self._montar()

    def _fechar_este_popup(self, *_):
        self.dismiss()
        if self.callback_atualizar:
            self.callback_atualizar()

    def _montar(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        scroll = ScrollView()
        conteudo = BoxLayout(orientation="vertical", size_hint_y=None,
                              spacing=dp(10))
        conteudo.bind(minimum_height=conteudo.setter("height"))

        if self.caixa_atual:
            self._montar_fechamento(conteudo)
        else:
            self._montar_abertura(conteudo)

        scroll.add_widget(conteudo)
        raiz.add_widget(scroll)

        btn_fechar_popup = Button(text="Fechar esta janela", size_hint_y=None,
                                   height=dp(44))
        btn_fechar_popup.bind(on_release=lambda *_: self.dismiss())
        raiz.add_widget(btn_fechar_popup)
        self.content = raiz

    def _montar_abertura(self, conteudo):
        conteudo.add_widget(label_esquerda(
            "Nenhum caixa aberto no momento.", color=COR_LARANJA,
            size_hint_y=None, height=dp(24), halign="center"))
        conteudo.add_widget(label_esquerda(
            "Valor de Abertura (R$):", bold=False,
            size_hint_y=None, height=dp(22)))
        self.e_valor = TextInput(text="0.00", multiline=False,
                                  size_hint_y=None, height=dp(44),
                                  input_filter="float")
        conteudo.add_widget(self.e_valor)

        btn_abrir = Button(text="Abrir Caixa", size_hint_y=None, height=dp(48),
                            background_color=COR_VERDE)
        btn_abrir.bind(on_release=self._abrir)
        conteudo.add_widget(btn_abrir)

    def _abrir(self, *_):
        try:
            valor = float((self.e_valor.text or "0").strip().replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Digite um valor numérico válido.")
            return
        try:
            abrir_caixa(self.usuario_nome, valor)
            mostrar_popup("Sucesso", "Caixa aberto com sucesso!")
            self._fechar_este_popup()
        except Exception as ex:
            utils.logger.exception(f"Erro ao abrir caixa: {ex}")
            mostrar_popup("Erro", f"Não foi possível abrir: {ex}")

    def _montar_fechamento(self, conteudo):
        cid = self.caixa_atual["id"]
        va = self.caixa_atual["valor_abertura"]
        da = self.caixa_atual["data_abertura"]
        ua = self.caixa_atual["usuario_abertura"]

        conteudo.add_widget(label_esquerda(
            f"Caixa #{cid} ABERTO", bold=True, color=COR_VERDE,
            size_hint_y=None, height=dp(24), halign="center"))
        conteudo.add_widget(label_esquerda(
            f"Aberto por: {ua or '-'}   |   Em: {da or '-'}\n"
            f"Valor de abertura: {utils.formatar_moeda(va)}",
            size_hint_y=None, height=dp(44), halign="center"))

        try:
            totais = calcular_totais_caixa(cid)
        except Exception as e:
            utils.logger.exception(f"Erro ao calcular totais: {e}")
            totais = None

        if totais:
            txt = "Resumo (vendas do caixa):\n"
            for forma, dados in totais["vendas_por_forma"].items():
                txt += f"  {forma}: {dados['qtd']}x  {utils.formatar_moeda(dados['soma'])}\n"
            txt += f"\nSangrias: {utils.formatar_moeda(totais['sangrias'])}"
            txt += f"\nSuprimentos: {utils.formatar_moeda(totais['suprimentos'])}"
            conteudo.add_widget(label_esquerda(
                txt, size_hint_y=None, height=dp(24 * (txt.count(chr(10)) + 1))))

            fiado = totais["vendas_por_forma"].get("FIADO", {})
            if fiado and fiado.get("soma", 0.0) > 0.001:
                conteudo.add_widget(label_esquerda(
                    f"Vendas FIADO no caixa: {utils.formatar_moeda(fiado['soma'])} "
                    f"({fiado['qtd']}x)\nNão entra no caixa físico — é conta a receber.",
                    color=COR_LARANJA, bold=False, size_hint_y=None, height=dp(46),
                    halign="center"))

        linha_mov = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        btn_sangria = Button(text="Sangria", background_color=COR_VERMELHO)
        btn_suprimento = Button(text="Suprimento", background_color=COR_AZUL)
        btn_sangria.bind(on_release=lambda *_: self._abrir_movimentacao("SANGRIA"))
        btn_suprimento.bind(on_release=lambda *_: self._abrir_movimentacao("SUPRIMENTO"))
        linha_mov.add_widget(btn_sangria)
        linha_mov.add_widget(btn_suprimento)
        conteudo.add_widget(linha_mov)

        conteudo.add_widget(label_esquerda(
            "Valores informados no fechamento (por forma):", bold=True,
            size_hint_y=None, height=dp(22)))

        esperado = totais["esperado_por_forma"] if totais else {}
        for forma in ["DINHEIRO", "PIX", "DEBITO", "CREDITO"]:
            linha = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            linha.add_widget(label_esquerda(forma, size_hint_x=0.4))
            campo = TextInput(text=f"{esperado.get(forma, 0.0):.2f}",
                               multiline=False, input_filter="float")
            self.entradas_forma[forma] = campo
            linha.add_widget(campo)
            conteudo.add_widget(linha)

        btn_fechar = Button(text="Fechar Caixa", size_hint_y=None, height=dp(50),
                             background_color=COR_VERMELHO)
        btn_fechar.bind(on_release=self._fechar)
        conteudo.add_widget(btn_fechar)

    def _abrir_movimentacao(self, tipo):
        if self.app_ref and not self.app_ref.verificar_permissao("sangria_suprimento"):
            mostrar_popup("Acesso Negado",
                          "Você não tem permissão para lançar sangria/suprimento.")
            return
        conteudo = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        conteudo.add_widget(label_esquerda(
            f"{tipo.capitalize()} de Caixa", bold=True, size_hint_y=None,
            height=dp(24), halign="center"))
        conteudo.add_widget(label_esquerda(
            "Valor (R$):", size_hint_y=None, height=dp(20)))
        e_valor = TextInput(multiline=False, size_hint_y=None, height=dp(44),
                             input_filter="float")
        conteudo.add_widget(e_valor)
        conteudo.add_widget(label_esquerda(
            "Motivo:", size_hint_y=None, height=dp(20)))
        e_motivo = TextInput(multiline=False, size_hint_y=None, height=dp(44))
        conteudo.add_widget(e_motivo)

        popup_mov = Popup(title=tipo.capitalize(), content=conteudo,
                           size_hint=(0.85, None), height=dp(320),
                           auto_dismiss=False)

        def salvar(*_):
            try:
                v = float((e_valor.text or "0").strip().replace(",", "."))
            except ValueError:
                mostrar_popup("Erro", "Valor inválido.")
                return
            try:
                registrar_movimentacao_caixa(
                    self.caixa_atual["id"], tipo, v,
                    e_motivo.text.strip(), self.usuario_nome)
                popup_mov.dismiss()
                mostrar_popup("Sucesso", f"{tipo.capitalize()} registrada!")
                self.dismiss()
                if self.callback_atualizar:
                    self.callback_atualizar()
                CaixaPopup(self.usuario_nome, app_ref=self.app_ref,
                           callback_atualizar=self.callback_atualizar).open()
            except Exception as e:
                utils.logger.exception(f"Erro ao registrar {tipo}: {e}")
                mostrar_popup("Erro", str(e))

        btn_confirmar = Button(text="Confirmar", size_hint_y=None, height=dp(46),
                                background_color=COR_VERDE)
        btn_confirmar.bind(on_release=salvar)
        conteudo.add_widget(btn_confirmar)
        popup_mov.open()

    def _fechar(self, *_):
        valores_por_forma = {}
        for forma, campo in self.entradas_forma.items():
            try:
                valores_por_forma[forma] = float(
                    (campo.text or "0").strip().replace(",", "."))
            except ValueError:
                mostrar_popup("Erro", f"Valor inválido para {forma}.")
                return

        def confirmado():
            try:
                resultado = fechar_caixa(self.caixa_atual["id"], valores_por_forma,
                                          self.usuario_nome)
                mostrar_popup(
                    "Sucesso",
                    f"Caixa fechado!\nEsperado: "
                    f"{utils.formatar_moeda(resultado['valor_esperado'])}\n"
                    f"Informado: {utils.formatar_moeda(resultado['valor_fechamento'])}\n"
                    f"Diferença: {utils.formatar_moeda(resultado['diferenca'])}")
                self._fechar_este_popup()
            except Exception as ex:
                utils.logger.exception(f"Erro ao fechar caixa: {ex}")
                mostrar_popup("Erro", f"Não foi possível fechar: {ex}")

        confirmar_popup("Confirmar", "Deseja realmente fechar o caixa?", confirmado)


# ==========================================
# CADASTRO RÁPIDO DE PRODUTO
# (versão enxuta, só pra destravar testes; o cadastro completo com fator
# de conversão, validade, etc. entra junto do módulo Gerencial)
# ==========================================
class CadastroProdutoPopup(Popup):
    def __init__(self, usuario_nome, **kwargs):
        kwargs.setdefault("title", "Cadastrar Produto Rápido")
        kwargs.setdefault("size_hint", (0.88, None))
        kwargs.setdefault("height", dp(560))
        super().__init__(**kwargs)
        self.usuario_nome = usuario_nome
        self._montar()

    def _campo(self, raiz, rotulo, hint="", filtro=None, valor_inicial=""):
        raiz.add_widget(label_esquerda(rotulo, size_hint_y=None, height=dp(20)))
        campo = TextInput(text=valor_inicial, hint_text=hint, multiline=False,
                           size_hint_y=None, height=dp(44),
                           input_filter=filtro)
        raiz.add_widget(campo)
        return campo

    def _montar(self):
        scroll = ScrollView()
        raiz = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(6),
                          size_hint_y=None)
        raiz.bind(minimum_height=raiz.setter("height"))

        self.e_codigo = self._campo(raiz, "Código de Barras / SKU:")
        self.e_nome = self._campo(raiz, "Nome do Produto:")
        self.e_preco = self._campo(raiz, "Preço de Venda (R$):", filtro="float")
        self.e_estoque = self._campo(raiz, "Estoque Inicial:", filtro="float",
                                      valor_inicial="0")
        self.e_minimo = self._campo(raiz, "Estoque Mínimo (alerta):", filtro="float",
                                     valor_inicial="0")

        raiz.add_widget(label_esquerda("Unidade:", size_hint_y=None, height=dp(20)))
        self.spinner_unidade = Spinner(
            text="UN", values=["UN", "KG", "G", "L", "ML", "CX", "PCT", "DZ"],
            size_hint_y=None, height=dp(44))
        raiz.add_widget(self.spinner_unidade)

        btn_salvar = Button(text="Salvar Produto", size_hint_y=None, height=dp(50),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        raiz.add_widget(btn_salvar)

        scroll.add_widget(raiz)
        self.content = scroll

    def _salvar(self, *_):
        nome = (self.e_nome.text or "").strip()
        if not nome:
            mostrar_popup("Erro", "Informe o nome do produto.")
            return
        try:
            preco = float((self.e_preco.text or "0").replace(",", "."))
            estoque = float((self.e_estoque.text or "0").replace(",", "."))
            minimo = float((self.e_minimo.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Preço/estoque/mínimo precisam ser números.")
            return
        if preco <= 0:
            mostrar_popup("Erro", "O preço de venda deve ser maior que zero.")
            return

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO produtos "
                "(codigo_barras, nome, preco_venda, estoque, estoque_minimo, "
                "unidade, fator_conversao_padrao, fator_conversao_operacao) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 'MULTIPLICAR')",
                ((self.e_codigo.text or "").strip() or None, nome, preco,
                 estoque, minimo, self.spinner_unidade.text))
            novo_id = cursor.lastrowid
            conn.commit()

            if estoque > 0:
                registrar_movimentacao_estoque(
                    novo_id, "ENTRADA", estoque, "CADASTRO",
                    self.usuario_nome, "Estoque inicial no cadastro")
            registrar_auditoria(self.usuario_nome, "CADASTRO_PRODUTO",
                                f"Produto '{nome}' cadastrado (ID {novo_id})")

            mostrar_popup("Sucesso", f"Produto '{nome}' cadastrado!")
            self.dismiss()
        except Exception as e:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao cadastrar produto: {e}")
            mostrar_popup("Erro", f"Erro ao cadastrar: {e}")
        finally:
            if conn:
                conn.close()


# ==========================================
# MENU PRINCIPAL
# equivalente a MenuFrame (main.py)
# ==========================================
class MenuConteudo(BoxLayout):
    def __init__(self, app_ref, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(24))
        kwargs.setdefault("spacing", dp(10))
        super().__init__(**kwargs)
        self.app_ref = app_ref

        self.add_widget(label_esquerda(
            "Sistema Comercial Integrado", bold=True, font_size="18sp",
            halign="center", size_hint_y=None, height=dp(30)))
        self.lbl_usuario = label_esquerda(
            "Usuário: Nenhum", color=(0.25, 0.82, 0.88, 1), halign="center",
            size_hint_y=None, height=dp(22))
        self.add_widget(self.lbl_usuario)
        self.lbl_caixa = label_esquerda(
            "Caixa: verificando...", color=COR_LARANJA, halign="center",
            size_hint_y=None, height=dp(22))
        self.add_widget(self.lbl_caixa)

        self.add_widget(BoxLayout(size_hint_y=None, height=dp(10)))

        self.botoes = {}
        self._botao("pdv", "Frente de Caixa (PDV)", COR_VERDE, self.abrir_pdv, alto=True)
        self._botao("abrir_fechar_caixa", "Abrir / Fechar / Movimentar Caixa",
                    COR_LARANJA, self.abrir_janela_caixa)
        self._botao("gerencial", "Módulo Gerencial", (0.20, 0.35, 0.85, 1),
                    self.abrir_gerencial, alto=True)
        self._botao("notas", "Notas Fiscais / XML", (0.45, 0.20, 0.65, 1),
                    self.abrir_notas, alto=True)
        self._botao("financeiro", "Gestão Financeira", (0.08, 0.42, 0.37, 1),
                    self.abrir_financeiro, alto=True)
        self._botao("cad_produto", "Cadastrar Produto Rápido", COR_CINZA,
                    self.cadastrar_produto_rapido)
        self._botao("ver_estoque", "Ver Alertas de Estoque Baixo", COR_CINZA,
                    self.ver_estoque_baixo)

        self.add_widget(BoxLayout(size_hint_y=None, height=dp(6)))
        btn_trocar = Button(text="Trocar Usuário / Operador", size_hint_y=None,
                             height=dp(42), background_color=COR_LARANJA)
        btn_trocar.bind(on_release=lambda *_: self.app_ref.trocar_usuario())
        self.add_widget(btn_trocar)

        btn_sair = Button(text="Sair do Sistema", size_hint_y=None, height=dp(46),
                           background_color=COR_VERMELHO)
        btn_sair.bind(on_release=lambda *_: self.app_ref.stop())
        self.add_widget(btn_sair)

        self.add_widget(BoxLayout())  # empurra tudo pra cima

    def _botao(self, chave_permissao, texto, cor, acao, alto=False):
        btn = Button(text=texto, size_hint_y=None,
                     height=dp(50) if alto else dp(42),
                     background_color=cor,
                     bold=alto)
        btn.bind(on_release=lambda *_: acao())
        self.botoes[chave_permissao] = btn
        self.add_widget(btn)

    def atualizar_usuario(self, usuario_tuple):
        if not usuario_tuple:
            self.lbl_usuario.text = "Usuário: Nenhum"
            return
        _, nome, _, perfil = usuario_tuple
        self.lbl_usuario.text = f"Usuário Logado: {nome} ({perfil or 'Padrao'})"
        self.atualizar_estado_botoes()

    def atualizar_estado_botoes(self):
        for chave, botao in self.botoes.items():
            if chave in ("abrir_fechar_caixa", "ver_estoque"):
                continue  # sempre liberados
            botao.disabled = not self.app_ref.verificar_permissao(chave)

    def atualizar_status_caixa(self):
        caixa = obter_caixa_aberto()
        if caixa:
            self.lbl_caixa.text = f"Caixa #{caixa['id']} ABERTO (desde {caixa['data_abertura']})"
            self.lbl_caixa.color = COR_VERDE
        else:
            self.lbl_caixa.text = "Caixa FECHADO - abra o caixa antes de vender"
            self.lbl_caixa.color = COR_LARANJA

    def abrir_janela_caixa(self):
        if not self.app_ref.usuario_atual:
            mostrar_popup("Aviso", "Faça login antes de operar o caixa.")
            return
        if not self.app_ref.verificar_permissao("abrir_fechar_caixa"):
            mostrar_popup("Acesso Negado", "Você não tem permissão para operar o caixa.")
            return
        CaixaPopup(self.app_ref.usuario_atual[1], app_ref=self.app_ref,
                   callback_atualizar=self.atualizar_status_caixa).open()

    def abrir_pdv(self):
        if not self.app_ref.verificar_permissao("pdv"):
            mostrar_popup("Acesso Negado", "Sem permissão para o PDV.")
            return
        if not obter_caixa_aberto():
            mostrar_popup("Caixa Fechado", "Abra o caixa antes de iniciar uma venda.")
            self.abrir_janela_caixa()
            return
        self.app_ref.sm.current = "pdv"

    def abrir_gerencial(self):
        if not self.app_ref.verificar_permissao("gerencial"):
            mostrar_popup("Acesso Negado", "Sem permissão para o Gerencial.")
            return
        self.app_ref.sm.current = "gerencial"

    def abrir_notas(self):
        if not self.app_ref.verificar_permissao("notas"):
            mostrar_popup("Acesso Negado", "Sem permissão para Notas.")
            return
        mostrar_popup("Em construção", "Notas Fiscais entram na Fase 4.")

    def abrir_financeiro(self):
        if not self.app_ref.verificar_permissao("financeiro"):
            mostrar_popup("Acesso Negado", "Sem permissão para o módulo Financeiro.")
            return
        mostrar_popup("Em construção", "O Financeiro entra em uma próxima fase.")

    def cadastrar_produto_rapido(self):
        if not self.app_ref.verificar_permissao("cad_produto"):
            mostrar_popup("Acesso Negado", "Sem permissão para cadastrar produtos.")
            return
        usuario_nome = self.app_ref.usuario_atual[1] if self.app_ref.usuario_atual else "desconhecido"
        CadastroProdutoPopup(usuario_nome).open()

    def ver_estoque_baixo(self):
        conteudo = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        bloco, tabela = criar_bloco_tabela(
            "Produtos no ou abaixo do estoque mínimo",
            ["Código", "Produto", "Atual", "Mínimo"], [1, 2.4, 1, 1])
        try:
            lista = obter_produtos_estoque_baixo(limite=100)
            linhas = [[p["codigo_barras"] or "-", p["nome"],
                       f"{p['estoque']:.2f}", f"{p['estoque_minimo']:.2f}"]
                      for p in lista]
        except Exception as e:
            utils.logger.exception(f"Erro ao consultar estoque: {e}")
            linhas = []
        tabela.set_dados(linhas, "Nenhum produto com estoque baixo.")
        tabela.size_hint_y = 1
        bloco.size_hint_y = 1
        conteudo.add_widget(bloco)

        popup = Popup(title="Alertas de Estoque Baixo", content=conteudo,
                       size_hint=(0.9, 0.85))
        popup.open()
