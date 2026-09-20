# Fase 2 — Dashboard, Menu Principal e Controle de Caixa

## Arquivos novos/alterados
- `components.py` (novo) — peças reutilizáveis: `CardIndicador` (os
  cartõezinhos), `TabelaDados` (tabela genérica em RecycleView),
  `GraficoBarras` (gráfico simples de vendas), `mostrar_popup` e
  `confirmar_popup`. Vai ser reaproveitado no PDV, gerencial e notas.
- `dashboard_menu.py` (novo) — `DashboardConteudo` (equivalente a
  `DashboardFrame`), `MenuConteudo` (equivalente a `MenuFrame`) e
  `CaixaPopup` (equivalente a `JanelaCaixa`, com abrir/fechar/sangria/
  suprimento).
- `app.py` — `PrincipalScreen` agora monta a barra superior (usuário +
  status do caixa) e as abas "Dashboard" / "Menu Principal" via
  `TabbedPanel`, com atualização automática (dashboard a cada 30s, status
  do caixa a cada 15s — igual ao `main.py` original).
- `sistemacomercial.kv` — removi o placeholder da tela principal (agora
  ela é montada 100% em Python).

## O que já funciona igual ao original
- Os 6 cards do topo (Vendas Hoje, Ticket Médio, Estoque Baixo, Fiados em
  Aberto, Fiados Vencidos, Caixa Atual).
- Gráfico de vendas dos últimos 7 dias.
- As 5 tabelas: Produtos Mais Vendidos, Top Clientes, Últimas Vendas,
  Estoque Baixo, Produtos Próximos do Vencimento.
- Menu com todos os botões, respeitando permissão por perfil (a mesma
  lógica `verificar_permissao` do `main.py`, incluindo a checagem
  separada de `sangria_suprimento` que eu conferi no seu código original).
- Abrir Caixa, Fechar Caixa (com esperado x informado x diferença por
  forma de pagamento), Sangria e Suprimento — tudo batendo com as funções
  do seu `database.py` (`abrir_caixa`, `fechar_caixa`,
  `calcular_totais_caixa`, `registrar_movimentacao_caixa`).
- Trocar Usuário e Sair.

## O que ainda é placeholder
PDV, Gerencial, Notas Fiscais e Financeiro mostram um aviso "em
construção" ao clicar — os botões já existem e já respeitam permissão,
só falta o conteúdo de cada um (próximas fases).

## Como testar
Com o `venv` já criado (Fase 1) e ativado:
```powershell
.\venv\Scripts\activate
python app.py
```
Faça login e confira: os cards batem com os números que você já viu no
sistema desktop? O gráfico mostra as barras certas? Teste abrir/fechar o
caixa e uma sangria/suprimento também.

## Próximo passo (Fase 3)
O módulo PDV — é o mais interativo (busca de produto, carrinho, formas de
pagamento) e vai reaproveitar o `TabelaDados` que criamos aqui pro
carrinho de compras.
