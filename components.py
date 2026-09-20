"""
Componentes visuais reutilizáveis do app Kivy.

- CardIndicador: os cartõezinhos do topo do dashboard (Vendas Hoje, etc.)
- TabelaDados + criar_cabecalho: tabela genérica em lista rolável, usada em
  todas as listas do dashboard e, nas próximas fases, no PDV/gerencial/notas.
- GraficoBarras: gráfico de barras simples (substitui o Canvas do Tkinter).

Paleta de cores segue a mesma do sistema original (fundo escuro #12141c /
#1b1e26, verde #2ecc71, azul #3498db, laranja #e8a33d, vermelho #e74c3c).
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.properties import ListProperty, ObjectProperty, BooleanProperty
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp


# ==========================================
# POPUPS (substituem messagebox do Tkinter)
# ==========================================
def mostrar_popup(titulo, mensagem):
    conteudo = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
    conteudo.add_widget(label_esquerda(mensagem, halign="center"))
    botao_ok = Button(text="OK", size_hint=(1, None), height=dp(48))
    conteudo.add_widget(botao_ok)
    popup = Popup(title=titulo, content=conteudo,
                   size_hint=(0.85, None), height=dp(220), auto_dismiss=False)
    botao_ok.bind(on_release=popup.dismiss)
    popup.open()
    return popup


def confirmar_popup(titulo, mensagem, ao_confirmar):
    """Popup Sim/Não. Chama ao_confirmar() só se o usuário confirmar."""
    conteudo = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
    conteudo.add_widget(label_esquerda(mensagem, halign="center"))
    linha_botoes = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
    btn_sim = Button(text="Sim")
    btn_nao = Button(text="Não")
    linha_botoes.add_widget(btn_nao)
    linha_botoes.add_widget(btn_sim)
    conteudo.add_widget(linha_botoes)
    popup = Popup(title=titulo, content=conteudo,
                   size_hint=(0.85, None), height=dp(240), auto_dismiss=False)

    def _sim(*_):
        popup.dismiss()
        ao_confirmar()

    btn_sim.bind(on_release=_sim)
    btn_nao.bind(on_release=popup.dismiss)
    popup.open()
    return popup

COR_VERDE = (0.18, 0.80, 0.44, 1)
COR_AZUL = (0.20, 0.60, 0.86, 1)
COR_LARANJA = (0.91, 0.64, 0.24, 1)
COR_VERMELHO = (0.91, 0.30, 0.24, 1)
COR_CINZA = (0.46, 0.50, 0.58, 1)
COR_FUNDO_CARD = (0.106, 0.118, 0.149, 1)
COR_TEXTO_TITULO = (0.65, 0.68, 0.73, 1)
COR_TEXTO_SUB = (0.49, 0.51, 0.60, 1)


def label_esquerda(texto, **kwargs):
    """Label alinhado à esquerda de verdade (o padrão do Kivy é centralizado
    mesmo com halign='left', porque falta vincular text_size à largura).
    Aceita halign/valign customizados via kwargs (ex.: halign='right')."""
    kwargs.setdefault("halign", "left")
    kwargs.setdefault("valign", "middle")
    lbl = Label(text=texto, **kwargs)
    lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
    return lbl


class _RetanguloFundo(BoxLayout):
    """Mixin simples: desenha um retângulo de fundo que acompanha o widget."""
    cor_fundo = ListProperty(COR_FUNDO_CARD)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*self.cor_fundo)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._atualizar, size=self._atualizar)

    def _atualizar(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class CardIndicador(_RetanguloFundo):
    """Um cartão de indicador do dashboard (ex.: 'VENDAS HOJE')."""

    def __init__(self, titulo, valor, cor, subtitulo="", **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(108))
        kwargs.setdefault("padding", (dp(14), dp(10)))
        kwargs.setdefault("spacing", dp(3))
        super().__init__(**kwargs)

        faixa = Widget(size_hint_y=None, height=dp(3))
        with faixa.canvas.before:
            Color(*cor)
            rect = Rectangle(pos=faixa.pos, size=faixa.size)

        def _upd_faixa(inst, *_):
            rect.pos = inst.pos
            rect.size = inst.size

        faixa.bind(pos=_upd_faixa, size=_upd_faixa)

        self.add_widget(faixa)
        self.add_widget(label_esquerda(
            titulo.upper(), font_size="11sp", bold=True,
            color=COR_TEXTO_TITULO, size_hint_y=None, height=dp(18),
            shorten=True, shorten_from="right"))
        self.add_widget(label_esquerda(
            valor, font_size="21sp", bold=False, color=cor,
            size_hint_y=None, height=dp(32),
            shorten=True, shorten_from="right"))
        self.add_widget(label_esquerda(
            subtitulo or " ", font_size="10sp", color=COR_TEXTO_SUB,
            size_hint_y=None, height=dp(16)))


# ==========================================
# TABELA (lista rolável simples — sem RecycleView)
# ==========================================
class LinhaTabela(BoxLayout):
    """Uma linha da tabela. Widgets normais, criados um por item —
    para as quantidades de dados deste sistema (dezenas/centenas de
    linhas), isso é simples, confiável e rápido o suficiente."""

    def __init__(self, textos, larguras, extra=None, indice=0, tabela=None, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(36))
        kwargs.setdefault("padding", (dp(10), 0))
        super().__init__(**kwargs)
        self.extra = extra
        self.tabela = tabela  # só é setado (não-None) quando a tabela é selecionável

        self._cor_normal = (0.11, 0.12, 0.16, 1) if indice % 2 else (0.145, 0.157, 0.196, 1)
        self._cor_selecionada = (0.14, 0.32, 0.52, 1)
        with self.canvas.before:
            self._cor = Color(*self._cor_normal)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._atualizar, size=self._atualizar)

        larguras = larguras or [1] * len(textos)
        for texto, largura in zip(textos, larguras):
            self.add_widget(label_esquerda(
                str(texto), size_hint_x=largura, font_size="12sp",
                color=(0.90, 0.91, 0.94, 1), shorten=True,
                shorten_from="right"))

    def _atualizar(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def destacar(self, ligado):
        self._cor.rgba = self._cor_selecionada if ligado else self._cor_normal

    def on_touch_down(self, touch):
        # Só intercepta o toque se esta tabela for selecionável — senão,
        # deixa o evento seguir normalmente (ex.: pro ScrollView rolar).
        if self.tabela is not None and self.collide_point(*touch.pos):
            self.tabela._linha_tocada(self)
            return True
        return super().on_touch_down(touch)


class TabelaDados(ScrollView):
    """
    Tabela genérica. Uso simples:
        tabela = TabelaDados(larguras=[3, 1, 1])
        tabela.set_dados([["Arroz 5kg", "12", "R$ 32,00"], ...])

    Uso selecionável (listas de cliente/produto, remover item etc.):
        tabela = TabelaDados(larguras=[...], selecionavel=True,
                              callback_selecao=lambda registro: ...)
        tabela.set_dados(linhas, dados_extra=[registro1, registro2, ...])
        # a linha tocada fica destacada em azul até outra ser tocada.
    """
    larguras = ListProperty([])
    selecionavel = BooleanProperty(False)
    callback_selecao = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.do_scroll_x = False
        self._linha_selecionada = None
        self._container = BoxLayout(orientation="vertical", size_hint_y=None)
        self._container.bind(minimum_height=self._container.setter("height"))
        super(TabelaDados, self).add_widget(self._container)

    def set_dados(self, linhas, texto_vazio="(sem dados)", dados_extra=None):
        self._container.clear_widgets()
        self._linha_selecionada = None
        if not linhas:
            linhas = [[texto_vazio] + [""] * max(0, len(self.larguras) - 1)]
            dados_extra = [None]
        extra = dados_extra if dados_extra is not None else [None] * len(linhas)
        tabela_ref = self if self.selecionavel else None
        for i, (linha, ex) in enumerate(zip(linhas, extra)):
            self._container.add_widget(LinhaTabela(
                linha, self.larguras, extra=ex, indice=i, tabela=tabela_ref))

    def _linha_tocada(self, linha_widget):
        if self._linha_selecionada is not None and self._linha_selecionada is not linha_widget:
            self._linha_selecionada.destacar(False)
        linha_widget.destacar(True)
        self._linha_selecionada = linha_widget
        if self.callback_selecao and linha_widget.extra is not None:
            self.callback_selecao(linha_widget.extra)


def criar_cabecalho(titulos, larguras, altura=dp(32)):
    """Linha de cabeçalho fixa (fora da lista rolável), usando as mesmas
    proporções de largura passadas pra TabelaDados, pra ficar alinhado."""
    linha = BoxLayout(size_hint_y=None, height=altura, padding=(dp(10), 0))
    with linha.canvas.before:
        Color(0.20, 0.22, 0.27, 1)
        rect = Rectangle(pos=linha.pos, size=linha.size)

    def _upd(inst, *_):
        rect.pos = inst.pos
        rect.size = inst.size

    linha.bind(pos=_upd, size=_upd)
    for titulo, largura in zip(titulos, larguras):
        linha.add_widget(label_esquerda(
            titulo, size_hint_x=largura, font_size="12sp", bold=True,
            color=(0.62, 0.76, 0.95, 1)))
    return linha


def criar_bloco_tabela(titulo, titulos_colunas, larguras, cor_titulo=(1, 1, 1, 1)):
    """
    Monta um bloco completo (título + cabeçalho + tabela) pronto pra receber
    dados via bloco['tabela'].set_dados(linhas).
    Retorna (widget_do_bloco, TabelaDados).
    """
    bloco = _RetanguloFundo(orientation="vertical", padding=(0, dp(8), 0, dp(8)),
                            spacing=dp(6))
    bloco.add_widget(label_esquerda(
        titulo, bold=True, font_size="13sp", color=cor_titulo,
        size_hint_y=None, height=dp(24), padding=(dp(12), 0)))
    bloco.add_widget(criar_cabecalho(titulos_colunas, larguras))
    tabela = TabelaDados(larguras=larguras, size_hint_y=None, height=dp(150))
    bloco.add_widget(tabela)
    return bloco, tabela


# ==========================================
# GRAFICO DE BARRAS SIMPLES
# ==========================================
class _Barra(BoxLayout):
    def __init__(self, valor, valor_norm, dia_label, cor, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.add_widget(Label(
            text=(f"{valor:.0f}" if valor > 0 else ""),
            size_hint_y=None, height=dp(18), font_size="11sp", bold=True))
        self.add_widget(Widget(size_hint_y=max(0.001, 1 - valor_norm)))

        barra = Widget(size_hint_y=max(0.03, valor_norm))
        with barra.canvas.before:
            Color(*(cor if valor > 0 else (0.23, 0.25, 0.32, 1)))
            rect = Rectangle(pos=barra.pos, size=barra.size)

        def _upd(inst, *_):
            rect.pos = inst.pos
            rect.size = inst.size

        barra.bind(pos=_upd, size=_upd)
        self.add_widget(barra)
        self.add_widget(Label(
            text=dia_label, size_hint_y=None, height=dp(20),
            font_size="10sp", color=COR_TEXTO_SUB))


class GraficoBarras(_RetanguloFundo):
    """Gráfico de barras simples para 'Vendas dos últimos N dias'."""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(14))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._titulo = label_esquerda(
            "Vendas dos Últimos 7 Dias", bold=True, font_size="13sp",
            size_hint_y=None, height=dp(22))
        self.add_widget(self._titulo)
        self._area = BoxLayout(spacing=dp(4))
        self.add_widget(self._area)

    def set_dados(self, dados):
        """dados: lista de tuplas (dia_str 'YYYY-MM-DD', valor_float)."""
        self._area.clear_widgets()
        if not dados:
            self._area.add_widget(Label(text="Sem dados", color=COR_TEXTO_SUB))
            return
        maior = max((v for _, v in dados), default=0.0) or 1.0
        for dia, valor in dados:
            try:
                from datetime import datetime
                rotulo = datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m")
            except Exception:
                rotulo = dia
            self._area.add_widget(_Barra(valor, valor / maior, rotulo, COR_VERDE))
