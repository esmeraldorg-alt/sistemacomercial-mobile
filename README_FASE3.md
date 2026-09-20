# Fase 3 — PDV (Frente de Caixa)

## Arquivo novo
- `pdv.py` — tela completa do PDV (`PDVScreen`), mais os popups de apoio:
  `BuscaProdutoPopup`, `SelecaoClientePopup`, `ProdutoFracionadoPopup`,
  `DescontoPopup` e `PagamentoPopup`.

## Arquivos alterados
- `components.py` — as tabelas (`TabelaDados`/`LinhaTabela`) ganharam
  suporte a **seleção por toque** (pra listas de produto/cliente e
  remoção de itens do carrinho).
- `app.py` — a tela `pdv` foi registrada no `ScreenManager`.
- `dashboard_menu.py` — o botão "Frente de Caixa (PDV)" do menu agora
  abre o PDV de verdade (antes mostrava "em construção").

## O que já funciona igual ao original
- Adicionar produto por código de barras, ID ou nome (busca parcial).
- Sintaxe `qtd*código` e também `qtd*` sozinho pra travar a quantidade
  antes de bipar vários itens iguais em sequência.
- Produto fracionado (KG, G, L, ML...) com peso ↔ valor sincronizados.
- Checagem de estoque antes de adicionar ao carrinho.
- Preço promocional (`obter_promocao_vigente`), com indicação visual.
- Carrinho com toque pra remover item (com confirmação).
- Desconto em R$ ou % (sincronizados), com atalhos de 5/10/15/20%.
- Seleção de cliente (busca por nome).
- Botões de pagamento rápido (as formas cadastradas no Gerencial).
- Tela de pagamento completa: DINHEIRO, PIX, DEBITO, CREDITO, A PRAZO
  (com checagem de limite de crédito), SALDO CREDITO (com checagem de
  saldo), VALE CREDITO (com checagem de código/saldo) e MÚLTIPLO
  (vários lançamentos na mesma venda, com troco calculado automaticamente).
- Gravação da venda: mesma lógica do `concluir_gravacao_venda` original
  (venda, pagamentos, fiado, baixa de estoque, auditoria, tudo na mesma
  transação).
- Cancelar venda, checagem de caixa aberto antes de vender.

## O que ainda não entrou (fica pra depois, como combinamos)
- Salvar/recuperar **Orçamentos**.
- **Histórico de vendas** e reimpressão de comprovante.
- Configuração de impressora (não se aplica da mesma forma no Android —
  quando chegarmos lá, a impressão vai ser via impressora térmica
  Bluetooth, não impressora do Windows).
- Atalhos de teclado F2/F4/F5/F6/F7/F9 (fazem sentido num PDV com
  teclado; no touch do Android, os botões na tela cobrem a mesma função).

## Como testar
Com o `database.py` e o `venv` já prontos, dá duplo-clique no
`testar.bat` (ou `python app.py`). No Menu Principal, clique em
"Frente de Caixa (PDV)" — com o caixa aberto, já dá pra simular uma
venda completa.

## Próximo passo (Fase 4)
Módulo Gerencial (cadastros de produto, cliente, etc.) — vai reaproveitar
o `BuscaProdutoPopup`/`SelecaoClientePopup` e o padrão de tabela que já
temos.
