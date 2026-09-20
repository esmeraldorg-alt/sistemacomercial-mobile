"""
Ponto de entrada da versão Android (Kivy) do Sistema Comercial.

Reaproveita a lógica de negócio de database.py (login, senha, permissões,
auditoria, caixa, dashboard) sem nenhuma alteração — essas funções são
puro sqlite3 e não dependem de Tkinter.

IMPORTANTE: copie o seu database.py original para esta mesma pasta antes
de rodar. Ele não precisa de nenhuma mudança.

Equivalências com o main.py original:
  TelaLoginUsuario           -> LoginScreen
  TelaTrocaSenhaObrigatoria  -> TrocaSenhaScreen
  MainApp (janela principal) -> PrincipalScreen (barra superior + abas)
  DashboardFrame             -> DashboardConteudo (dashboard_menu.py)
  MenuFrame                  -> MenuConteudo (dashboard_menu.py)
  JanelaCaixa                -> CaixaPopup (dashboard_menu.py)
  messagebox.showerror/info  -> mostrar_popup() (components.py)
"""
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.properties import ObjectProperty
from kivy.clock import Clock
from kivy.metrics import dp

import utils_mobile as utils
from components import mostrar_popup, label_esquerda, COR_LARANJA

from database import (
    criar_conexao, verificar_senha, gerar_hash_senha,
    registrar_auditoria, registrar_tentativa_login,
    contar_tentativas_falhas_recentes, obter_permissoes_usuario,
    obter_caixa_aberto,
)

MAX_TENTATIVAS = 5
JANELA_BLOQUEIO_MIN = 5

# Não é preciso chamar Builder.load_file() aqui: o Kivy já carrega
# automaticamente um arquivo com o nome da classe do App em minúsculas
# (SistemaComercialApp -> sistemacomercial.kv). Chamar de novo manualmente
# fazia ele carregar duas vezes (mostrava um aviso no log).


# ==========================================
# TELA DE LOGIN
# equivalente a TelaLoginUsuario (main.py, linhas 93-186)
# ==========================================
class LoginScreen(Screen):
    campo_usuario = ObjectProperty(None)
    campo_senha = ObjectProperty(None)

    def on_pre_enter(self, *args):
        self.usuarios_dados = []
        self.carregar_usuarios_db()

    def carregar_usuarios_db(self):
        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, nome, senha, perfil, senha_provisoria "
                "FROM usuarios WHERE ativo = 1"
            )
            self.usuarios_dados = cursor.fetchall()
        except Exception as e:
            utils.logger.exception(f"Erro ao carregar usuarios: {e}")
            self.usuarios_dados = []
        finally:
            if conn:
                conn.close()

    def confirmar(self):
        nome = (self.campo_usuario.text or "").strip()
        senha = (self.campo_senha.text or "").strip()

        if not nome:
            mostrar_popup("Erro", "Digite o nome de usuário.")
            return

        falhas = contar_tentativas_falhas_recentes(nome, JANELA_BLOQUEIO_MIN)
        if falhas >= MAX_TENTATIVAS:
            mostrar_popup(
                "Conta Bloqueada",
                f"Muitas tentativas falhas para '{nome}'.\n"
                f"Aguarde {JANELA_BLOQUEIO_MIN} minutos.",
            )
            return

        usuario = None
        for u in self.usuarios_dados:
            if u["nome"] == nome:
                usuario = u
                break

        if not usuario:
            registrar_tentativa_login(nome, False)
            mostrar_popup("Erro", "Usuário não encontrado.")
            return

        if verificar_senha(senha, usuario["senha"]):
            if "$" not in (usuario["senha"] or ""):
                conn = None
                try:
                    conn = criar_conexao()
                    conn.execute("UPDATE usuarios SET senha = ? WHERE id = ?",
                                 (gerar_hash_senha(senha), usuario["id"]))
                    conn.commit()
                finally:
                    if conn:
                        conn.close()

            registrar_tentativa_login(nome, True)
            registrar_auditoria(nome, "LOGIN", "Login realizado com sucesso")

            usuario_tuple = (usuario["id"], usuario["nome"],
                              usuario["senha"], usuario["perfil"])

            self.campo_senha.text = ""

            if usuario["senha_provisoria"]:
                tela_troca = self.manager.get_screen("troca_senha")
                tela_troca.usuario_tuple = usuario_tuple
                self.manager.current = "troca_senha"
                return

            self._entrar_no_sistema(usuario_tuple)
        else:
            registrar_tentativa_login(nome, False)
            mostrar_popup("Erro", "Senha incorreta.")

    def _entrar_no_sistema(self, usuario_tuple):
        app = App.get_running_app()
        app.usuario_atual = usuario_tuple
        try:
            app.permissoes_usuario = obter_permissoes_usuario(usuario_tuple[0])
        except Exception as e:
            utils.logger.warning(f"Erro ao carregar permissoes: {e}")
            app.permissoes_usuario = []
        self.manager.current = "principal"


# ==========================================
# TELA DE TROCA DE SENHA OBRIGATÓRIA
# equivalente a TelaTrocaSenhaObrigatoria (main.py, linhas 29-91)
# ==========================================
class TrocaSenhaScreen(Screen):
    campo_nova = ObjectProperty(None)
    campo_confirmacao = ObjectProperty(None)
    usuario_tuple = None

    def salvar(self):
        nova = (self.campo_nova.text or "").strip()
        conf = (self.campo_confirmacao.text or "").strip()

        if len(nova) < 6:
            mostrar_popup("Erro", "A senha deve ter pelo menos 6 caracteres.")
            return
        if nova != conf:
            mostrar_popup("Erro", "As senhas não coincidem.")
            return
        if nova == "admin":
            mostrar_popup("Erro", "Não use a senha padrão 'admin'.")
            return

        conn = None
        try:
            conn = criar_conexao()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE usuarios SET senha = ?, senha_provisoria = 0 WHERE id = ?",
                (gerar_hash_senha(nova), self.usuario_tuple[0]),
            )
            conn.commit()
            registrar_auditoria(self.usuario_tuple[1], "TROCA_SENHA_OBRIGATORIA",
                                 "Senha provisoria trocada no primeiro acesso")
            mostrar_popup("Sucesso", "Senha alterada com sucesso!")

            self.campo_nova.text = ""
            self.campo_confirmacao.text = ""

            login_screen = self.manager.get_screen("login")
            login_screen._entrar_no_sistema(self.usuario_tuple)
        except Exception as e:
            if conn:
                conn.rollback()
            utils.logger.exception(f"Erro ao salvar senha: {e}")
            mostrar_popup("Erro", f"Erro ao salvar senha: {e}")
        finally:
            if conn:
                conn.close()


# ==========================================
# TELA PRINCIPAL: barra superior + abas Dashboard / Menu Principal
# equivalente a MainApp (main.py)
# ==========================================
class PrincipalScreen(Screen):
    def on_pre_enter(self, *args):
        app = App.get_running_app()
        if not getattr(self, "_construido", False):
            self._construir(app)
            self._construido = True
        else:
            self.dashboard.carregar_dados()
        self.menu.atualizar_usuario(app.usuario_atual)
        self.menu.atualizar_status_caixa()
        self._atualizar_barra_superior(app)

    def _construir(self, app):
        # Import tardio pra evitar import circular (dashboard_menu usa
        # componentes que, por sua vez, não dependem deste módulo).
        from dashboard_menu import DashboardConteudo, MenuConteudo

        raiz = BoxLayout(orientation="vertical")

        topo = BoxLayout(size_hint_y=None, height=dp(54), padding=(dp(16), 0))
        info_usuario = BoxLayout(orientation="vertical")
        self.lbl_usuario_topo = label_esquerda(
            "Nenhum usuário logado", bold=True, font_size="13sp",
            color=(0.25, 0.82, 0.88, 1))
        self.lbl_caixa_topo = label_esquerda(
            "Caixa: -", font_size="10sp", color=COR_LARANJA)
        info_usuario.add_widget(self.lbl_usuario_topo)
        info_usuario.add_widget(self.lbl_caixa_topo)
        topo.add_widget(info_usuario)

        btn_atualizar = Button(text="Atualizar Dashboard", size_hint=(None, None),
                                size=(dp(190), dp(36)),
                                pos_hint={"center_y": 0.5})
        btn_atualizar.bind(on_release=lambda *_: self.dashboard.carregar_dados())
        topo.add_widget(btn_atualizar)

        raiz.add_widget(topo)

        tabs = TabbedPanel(do_default_tab=False, tab_width=dp(160))

        aba_dashboard = TabbedPanelItem(text="Dashboard")
        self.dashboard = DashboardConteudo()
        aba_dashboard.add_widget(self.dashboard)
        tabs.add_widget(aba_dashboard)

        aba_menu = TabbedPanelItem(text="Menu Principal")
        self.menu = MenuConteudo(app)
        aba_menu.add_widget(self.menu)
        tabs.add_widget(aba_menu)

        tabs.default_tab = aba_dashboard
        raiz.add_widget(tabs)

        self.add_widget(raiz)

        # Atualização automática, como no original (main.py: after(15000)/(30000))
        Clock.schedule_interval(lambda dt: self._atualizar_barra_superior(app), 15)
        Clock.schedule_interval(lambda dt: self.menu.atualizar_status_caixa(), 15)
        Clock.schedule_interval(lambda dt: self.dashboard.carregar_dados(), 30)

    def _atualizar_barra_superior(self, app):
        if app.usuario_atual:
            nome, perfil = app.usuario_atual[1], app.usuario_atual[3]
            self.lbl_usuario_topo.text = f"{nome} ({perfil or 'Padrao'})"
        else:
            self.lbl_usuario_topo.text = "Nenhum usuário logado"

        caixa = obter_caixa_aberto()
        if caixa:
            self.lbl_caixa_topo.text = f"Caixa #{caixa['id']} ABERTO"
            self.lbl_caixa_topo.color = (0.18, 0.80, 0.44, 1)
        else:
            self.lbl_caixa_topo.text = "Caixa FECHADO"
            self.lbl_caixa_topo.color = COR_LARANJA


class SistemaComercialManager(ScreenManager):
    pass


class SistemaComercialApp(App):
    usuario_atual = None
    permissoes_usuario = []

    def build(self):
        # Define onde o banco/backups/logs vão morar. No Android,
        # self.user_data_dir já aponta para a pasta privada do app.
        utils.definir_base_dir(self.user_data_dir)

        from database import inicializar_banco
        inicializar_banco()

        sm = SistemaComercialManager(transition=NoTransition())
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(TrocaSenhaScreen(name="troca_senha"))
        sm.add_widget(PrincipalScreen(name="principal"))

        from pdv import PDVScreen
        sm.add_widget(PDVScreen(name="pdv"))

        from gerencial_produtos import GerencialScreen
        sm.add_widget(GerencialScreen(name="gerencial"))

        sm.current = "login"
        self.sm = sm
        return sm

    def on_start(self):
        Clock.schedule_once(lambda dt: utils.fazer_backup_diario(), 2)

    def verificar_permissao(self, nome_tela):
        if not self.usuario_atual:
            return False
        perfil = self.usuario_atual[3]
        if perfil == "Administrador":
            return True
        return nome_tela in self.permissoes_usuario

    def trocar_usuario(self):
        self.usuario_atual = None
        self.permissoes_usuario = []
        self.sm.current = "login"


if __name__ == "__main__":
    SistemaComercialApp().run()
