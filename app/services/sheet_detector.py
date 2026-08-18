from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .excel_reader import TableData, WorkbookData, combine_tables
from .text_utils import normalize_text
from .normalizer import find_column, to_float, ValueParseError


@dataclass
class DetectedSheets:
    previsto: TableData
    realizado: TableData
    base_dados: TableData | None = None


@dataclass
class InputDetection:
    previsto_tables: list[TableData]
    realizado_tables: list[TableData]
    ignored_tables: list[TableData]
    notes: list[str] = field(default_factory=list)

    @property
    def previsto(self) -> TableData:
        return combine_tables(self.previsto_tables, "PREVISTO CONSOLIDADO")

    @property
    def realizado(self) -> TableData:
        return combine_tables(self.realizado_tables, "REALIZADO CONSOLIDADO")


class SheetDetectionError(RuntimeError):
    pass


EXPECTED = {
    "previsto": ["COD FORNECEDOR", "FORNECEDOR", "DATA PREVISTA", "VALOR PREVISTO"],
    "realizado": ["TITULO", "FORNECEDOR", "NOME FORNECEDOR", "VLR ORIGINAL", "VENCIMENTO"],
    "base": ["COD FORNECEDOR", "FORNECEDOR", "FLUXO JMM", "CATEGORIA"],
    # Formato consolidado encontrado na planilha do cliente. A coluna Situação FC
    # define deterministicamente se a linha pertence ao PREVISTO ou REALIZADO.
    "consolidado": ["TITULO", "COD FORNECEDOR", "FORNECEDOR", "DATA", "PREVISTO", "REALIZADO", "SITUACAO FC"],
}


def _score(table: TableData, keys: list[str]) -> int:
    headers = {normalize_text(h) for h in table.headers}
    return sum(1 for key in keys if any(key == h or key in h for h in headers))


def _has_all(table: TableData, aliases: list[tuple[str, ...]]) -> bool:
    return all(find_column(table, *group) is not None for group in aliases)


def _consolidated_value_columns(table: TableData) -> tuple[str, str, str] | None:
    """Resolve, de forma determinística, o par de colunas monetárias do consolidado.

    Contratos aceitos:
    1) Previsto + Realizado;
    2) Valor + Valor2, modelo operacional em que Situação FC define o tipo da
       linha, Valor alimenta PREVISTO e Valor2 alimenta REALIZADO.

    A identificação não usa posição da coluna, sinal isolado nem aproximação de
    nomes. Isso evita interpretar layouts desconhecidos como dados financeiros.
    """
    c_prev = find_column(table, "Previsto")
    c_real = find_column(table, "Realizado")
    if c_prev and c_real:
        return "previsto_realizado", c_prev, c_real

    c_value = find_column(table, "Valor")
    c_value2 = find_column(table, "Valor2", "Valor 2")
    if c_value and c_value2:
        return "valor_valor2", c_value, c_value2
    return None


def _is_consolidated_fc(table: TableData) -> bool:
    """Reconhece o consolidado somente com contrato estrutural completo.

    A coluna Situação FC continua sendo a chave determinística de separação
    PREVISTO/REALIZADO. O par monetário pode ser Previsto/Realizado ou
    Valor/Valor2, ambos explicitamente conhecidos e validados.
    """
    required = [
        ("Título", "Titulo"),
        ("Cód Fornecedor", "Codigo Fornecedor"),
        ("Fornecedor",),
        ("Data",),
        ("Situação FC", "Situacao FC", "Situação", "Situacao"),
    ]
    return _has_all(table, required) and _consolidated_value_columns(table) is not None


def table_role(table: TableData) -> str | None:
    if _is_consolidated_fc(table):
        return "consolidado"
    p = _score(table, EXPECTED["previsto"])
    r = _score(table, EXPECTED["realizado"])
    b = _score(table, EXPECTED["base"])
    # BASE DADOS compartilha colunas com PREVISTO. Ela só é marcada como base
    # quando possui a estrutura de classificação e não a estrutura financeira.
    if b >= 3 and p < 3 and r < 4:
        return "base"
    if r >= 4 and r > p:
        return "realizado"
    if p >= 3:
        return "previsto"
    return None


def _canonicalize(table: TableData, role: str) -> TableData:
    aliases = {
        "previsto": {
            "Título Previsto": ("Título Previsto", "Titulo Previsto"),
            "Cód Fornecedor": ("Cód Fornecedor", "Codigo Fornecedor"),
            "Fornecedor": ("Fornecedor",),
            "Data prevista": ("Data prevista",),
            "Valor previsto": ("Valor previsto",),
            "Mês": ("Mês", "Mes"),
        },
        "realizado": {
            "Título": ("Título", "Titulo"),
            "Fornecedor": ("Fornecedor", "Cód Fornecedor"),
            "Nome Fornecedor": ("Nome Fornecedor", "Fornecedor Nome"),
            "Vlr.Original": ("Vlr.Original", "Valor Original", "Total"),
            "Emissão": ("Emissão", "Emissao"),
            "Ult. Pgto.": ("Ult. Pgto.", "Ult Pgto", "Data Pagamento"),
            "Vencimento": ("Vencimento",),
            "Empresa": ("Empresa",),
            "Filial": ("Filial",),
            "Sit.": ("Sit.", "Sit"),
            "Desc. Conta Contábil": ("Desc. Conta Contábil", "Desc Conta Contábil"),
            "Desc. Conta Financeira": ("Desc. Conta Financeira", "Desc Conta Financeira"),
            "Desc. Centro de Custo": ("Desc. Centro de Custo", "Desc Centro de Custo"),
        },
    }[role]
    mapping = {canonical: find_column(table, *alts) for canonical, alts in aliases.items()}
    headers = list(table.headers)
    for canonical in aliases:
        if canonical not in headers:
            headers.append(canonical)
    rows = []
    for original in table.rows:
        row = dict(original)
        for canonical, raw in mapping.items():
            if raw is not None:
                row[canonical] = original.get(raw)
        rows.append(row)
    return TableData(table.sheet_name, headers, rows, table.source_path, table.header_row)


def _split_consolidated_fc(table: TableData) -> tuple[TableData, TableData, list[str]]:
    """Converte o layout consolidado do cliente em duas tabelas canônicas.

    Regras de segurança:
    - Situação FC é a única chave usada para separar PREVISTO/REALIZADO.
    - PREVISTO usa somente a coluna Previsto.
    - REALIZADO usa o valor absoluto da coluna Realizado, pois o layout do cliente
      representa saídas realizadas com sinal negativo.
    - Fluxo JMM/Categoria existentes no arquivo NÃO são usados para classificação;
      a classificação permanece vinda exclusivamente da BASE DADOS fixa.
    - O layout não possui Vencimento. A Data é tratada como data do realizado e a
      pontualidade permanece indisponível, evitando inferência incorreta.
    """
    c_title = find_column(table, "Título", "Titulo")
    c_code = find_column(table, "Cód Fornecedor", "Codigo Fornecedor")
    c_name = find_column(table, "Fornecedor")
    c_date = find_column(table, "Data")
    value_columns = _consolidated_value_columns(table)
    c_status = find_column(table, "Situação FC", "Situacao FC", "Situação", "Situacao")
    c_month = find_column(table, "Mês", "Mes")

    assert value_columns is not None
    value_layout, c_prev, c_real = value_columns
    assert all((c_title, c_code, c_name, c_date, c_prev, c_real, c_status))

    p_rows: list[dict[str, Any]] = []
    r_rows: list[dict[str, Any]] = []
    unknown_status = 0

    for original in table.rows:
        status = normalize_text(original.get(c_status))
        if status == "PREVISTO":
            row = dict(original)
            row["Título Previsto"] = original.get(c_title)
            row["Cód Fornecedor"] = original.get(c_code)
            row["Fornecedor"] = original.get(c_name)
            row["Data prevista"] = original.get(c_date)
            row["Valor previsto"] = original.get(c_prev)
            if c_month:
                row["Mês"] = original.get(c_month)
            p_rows.append(row)
        elif status == "REALIZADO":
            row = dict(original)
            row["Título"] = original.get(c_title)
            # O reconciliador legado usa "Fornecedor" como código no REALIZADO.
            row["Fornecedor"] = original.get(c_code)
            row["Nome Fornecedor"] = original.get(c_name)
            try:
                raw_actual = to_float(original.get(c_real), field="Realizado")
            except ValueParseError as exc:
                src_row = int(original.get("__source_row__") or 0)
                raise SheetDetectionError(
                    f"Na aba '{table.sheet_name}', linha {src_row}, o valor da coluna Realizado não é válido: {exc}."
                ) from exc
            row["Vlr.Original"] = abs(raw_actual)
            # O layout consolidado não possui uma coluna de emissão separada.
            # A própria Data é a referência temporal segura disponível para o
            # realizado e, portanto, também alimenta o filtro de competência.
            row["Emissão"] = original.get(c_date)
            row["Ult. Pgto."] = original.get(c_date)
            row["Vencimento"] = None
            r_rows.append(row)
        elif status:
            unknown_status += 1

    source = table.source_path
    p = TableData(
        sheet_name=f"{table.sheet_name} • PREVISTO",
        headers=["Título Previsto", "Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto", "Mês"],
        rows=p_rows,
        source_path=source,
        header_row=table.header_row,
    )
    r = TableData(
        sheet_name=f"{table.sheet_name} • REALIZADO",
        headers=["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Emissão", "Ult. Pgto.", "Vencimento"],
        rows=r_rows,
        source_path=source,
        header_row=table.header_row,
    )

    notes = [
        f"Layout consolidado identificado em '{table.sheet_name}': {len(p_rows)} linha(s) PREVISTO e {len(r_rows)} linha(s) REALIZADO foram separadas automaticamente pela coluna Situação FC.",
        "Neste layout, a coluna Data do REALIZADO é usada como data de realização. Como não existe Vencimento, a pontualidade não é inferida e aparecerá como indisponível.",
        "Fluxo JMM e Categoria eventualmente presentes no arquivo importado são ignorados na classificação; a automação continua usando somente a BASE DADOS fixa para evitar inconsistências.",
    ]
    if value_layout == "valor_valor2":
        notes.insert(
            1,
            "Mapeamento seguro reconhecido: Valor alimenta PREVISTO e Valor2 alimenta REALIZADO. "
            "O sinal negativo eventualmente presente em Valor2 é normalizado somente depois de a Situação FC confirmar que a linha é REALIZADO."
        )
    if unknown_status:
        notes.append(
            f"{unknown_status} linha(s) do layout consolidado possuíam Situação FC diferente de PREVISTO/REALIZADO e foram ignoradas por segurança."
        )
    return p, r, notes


def _friendly_detection_error(workbooks: list[WorkbookData], previsto: list[TableData], realizado: list[TableData]) -> SheetDetectionError:
    found = []
    for wb in workbooks:
        for table in wb.tables[:8]:
            cols = ", ".join(str(h) for h in table.headers[:14])
            found.append(f"• {wb.path.name} > {table.sheet_name}: {cols}")
    found_text = "\n".join(found) if found else "• Nenhuma tabela legível foi encontrada."
    missing = []
    if not previsto:
        missing.append("PREVISTO")
    if not realizado:
        missing.append("REALIZADO")
    return SheetDetectionError(
        "Não consegui identificar com segurança os dados necessários para gerar o relatório.\n\n"
        f"Faltou identificar: {', '.join(missing)}. Nenhum valor foi estimado ou reaproveitado de uma coluna ambígua.\n\n"
        "A automação aceita atualmente:\n"
        "1) Relatórios separados: PREVISTO com Cód Fornecedor, Fornecedor, Data prevista e Valor previsto; "
        "REALIZADO com Título, código/nome do fornecedor, Vlr.Original, pagamento e vencimento.\n"
        "2) Relatório consolidado: Título, Cód Fornecedor, Fornecedor, Data, Situação FC e um dos pares monetários conhecidos: Previsto/Realizado ou Valor/Valor2.\n\n"
        "Colunas encontradas:\n" + found_text +
        "\n\nSe os dados existem com nomes diferentes, ajuste apenas os cabeçalhos ou envie o modelo para inclusão de um novo mapeamento seguro."
    )


def detect_input_tables(workbooks: list[WorkbookData]) -> InputDetection:
    previsto: list[TableData] = []
    realizado: list[TableData] = []
    ignored: list[TableData] = []
    notes: list[str] = []

    for wb in workbooks:
        for table in wb.tables:
            role = table_role(table)
            if role == "consolidado":
                p, r, format_notes = _split_consolidated_fc(table)
                if p.rows:
                    previsto.append(p)
                if r.rows:
                    realizado.append(r)
                notes.extend(format_notes)
            elif role == "previsto":
                previsto.append(_canonicalize(table, "previsto"))
            elif role == "realizado":
                realizado.append(_canonicalize(table, "realizado"))
            else:
                # BASE DADOS existente no arquivo do usuário é deliberadamente ignorada:
                # a classificação vem somente da base fixa da automação.
                ignored.append(table)

    if not previsto or not realizado:
        raise _friendly_detection_error(workbooks, previsto, realizado)
    return InputDetection(previsto, realizado, ignored, notes)


def detect_base_table(workbook: WorkbookData) -> TableData:
    candidates = [(table, _score(table, EXPECTED["base"])) for table in workbook.tables]
    candidates = [(table, score) for table, score in candidates if score >= 3]
    if not candidates:
        raise SheetDetectionError(
            "Não encontrei uma BASE DADOS válida. São necessárias as colunas: "
            "Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria."
        )
    # Preferência determinística: maior score; em empate, nome que contenha BASE.
    candidates.sort(key=lambda item: (item[1], "BASE" in normalize_text(item[0].sheet_name)), reverse=True)
    return candidates[0][0]


def detect_sheets(workbook: WorkbookData) -> DetectedSheets:
    """Compatibilidade com versões anteriores e utilitários de validação."""
    det = detect_input_tables([workbook])
    try:
        base = detect_base_table(workbook)
    except SheetDetectionError:
        base = None
    return DetectedSheets(previsto=det.previsto, realizado=det.realizado, base_dados=base)
