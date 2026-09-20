# Fase 4b — Gerencial: Clientes e Fornecedores

## Arquivo novo
- `gerencial_pessoas.py` — 4 telas novas, todas dentro do Módulo Gerencial:
  - **Cadastrar Cliente**: nome, telefone, CPF, limite de crédito, e
    endereço completo com busca automática de CEP (via ViaCEP, roda numa
    thread separada pra não travar a tela).
  - **Gerenciar Clientes**: busca (nome/telefone/CPF) + tabela + edição.
  - **Cadastrar Fornecedor**: nome/razão social, CNPJ, telefone, endereço
    com CEP.
  - **Gerenciar Fornecedores**: busca (nome/CNPJ) + tabela + edição.

## Arquivo alterado
- `gerencial_produtos.py` — o `GerencialScreen` agora tem 6 abas ao todo:
  Cadastrar Produto, Gerenciar Produtos, Cadastrar Cliente, Gerenciar
  Clientes, Cadastrar Fornecedor, Gerenciar Fornecedores.

## O que já funciona igual ao original
- Validação de CPF (11 dígitos) e CNPJ (14 dígitos) — avisa se parecer
  errado, mas permite salvar mesmo assim.
- Busca de CEP preenchendo logradouro/bairro/cidade automaticamente.
- Edição completa de cliente (inclusive limite de crédito) e fornecedor.
- Auditoria registrada em cada cadastro/edição, igual ao original.

## Ainda não incluído
Usuários, Relatórios de Venda, Auditoria (tela de consulta), Dívidas/
Fiados, Devolução/Troca, Histórico de Caixas, Formas de Pagamento
(cadastro) — módulos do Financeiro e Notas Fiscais também de fora ainda.

## Como testar
Duplo-clique no `testar.bat`. No Menu Principal → Módulo Gerencial, agora
tem as abas de Cliente e Fornecedor. Cadastra um cliente com CEP válido
pra testar a busca automática, depois vai em "Gerenciar Clientes",
procura ele e edita alguma coisa.
