"""arff_reader.py — 通用 ARFF 文件读取器。

同时服务：
- 数据集登记/回填（fields_schema 需要样例值 sample_values，V3.0 §3.1.4）
- 数据内容预览接口（V3.0 §2.4：读取前 N 条数据，标签列高亮，后端限单次 ≤100 条）

约定：
- 字段类型：numeric / enum / string（date 与 real/integer 归并为 numeric）
- 枚举值域用 `_split_enum_values` 正确切分带引号/逗号的值
- 数据行支持带引号字段（值内可能含逗号，如 `'Circuit Breaker'`）
- 样例值取每个字段前 2 个不同的真实值（`?` 缺失值跳过）
"""
import re

_ATTR_RE = re.compile(r"@ATTRIBUTE\s+(.+)$", re.IGNORECASE)


def _split_arff_values(content: str, *, keep_empty: bool) -> list[str]:
    """用统一的引号/转义/逗号状态机切分 ARFF 列表。"""
    values: list[str] = []
    buf: list[str] = []
    in_quote = False
    quote_char = ""
    i = 0

    def append_value() -> None:
        value = "".join(buf).strip()
        if keep_empty or value:
            values.append(value)
        buf.clear()

    while i < len(content):
        ch = content[i]
        if in_quote:
            if ch == "\\" and i + 1 < len(content) and content[i + 1] == quote_char:
                buf.append(quote_char)
                i += 2
                continue
            if ch == quote_char:
                in_quote = False
            else:
                buf.append(ch)
        elif ch in ("'", '"'):
            in_quote = True
            quote_char = ch
        elif ch == ",":
            append_value()
        else:
            buf.append(ch)
        i += 1

    append_value()
    return values


def _split_enum_values(content: str):
    """切分 ARFF 枚举定义 `{a, b, 'c d', ...}` -> 值列表（正确处理转义引号与逗号）。"""
    return _split_arff_values(content, keep_empty=False)


def _split_data_row(line: str):
    """切分一行 @DATA 记录，支持带引号字段与转义字符（值内可能含逗号）。"""
    return _split_arff_values(line, keep_empty=True)


def _parse_attribute(body: str):
    """解析一条 @ATTRIBUTE 的「名字 + 类型」部分。

    返回字段描述 dict（与 read_arff 的 fields 元素同构）；无法解析时返回 None。
    """
    if body.startswith("'") or body.startswith('"'):
        q = body[0]
        name, _, typ = body[1:].partition(q)
        typ = typ.strip()
    else:
        parts = body.split(None, 1)
        if len(parts) != 2:
            return None
        name, typ = parts[0], parts[1].strip()
    name = name.lstrip("\ufeff").strip()
    if typ.lower().startswith("{"):
        enum_values = _split_enum_values(typ.strip("{}"))
        field_type = "enum"
    else:
        enum_values = []
        base = typ.lower().split()[0] if typ.split() else "numeric"
        field_type = "numeric" if base in ("numeric", "real", "integer", "date") else "string"
    return {
        "name": name,
        "type": field_type,
        "enum_values": enum_values,
        "sample_values": [],
    }


def read_arff(path: str, max_rows: int | None = None):
    """解析 ARFF，返回 (fields, rows)。

    - fields: [{name, type, enum_values, sample_values}]（不含 role，由调用方按标签字段标记）
    - rows: list[list[str]]，最多 max_rows 行（@DATA 之后的有效记录）
    """
    fields: list[dict] = []
    rows: list[list[str]] = []
    in_data = False

    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r").strip()
            if not line or line.startswith("%"):
                continue
            upper = line.upper()
            if upper.startswith("@ATTRIBUTE"):
                m = _ATTR_RE.match(line)
                if not m:
                    continue
                field = _parse_attribute(m.group(1).strip())
                if field is not None:
                    fields.append(field)
                continue
            if upper.startswith("@DATA"):
                in_data = True
                continue
            if upper.startswith("@") or not in_data:
                continue
            # @DATA 数据行
            values = _split_data_row(line)
            rows.append(values)
            # 采集样例值：每字段前 2 个不同值（先判上限再判是否新增）
            for i, v in enumerate(values):
                if i >= len(fields):
                    break
                if len(fields[i]["sample_values"]) >= 2:
                    continue
                if v and v != "?" and v not in fields[i]["sample_values"]:
                    fields[i]["sample_values"].append(v)
            if max_rows is not None and len(rows) >= max_rows:
                break

    return fields, rows


def count_arff_rows(path: str) -> int:
    """统计 ARFF @DATA 段的有效记录行数（预览分页 total 用）。"""
    count = 0
    in_data = False
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r").strip()
            if not line or line.startswith("%"):
                continue
            upper = line.upper()
            if upper.startswith("@DATA"):
                in_data = True
                continue
            if in_data and not upper.startswith("@"):
                count += 1
    return count