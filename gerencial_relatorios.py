"""
Gerencial — Relatórios e Histórico (Fase 4c). Equivalente a
janela_relatorio_vendas, janela_auditoria, janela_historico_movimentacoes_estoque
e janela_historico_caixas do modulo_gerencial.py original.
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.metrics import dp

import utils_mobile as utils
from components import (
    TabelaDados, criar_cabecalho, label_esquerda,
    mostrar_popup,
    COR_VERDE, COR_AZUL, COR_LARANJA, COR_VERMELHO, COR_CINZA,
)

from database import criar_conexao, obter_auditoria, calcular_totais_caixa

PERIODOS = ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Tudo"]


def _filtro_data_sql(periodo, coluna="data"):
    if periodo == "Hoje":
        return f"AND date({coluna}) = date('now', 'localtime')"
    if periodo == "Últimos 7 dias":
        return f"AND date({coluna}) >= date('now', '-7 days', 'localtime')"
    if periodo == "Últimos 30 dias":
        return f"AND date({coluna}) >= date('now', '-30 days', 'localtime')"
    return ""


# ==========================================
# RELATÓRIO DE VENDAS
# ==========================================
class RelatorioVendasTab(BoxLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(14))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._montar()

    def _montar(self):
        barra = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        barra.add_widget(label_esquerda("Período:", size_hint_x=None, width=dp(70)))
        self.spinner_periodo = Spinner(text="Hoje", values=PERIODOS, size_hint_x=None,
                                        width=dp(180))
        barra.add_widget(self.spinner_periodo)
        btn_gerar = Button(text="Gerar", size_hint_x=None, width=dp(120),
                           background_color=COR_VERDE)
        btn_gerar.bind(on_release=lambda *_: self._gerar())
        barra.add_widget(btn_gerar)
        barra.add_widget(BoxLayout())
        self.add_widget(barra)

        self.lbl_resumo = label_esquerda(
            "", size_hint_y=None, height=dp(26), color=COR_LARANJA, bold=False)
        self.add_widget(self.lbl_resumo)

        titulos = ["Forma de Pagamento", "Qtd. Vendas", "Total"]
        larguras = [1.4, 1, 1]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras)
        self.add_widget(self.tabela)

        self._gerar()

    def _gerar(self):
        filtro_data = _filtro_data_sql(self.spinner_periodo.text, "v.data")
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT v.forma_pagamento, COUNT(*) AS qtd, SUM(v.total) AS soma "
                "FROM vendas v LEFT JOIN vendas_historico h ON v.id = h.venda_id "
                "WHERE (h.status IS NULL OR h.status != 'CANCELADA') "
                f"{filtro_data} GROUP BY v.forma_pagamento")
            linhas_db = cursor.fetchall()

            cursor.execute(
                "SELECT COUNT(*) AS qtd, SUM(v.total) AS soma FROM vendas v "
                "LEFT JOIN vendas_historico h ON v.id = h.venda_id "
                f"WHERE (h.status IS NULL OR h.status != 'CANCELADA') {filtro_data}")
            resumo = cursor.fetchone()
        except Exception as e:
            utils.logger.exception(f"Erro ao gerar relatório de vendas: {e}")
            mostrar_popup("Erro", f"Erro ao gerar relatório: {e}")
            return
        finally:
            if conn:
                conn.close()

        linhas = [[l["forma_pagamento"] or "—", str(l["qtd"]),
                   utils.formatar_moeda(l["soma"] or 0.0)] for l in linhas_db]
        self.tabela.set_dados(linhas, "Nenhuma venda no período.")

        total_qtd = resumo["qtd"] or 0
        total_soma = resumo["soma"] or 0.0
        ticket_medio = (total_soma / total_qtd) if total_qtd else 0.0
        self.lbl_resumo.text = (
            f"Total de vendas: {total_qtd}   |   Faturamento: "
            f"{utils.formatar_moeda(total_soma)}   |   Ticket médio: "
            f"{utils.formatar_moeda(ticket_medio)}")


# ==========================================
# AUDITORIA
# ==========================================
class AuditoriaTab(BoxLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(14))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._montar()

    def _montar(self):
        l1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l1.add_widget(label_esquerda("Usuário:", size_hint_x=None, width=dp(70)))
        self.e_usuario = TextInput(multiline=False)
        l1.add_widget(self.e_usuario)
        l1.add_widget(label_esquerda("Ação contém:", size_hint_x=None, width=dp(95)))
        self.e_acao = TextInput(multiline=False)
        l1.add_widget(self.e_acao)
        self.add_widget(l1)

        l2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l2.add_widget(label_esquerda("Período:", size_hint_x=None, width=dp(70)))
        self.spinner_periodo = Spinner(text="Últimos 7 dias", values=PERIODOS,
                                       size_hint_x=None, width=dp(180))
        l2.add_widget(self.spinner_periodo)
        btn_filtrar = Button(text="Filtrar", size_hint_x=None, width=dp(110),
                             background_color=COR_AZUL)
        btn_filtrar.bind(on_release=lambda *_: self._carregar())
        l2.add_widget(btn_filtrar)
        btn_limpar = Button(text="Limpar Filtros", size_hint_x=None, width=dp(140),
                            background_color=COR_CINZA)
        btn_limpar.bind(on_release=lambda *_: self._limpar())
        l2.add_widget(btn_limpar)
        self.add_widget(l2)

        titulos = ["ID", "Data/Hora", "Usuário", "Ação", "Detalhes"]
        larguras = [0.5, 1.4, 1, 1.4, 2.6]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras)
        self.add_widget(self.tabela)

        self._carregar()

    def _limpar(self):
        self.e_usuario.text = ""
        self.e_acao.text = ""
        self.spinner_periodo.text = "Últimos 7 dias"
        self._carregar()

    def _carregar(self):
        dias = {"Hoje": 1, "Últimos 7 dias": 7, "Últimos 30 dias": 30,
                "Tudo": None}.get(self.spinner_periodo.text)
        try:
            registros = obter_auditoria(
                limite=500, filtro_usuario=self.e_usuario.text.strip() or None,
                filtro_acao=self.e_acao.text.strip() or None, dias=dias)
        except Exception as e:
            utils.logger.exception(f"Erro ao consultar auditoria: {e}")
            mostrar_popup("Erro", f"Erro ao consultar auditoria: {e}")
            return

        linhas = [[str(r["id"]), r["data"], r["usuario"], r["acao"],
                   (r["detalhes"] or "").replace("\n", " | ")] for r in registros]
        self.tabela.set_dados(linhas, "(nenhum registro)")


# ==========================================
# HISTÓRICO DE MOVIMENTAÇÕES DE ESTOQUE
# ==========================================
class HistoricoEstoqueTab(BoxLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(14))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._montar()

    def _montar(self):
        l1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l1.add_widget(label_esquerda("Produto:", size_hint_x=None, width=dp(80)))
        self.e_produto = TextInput(hint_text="nome ou código...", multiline=False)
        l1.add_widget(self.e_produto)
        l1.add_widget(label_esquerda("Tipo:", size_hint_x=None, width=dp(50)))
        self.spinner_tipo = Spinner(text="Todos",
                                    values=["Todos", "ENTRADA", "SAIDA", "AJUSTE", "ESTORNO"],
                                    size_hint_x=None, width=dp(140))
        l1.add_widget(self.spinner_tipo)
        self.add_widget(l1)

        l2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l2.add_widget(label_esquerda("Período:", size_hint_x=None, width=dp(70)))
        self.spinner_periodo = Spinner(text="Últimos 7 dias", values=PERIODOS,
                                       size_hint_x=None, width=dp(180))
        l2.add_widget(self.spinner_periodo)
        btn_filtrar = Button(text="Filtrar", size_hint_x=None, width=dp(110),
                             background_color=COR_AZUL)
        btn_filtrar.bind(on_release=lambda *_: self._carregar())
        l2.add_widget(btn_filtrar)
        btn_limpar = Button(text="Limpar Filtros", size_hint_x=None, width=dp(140),
                            background_color=COR_CINZA)
        btn_limpar.bind(on_release=lambda *_: self._limpar())
        l2.add_widget(btn_limpar)
        self.add_widget(l2)

        titulos = ["ID", "Data/Hora", "Produto", "Tipo", "Qtd.", "Origem", "Usuário", "Detalhes"]
        larguras = [0.5, 1.3, 1.8, 0.8, 0.8, 1, 1, 1.6]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras)
        self.add_widget(self.tabela)

        self._carregar()

    def _limpar(self):
        self.e_produto.text = ""
        self.spinner_tipo.text = "Todos"
        self.spinner_periodo.text = "Últimos 7 dias"
        self._carregar()

    def _carregar(self):
        filtro_data = _filtro_data_sql(self.spinner_periodo.text, "m.data")
        params = []
        filtro_tipo = ""
        if self.spinner_tipo.text != "Todos":
            filtro_tipo = "AND m.tipo = ?"
            params.append(self.spinner_tipo.text)

        filtro_produto = ""
        produto_txt = self.e_produto.text.strip()
        if produto_txt:
            filtro_produto = "AND (p.nome LIKE ? OR p.codigo_barras LIKE ?)"
            params.extend([f"%{produto_txt}%", f"%{produto_txt}%"])

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT m.id, m.data, p.nome AS produto_nome, m.tipo, m.quantidade, "
                "m.origem, m.usuario, m.detalhes FROM movimentacoes_estoque m "
                "LEFT JOIN produtos p ON p.id = m.produto_id "
                f"WHERE 1=1 {filtro_data} {filtro_tipo} {filtro_produto} "
                "ORDER BY m.id DESC LIMIT 500", params)
            linhas_db = cursor.fetchall()
        except Exception as e:
            utils.logger.exception(f"Erro ao consultar movimentações: {e}")
            mostrar_popup("Erro", f"Erro ao consultar: {e}")
            return
        finally:
            if conn:
                conn.close()

        linhas = []
        for r in linhas_db:
            sinal = "+" if r["tipo"] in ("ENTRADA", "ESTORNO") else ("-" if r["tipo"] == "SAIDA" else "")
            qtd_txt = f"{sinal}{r['quantidade']:.2f}" if sinal else f"{r['quantidade']:.2f}"
            linhas.append([str(r["id"]), r["data"], r["produto_nome"] or "(produto removido)",
                           r["tipo"], qtd_txt, r["origem"] or "", r["usuario"] or "",
                           r["detalhes"] or ""])
        self.tabela.set_dados(linhas, "(nenhuma movimentação)")


# ==========================================
# HISTÓRICO DE CAIXAS
# ==========================================
class HistoricoCaixasTab(BoxLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(14))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._montar()

    def _montar(self):
        barra = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        btn_atualizar = Button(text="🔄 Atualizar", size_hint_x=None, width=dp(140),
                               background_color=COR_AZUL)
        btn_atualizar.bind(on_release=lambda *_: self._carregar())
        barra.add_widget(btn_atualizar)
        barra.add_widget(label_esquerda(
            "Toque num caixa da lista pra ver detalhes.", color=COR_CINZA, font_size="11sp"))
        self.add_widget(barra)

        titulos = ["ID", "Status", "Abertura", "Usu. Abert.", "Val. Abert.",
                   "Fechamento", "Esperado", "Informado", "Diferença"]
        larguras = [0.5, 0.9, 1.2, 1, 1, 1.2, 1, 1, 1]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, selecionavel=True,
                                  callback_selecao=self._ver_detalhes)
        self.add_widget(self.tabela)

        self._carregar()

    def _carregar(self):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, status, valor_abertura, valor_fechamento, valor_esperado, "
                "diferenca, usuario_abertura, usuario_fechamento, data_abertura, "
                "data_fechamento FROM caixa ORDER BY id DESC")
            linhas_db = cursor.fetchall()
        except Exception as e:
            utils.logger.exception(f"Erro ao consultar histórico de caixas: {e}")
            mostrar_popup("Erro", f"Erro ao consultar: {e}")
            return
        finally:
            if conn:
                conn.close()

        linhas, extra = [], []
        for r in linhas_db:
            if r["status"] == "ABERTO":
                fech_txt, esperado_txt, informado_txt, dif_txt = "-", "-", "-", "-"
            else:
                diferenca = r["diferenca"] or 0.0
                fech_txt = r["data_fechamento"] or "-"
                esperado_txt = utils.formatar_moeda(r["valor_esperado"] or 0.0)
                informado_txt = utils.formatar_moeda(r["valor_fechamento"] or 0.0)
                dif_txt = utils.formatar_moeda(diferenca)
            linhas.append([str(r["id"]), r["status"], r["data_abertura"] or "-",
                           r["usuario_abertura"] or "-",
                           utils.formatar_moeda(r["valor_abertura"] or 0.0),
                           fech_txt, esperado_txt, informado_txt, dif_txt])
            extra.append(dict(r))
        self.tabela.set_dados(linhas, "(nenhum caixa registrado)", dados_extra=extra)

    def _ver_detalhes(self, caixa):
        try:
            totais = calcular_totais_caixa(caixa["id"])
        except Exception as e:
            utils.logger.exception(f"Erro ao detalhar caixa: {e}")
            mostrar_popup("Erro", f"Erro ao detalhar caixa: {e}")
            return

        txt = (f"Abertura: {utils.formatar_moeda(totais['valor_abertura'])} em "
               f"{totais['data_abertura']}\n\nVendas por forma de pagamento:\n")
        for forma, dados in totais["vendas_por_forma"].items():
            txt += f"  {forma}: {dados['qtd']}x  {utils.formatar_moeda(dados['soma'])}\n"
        txt += f"\nSangrias: {utils.formatar_moeda(totais['sangrias'])}"
        txt += f"\nSuprimentos: {utils.formatar_moeda(totais['suprimentos'])}"
        txt += f"\nValor esperado no fechamento: {utils.formatar_moeda(totais['valor_esperado'])}"

        conteudo = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        conteudo.add_widget(label_esquerda(f"Caixa #{caixa['id']}", bold=True,
                                           font_size="15sp", halign="center",
                                           size_hint_y=None, height=dp(30)))
        conteudo.add_widget(label_esquerda(txt, size_hint_y=None, height=dp(220)))
        popup = Popup(title="Detalhes do Caixa", content=conteudo,
                     size_hint=(0.8, None), height=dp(340))
        btn_fechar = Button(text="Fechar", size_hint_y=None, height=dp(44))
        btn_fechar.bind(on_release=lambda *_: popup.dismiss())
        conteudo.add_widget(btn_fechar)
        popup.open()
