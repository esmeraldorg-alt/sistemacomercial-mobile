import sqlite3
import hashlib
import secrets
import json
from datetime import datetime, timedelta

from utils import DB_PATH, logger, fazer_backup_diario, formatar_moeda

NOME_BANCO = str(DB_PATH)


# ==========================================
# CONEXAO
# ==========================================
def criar_conexao():
    conn = sqlite3.connect(NOME_BANCO, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# ==========================================
# SENHAS
# ==========================================
def gerar_hash_senha(senha_texto_puro, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", senha_texto_puro.encode("utf-8"),
        salt.encode("utf-8"), 200_000,
    )
    return f"{salt}${hash_bytes.hex()}"


def verificar_senha(senha_texto_puro, hash_armazenado):
    if not hash_armazenado or "$" not in hash_armazenado:
        return senha_texto_puro == hash_armazenado
    salt, _ = hash_armazenado.split("$", 1)
    return gerar_hash_senha(senha_texto_puro, salt) == hash_armazenado


# ==========================================
# AUDITORIA
# ==========================================
def registrar_auditoria(usuario, acao, detalhes=""):
    conn = None
    try:
        conn = criar_conexao()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO auditoria (usuario, acao, detalhes, data) VALUES (?, ?, ?, ?)",
            (usuario or "desconhecido", acao, detalhes,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    except Exception as e:
        logger.exception(f"Erro ao registrar auditoria ({acao}): {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def obter_auditoria(limite=200, filtro_usuario=None, filtro_acao=None, dias=None):
    """Consulta o log de auditoria, do mais recente pro mais antigo.
    Filtros opcionais: usuario (LIKE), acao (LIKE) e janela de dias."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        query = "SELECT id, usuario, acao, detalhes, data FROM auditoria WHERE 1=1"
        params = []
        if filtro_usuario:
            query += " AND usuario LIKE ?"
            params.append(f"%{filtro_usuario}%")
        if filtro_acao:
            query += " AND acao LIKE ?"
            params.append(f"%{filtro_acao}%")
        if dias:
            query += " AND data >= datetime('now', 'localtime', ?)"
            params.append(f"-{int(dias)} days")
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limite))
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


# ==========================================
# CAIXA
# ==========================================
def obter_caixa_aberto():
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, valor_abertura, data_abertura, usuario_abertura "
            "FROM caixa WHERE status = 'ABERTO' ORDER BY id DESC LIMIT 1")
        return cursor.fetchone()
    finally:
        conn.close()


def abrir_caixa(usuario_nome, valor_abertura):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO caixa
                   (status, valor_abertura, valor_fechamento,
                    usuario_abertura, data_abertura)
               VALUES ('ABERTO', ?, NULL, ?, ?)""",
            (valor_abertura, usuario_nome,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        caixa_id = cursor.lastrowid
        registrar_auditoria(usuario_nome, "ABERTURA_CAIXA",
                            f"Caixa #{caixa_id} - {formatar_moeda(valor_abertura)}")
        return caixa_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _totais_vendas_por_forma(cursor, caixa_id):
    """
    Retorna dict {forma: {'qtd': N, 'soma': X}} agregando as vendas do caixa.
    Usa a tabela `vendas_pagamentos` quando há registros; caso contrário cai
    no fallback pela coluna `vendas.forma_pagamento` (dados antigos).
    """
    # 1) Tenta pela tabela nova
    cursor.execute("""
        SELECT vp.forma AS forma,
               COUNT(DISTINCT v.id) AS qtd,
               COALESCE(SUM(vp.valor), 0) AS soma
        FROM vendas_pagamentos vp
        JOIN vendas v ON v.id = vp.venda_id
        LEFT JOIN vendas_historico h ON h.venda_id = v.id
        WHERE v.caixa_id = ?
          AND (h.status IS NULL OR h.status != 'CANCELADA')
        GROUP BY vp.forma
    """, (caixa_id,))
    linhas = cursor.fetchall()
    if linhas:
        return {r["forma"]: {"qtd": r["qtd"], "soma": r["soma"]} for r in linhas}

    # 2) Fallback (bases antigas / vendas sem detalhamento por forma)
    cursor.execute("""
        SELECT v.forma_pagamento AS forma,
               COUNT(*) AS qtd,
               COALESCE(SUM(v.total), 0) AS soma
        FROM vendas v
        LEFT JOIN vendas_historico h ON h.venda_id = v.id
        WHERE v.caixa_id = ?
          AND (h.status IS NULL OR h.status != 'CANCELADA')
        GROUP BY v.forma_pagamento
    """, (caixa_id,))
    return {
        r["forma"]: {"qtd": r["qtd"], "soma": r["soma"]}
        for r in cursor.fetchall()
    }


def calcular_totais_caixa(caixa_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT valor_abertura, data_abertura FROM caixa WHERE id = ?",
            (caixa_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Caixa nao encontrado.")
        valor_abertura = row["valor_abertura"] or 0.0
        data_abertura = row["data_abertura"] or ""

        vendas_por_forma = _totais_vendas_por_forma(cursor, caixa_id)

        cursor.execute("""
            SELECT tipo, COALESCE(SUM(valor), 0) AS total
            FROM movimentacoes_caixa WHERE caixa_id = ? GROUP BY tipo
        """, (caixa_id,))
        mov = {r["tipo"]: r["total"] for r in cursor.fetchall()}
        sangrias = mov.get("SANGRIA", 0.0)
        suprimentos = mov.get("SUPRIMENTO", 0.0)

        dinheiro = vendas_por_forma.get("DINHEIRO", {}).get("soma", 0.0)

        # Esperado POR FORMA — DINHEIRO/PIX/DEBITO/CREDITO apenas.
        # FIADO e MULTIPLO NÃO entram no esperado de caixa:
        #   - FIADO é conta a receber (não tem dinheiro no caixa)
        #   - MULTIPLO já é detalhado em vendas_pagamentos por forma real
        esperado_por_forma = {
            "DINHEIRO": valor_abertura + dinheiro + suprimentos - sangrias,
            "PIX":      vendas_por_forma.get("PIX", {}).get("soma", 0.0),
            "DEBITO":   vendas_por_forma.get("DEBITO", {}).get("soma", 0.0),
            "CREDITO":  vendas_por_forma.get("CREDITO", {}).get("soma", 0.0),
        }

        valor_esperado = (valor_abertura + dinheiro + suprimentos - sangrias)

        return {
            "valor_abertura": valor_abertura,
            "data_abertura": data_abertura,
            "vendas_por_forma": vendas_por_forma,
            "sangrias": sangrias,
            "suprimentos": suprimentos,
            "valor_esperado": valor_esperado,
            "esperado_por_forma": esperado_por_forma,
        }
    finally:
        conn.close()


def fechar_caixa(caixa_id, valores_por_forma, usuario_nome):
    """
    valores_por_forma: dict {"DINHEIRO": 100.0, "PIX": 50.0, ...}
    """
    conn = criar_conexao()
    try:
        totais = calcular_totais_caixa(caixa_id)
        esperado = totais["esperado_por_forma"]

        valor_fechamento = sum(valores_por_forma.values())
        valor_esperado = sum(esperado.values())
        diferenca = valor_fechamento - valor_esperado

        # Detalhamento textual das diferenças por forma (vai pra auditoria)
        detalhes_formas = []
        for forma, val_inf in valores_por_forma.items():
            val_esp = esperado.get(forma, 0.0)
            d = val_inf - val_esp
            detalhes_formas.append(
                f"{forma}: esp {formatar_moeda(val_esp)} | inf {formatar_moeda(val_inf)} | dif {formatar_moeda(d)}"
            )

        cursor = conn.cursor()
        cursor.execute("""
            UPDATE caixa
               SET status = 'FECHADO', valor_fechamento = ?,
                   valor_esperado = ?, diferenca = ?,
                   data_fechamento = ?, usuario_fechamento = ?
             WHERE id = ?
        """, (valor_fechamento, valor_esperado, diferenca,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              usuario_nome, caixa_id))
        conn.commit()

        registrar_auditoria(
            usuario_nome, "FECHAMENTO_CAIXA",
            f"Caixa #{caixa_id} | Esperado: {formatar_moeda(valor_esperado)} | "
            f"Informado: {formatar_moeda(valor_fechamento)} | Dif: {formatar_moeda(diferenca)}\n"
            + "\n".join(detalhes_formas)
        )
        return {
            "valor_esperado": valor_esperado,
            "valor_fechamento": valor_fechamento,
            "diferenca": diferenca,
            "totais": totais,
            "esperado_por_forma": esperado,
            "informado_por_forma": valores_por_forma,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def registrar_movimentacao_caixa(caixa_id, tipo, valor, motivo, usuario_nome):
    if tipo not in ("SANGRIA", "SUPRIMENTO"):
        raise ValueError("Tipo invalido.")
    if valor <= 0:
        raise ValueError("Valor deve ser maior que zero.")
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO movimentacoes_caixa
                (caixa_id, tipo, valor, motivo, usuario, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (caixa_id, tipo, valor, motivo or "", usuario_nome,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        registrar_auditoria(usuario_nome, f"{tipo}_CAIXA",
                            f"Caixa #{caixa_id} | {formatar_moeda(valor)} | {motivo}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==========================================
# PERMISSOES
# ==========================================
def obter_permissoes_usuario(usuario_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tela FROM permissoes_usuario WHERE usuario_id = ?",
            (usuario_id,))
        return [r["tela"] for r in cursor.fetchall()]
    finally:
        conn.close()


# ==========================================
# FORMAS DE PAGAMENTO
# ==========================================
def obter_formas_pagamento(apenas_ativas=False):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        if apenas_ativas:
            cursor.execute(
                "SELECT * FROM formas_pagamento WHERE ativo = 1 ORDER BY ordem, nome")
        else:
            cursor.execute("SELECT * FROM formas_pagamento ORDER BY ordem, nome")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def criar_forma_pagamento(nome, atalho=None, ativo=1):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(ordem), -1) + 1 AS prox FROM formas_pagamento")
        prox_ordem = cursor.fetchone()["prox"]
        cursor.execute(
            "INSERT INTO formas_pagamento (nome, atalho, ativo, ordem) "
            "VALUES (?, ?, ?, ?)",
            (nome.strip().upper(), (atalho or "").strip().upper() or None,
             1 if ativo else 0, prox_ordem))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def atualizar_forma_pagamento(forma_id, nome, atalho=None, ativo=1):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE formas_pagamento SET nome = ?, atalho = ?, ativo = ? WHERE id = ?",
            (nome.strip().upper(), (atalho or "").strip().upper() or None,
             1 if ativo else 0, forma_id))
        conn.commit()
    finally:
        conn.close()


def excluir_forma_pagamento(forma_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM formas_pagamento WHERE id = ?", (forma_id,))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# MOVIMENTACAO DE ESTOQUE
# ==========================================
def registrar_movimentacao_estoque(produto_id, tipo, quantidade, origem,
                                   usuario, detalhes=""):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO movimentacoes_estoque
                (produto_id, tipo, quantidade, origem, usuario, detalhes, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (produto_id, tipo, quantidade, origem, usuario, detalhes,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    except Exception as e:
        logger.exception(f"Erro ao registrar movimentacao: {e}")
    finally:
        conn.close()


# ==========================================
# TENTATIVAS DE LOGIN
# ==========================================
def registrar_tentativa_login(nome_usuario, sucesso):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tentativas_login (usuario, sucesso, data)
            VALUES (?, ?, ?)
        """, (nome_usuario, 1 if sucesso else 0,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    except Exception as e:
        logger.exception(f"Erro ao registrar tentativa: {e}")
    finally:
        conn.close()


def contar_tentativas_falhas_recentes(nome_usuario, minutos=5):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS total FROM tentativas_login
            WHERE usuario = ? AND sucesso = 0
              AND data >= datetime('now', 'localtime', ?)
        """, (nome_usuario, f"-{int(minutos)} minutes"))
        return cursor.fetchone()["total"]
    finally:
        conn.close()


# ==========================================
# INDICADORES DO DASHBOARD
# ==========================================
def obter_resumo_dia():
    conn = criar_conexao()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) AS qtd, COALESCE(SUM(v.total), 0) AS total
            FROM vendas v
            LEFT JOIN vendas_historico h ON h.venda_id = v.id
            WHERE date(v.data) = date('now', 'localtime')
              AND (h.status IS NULL OR h.status != 'CANCELADA')
        """)
        row = cursor.fetchone()
        qtd = row["qtd"] or 0
        total = row["total"] or 0.0
        ticket_medio = (total / qtd) if qtd else 0.0

        cursor.execute("""
            SELECT COUNT(*) AS qtd FROM produtos
            WHERE ativo = 1 AND (estoque <= estoque_minimo OR estoque <= 5)
        """)
        estoque_baixo = cursor.fetchone()["qtd"] or 0

        cursor.execute("""
            SELECT COUNT(*) AS qtd, COALESCE(SUM(valor), 0) AS total
            FROM fiados WHERE status = 'ABERTO'
        """)
        row = cursor.fetchone()
        fiados_qtd = row["qtd"] or 0
        fiados_total = row["total"] or 0.0

        cursor.execute("""
            SELECT COUNT(*) AS qtd, COALESCE(SUM(valor), 0) AS total
            FROM fiados
            WHERE status = 'ABERTO'
              AND vencimento IS NOT NULL
              AND date(vencimento) < date('now', 'localtime')
        """)
        row = cursor.fetchone()
        vencidos_qtd = row["qtd"] or 0
        vencidos_total = row["total"] or 0.0

        caixa = obter_caixa_aberto()
        caixa_id = caixa["id"] if caixa else None
        caixa_esperado = 0.0
        if caixa_id:
            try:
                caixa_esperado = calcular_totais_caixa(caixa_id)["valor_esperado"]
            except Exception:
                pass

        return {
            "vendas_qtd": qtd, "vendas_total": total,
            "ticket_medio": ticket_medio, "estoque_baixo": estoque_baixo,
            "fiados_qtd": fiados_qtd, "fiados_total": fiados_total,
            "vencidos_qtd": vencidos_qtd, "vencidos_total": vencidos_total,
            "caixa_id": caixa_id, "caixa_esperado": caixa_esperado,
        }
    finally:
        conn.close()


def obter_vendas_ultimos_dias(dias=7):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date(v.data) AS dia,
                   COALESCE(SUM(v.total), 0) AS total
            FROM vendas v
            LEFT JOIN vendas_historico h ON h.venda_id = v.id
            WHERE date(v.data) >= date('now', 'localtime', ?)
              AND (h.status IS NULL OR h.status != 'CANCELADA')
            GROUP BY date(v.data)
            ORDER BY dia ASC
        """, (f"-{int(dias - 1)} days",))
        resultados = {r["dia"]: r["total"] for r in cursor.fetchall()}
        hoje = datetime.now().date()
        saida = []
        for i in range(dias - 1, -1, -1):
            dia = (hoje - timedelta(days=i)).strftime("%Y-%m-%d")
            saida.append((dia, resultados.get(dia, 0.0)))
        return saida
    finally:
        conn.close()


def obter_ultimas_vendas(limite=5):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT v.id, v.data, v.forma_pagamento, v.total, h.status
            FROM vendas v
            LEFT JOIN vendas_historico h ON v.id = h.venda_id
            ORDER BY v.id DESC LIMIT ?
        """, (limite,))
        return cursor.fetchall()
    finally:
        conn.close()


def obter_produtos_estoque_baixo(limite=8):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT codigo_barras, nome, estoque, estoque_minimo
            FROM produtos
            WHERE ativo = 1 AND (estoque <= estoque_minimo OR estoque <= 5)
            ORDER BY estoque ASC LIMIT ?
        """, (limite,))
        return cursor.fetchall()
    finally:
        conn.close()


# ==========================================
# PROMOÇÕES (preço promocional por período)
# ==========================================
def criar_promocao(produto_id, preco_promocional, data_inicio, data_fim, usuario):
    """data_inicio/data_fim no formato 'YYYY-MM-DD'."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        # Qualquer promoção ativa anterior do mesmo produto é encerrada,
        # para não haver duas promoções vigentes ao mesmo tempo.
        cursor.execute(
            "UPDATE promocoes SET ativo = 0 WHERE produto_id = ? AND ativo = 1",
            (produto_id,))
        cursor.execute(
            "INSERT INTO promocoes "
            "(produto_id, preco_promocional, data_inicio, data_fim, ativo, usuario) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (produto_id, preco_promocional, data_inicio, data_fim, usuario))
        promocao_id = cursor.lastrowid
        conn.commit()
        return promocao_id
    finally:
        conn.close()


def obter_promocao_vigente(produto_id):
    """Retorna a promoção ativa e dentro do período de validade para o
    produto, ou None se não houver nenhuma vigente hoje."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM promocoes "
            "WHERE produto_id = ? AND ativo = 1 "
            "AND date('now', 'localtime') BETWEEN date(data_inicio) AND date(data_fim) "
            "ORDER BY id DESC LIMIT 1",
            (produto_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def obter_promocoes(produto_id=None, apenas_ativas=False):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        condicoes = []
        params = []
        if produto_id is not None:
            condicoes.append("p.produto_id = ?")
            params.append(produto_id)
        if apenas_ativas:
            condicoes.append("p.ativo = 1")
        where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
        cursor.execute(f"""
            SELECT p.*, pr.nome AS produto_nome, pr.codigo_barras,
                   pr.preco_venda AS preco_normal,
                   CASE WHEN p.ativo = 1 AND date('now', 'localtime')
                        BETWEEN date(p.data_inicio) AND date(p.data_fim)
                        THEN 1 ELSE 0 END AS vigente
            FROM promocoes p
            JOIN produtos pr ON pr.id = p.produto_id
            {where}
            ORDER BY p.id DESC
        """, params)
        return cursor.fetchall()
    finally:
        conn.close()


def cancelar_promocao(promocao_id, usuario):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE promocoes SET ativo = 0 WHERE id = ?",
                       (promocao_id,))
        conn.commit()
        registrar_auditoria(usuario, "CANCELAR_PROMOCAO",
                            f"Promoção #{promocao_id} cancelada")
    finally:
        conn.close()


# ==========================================
# VALIDADE DE PRODUTOS
# ==========================================
def obter_produtos_proximos_validade(dias=7, limite=15):
    """Produtos com validade cadastrada, vencidos ou vencendo dentro de
    `dias` dias, ordenados do mais urgente pro menos urgente."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT codigo_barras, nome, estoque, validade,
                   CAST(julianday(validade) - julianday('now', 'localtime') AS INTEGER)
                       AS dias_restantes
            FROM produtos
            WHERE ativo = 1 AND validade IS NOT NULL AND validade != ''
              AND date(validade) <= date('now', 'localtime', ?)
            ORDER BY validade ASC
            LIMIT ?
        """, (f"+{int(dias)} days", limite))
        return cursor.fetchall()
    finally:
        conn.close()


def obter_produtos_mais_vendidos(dias=30, limite=5):
    import json as _json
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT h.carrinho_json
            FROM vendas v
            JOIN vendas_historico h ON h.venda_id = v.id
            WHERE date(v.data) >= date('now', 'localtime', ?)
              AND (h.status IS NULL OR h.status != 'CANCELADA')
        """, (f"-{int(dias)} days",))
        acumulado = {}
        for row in cursor.fetchall():
            if not row["carrinho_json"]:
                continue
            try:
                dados = _json.loads(row["carrinho_json"])
            except Exception:
                continue
            itens = dados.get("itens", []) if isinstance(dados, dict) else dados
            for it in itens:
                pid = it.get("id")
                nome = it.get("nome") or f"Produto #{pid}"
                qtd = it.get("quantidade", 0) or 0
                if pid is None:
                    continue
                if pid not in acumulado:
                    acumulado[pid] = {"nome": nome, "quantidade": 0.0, "total": 0.0}
                acumulado[pid]["quantidade"] += qtd
                acumulado[pid]["total"] += qtd * (it.get("preco", 0) or 0)
        ordenado = sorted(acumulado.values(),
                          key=lambda x: x["quantidade"], reverse=True)
        return ordenado[:limite]
    finally:
        conn.close()


def obter_clientes_top_compradores(dias=30, limite=5):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.id, c.nome,
                   COUNT(v.id) AS qtd_compras,
                   COALESCE(SUM(v.total), 0) AS total
            FROM vendas v
            JOIN clientes c ON c.id = v.cliente_id
            LEFT JOIN vendas_historico h ON h.venda_id = v.id
            WHERE v.cliente_id IS NOT NULL
              AND date(v.data) >= date('now', 'localtime', ?)
              AND (h.status IS NULL OR h.status != 'CANCELADA')
            GROUP BY c.id, c.nome
            ORDER BY total DESC LIMIT ?
        """, (f"-{int(dias)} days", limite))
        return cursor.fetchall()
    finally:
        conn.close()


# ==========================================
# ORÇAMENTOS (cotação para o cliente — não afeta estoque nem caixa)
# ==========================================
def salvar_orcamento(cliente_id, cliente_nome, subtotal, desconto, total,
                     itens, usuario, validade_dias=7):
    """Grava um orçamento (carrinho + valores) sem tocar em estoque/caixa.
    `itens` é a lista de dicts do carrinho do PDV (mesmo formato de venda)."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO orcamentos "
            "(cliente_id, cliente_nome, subtotal, desconto, total, "
            "carrinho_json, usuario, status, validade_dias) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'ABERTO', ?)",
            (cliente_id, cliente_nome, subtotal, desconto, total,
             json.dumps(itens), usuario, validade_dias))
        orcamento_id = cursor.lastrowid
        conn.commit()
        return orcamento_id
    finally:
        conn.close()


def obter_orcamentos(status=None, limite=200):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM orcamentos WHERE status = ? "
                "ORDER BY id DESC LIMIT ?", (status, limite))
        else:
            cursor.execute(
                "SELECT * FROM orcamentos ORDER BY id DESC LIMIT ?", (limite,))
        return cursor.fetchall()
    finally:
        conn.close()


def obter_orcamento(orcamento_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orcamentos WHERE id = ?", (orcamento_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def atualizar_status_orcamento(orcamento_id, status, venda_id=None):
    """status: 'ABERTO', 'CONVERTIDO' ou 'CANCELADO'."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orcamentos SET status = ?, venda_id = ? WHERE id = ?",
            (status, venda_id, orcamento_id))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# FIADOS — SALDO DO CLIENTE
# ==========================================
def obter_total_fiados_abertos_cliente(cliente_id):
    """Retorna o total de fiados em aberto do cliente, para validação de limite."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0) AS total
            FROM fiados
            WHERE cliente_id = ? AND status = 'ABERTO'
        """, (cliente_id,))
        return cursor.fetchone()["total"] or 0.0
    finally:
        conn.close()


# ==========================================
# CRÉDITO DO CLIENTE (gerado em devoluções/trocas)
# ==========================================
def obter_credito_cliente(cliente_id):
    """Retorna o saldo de crédito de loja disponível do cliente."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT credito_saldo FROM clientes WHERE id = ?",
                       (cliente_id,))
        row = cursor.fetchone()
        return (row["credito_saldo"] or 0.0) if row else 0.0
    finally:
        conn.close()


def adicionar_credito_cliente(cliente_id, valor, origem, usuario_nome, conn=None):
    """Credita saldo de loja ao cliente (ex.: devolução sem produto de troca,
    ou troca por item mais barato). Se `conn` for informado, participa da
    transação já aberta pelo chamador (não faz commit/close)."""
    if valor <= 0:
        return
    conn_local = conn or criar_conexao()
    try:
        cursor = conn_local.cursor()
        cursor.execute(
            "UPDATE clientes SET credito_saldo = COALESCE(credito_saldo, 0) + ? "
            "WHERE id = ?", (valor, cliente_id))
        cursor.execute(
            "INSERT INTO movimentacoes_credito "
            "(cliente_id, tipo, valor, origem, usuario) VALUES (?, 'GERADO', ?, ?, ?)",
            (cliente_id, valor, origem, usuario_nome))
        if conn is None:
            conn_local.commit()
    except Exception:
        if conn is None:
            conn_local.rollback()
        raise
    finally:
        if conn is None:
            conn_local.close()


def usar_credito_cliente(cliente_id, valor, origem, usuario_nome, conn=None):
    """Debita saldo de crédito de loja do cliente (uso como forma de
    pagamento no PDV). Levanta ValueError se o saldo for insuficiente."""
    if valor <= 0:
        return
    conn_local = conn or criar_conexao()
    try:
        cursor = conn_local.cursor()
        cursor.execute("SELECT credito_saldo FROM clientes WHERE id = ?",
                       (cliente_id,))
        row = cursor.fetchone()
        saldo_atual = (row["credito_saldo"] or 0.0) if row else 0.0
        if valor > saldo_atual + 0.01:
            raise ValueError(
                f"Saldo de crédito insuficiente (disponível: {formatar_moeda(saldo_atual)}).")

        cursor.execute(
            "UPDATE clientes SET credito_saldo = COALESCE(credito_saldo, 0) - ? "
            "WHERE id = ?", (valor, cliente_id))
        cursor.execute(
            "INSERT INTO movimentacoes_credito "
            "(cliente_id, tipo, valor, origem, usuario) VALUES (?, 'UTILIZADO', ?, ?, ?)",
            (cliente_id, valor, origem, usuario_nome))
        if conn is None:
            conn_local.commit()
    except Exception:
        if conn is None:
            conn_local.rollback()
        raise
    finally:
        if conn is None:
            conn_local.close()


def obter_extrato_credito_cliente(cliente_id, limite=100):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tipo, valor, origem, usuario, data
            FROM movimentacoes_credito
            WHERE cliente_id = ?
            ORDER BY id DESC LIMIT ?
        """, (cliente_id, limite))
        return cursor.fetchall()
    finally:
        conn.close()


# ==========================================
# VALE DE CRÉDITO (impresso, para cliente avulso/não cadastrado)
# ==========================================
def _gerar_codigo_vale():
    """Código curto, legível e fácil de digitar (sem 0/O/1/I para evitar
    confusão na hora de ler o vale impresso)."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    bloco = lambda n: "".join(secrets.choice(alfabeto) for _ in range(n))
    return f"VALE-{bloco(4)}-{bloco(4)}"


def criar_vale_credito(valor, cliente_id, origem, usuario_nome, conn=None):
    """Cria um vale de crédito com código único, para ser impresso e
    entregue ao cliente (útil quando não há cadastro de cliente para
    guardar o saldo). Retorna {"id", "codigo", "valor"}."""
    if valor <= 0:
        return None
    conn_local = conn or criar_conexao()
    try:
        cursor = conn_local.cursor()
        codigo = _gerar_codigo_vale()
        for _ in range(5):
            cursor.execute("SELECT 1 FROM vales_credito WHERE codigo = ?", (codigo,))
            if not cursor.fetchone():
                break
            codigo = _gerar_codigo_vale()

        cursor.execute(
            "INSERT INTO vales_credito "
            "(codigo, valor_original, valor_disponivel, cliente_id, origem, "
            " usuario_emissao, status) VALUES (?, ?, ?, ?, ?, ?, 'ABERTO')",
            (codigo, valor, valor, cliente_id, origem, usuario_nome))
        vale_id = cursor.lastrowid
        if conn is None:
            conn_local.commit()
            registrar_auditoria(
                usuario_nome, "EMISSAO_VALE_CREDITO",
                f"Vale {codigo} | {formatar_moeda(valor)} | {origem}")
        return {"id": vale_id, "codigo": codigo, "valor": valor}
    except Exception:
        if conn is None:
            conn_local.rollback()
        raise
    finally:
        if conn is None:
            conn_local.close()


def obter_saldo_vale_credito(codigo):
    """Retorna o saldo disponível de um vale, ou 0.0 se inválido/utilizado."""
    vale = obter_vale_credito(codigo)
    if not vale or vale["status"] != "ABERTO":
        return 0.0
    return max(0.0, vale["valor_disponivel"] or 0.0)


def obter_historico_vales_credito(limite=200, apenas_abertos=False,
                                  filtro_codigo=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        query = ("SELECT v.*, c.nome AS cliente_nome FROM vales_credito v "
                "LEFT JOIN clientes c ON c.id = v.cliente_id WHERE 1=1")
        params = []
        if apenas_abertos:
            query += " AND v.status = 'ABERTO'"
        if filtro_codigo:
            query += " AND v.codigo LIKE ?"
            params.append(f"%{filtro_codigo.strip().upper()}%")
        query += " ORDER BY v.id DESC LIMIT ?"
        params.append(int(limite))
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


def obter_vale_credito(codigo):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vales_credito WHERE codigo = ?",
                       ((codigo or "").strip().upper(),))
        return cursor.fetchone()
    finally:
        conn.close()


def usar_vale_credito(codigo, valor, usuario_nome, conn=None):
    """Debita (total ou parcialmente) um vale de crédito pelo código.
    Levanta ValueError se o vale não existir, já estiver utilizado/cancelado,
    ou não tiver saldo suficiente."""
    if valor <= 0:
        return None
    conn_local = conn or criar_conexao()
    try:
        cursor = conn_local.cursor()
        codigo_norm = (codigo or "").strip().upper()
        cursor.execute("SELECT * FROM vales_credito WHERE codigo = ?", (codigo_norm,))
        vale = cursor.fetchone()
        if not vale:
            raise ValueError(f"Vale de crédito '{codigo_norm}' não encontrado.")
        if vale["status"] != "ABERTO":
            raise ValueError(
                f"Vale '{codigo_norm}' já foi utilizado ou está cancelado.")

        disponivel = vale["valor_disponivel"] or 0.0
        if valor > disponivel + 0.01:
            raise ValueError(
                f"Vale '{codigo_norm}' possui apenas {formatar_moeda(disponivel)} disponível.")

        novo_saldo = max(disponivel - valor, 0.0)
        novo_status = "UTILIZADO" if novo_saldo <= 0.01 else "ABERTO"
        cursor.execute(
            "UPDATE vales_credito SET valor_disponivel = ?, status = ?, "
            "data_utilizacao = ? WHERE id = ?",
            (novo_saldo, novo_status,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), vale["id"]))
        if conn is None:
            conn_local.commit()
            registrar_auditoria(
                usuario_nome, "USO_VALE_CREDITO",
                f"Vale {codigo_norm} | Usado: {formatar_moeda(valor)} | "
                f"Saldo restante: {formatar_moeda(novo_saldo)}")
        return {"codigo": codigo_norm, "valor_usado": valor,
                "saldo_restante": novo_saldo}
    except Exception:
        if conn is None:
            conn_local.rollback()
        raise
    finally:
        if conn is None:
            conn_local.close()


# ==========================================
# DEVOLUÇÃO / TROCA DE MERCADORIA
# ==========================================
def registrar_devolucao(itens_devolvidos, venda_id, cliente_id, usuario_nome,
                        itens_novos=None, forma_pagamento_diferenca=None,
                        forma_ressarcimento="DINHEIRO", observacao="",
                        caixa_id=None):
    """
    Registra uma devolução de mercadoria, com troca opcional por outro(s)
    produto(s).

    itens_devolvidos: lista de dicts [{"id", "nome", "quantidade", "preco"}, ...]
        (o que o cliente está devolvendo). O estoque desses produtos é
        incrementado.

    itens_novos: lista opcional no mesmo formato — produtos que o cliente
        está levando em troca. O estoque desses produtos é decrementado
        (com checagem de disponibilidade). Se None/vazio, é uma devolução
        simples (sem troca de produto).

    forma_ressarcimento: usado quando a diferença (itens_novos - devolvidos)
        é <= 0, ou seja, quando o cliente tem valor a receber:
            "DINHEIRO" -> registra uma SANGRIA no caixa informado (se houver)
            "CREDITO"  -> credita o saldo de crédito de loja do cliente
                          (exige cliente_id)
            "VALE"     -> emite um vale-crédito avulso com código impresso,
                          para cliente não cadastrado (não exige cliente_id)

    forma_pagamento_diferenca: usado quando a diferença é > 0 (o cliente
        precisa pagar a mais pela troca) — texto livre (ex.: "DINHEIRO",
        "PIX", "CREDITO_CLIENTE"), apenas para registro/auditoria; o
        lançamento de caixa dessa entrada extra deve ser feito pelo PDV
        normalmente caso já não esteja coberto por uma venda.

    Retorna um dict com {"id", "valor_devolvido", "valor_itens_novos",
    "diferenca", "vale"}. "vale" é {"id", "codigo", "valor"} quando
    forma_ressarcimento == "VALE", senão None.
    """
    if not itens_devolvidos:
        raise ValueError("Informe ao menos um item para devolução.")

    itens_novos = itens_novos or []

    valor_devolvido = sum(
        (it.get("quantidade", 0) or 0) * (it.get("preco", 0) or 0)
        for it in itens_devolvidos)
    valor_itens_novos = sum(
        (it.get("quantidade", 0) or 0) * (it.get("preco", 0) or 0)
        for it in itens_novos)
    diferenca = valor_itens_novos - valor_devolvido

    if diferenca < 0 and forma_ressarcimento == "CREDITO" and not cliente_id:
        raise ValueError("Selecione um cliente para gerar crédito de loja.")
    if diferenca > 0 and forma_pagamento_diferenca == "CREDITO_CLIENTE" and not cliente_id:
        raise ValueError("Selecione um cliente para descontar do saldo de crédito.")

    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        # Estoque: itens devolvidos voltam para o estoque
        for it in itens_devolvidos:
            cursor.execute(
                "UPDATE produtos SET estoque = estoque + ? WHERE id = ?",
                (it["quantidade"], it["id"]))

        # Estoque: itens novos (troca) saem do estoque, com checagem
        for it in itens_novos:
            cursor.execute("SELECT estoque FROM produtos WHERE id = ?",
                           (it["id"],))
            res = cursor.fetchone()
            estoque_atual = res["estoque"] if res else 0
            if estoque_atual < it["quantidade"]:
                raise ValueError(
                    f"Estoque insuficiente para '{it.get('nome', it['id'])}' "
                    f"(disponível: {estoque_atual:.2f}, "
                    f"solicitado: {it['quantidade']:.2f}).")
        for it in itens_novos:
            cursor.execute(
                "UPDATE produtos SET estoque = estoque - ? WHERE id = ?",
                (it["quantidade"], it["id"]))

        tipo = "TROCA" if itens_novos else "DEVOLUCAO"

        cursor.execute(
            """INSERT INTO devolucoes
                   (venda_id, cliente_id, usuario, itens_devolvidos_json,
                    valor_devolvido, tipo, itens_novos_json, valor_itens_novos,
                    diferenca, forma_pagamento_diferenca, forma_ressarcimento,
                    observacao)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (venda_id, cliente_id, usuario_nome,
             json.dumps(itens_devolvidos, ensure_ascii=False), valor_devolvido,
             tipo,
             json.dumps(itens_novos, ensure_ascii=False) if itens_novos else None,
             valor_itens_novos, diferenca,
             forma_pagamento_diferenca if diferenca > 0.001 else None,
             forma_ressarcimento if diferenca < -0.001 else None, observacao))
        devolucao_id = cursor.lastrowid

        # Diferença a favor da loja: cliente paga a mais na troca
        if diferenca > 0.001:
            if forma_pagamento_diferenca == "CREDITO_CLIENTE":
                usar_credito_cliente(
                    cliente_id, diferenca, f"Troca #{devolucao_id}",
                    usuario_nome, conn=conn)
            elif caixa_id:
                cursor.execute(
                    """INSERT INTO movimentacoes_caixa
                           (caixa_id, tipo, valor, motivo, usuario, data)
                       VALUES (?, 'SUPRIMENTO', ?, ?, ?, ?)""",
                    (caixa_id, diferenca,
                     f"Diferença recebida - Troca #{devolucao_id} "
                     f"({forma_pagamento_diferenca or 'N/D'})", usuario_nome,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        # Se sobrou valor a favor do cliente (diferenca < 0), ressarcir
        vale_gerado = None
        if diferenca < -0.001:
            valor_a_ressarcir = abs(diferenca)
            if forma_ressarcimento == "CREDITO":
                adicionar_credito_cliente(
                    cliente_id, valor_a_ressarcir,
                    f"Devolução #{devolucao_id}", usuario_nome, conn=conn)
            elif forma_ressarcimento == "VALE":
                vale_gerado = criar_vale_credito(
                    valor_a_ressarcir, cliente_id,
                    f"Devolução #{devolucao_id}", usuario_nome, conn=conn)
            elif forma_ressarcimento == "DINHEIRO" and caixa_id:
                cursor.execute(
                    """INSERT INTO movimentacoes_caixa
                           (caixa_id, tipo, valor, motivo, usuario, data)
                       VALUES (?, 'SANGRIA', ?, ?, ?, ?)""",
                    (caixa_id, valor_a_ressarcir,
                     f"Ressarcimento Devolução #{devolucao_id}", usuario_nome,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        conn.commit()

        for it in itens_devolvidos:
            registrar_movimentacao_estoque(
                it["id"], "ENTRADA", it["quantidade"], "DEVOLUCAO",
                usuario_nome, f"Devolução #{devolucao_id}")
        for it in itens_novos:
            registrar_movimentacao_estoque(
                it["id"], "SAIDA", it["quantidade"], "TROCA",
                usuario_nome, f"Devolução/Troca #{devolucao_id}")

        detalhe = (
            f"Devolução #{devolucao_id} [{tipo}] - Devolvido: {formatar_moeda(valor_devolvido)}"
        )
        if itens_novos:
            detalhe += (f" | Novo(s): {formatar_moeda(valor_itens_novos)} "
                       f"| Diferença: {formatar_moeda(diferenca)}")
        if vale_gerado:
            detalhe += f" | Vale emitido: {vale_gerado['codigo']}"
        registrar_auditoria(usuario_nome, "DEVOLUCAO", detalhe)

        if vale_gerado:
            registrar_auditoria(
                usuario_nome, "EMISSAO_VALE_CREDITO",
                f"Vale {vale_gerado['codigo']} | {formatar_moeda(vale_gerado['valor'])} "
                f"| Devolução #{devolucao_id}")

        return {
            "id": devolucao_id,
            "valor_devolvido": valor_devolvido,
            "valor_itens_novos": valor_itens_novos,
            "diferenca": diferenca,
            "vale": vale_gerado,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obter_historico_devolucoes(limite=200, filtro_cliente=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        query = """
            SELECT d.id, d.venda_id, d.cliente_id, d.usuario, d.data,
                   d.valor_devolvido, d.tipo, d.valor_itens_novos,
                   d.diferenca, d.forma_ressarcimento, d.observacao,
                   c.nome AS cliente_nome
            FROM devolucoes d
            LEFT JOIN clientes c ON c.id = d.cliente_id
            WHERE 1=1
        """
        params = []
        if filtro_cliente:
            query += " AND c.nome LIKE ?"
            params.append(f"%{filtro_cliente}%")
        query += " ORDER BY d.id DESC LIMIT ?"
        params.append(int(limite))
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


# ==========================================
# GESTAO FINANCEIRA — CENTRO DE CUSTO
# ==========================================
def criar_centro_custo(nome, descricao=""):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO centros_custo (nome, descricao, ativo) VALUES (?, ?, 1)",
            (nome.strip().upper(), (descricao or "").strip()))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def obter_centros_custo(apenas_ativos=False):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        if apenas_ativos:
            cursor.execute(
                "SELECT * FROM centros_custo WHERE ativo = 1 ORDER BY nome")
        else:
            cursor.execute("SELECT * FROM centros_custo ORDER BY nome")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def atualizar_centro_custo(centro_id, nome, descricao="", ativo=1):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE centros_custo SET nome = ?, descricao = ?, ativo = ? WHERE id = ?",
            (nome.strip().upper(), (descricao or "").strip(),
             1 if ativo else 0, centro_id))
        conn.commit()
    finally:
        conn.close()


def excluir_centro_custo(centro_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT (SELECT COUNT(*) FROM contas_pagar WHERE centro_custo_id = ?) + "
            "(SELECT COUNT(*) FROM contas_receber WHERE centro_custo_id = ?) AS qtd",
            (centro_id, centro_id))
        if cursor.fetchone()["qtd"] > 0:
            raise ValueError(
                "Este centro de custo já possui contas vinculadas. "
                "Desative-o em vez de excluir.")
        cursor.execute("DELETE FROM centros_custo WHERE id = ?", (centro_id,))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# GESTAO FINANCEIRA — CATEGORIAS
# ==========================================
def criar_categoria_financeira(nome, tipo):
    tipo = (tipo or "").strip().upper()
    if tipo not in ("PAGAR", "RECEBER"):
        raise ValueError("Tipo de categoria inválido.")
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categorias_financeiras (nome, tipo, ativo) VALUES (?, ?, 1)",
            (nome.strip().upper(), tipo))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def obter_categorias_financeiras(tipo=None, apenas_ativas=False):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM categorias_financeiras WHERE 1=1"
        params = []
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo.strip().upper())
        if apenas_ativas:
            query += " AND ativo = 1"
        query += " ORDER BY nome"
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def atualizar_categoria_financeira(categoria_id, nome, ativo=1):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE categorias_financeiras SET nome = ?, ativo = ? WHERE id = ?",
            (nome.strip().upper(), 1 if ativo else 0, categoria_id))
        conn.commit()
    finally:
        conn.close()


def excluir_categoria_financeira(categoria_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT (SELECT COUNT(*) FROM contas_pagar WHERE categoria_id = ?) + "
            "(SELECT COUNT(*) FROM contas_receber WHERE categoria_id = ?) AS qtd",
            (categoria_id, categoria_id))
        if cursor.fetchone()["qtd"] > 0:
            raise ValueError(
                "Esta categoria já possui contas vinculadas. "
                "Desative-a em vez de excluir.")
        cursor.execute("DELETE FROM categorias_financeiras WHERE id = ?", (categoria_id,))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# GESTAO FINANCEIRA — CONTAS A PAGAR
# ==========================================
def _gerar_grupo_parcelamento():
    return f"PG-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def criar_conta_pagar(descricao, valor, vencimento, fornecedor_id=None,
                      fornecedor_nome=None, categoria_id=None, centro_custo_id=None,
                      numero_documento=None, observacao=None, usuario=None,
                      data_emissao=None, parcelas=1, intervalo_dias=30):
    """Cria uma conta a pagar. Se parcelas > 1, gera N lançamentos ligados
    pelo mesmo grupo_parcelamento, com vencimentos espaçados por
    intervalo_dias e valor total dividido (ajuste de arredondamento na
    última parcela). Retorna a lista de IDs criados."""
    parcelas = max(1, int(parcelas or 1))
    valor = float(valor or 0.0)
    grupo = _gerar_grupo_parcelamento() if parcelas > 1 else None
    data_emissao = data_emissao or datetime.now().strftime("%Y-%m-%d")

    valor_parcela = round(valor / parcelas, 2)
    ids_criados = []

    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        soma_parcelas = 0.0
        for i in range(1, parcelas + 1):
            if i < parcelas:
                v = valor_parcela
            else:
                v = round(valor - soma_parcelas, 2)  # ajusta arredondamento na última
            soma_parcelas += v

            venc = datetime.strptime(vencimento, "%Y-%m-%d") + timedelta(
                days=intervalo_dias * (i - 1))
            cursor.execute("""
                INSERT INTO contas_pagar
                    (descricao, fornecedor_id, fornecedor_nome, categoria_id,
                     centro_custo_id, valor, valor_pago, vencimento, data_emissao,
                     status, numero_documento, observacao, parcela_numero,
                     parcela_total, grupo_parcelamento, usuario_cadastro)
                VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, 'ABERTO', ?, ?, ?, ?, ?, ?)
            """, (descricao.strip(), fornecedor_id, fornecedor_nome, categoria_id,
                  centro_custo_id, v, venc.strftime("%Y-%m-%d"), data_emissao,
                  numero_documento, observacao, i, parcelas, grupo, usuario))
            ids_criados.append(cursor.lastrowid)
        conn.commit()
        return ids_criados
    finally:
        conn.close()


def _query_contas(tabela, status=None, centro_custo_id=None, categoria_id=None,
                  pessoa_id=None, coluna_pessoa_id=None, data_ini=None,
                  data_fim=None, busca=None, limite=500):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        hoje = datetime.now().strftime("%Y-%m-%d")
        query = f"SELECT * FROM {tabela} WHERE 1=1"
        params = []
        if status == "VENCIDO":
            query += " AND status IN ('ABERTO', 'PARCIAL') AND vencimento < ?"
            params.append(hoje)
        elif status:
            query += " AND status = ?"
            params.append(status)
        if centro_custo_id:
            query += " AND centro_custo_id = ?"
            params.append(centro_custo_id)
        if categoria_id:
            query += " AND categoria_id = ?"
            params.append(categoria_id)
        if pessoa_id and coluna_pessoa_id:
            query += f" AND {coluna_pessoa_id} = ?"
            params.append(pessoa_id)
        if data_ini:
            query += " AND vencimento >= ?"
            params.append(data_ini)
        if data_fim:
            query += " AND vencimento <= ?"
            params.append(data_fim)
        if busca:
            query += " AND descricao LIKE ?"
            params.append(f"%{busca}%")
        query += " ORDER BY vencimento ASC, id ASC LIMIT ?"
        params.append(int(limite))
        cursor.execute(query, params)
        resultado = []
        for row in cursor.fetchall():
            item = dict(row)
            if item["status"] in ("ABERTO", "PARCIAL") and item["vencimento"] < hoje:
                item["status_efetivo"] = "VENCIDO"
            else:
                item["status_efetivo"] = item["status"]
            resultado.append(item)
        return resultado
    finally:
        conn.close()


def obter_contas_pagar(status=None, centro_custo_id=None, categoria_id=None,
                       fornecedor_id=None, data_ini=None, data_fim=None,
                       busca=None, limite=500):
    return _query_contas("contas_pagar", status, centro_custo_id, categoria_id,
                         fornecedor_id, "fornecedor_id", data_ini, data_fim,
                         busca, limite)


def obter_conta_pagar(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contas_pagar WHERE id = ?", (conta_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def atualizar_conta_pagar(conta_id, descricao, valor, vencimento, fornecedor_id=None,
                          fornecedor_nome=None, categoria_id=None, centro_custo_id=None,
                          numero_documento=None, observacao=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE contas_pagar SET descricao = ?, valor = ?, vencimento = ?,
                fornecedor_id = ?, fornecedor_nome = ?, categoria_id = ?,
                centro_custo_id = ?, numero_documento = ?, observacao = ?
            WHERE id = ?
        """, (descricao.strip(), float(valor), vencimento, fornecedor_id,
              fornecedor_nome, categoria_id, centro_custo_id, numero_documento,
              observacao, conta_id))
        conn.commit()
    finally:
        conn.close()


def registrar_pagamento_conta_pagar(conta_id, valor, forma_pagamento, usuario,
                                    observacao=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT valor, valor_pago FROM contas_pagar WHERE id = ?",
                      (conta_id,))
        conta = cursor.fetchone()
        if not conta:
            raise ValueError("Conta a pagar não encontrada.")

        valor = float(valor)
        novo_pago = float(conta["valor_pago"]) + valor
        if novo_pago > float(conta["valor"]) + 0.005:
            raise ValueError("Valor do pagamento excede o saldo devedor da conta.")

        novo_status = "PAGO" if novo_pago >= float(conta["valor"]) - 0.005 else "PARCIAL"

        cursor.execute("""
            INSERT INTO contas_pagar_pagamentos
                (conta_id, valor, forma_pagamento, usuario, observacao, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conta_id, valor, forma_pagamento, usuario, observacao,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        cursor.execute(
            "UPDATE contas_pagar SET valor_pago = ?, status = ? WHERE id = ?",
            (novo_pago, novo_status, conta_id))
        conn.commit()
    finally:
        conn.close()


def obter_pagamentos_conta_pagar(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM contas_pagar_pagamentos WHERE conta_id = ? ORDER BY id DESC",
            (conta_id,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def estornar_pagamento_conta_pagar(pagamento_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conta_id, valor FROM contas_pagar_pagamentos WHERE id = ?",
            (pagamento_id,))
        pg = cursor.fetchone()
        if not pg:
            raise ValueError("Pagamento não encontrado.")
        cursor.execute("SELECT valor, valor_pago FROM contas_pagar WHERE id = ?",
                      (pg["conta_id"],))
        conta = cursor.fetchone()
        novo_pago = max(0.0, float(conta["valor_pago"]) - float(pg["valor"]))
        novo_status = "ABERTO" if novo_pago <= 0.005 else "PARCIAL"
        cursor.execute("DELETE FROM contas_pagar_pagamentos WHERE id = ?", (pagamento_id,))
        cursor.execute(
            "UPDATE contas_pagar SET valor_pago = ?, status = ? WHERE id = ?",
            (novo_pago, novo_status, pg["conta_id"]))
        conn.commit()
    finally:
        conn.close()


def cancelar_conta_pagar(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE contas_pagar SET status = 'CANCELADO' WHERE id = ?",
                      (conta_id,))
        conn.commit()
    finally:
        conn.close()


def excluir_conta_pagar(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS qtd FROM contas_pagar_pagamentos WHERE conta_id = ?",
            (conta_id,))
        if cursor.fetchone()["qtd"] > 0:
            raise ValueError(
                "Esta conta já possui pagamentos registrados. Cancele-a em vez de excluir.")
        cursor.execute("DELETE FROM contas_pagar WHERE id = ?", (conta_id,))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# GESTAO FINANCEIRA — CONTAS A RECEBER
# ==========================================
def criar_conta_receber(descricao, valor, vencimento, cliente_id=None,
                        cliente_nome=None, categoria_id=None, centro_custo_id=None,
                        numero_documento=None, observacao=None, usuario=None,
                        data_emissao=None, parcelas=1, intervalo_dias=30):
    """Cria uma conta a receber (recebimento avulso: aluguel, serviço,
    parcelamento externo etc.) — não deve ser usada para vendas do PDV,
    que já têm controle próprio via 'fiados'. Suporta parcelamento como
    criar_conta_pagar()."""
    parcelas = max(1, int(parcelas or 1))
    valor = float(valor or 0.0)
    grupo = _gerar_grupo_parcelamento().replace("PG-", "RC-") if parcelas > 1 else None
    data_emissao = data_emissao or datetime.now().strftime("%Y-%m-%d")

    valor_parcela = round(valor / parcelas, 2)
    ids_criados = []

    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        soma_parcelas = 0.0
        for i in range(1, parcelas + 1):
            if i < parcelas:
                v = valor_parcela
            else:
                v = round(valor - soma_parcelas, 2)
            soma_parcelas += v

            venc = datetime.strptime(vencimento, "%Y-%m-%d") + timedelta(
                days=intervalo_dias * (i - 1))
            cursor.execute("""
                INSERT INTO contas_receber
                    (descricao, cliente_id, cliente_nome, categoria_id,
                     centro_custo_id, valor, valor_recebido, vencimento, data_emissao,
                     status, numero_documento, observacao, parcela_numero,
                     parcela_total, grupo_parcelamento, usuario_cadastro)
                VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, 'ABERTO', ?, ?, ?, ?, ?, ?)
            """, (descricao.strip(), cliente_id, cliente_nome, categoria_id,
                  centro_custo_id, v, venc.strftime("%Y-%m-%d"), data_emissao,
                  numero_documento, observacao, i, parcelas, grupo, usuario))
            ids_criados.append(cursor.lastrowid)
        conn.commit()
        return ids_criados
    finally:
        conn.close()


def obter_contas_receber(status=None, centro_custo_id=None, categoria_id=None,
                         cliente_id=None, data_ini=None, data_fim=None,
                         busca=None, limite=500):
    return _query_contas("contas_receber", status, centro_custo_id, categoria_id,
                         cliente_id, "cliente_id", data_ini, data_fim, busca, limite)


def obter_conta_receber(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contas_receber WHERE id = ?", (conta_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def atualizar_conta_receber(conta_id, descricao, valor, vencimento, cliente_id=None,
                            cliente_nome=None, categoria_id=None, centro_custo_id=None,
                            numero_documento=None, observacao=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE contas_receber SET descricao = ?, valor = ?, vencimento = ?,
                cliente_id = ?, cliente_nome = ?, categoria_id = ?,
                centro_custo_id = ?, numero_documento = ?, observacao = ?
            WHERE id = ?
        """, (descricao.strip(), float(valor), vencimento, cliente_id,
              cliente_nome, categoria_id, centro_custo_id, numero_documento,
              observacao, conta_id))
        conn.commit()
    finally:
        conn.close()


def registrar_recebimento_conta_receber(conta_id, valor, forma_pagamento, usuario,
                                        observacao=None):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT valor, valor_recebido FROM contas_receber WHERE id = ?",
                      (conta_id,))
        conta = cursor.fetchone()
        if not conta:
            raise ValueError("Conta a receber não encontrada.")

        valor = float(valor)
        novo_recebido = float(conta["valor_recebido"]) + valor
        if novo_recebido > float(conta["valor"]) + 0.005:
            raise ValueError("Valor do recebimento excede o saldo da conta.")

        novo_status = "PAGO" if novo_recebido >= float(conta["valor"]) - 0.005 else "PARCIAL"

        cursor.execute("""
            INSERT INTO contas_receber_pagamentos
                (conta_id, valor, forma_pagamento, usuario, observacao, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conta_id, valor, forma_pagamento, usuario, observacao,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        cursor.execute(
            "UPDATE contas_receber SET valor_recebido = ?, status = ? WHERE id = ?",
            (novo_recebido, novo_status, conta_id))
        conn.commit()
    finally:
        conn.close()


def obter_pagamentos_conta_receber(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM contas_receber_pagamentos WHERE conta_id = ? ORDER BY id DESC",
            (conta_id,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def estornar_recebimento_conta_receber(pagamento_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conta_id, valor FROM contas_receber_pagamentos WHERE id = ?",
            (pagamento_id,))
        pg = cursor.fetchone()
        if not pg:
            raise ValueError("Recebimento não encontrado.")
        cursor.execute("SELECT valor, valor_recebido FROM contas_receber WHERE id = ?",
                      (pg["conta_id"],))
        conta = cursor.fetchone()
        novo_recebido = max(0.0, float(conta["valor_recebido"]) - float(pg["valor"]))
        novo_status = "ABERTO" if novo_recebido <= 0.005 else "PARCIAL"
        cursor.execute("DELETE FROM contas_receber_pagamentos WHERE id = ?", (pagamento_id,))
        cursor.execute(
            "UPDATE contas_receber SET valor_recebido = ?, status = ? WHERE id = ?",
            (novo_recebido, novo_status, pg["conta_id"]))
        conn.commit()
    finally:
        conn.close()


def cancelar_conta_receber(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE contas_receber SET status = 'CANCELADO' WHERE id = ?",
                      (conta_id,))
        conn.commit()
    finally:
        conn.close()


def excluir_conta_receber(conta_id):
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS qtd FROM contas_receber_pagamentos WHERE conta_id = ?",
            (conta_id,))
        if cursor.fetchone()["qtd"] > 0:
            raise ValueError(
                "Esta conta já possui recebimentos registrados. Cancele-a em vez de excluir.")
        cursor.execute("DELETE FROM contas_receber WHERE id = ?", (conta_id,))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# GESTAO FINANCEIRA — RELATÓRIOS
# ==========================================
def obter_contas_vencendo(dias=7):
    """Retorna contas a pagar e a receber (abertas/parciais) vencendo entre
    hoje e daqui a `dias` dias, mais as já vencidas — útil para alertas."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    limite_data = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, descricao, valor - valor_pago AS saldo, vencimento,
                   fornecedor_nome AS pessoa, 'PAGAR' AS tipo
            FROM contas_pagar
            WHERE status IN ('ABERTO', 'PARCIAL') AND vencimento <= ?
            ORDER BY vencimento ASC
        """, (limite_data,))
        pagar = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT id, descricao, valor - valor_recebido AS saldo, vencimento,
                   cliente_nome AS pessoa, 'RECEBER' AS tipo
            FROM contas_receber
            WHERE status IN ('ABERTO', 'PARCIAL') AND vencimento <= ?
            ORDER BY vencimento ASC
        """, (limite_data,))
        receber = [dict(r) for r in cursor.fetchall()]

        for item in pagar + receber:
            item["vencida"] = item["vencimento"] < hoje
        return pagar + receber
    finally:
        conn.close()


def obter_fluxo_caixa_previsto(data_ini, data_fim, centro_custo_id=None):
    """Agrupa por data de vencimento o total a pagar e a receber (contas
    ainda em aberto/parcial) no período — projeção de fluxo de caixa."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        query_pagar = """
            SELECT vencimento, SUM(valor - valor_pago) AS total
            FROM contas_pagar
            WHERE status IN ('ABERTO', 'PARCIAL')
              AND vencimento BETWEEN ? AND ?
        """
        params_pagar = [data_ini, data_fim]
        if centro_custo_id:
            query_pagar += " AND centro_custo_id = ?"
            params_pagar.append(centro_custo_id)
        query_pagar += " GROUP BY vencimento ORDER BY vencimento"
        cursor.execute(query_pagar, params_pagar)
        pagar_por_dia = {r["vencimento"]: r["total"] for r in cursor.fetchall()}

        query_receber = """
            SELECT vencimento, SUM(valor - valor_recebido) AS total
            FROM contas_receber
            WHERE status IN ('ABERTO', 'PARCIAL')
              AND vencimento BETWEEN ? AND ?
        """
        params_receber = [data_ini, data_fim]
        if centro_custo_id:
            query_receber += " AND centro_custo_id = ?"
            params_receber.append(centro_custo_id)
        query_receber += " GROUP BY vencimento ORDER BY vencimento"
        cursor.execute(query_receber, params_receber)
        receber_por_dia = {r["vencimento"]: r["total"] for r in cursor.fetchall()}

        datas = sorted(set(pagar_por_dia) | set(receber_por_dia))
        resultado = []
        saldo_acumulado = 0.0
        for d in datas:
            a_pagar = pagar_por_dia.get(d, 0.0)
            a_receber = receber_por_dia.get(d, 0.0)
            saldo_dia = a_receber - a_pagar
            saldo_acumulado += saldo_dia
            resultado.append({
                "data": d, "a_pagar": a_pagar, "a_receber": a_receber,
                "saldo_dia": saldo_dia, "saldo_acumulado": saldo_acumulado,
            })
        return resultado
    finally:
        conn.close()


def obter_dre_por_centro_custo(data_ini, data_fim):
    """DRE simplificado: para cada centro de custo, soma os valores
    efetivamente pagos/recebidos (pela data do pagamento/recebimento, não
    do vencimento) dentro do período — ou seja, o regime de caixa."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(cc.nome, 'SEM CENTRO DE CUSTO') AS centro,
                   COALESCE(SUM(pg.valor), 0.0) AS total_pago
            FROM contas_pagar_pagamentos pg
            JOIN contas_pagar cp ON cp.id = pg.conta_id
            LEFT JOIN centros_custo cc ON cc.id = cp.centro_custo_id
            WHERE date(pg.data) BETWEEN ? AND ?
            GROUP BY centro
        """, (data_ini, data_fim))
        despesas = {r["centro"]: r["total_pago"] for r in cursor.fetchall()}

        cursor.execute("""
            SELECT COALESCE(cc.nome, 'SEM CENTRO DE CUSTO') AS centro,
                   COALESCE(SUM(pg.valor), 0.0) AS total_recebido
            FROM contas_receber_pagamentos pg
            JOIN contas_receber cr ON cr.id = pg.conta_id
            LEFT JOIN centros_custo cc ON cc.id = cr.centro_custo_id
            WHERE date(pg.data) BETWEEN ? AND ?
            GROUP BY centro
        """, (data_ini, data_fim))
        receitas = {r["centro"]: r["total_recebido"] for r in cursor.fetchall()}

        centros = sorted(set(despesas) | set(receitas))
        resultado = []
        for c in centros:
            r = receitas.get(c, 0.0)
            d = despesas.get(c, 0.0)
            resultado.append({
                "centro": c, "receitas": r, "despesas": d, "resultado": r - d,
            })
        return resultado
    finally:
        conn.close()


def obter_resumo_financeiro_consolidado(data_ini, data_fim):
    """Visão geral: faturamento de vendas do PDV, recebimentos e pagamentos
    diversos (contas a pagar/receber), tudo em regime de caixa no período."""
    conn = criar_conexao()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0.0) AS total
            FROM vendas_historico
            WHERE status = 'CONCLUIDA' AND date(data) BETWEEN ? AND ?
        """, (data_ini, data_fim))
        faturamento_vendas = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0.0) AS total FROM contas_receber_pagamentos
            WHERE date(data) BETWEEN ? AND ?
        """, (data_ini, data_fim))
        recebimentos_diversos = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0.0) AS total FROM contas_pagar_pagamentos
            WHERE date(data) BETWEEN ? AND ?
        """, (data_ini, data_fim))
        pagamentos_realizados = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COALESCE(SUM(valor - valor_pago), 0.0) AS total FROM contas_pagar
            WHERE status IN ('ABERTO', 'PARCIAL')
        """)
        total_a_pagar_em_aberto = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COALESCE(SUM(valor - valor_recebido), 0.0) AS total FROM contas_receber
            WHERE status IN ('ABERTO', 'PARCIAL')
        """)
        total_a_receber_em_aberto = cursor.fetchone()["total"]

        entradas = faturamento_vendas + recebimentos_diversos
        saidas = pagamentos_realizados
        return {
            "faturamento_vendas": faturamento_vendas,
            "recebimentos_diversos": recebimentos_diversos,
            "pagamentos_realizados": pagamentos_realizados,
            "total_a_pagar_em_aberto": total_a_pagar_em_aberto,
            "total_a_receber_em_aberto": total_a_receber_em_aberto,
            "entradas": entradas,
            "saidas": saidas,
            "resultado": entradas - saidas,
        }
    finally:
        conn.close()


# ==========================================
# MIGRACAO LEVE
# ==========================================
def _adicionar_coluna_se_nao_existir(cursor, tabela, coluna, definicao):
    cursor.execute(f"PRAGMA table_info({tabela})")
    cols = [c[1] for c in cursor.fetchall()]
    if coluna not in cols:
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


# ==========================================
# INICIALIZACAO
# ==========================================
def inicializar_banco():
    fazer_backup_diario()
    conn = criar_conexao()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL, telefone TEXT, cpf TEXT, cep TEXT,
        logradouro TEXT, numero TEXT, bairro TEXT, cidade_uf TEXT,
        limite_credito REAL DEFAULT 0.0,
        credito_saldo REAL DEFAULT 0.0
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_barras TEXT UNIQUE, nome TEXT NOT NULL,
        preco_venda REAL, estoque REAL DEFAULT 0.0,
        estoque_minimo REAL DEFAULT 0.0,
        ativo INTEGER DEFAULT 1,
        unidade TEXT DEFAULT 'UN'
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS promocoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        preco_promocional REAL NOT NULL,
        data_inicio TEXT NOT NULL,
        data_fim TEXT NOT NULL,
        ativo INTEGER DEFAULT 1,
        usuario TEXT,
        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(produto_id) REFERENCES produtos(id)
    )""")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_promocoes_produto
        ON promocoes(produto_id, ativo)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fornecedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL, cnpj TEXT, telefone TEXT, cep TEXT,
        logradouro TEXT, numero TEXT, bairro TEXT, cidade_uf TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE, senha TEXT NOT NULL,
        perfil TEXT, ativo INTEGER DEFAULT 1,
        senha_provisoria INTEGER DEFAULT 0
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS permissoes_usuario (
        usuario_id INTEGER, tela TEXT,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS formas_pagamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        atalho TEXT,
        ativo INTEGER DEFAULT 1,
        ordem INTEGER DEFAULT 0
    )""")

    cursor.execute("SELECT COUNT(*) AS qtd FROM formas_pagamento")
    if cursor.fetchone()["qtd"] == 0:
        for i, nome in enumerate(["DINHEIRO", "PIX", "DEBITO", "CREDITO"]):
            cursor.execute(
                "INSERT INTO formas_pagamento (nome, atalho, ativo, ordem) "
                "VALUES (?, NULL, 1, ?)",
                (nome, i))
        conn.commit()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notas_entrada_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_nf TEXT, chave_acesso TEXT UNIQUE, fornecedor TEXT,
        tipo TEXT, data_entrada TEXT, itens_json TEXT, status TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS caixa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT, valor_abertura REAL, valor_fechamento REAL,
        valor_esperado REAL, diferenca REAL,
        usuario_abertura TEXT, usuario_fechamento TEXT,
        data_abertura TEXT, data_fechamento TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimentacoes_caixa (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caixa_id INTEGER, tipo TEXT NOT NULL, valor REAL NOT NULL,
        motivo TEXT, usuario TEXT, data TEXT,
        FOREIGN KEY(caixa_id) REFERENCES caixa(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimentacoes_estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER, tipo TEXT NOT NULL, quantidade REAL NOT NULL,
        origem TEXT, usuario TEXT, detalhes TEXT, data TEXT,
        FOREIGN KEY(produto_id) REFERENCES produtos(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tentativas_login (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT, sucesso INTEGER, data TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, total REAL, forma_pagamento TEXT,
        usuario TEXT, caixa_id INTEGER,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendas_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER, total REAL, desconto REAL,
        forma_pagamento TEXT, carrinho_json TEXT,
        status TEXT DEFAULT 'CONCLUIDA',
        usuario_cancelamento TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # NOVA TABELA — detalha cada forma de pagamento usada numa venda
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendas_pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER NOT NULL,
        forma TEXT NOT NULL,
        valor REAL NOT NULL,
        FOREIGN KEY(venda_id) REFERENCES vendas(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_vendas_pagamentos_venda
        ON vendas_pagamentos(venda_id)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orcamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, cliente_nome TEXT,
        subtotal REAL, desconto REAL, total REAL,
        carrinho_json TEXT, usuario TEXT,
        status TEXT DEFAULT 'ABERTO',
        validade_dias INTEGER DEFAULT 7,
        venda_id INTEGER,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_orcamentos_status
        ON orcamentos(status)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fiados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, valor REAL NOT NULL,
        vencimento TEXT, status TEXT DEFAULT 'ABERTO',
        data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fiados_pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fiado_id INTEGER, valor REAL NOT NULL,
        forma TEXT, usuario TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(fiado_id) REFERENCES fiados(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT, acao TEXT, detalhes TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devolucoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        cliente_id INTEGER,
        usuario TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        itens_devolvidos_json TEXT,
        valor_devolvido REAL DEFAULT 0.0,
        tipo TEXT,
        itens_novos_json TEXT,
        valor_itens_novos REAL DEFAULT 0.0,
        diferenca REAL DEFAULT 0.0,
        forma_pagamento_diferenca TEXT,
        forma_ressarcimento TEXT,
        observacao TEXT,
        vale_codigo TEXT,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vales_credito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        valor_original REAL NOT NULL,
        valor_disponivel REAL NOT NULL,
        cliente_id INTEGER,
        origem TEXT,
        usuario_emissao TEXT,
        data_emissao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'ABERTO',
        data_utilizacao TIMESTAMP,
        observacao TEXT,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movimentacoes_credito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        valor REAL NOT NULL,
        origem TEXT,
        usuario TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")

    # ==========================================
    # GESTAO FINANCEIRA (CONTAS A PAGAR/RECEBER + CENTRO DE CUSTO)
    # ==========================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS centros_custo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        descricao TEXT,
        ativo INTEGER DEFAULT 1
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categorias_financeiras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT NOT NULL,
        ativo INTEGER DEFAULT 1,
        UNIQUE(nome, tipo)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas_pagar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT NOT NULL,
        fornecedor_id INTEGER,
        fornecedor_nome TEXT,
        categoria_id INTEGER,
        centro_custo_id INTEGER,
        valor REAL NOT NULL,
        valor_pago REAL DEFAULT 0.0,
        vencimento TEXT NOT NULL,
        data_emissao TEXT,
        status TEXT DEFAULT 'ABERTO',
        numero_documento TEXT,
        observacao TEXT,
        parcela_numero INTEGER DEFAULT 1,
        parcela_total INTEGER DEFAULT 1,
        grupo_parcelamento TEXT,
        usuario_cadastro TEXT,
        data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(fornecedor_id) REFERENCES fornecedores(id),
        FOREIGN KEY(categoria_id) REFERENCES categorias_financeiras(id),
        FOREIGN KEY(centro_custo_id) REFERENCES centros_custo(id)
    )""")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_contas_pagar_status_venc
        ON contas_pagar(status, vencimento)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas_pagar_pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conta_id INTEGER NOT NULL,
        valor REAL NOT NULL,
        forma_pagamento TEXT,
        usuario TEXT,
        observacao TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conta_id) REFERENCES contas_pagar(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas_receber (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT NOT NULL,
        cliente_id INTEGER,
        cliente_nome TEXT,
        categoria_id INTEGER,
        centro_custo_id INTEGER,
        valor REAL NOT NULL,
        valor_recebido REAL DEFAULT 0.0,
        vencimento TEXT NOT NULL,
        data_emissao TEXT,
        status TEXT DEFAULT 'ABERTO',
        numero_documento TEXT,
        observacao TEXT,
        parcela_numero INTEGER DEFAULT 1,
        parcela_total INTEGER DEFAULT 1,
        grupo_parcelamento TEXT,
        usuario_cadastro TEXT,
        data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id),
        FOREIGN KEY(categoria_id) REFERENCES categorias_financeiras(id),
        FOREIGN KEY(centro_custo_id) REFERENCES centros_custo(id)
    )""")

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_contas_receber_status_venc
        ON contas_receber(status, vencimento)
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS contas_receber_pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conta_id INTEGER NOT NULL,
        valor REAL NOT NULL,
        forma_pagamento TEXT,
        usuario TEXT,
        observacao TEXT,
        data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conta_id) REFERENCES contas_receber(id) ON DELETE CASCADE
    )""")

    conn.commit()

    cursor.execute("SELECT COUNT(*) AS qtd FROM categorias_financeiras")
    if cursor.fetchone()["qtd"] == 0:
        categorias_padrao = [
            ("ALUGUEL", "PAGAR"), ("FORNECEDORES", "PAGAR"),
            ("SALARIOS/FOLHA", "PAGAR"), ("ENERGIA/AGUA/INTERNET", "PAGAR"),
            ("IMPOSTOS/TAXAS", "PAGAR"), ("MANUTENCAO", "PAGAR"),
            ("MARKETING", "PAGAR"), ("OUTROS (PAGAR)", "PAGAR"),
            ("VENDAS", "RECEBER"), ("SERVICOS PRESTADOS", "RECEBER"),
            ("ALUGUEL RECEBIDO", "RECEBER"), ("OUTROS (RECEBER)", "RECEBER"),
        ]
        for nome, tipo in categorias_padrao:
            cursor.execute(
                "INSERT INTO categorias_financeiras (nome, tipo, ativo) VALUES (?, ?, 1)",
                (nome, tipo))
        conn.commit()

    cursor.execute("SELECT COUNT(*) AS qtd FROM centros_custo")
    if cursor.fetchone()["qtd"] == 0:
        for nome in ["ADMINISTRATIVO", "VENDAS/LOJA", "ESTOQUE/COMPRAS"]:
            cursor.execute(
                "INSERT INTO centros_custo (nome, descricao, ativo) VALUES (?, '', 1)",
                (nome,))
        conn.commit()

    migracoes = [
        ("produtos", "estoque_minimo", "REAL DEFAULT 0.0"),
        ("produtos", "ativo", "INTEGER DEFAULT 1"),
        ("produtos", "unidade", "TEXT DEFAULT 'UN'"),
        ("clientes", "cpf", "TEXT"),
        ("usuarios", "ativo", "INTEGER DEFAULT 1"),
        ("usuarios", "senha_provisoria", "INTEGER DEFAULT 0"),
        ("vendas", "usuario", "TEXT"),
        ("vendas", "caixa_id", "INTEGER"),
        ("vendas_historico", "usuario_cancelamento", "TEXT"),
        ("caixa", "usuario_abertura", "TEXT"),
        ("caixa", "usuario_fechamento", "TEXT"),
        ("caixa", "data_abertura", "TEXT"),
        ("caixa", "data_fechamento", "TEXT"),
        ("caixa", "valor_esperado", "REAL"),
        ("caixa", "diferenca", "REAL"),
        ("notas_entrada_historico", "chave_acesso", "TEXT"),
        ("clientes", "credito_saldo", "REAL DEFAULT 0.0"),
        ("devolucoes", "vale_codigo", "TEXT"),
        ("produtos", "validade", "TEXT"),
        ("produtos", "fator_conversao_padrao", "REAL DEFAULT 1.0"),
        ("produtos", "fator_conversao_operacao", "TEXT DEFAULT 'MULTIPLICAR'"),
    ]
    for tabela, coluna, definicao in migracoes:
        try:
            _adicionar_coluna_se_nao_existir(cursor, tabela, coluna, definicao)
        except Exception as e:
            logger.warning(f"Falha em migracao {tabela}.{coluna}: {e}")
    conn.commit()

    # Backfill: para vendas antigas (antes da existência de vendas_pagamentos),
    # cria um registro único na nova tabela com a forma original. Isso garante
    # que relatórios de caixa por forma funcionem retroativamente.
    try:
        cursor.execute("""
            INSERT INTO vendas_pagamentos (venda_id, forma, valor)
            SELECT v.id, v.forma_pagamento, v.total
            FROM vendas v
            WHERE v.forma_pagamento IS NOT NULL
              AND v.forma_pagamento NOT IN ('MULTIPLO', 'FIADO')
              AND NOT EXISTS (
                  SELECT 1 FROM vendas_pagamentos vp WHERE vp.venda_id = v.id
              )
        """)
        conn.commit()
    except Exception as e:
        logger.warning(f"Falha no backfill de vendas_pagamentos: {e}")

    cursor.execute("SELECT id FROM usuarios WHERE nome = 'admin'")
    if not cursor.fetchone():
        senha_hash = gerar_hash_senha("admin")
        cursor.execute(
            "INSERT INTO usuarios (nome, senha, perfil, ativo, senha_provisoria) "
            "VALUES (?, ?, ?, 1, 1)",
            ("admin", senha_hash, "Administrador"))
        admin_id = cursor.lastrowid
        for tela in ["pdv", "gerencial", "notas", "cad_produto",
                     "cancelar_venda", "excluir_produto",
                     "gerenciar_usuarios", "abrir_fechar_caixa",
                     "ver_relatorios", "sangria_suprimento",
                     "gerenciar_dividas", "cancelar_entrada_nf",
                     "financeiro"]:
            cursor.execute(
                "INSERT INTO permissoes_usuario (usuario_id, tela) VALUES (?, ?)",
                (admin_id, tela))
        conn.commit()

    conn.close()


if __name__ == "__main__":
    inicializar_banco()
    print("Banco inicializado com sucesso.")