[app]
title = Sistema Comercial
package.name = sistemacomercial
package.domain = org.seudominio

source.dir = .
source.include_exts = py,kv,png,jpg,ttf

version = 0.1

# sqlite3 já vem com o Python; kivy é a UI.
requirements = python3,kivy

orientation = portrait
fullscreen = 0

# Permissão de rede necessária para buscar_cep() (ViaCEP)
android.permissions = INTERNET
android.accept_sdk_license = True
p4a.branch = develop
[buildozer]
log_level = 2
