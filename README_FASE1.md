# Fase 1 — Esqueleto do app + Login (Kivy)

## O que tem aqui
- `app.py` — App Kivy com 3 telas: Login, Troca de Senha Obrigatória e uma
  tela Principal (placeholder — dashboard/menu vêm na Fase 2).
- `sistemacomercial.kv` — layout visual das telas acima.
- `utils_mobile.py` — versão do seu `utils.py` sem as partes de Tkinter
  (removidas `centralizar_janela`, `trazer_janela_para_frente` e
  `aplicar_estilo_treeview`, que não existem no Kivy). O resto
  (`formatar_moeda`, `desformatar_moeda`, `aplicar_fator_conversao`,
  `buscar_cep`, backup, log) é idêntico.
- `buildozer.spec` — configuração inicial para gerar o APK (Fase 5).

## O que você precisa adicionar
Copie o seu `database.py` original para esta mesma pasta, **sem
alterações** — ele é puro `sqlite3`, então funciona igual aqui. As funções
usadas nesta fase (`criar_conexao`, `verificar_senha`, `gerar_hash_senha`,
`registrar_auditoria`, `registrar_tentativa_login`,
`contar_tentativas_falhas_recentes`, `obter_permissoes_usuario`,
`inicializar_banco`) precisam existir nele.

## Como testar no computador (antes de ir pro Android)
```bash
pip install kivy
python app.py
```
Isso já valida login, bloqueio por tentativas, troca de senha obrigatória
e a passagem pra tela principal — tudo sem precisar de emulador Android.

## O que muda de verdade em relação ao main.py original
- `CTkToplevel` → `Screen` dentro de um `ScreenManager` (não são mais
  janelas separadas, são telas que se alternam no mesmo app).
- `messagebox.showerror/showinfo` → `mostrar_popup()` (função no `app.py`).
- Caminho do banco: antes fixo do lado do `.py`/executável; agora definido
  em `utils.definir_base_dir(self.user_data_dir)`, chamado uma vez no
  `App.build()`. No Android isso aponta pra pasta privada do app; no
  desktop, se quiser manter o comportamento antigo, é só passar `None`.

## Próximo passo (Fase 2)
Recriar o dashboard e o menu principal (que hoje ficam em `MainApp` no
`main.py`) como conteúdo real da `PrincipalScreen`, e começar o módulo
gerencial — que é onde vamos definir o componente de tabela padrão em
`RecycleView` que o PDV e as notas fiscais vão reaproveitar depois.
