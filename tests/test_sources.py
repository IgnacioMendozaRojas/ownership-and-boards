from boards import cmf, cnmv
from boards.cli import match_firms

TOP12 = """<table><tr><th>Nombre (Apellido paterno, materno, nombres)</th>
<th>Número de acciones suscritas</th><th>Número de acciones pagadas</th>
<th>% de propiedad (*)</th></tr>
<tr><td>ANTARCHILE S.A.</td><td>790.581.560</td><td>790.581.560</td><td>60,82%</td></tr>
<tr><td>VIECAL S.A.</td><td>29.439.066</td><td>29.439.066</td><td>2,26%</td></tr></table>"""

BOARD = """<table><tr><th>RUT</th><th>Nombre</th><th>Cargo</th><th>Fecha Nombramiento</th></tr>
<tr><td>5.625.652-0</td><td>ROBERTO ANGELINI ROSSI</td><td>Presidente</td><td>24/04/2024</td></tr>
</table>
<table><tr><td>Periodo comprendido entre el 01/01/2010 y 31/12/2012</td></tr>
<tr><th>RUT</th><th>Nombre</th><th>Cargo</th><th>Fecha Nombramiento</th><th>Fecha término</th></tr>
<tr><td>2.779.390-8</td><td>JOSE TOMAS  GUZMAN DUMAS</td><td>Vicepresidente</td>
<td>28/04/2011</td><td>23/04/2014</td></tr></table>"""

ISSUERS = """<table><tr>
<td><a href="entidad.php?mercado=V&rut=90690000&tipoentidad=RVEMI">90690000-9</a></td>
<td><a href="entidad.php?mercado=V&rut=90690000&tipoentidad=RVEMI">EMPRESAS COPEC S.A.</a></td></tr>
<tr><td><a href="entidad.php?rut=91705000">QUIÑENCO S.A.</a></td></tr></table>"""

INDEX = """<table><tr><td>AENA, S.M.E., S.A.</td><td>2026028900</td><td>25/02/2026</td><td>2025</td>
<td><a href="/webservices/verdocumento/ver?e=abc">pdf</a></td></tr></table>"""


def test_number_handles_chilean_formats():
    assert cmf.number("790.581.560") == 790581560
    assert cmf.number("60,82%") == 60.82
    assert cmf.number("") is None


def test_parse_top12():
    rows = cmf.parse_top12(TOP12)
    assert [r["holder"] for r in rows] == ["ANTARCHILE S.A.", "VIECAL S.A."]
    assert rows[0]["pct"] == 60.82 and rows[0]["rank"] == 1


def test_parse_board_current_and_history():
    now = cmf.parse_board(BOARD, history=False)
    past = cmf.parse_board(BOARD, history=True)
    assert now[0]["director_rut"] == "5625652-0" and now[0]["ended"] == ""
    assert past[0]["director"] == "JOSE TOMAS GUZMAN DUMAS"
    assert past[0]["ended"] == "23/04/2014"


def test_parse_n_holders():
    html = "<p>Número total de registros :  6045 (este número se conforma...)</p>"
    assert cmf.parse_n_holders(html) == 6045


def test_issuers_and_matching_ignore_accents():
    issuers = cmf.parse_issuers(ISSUERS)
    assert [x["rut"] for x in issuers] == ["90690000", "91705000"]
    found, missing = match_firms(issuers, ["EMPRESAS COPEC", "QUINENCO", "^NOPE"])
    assert [f["rut"] for f in found] == ["90690000", "91705000"]
    assert missing == ["^NOPE"]


def test_parse_cnmv_index():
    e = cnmv.parse_index(INDEX)[0]
    assert e["year"] == 2025 and e["registered"] == "25/02/2026"
    assert e["url"].startswith("https://www.cnmv.es/webservices/verdocumento")


def test_year_range_latest_is_the_last_full_year():
    from datetime import date

    from boards.cli import year_range

    assert year_range({"years": [2010, "latest"]}, date(2027, 4, 15)) == (2010, 2026)
    assert year_range({"years": [2015, 2025]}) == (2015, 2025)
