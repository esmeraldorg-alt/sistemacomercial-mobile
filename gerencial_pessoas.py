"""
Gerencial — Clientes e Fornecedores (Fase 4b). Equivalente a janela_cliente,
janela_fornecedor, janela_gerenciar_clientes e janela_gerenciar_fornecedores
do modulo_gerencial.py original.
"""
import re
import threading

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.metrics import dp

import utils_mobile as utils
from components import (
    TabelaDados, criar_cabecalho, label_esquerda,
    mostrar_popup, confirmar_popup,
    COR_VERDE, COR_AZUL, COR_LARANJA, COR_VERMELHO, COR_CINZA,
)

from database import criar_conexao, registrar_auditoria


def _apenas_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def cpf_parece_valido(cpf):
    d = _apenas_digitos(cpf)
    return d == "" or len(d) == 11


def cnpj_parece_valido(cnpj):
    d = _apenas_digitos(cnpj)
    return d == "" or len(d) == 14


def _buscar_cep_async(codigo_cep, campo_log, campo_bairro, campo_cidade, botao=None):
    """Busca o CEP numa thread separada (rede não pode travar a UI do Kivy)
    e aplica o resultado de volta na thread principal."""
    if botao:
        botao.disabled = True
        botao.text = "..."

    def trabalhar():
        try:
            dados = utils.buscar_cep(codigo_cep)
            erro = None
        except Exception as e:
            dados, erro = None, str(e)

        def aplicar(dt):
            if botao:
                botao.disabled = False
                botao.text = "Buscar CEP"
            if erro:
                mostrar_popup("Erro", erro)
                return
            campo_log.text = dados["logradouro"]
            campo_bairro.text = dados["bairro"]
            campo_cidade.text = dados["cidade_uf"]

        Clock.schedule_once(aplicar, 0)

    threading.Thread(target=trabalhar, daemon=True).start()


def _bloco_endereco(raiz, campo):
    """Cria os campos de CEP (+ botão buscar), número, bairro, logradouro
    e cidade/UF, retornando os TextInputs criados."""
    linha_cep = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
    e_cep = campo(None, filtro=None, inline=True)
    linha_cep.add_widget(e_cep)
    btn_cep = Button(text="Buscar CEP", size_hint_x=None, width=dp(120),
                     background_color=COR_AZUL)
    linha_cep.add_widget(btn_cep)
    raiz.add_widget(label_esquerda("CEP:", size_hint_y=None, height=dp(20)))
    raiz.add_widget(linha_cep)

    e_log = campo("Logradouro (Rua/Av):")
    e_num = campo("Número:")
    e_bairro = campo("Bairro:")
    e_cidade = campo("Cidade / UF:")

    btn_cep.bind(on_release=lambda *_: _buscar_cep_async(
        e_cep.text.strip(), e_log, e_bairro, e_cidade, botao=btn_cep))

    return e_cep, e_log, e_num, e_bairro, e_cidade


# ==========================================
# CLIENTES
# ==========================================
class CadastrarClienteTab(BoxLayout):
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

        def campo(rotulo, filtro=None, valor_inicial="", inline=False):
            if rotulo:
                raiz.add_widget(label_esquerda(rotulo, size_hint_y=None, height=dp(20)))
            c = TextInput(text=valor_inicial, multiline=False, input_filter=filtro,
                          size_hint_y=None, height=dp(44))
            if not inline:
                raiz.add_widget(c)
            return c

        self.e_nome = campo("Nome:*")
        self.e_tel = campo("Telefone:")
        self.e_cpf = campo("CPF:")
        self.e_limite = campo("Limite de Crédito (Prazo):", filtro="float", valor_inicial="0.00")

        (self.e_cep, self.e_log, self.e_num, self.e_bairro,
         self.e_cidade) = _bloco_endereco(raiz, campo)

        btn_salvar = Button(text="Salvar Cliente", size_hint_y=None, height=dp(50),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        raiz.add_widget(btn_salvar)

        scroll.add_widget(raiz)
        self.add_widget(scroll)

    def _salvar(self, *_):
        nome = self.e_nome.text.strip()
        if not nome:
            mostrar_popup("Erro", "O nome do cliente é obrigatório.")
            return
        if not cpf_parece_valido(self.e_cpf.text):
            mostrar_popup("CPF suspeito",
                          "O CPF informado não tem 11 dígitos. Corrija ou deixe em branco.")
            return
        try:
            limite = float((self.e_limite.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Limite de crédito precisa ser um número.")
            return

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO clientes (nome, telefone, cpf, cep, logradouro, numero, "
                "bairro, cidade_uf, limite_credito) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nome, self.e_tel.text.strip(), self.e_cpf.text.strip(),
                 self.e_cep.text.strip(), self.e_log.text.strip(), self.e_num.text.strip(),
                 self.e_bairro.text.strip(), self.e_cidade.text.strip(), limite))
            conn.commit()
            registrar_auditoria(self.usuario_nome, "CADASTRO_CLIENTE",
                                f"{nome} | CPF: {self.e_cpf.text.strip()}")
            mostrar_popup("Sucesso", "Cliente cadastrado com sucesso!")

            for campo_ in (self.e_nome, self.e_tel, self.e_cpf, self.e_cep,
                          self.e_log, self.e_num, self.e_bairro, self.e_cidade):
                campo_.text = ""
            self.e_limite.text = "0.00"
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao salvar cliente: {ex}")
            mostrar_popup("Erro", f"Erro ao salvar cliente: {ex}")
        finally:
            if conn:
                conn.close()


class GerenciarClientesTab(BoxLayout):
    def __init__(self, app_ref, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(12))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.usuario_nome = app_ref.usuario_atual[1] if app_ref.usuario_atual else "desconhecido"
        self.cliente_selecionado = None
        self._montar()

    def _montar(self):
        barra_busca = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.e_busca = TextInput(hint_text="Buscar por nome, telefone ou CPF...",
                                  multiline=False)
        self.e_busca.bind(text=lambda inst, val: self._carregar(val))
        barra_busca.add_widget(self.e_busca)
        self.add_widget(barra_busca)

        titulos = ["Nome", "Telefone", "CPF", "Limite Créd."]
        larguras = [2.4, 1.2, 1.2, 1.2]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, size_hint_y=1.2,
                                   selecionavel=True, callback_selecao=self._selecionar)
        self.add_widget(self.tabela)

        self.painel = BoxLayout(orientation="vertical", size_hint_y=None,
                                height=dp(280), padding=dp(10), spacing=dp(4))
        self._montar_painel()
        self.add_widget(self.painel)
        self._carregar("")

    def _montar_painel(self):
        self.painel.add_widget(label_esquerda(
            "Selecione um cliente na tabela pra editar:", bold=True, color=COR_LARANJA,
            size_hint_y=None, height=dp(24)))

        l1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l1.add_widget(label_esquerda("Nome:", size_hint_x=None, width=dp(60)))
        self.e_nome = TextInput(multiline=False)
        l1.add_widget(self.e_nome)
        l1.add_widget(label_esquerda("Telefone:", size_hint_x=None, width=dp(70)))
        self.e_tel = TextInput(multiline=False, size_hint_x=0.7)
        l1.add_widget(self.e_tel)
        self.painel.add_widget(l1)

        l2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l2.add_widget(label_esquerda("CPF:", size_hint_x=None, width=dp(60)))
        self.e_cpf = TextInput(multiline=False)
        l2.add_widget(self.e_cpf)
        l2.add_widget(label_esquerda("Limite (R$):", size_hint_x=None, width=dp(85)))
        self.e_limite = TextInput(multiline=False, input_filter="float", size_hint_x=0.6)
        l2.add_widget(self.e_limite)
        self.painel.add_widget(l2)

        l3 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l3.add_widget(label_esquerda("CEP:", size_hint_x=None, width=dp(60)))
        self.e_cep = TextInput(multiline=False)
        l3.add_widget(self.e_cep)
        btn_cep = Button(text="Buscar", size_hint_x=None, width=dp(80),
                         background_color=COR_AZUL)
        l3.add_widget(btn_cep)
        l3.add_widget(label_esquerda("Número:", size_hint_x=None, width=dp(70)))
        self.e_num = TextInput(multiline=False, size_hint_x=0.6)
        l3.add_widget(self.e_num)
        self.painel.add_widget(l3)

        l4 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l4.add_widget(label_esquerda("Logradouro:", size_hint_x=None, width=dp(90)))
        self.e_log = TextInput(multiline=False)
        l4.add_widget(self.e_log)
        l4.add_widget(label_esquerda("Bairro:", size_hint_x=None, width=dp(60)))
        self.e_bairro = TextInput(multiline=False, size_hint_x=0.7)
        l4.add_widget(self.e_bairro)
        self.painel.add_widget(l4)

        l5 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l5.add_widget(label_esquerda("Cidade/UF:", size_hint_x=None, width=dp(90)))
        self.e_cidade = TextInput(multiline=False)
        l5.add_widget(self.e_cidade)
        self.painel.add_widget(l5)

        btn_cep.bind(on_release=lambda *_: _buscar_cep_async(
            self.e_cep.text.strip(), self.e_log, self.e_bairro, self.e_cidade, botao=btn_cep))

        btn_salvar = Button(text="Salvar Alterações", size_hint_y=None, height=dp(46),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        self.painel.add_widget(btn_salvar)

    def _carregar(self, filtro):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            if filtro:
                cursor.execute(
                    "SELECT id, nome, telefone, cpf, limite_credito FROM clientes "
                    "WHERE nome LIKE ? OR telefone LIKE ? OR cpf LIKE ? ORDER BY nome",
                    (f"%{filtro}%", f"%{filtro}%", f"%{filtro}%"))
            else:
                cursor.execute(
                    "SELECT id, nome, telefone, cpf, limite_credito FROM clientes "
                    "ORDER BY nome LIMIT 300")
            linhas, extra = [], []
            for row in cursor.fetchall():
                linhas.append([row["nome"], row["telefone"] or "-", row["cpf"] or "-",
                                utils.formatar_moeda(row["limite_credito"])])
                extra.append(dict(row))
            self.tabela.set_dados(linhas, "Nenhum cliente encontrado.", dados_extra=extra)
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar clientes: {e}")
        finally:
            if conn:
                conn.close()

    def _selecionar(self, cliente):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM clientes WHERE id = ?", (cliente["id"],))
            row = cursor.fetchone()
        finally:
            if conn:
                conn.close()
        if not row:
            return
        self.cliente_selecionado = dict(row)
        self.e_nome.text = row["nome"] or ""
        self.e_tel.text = row["telefone"] or ""
        self.e_cpf.text = row["cpf"] or ""
        self.e_limite.text = f"{row['limite_credito']:.2f}"
        self.e_cep.text = row["cep"] or ""
        self.e_log.text = row["logradouro"] or ""
        self.e_num.text = row["numero"] or ""
        self.e_bairro.text = row["bairro"] or ""
        self.e_cidade.text = row["cidade_uf"] or ""

    def _salvar(self, *_):
        if not self.cliente_selecionado:
            mostrar_popup("Aviso", "Selecione um cliente na tabela para editar.")
            return
        novo_nome = self.e_nome.text.strip()
        if not novo_nome:
            mostrar_popup("Erro", "O nome do cliente é obrigatório.")
            return
        if not cpf_parece_valido(self.e_cpf.text):
            mostrar_popup("CPF suspeito", "O CPF informado não tem 11 dígitos.")
            return
        try:
            limite = float((self.e_limite.text or "0").replace(",", "."))
        except ValueError:
            mostrar_popup("Erro", "Limite de crédito precisa ser um número.")
            return

        pid = self.cliente_selecionado["id"]
        conn = None
        try:
            conn = criar_conexao()
            conn.execute(
                "UPDATE clientes SET nome=?, telefone=?, cpf=?, cep=?, logradouro=?, "
                "numero=?, bairro=?, cidade_uf=?, limite_credito=? WHERE id=?",
                (novo_nome, self.e_tel.text.strip(), self.e_cpf.text.strip(),
                 self.e_cep.text.strip(), self.e_log.text.strip(), self.e_num.text.strip(),
                 self.e_bairro.text.strip(), self.e_cidade.text.strip(), limite, pid))
            conn.commit()
            registrar_auditoria(self.usuario_nome, "EDICAO_CLIENTE", f"ID {pid} | {novo_nome}")
            mostrar_popup("Sucesso", "Cliente atualizado com sucesso!")
            self._carregar(self.e_busca.text)
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao atualizar cliente: {ex}")
            mostrar_popup("Erro", f"Erro ao atualizar cliente: {ex}")
        finally:
            if conn:
                conn.close()


# ==========================================
# FORNECEDORES
# ==========================================
class CadastrarFornecedorTab(BoxLayout):
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

        def campo(rotulo, filtro=None, valor_inicial="", inline=False):
            if rotulo:
                raiz.add_widget(label_esquerda(rotulo, size_hint_y=None, height=dp(20)))
            c = TextInput(text=valor_inicial, multiline=False, input_filter=filtro,
                          size_hint_y=None, height=dp(44))
            if not inline:
                raiz.add_widget(c)
            return c

        self.e_nome = campo("Nome / Razão Social:*")
        self.e_cnpj = campo("CNPJ:")
        self.e_tel = campo("Telefone:")

        (self.e_cep, self.e_log, self.e_num, self.e_bairro,
         self.e_cidade) = _bloco_endereco(raiz, campo)

        btn_salvar = Button(text="Salvar Fornecedor", size_hint_y=None, height=dp(50),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        raiz.add_widget(btn_salvar)

        scroll.add_widget(raiz)
        self.add_widget(scroll)

    def _salvar(self, *_):
        nome = self.e_nome.text.strip()
        if not nome:
            mostrar_popup("Erro", "O nome do fornecedor é obrigatório.")
            return
        if not cnpj_parece_valido(self.e_cnpj.text):
            mostrar_popup("CNPJ suspeito",
                          "O CNPJ informado não tem 14 dígitos. Corrija ou deixe em branco.")
            return

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fornecedores (nome, cnpj, telefone, cep, logradouro, "
                "numero, bairro, cidade_uf) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (nome, self.e_cnpj.text.strip(), self.e_tel.text.strip(),
                 self.e_cep.text.strip(), self.e_log.text.strip(), self.e_num.text.strip(),
                 self.e_bairro.text.strip(), self.e_cidade.text.strip()))
            conn.commit()
            registrar_auditoria(self.usuario_nome, "CADASTRO_FORNECEDOR", nome)
            mostrar_popup("Sucesso", "Fornecedor cadastrado com sucesso!")

            for campo_ in (self.e_nome, self.e_cnpj, self.e_tel, self.e_cep,
                          self.e_log, self.e_num, self.e_bairro, self.e_cidade):
                campo_.text = ""
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao salvar fornecedor: {ex}")
            mostrar_popup("Erro", f"Erro ao salvar fornecedor: {ex}")
        finally:
            if conn:
                conn.close()


class GerenciarFornecedoresTab(BoxLayout):
    def __init__(self, app_ref, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(12))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.usuario_nome = app_ref.usuario_atual[1] if app_ref.usuario_atual else "desconhecido"
        self.fornecedor_selecionado = None
        self._montar()

    def _montar(self):
        barra_busca = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.e_busca = TextInput(hint_text="Buscar por nome ou CNPJ...", multiline=False)
        self.e_busca.bind(text=lambda inst, val: self._carregar(val))
        barra_busca.add_widget(self.e_busca)
        self.add_widget(barra_busca)

        titulos = ["Nome", "CNPJ", "Telefone"]
        larguras = [2.6, 1.4, 1.2]
        self.add_widget(criar_cabecalho(titulos, larguras))
        self.tabela = TabelaDados(larguras=larguras, size_hint_y=1.2,
                                   selecionavel=True, callback_selecao=self._selecionar)
        self.add_widget(self.tabela)

        self.painel = BoxLayout(orientation="vertical", size_hint_y=None,
                                height=dp(240), padding=dp(10), spacing=dp(4))
        self._montar_painel()
        self.add_widget(self.painel)
        self._carregar("")

    def _montar_painel(self):
        self.painel.add_widget(label_esquerda(
            "Selecione um fornecedor na tabela pra editar:", bold=True, color=COR_LARANJA,
            size_hint_y=None, height=dp(24)))

        l1 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l1.add_widget(label_esquerda("Nome:", size_hint_x=None, width=dp(60)))
        self.e_nome = TextInput(multiline=False)
        l1.add_widget(self.e_nome)
        l1.add_widget(label_esquerda("CNPJ:", size_hint_x=None, width=dp(60)))
        self.e_cnpj = TextInput(multiline=False, size_hint_x=0.7)
        l1.add_widget(self.e_cnpj)
        self.painel.add_widget(l1)

        l2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l2.add_widget(label_esquerda("Telefone:", size_hint_x=None, width=dp(75)))
        self.e_tel = TextInput(multiline=False)
        l2.add_widget(self.e_tel)
        l2.add_widget(label_esquerda("CEP:", size_hint_x=None, width=dp(50)))
        self.e_cep = TextInput(multiline=False, size_hint_x=0.5)
        l2.add_widget(self.e_cep)
        btn_cep = Button(text="Buscar", size_hint_x=None, width=dp(80),
                         background_color=COR_AZUL)
        l2.add_widget(btn_cep)
        self.painel.add_widget(l2)

        l3 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l3.add_widget(label_esquerda("Logradouro:", size_hint_x=None, width=dp(90)))
        self.e_log = TextInput(multiline=False)
        l3.add_widget(self.e_log)
        l3.add_widget(label_esquerda("Número:", size_hint_x=None, width=dp(70)))
        self.e_num = TextInput(multiline=False, size_hint_x=0.5)
        l3.add_widget(self.e_num)
        self.painel.add_widget(l3)

        l4 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        l4.add_widget(label_esquerda("Bairro:", size_hint_x=None, width=dp(60)))
        self.e_bairro = TextInput(multiline=False)
        l4.add_widget(self.e_bairro)
        l4.add_widget(label_esquerda("Cidade/UF:", size_hint_x=None, width=dp(90)))
        self.e_cidade = TextInput(multiline=False, size_hint_x=0.7)
        l4.add_widget(self.e_cidade)
        self.painel.add_widget(l4)

        btn_cep.bind(on_release=lambda *_: _buscar_cep_async(
            self.e_cep.text.strip(), self.e_log, self.e_bairro, self.e_cidade, botao=btn_cep))

        btn_salvar = Button(text="Salvar Alterações", size_hint_y=None, height=dp(46),
                             background_color=COR_VERDE, bold=True)
        btn_salvar.bind(on_release=self._salvar)
        self.painel.add_widget(btn_salvar)

    def _carregar(self, filtro):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            if filtro:
                cursor.execute(
                    "SELECT id, nome, cnpj, telefone FROM fornecedores "
                    "WHERE nome LIKE ? OR cnpj LIKE ? ORDER BY nome",
                    (f"%{filtro}%", f"%{filtro}%"))
            else:
                cursor.execute(
                    "SELECT id, nome, cnpj, telefone FROM fornecedores "
                    "ORDER BY nome LIMIT 300")
            linhas, extra = [], []
            for row in cursor.fetchall():
                linhas.append([row["nome"], row["cnpj"] or "-", row["telefone"] or "-"])
                extra.append(dict(row))
            self.tabela.set_dados(linhas, "Nenhum fornecedor encontrado.", dados_extra=extra)
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar fornecedores: {e}")
        finally:
            if conn:
                conn.close()

    def _selecionar(self, fornecedor):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fornecedores WHERE id = ?", (fornecedor["id"],))
            row = cursor.fetchone()
        finally:
            if conn:
                conn.close()
        if not row:
            return
        self.fornecedor_selecionado = dict(row)
        self.e_nome.text = row["nome"] or ""
        self.e_cnpj.text = row["cnpj"] or ""
        self.e_tel.text = row["telefone"] or ""
        self.e_cep.text = row["cep"] or ""
        self.e_log.text = row["logradouro"] or ""
        self.e_num.text = row["numero"] or ""
        self.e_bairro.text = row["bairro"] or ""
        self.e_cidade.text = row["cidade_uf"] or ""

    def _salvar(self, *_):
        if not self.fornecedor_selecionado:
            mostrar_popup("Aviso", "Selecione um fornecedor na tabela para editar.")
            return
        novo_nome = self.e_nome.text.strip()
        if not novo_nome:
            mostrar_popup("Erro", "O nome do fornecedor é obrigatório.")
            return
        if not cnpj_parece_valido(self.e_cnpj.text):
            mostrar_popup("CNPJ suspeito", "O CNPJ informado não tem 14 dígitos.")
            return

        pid = self.fornecedor_selecionado["id"]
        conn = None
        try:
            conn = criar_conexao()
            conn.execute(
                "UPDATE fornecedores SET nome=?, cnpj=?, telefone=?, cep=?, logradouro=?, "
                "numero=?, bairro=?, cidade_uf=? WHERE id=?",
                (novo_nome, self.e_cnpj.text.strip(), self.e_tel.text.strip(),
                 self.e_cep.text.strip(), self.e_log.text.strip(), self.e_num.text.strip(),
                 self.e_bairro.text.strip(), self.e_cidade.text.strip(), pid))
            conn.commit()
            registrar_auditoria(self.usuario_nome, "EDICAO_FORNECEDOR", f"ID {pid} | {novo_nome}")
            mostrar_popup("Sucesso", "Fornecedor atualizado com sucesso!")
            self._carregar(self.e_busca.text)
        except Exception as ex:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao atualizar fornecedor: {ex}")
            mostrar_popup("Erro", f"Erro ao atualizar fornecedor: {ex}")
        finally:
            if conn:
                conn.close()
