from boards.probe import find_links, form_fields, pdf_markers, table_shapes, years_in

PAGE = """
<html><body>
<form action="entidad.php" method="post">
  <input name="rut" type="hidden" value="90690000">
  <select name="aa"><option value="2026">2026</option><option value="2025">2025</option></select>
  <select name="mm">
    <option>03</option><option>06</option><option>09</option><option>12</option>
  </select>
</form>
<table>
  <tr><th>Nombre</th><th>Acciones</th><th>% de propiedad</th></tr>
  <tr><td>ANTARCHILE S.A.</td><td>790581560</td><td>60,82</td></tr>
  <tr><td>VIECAL S.A.</td><td>29439066</td><td>2,26</td></tr>
</table>
<table><tr><td>2024 | IAGC</td><td><a href="/webservices/verdocumento/ver?e=abc">PDF</a></td></tr>
<tr><td>2015 | IAGC</td><td><a href="/webservices/verdocumento/ver?e=def">PDF</a></td></tr></table>
</body></html>
"""


def test_form_fields_reads_selects_and_hidden_inputs():
    forms = form_fields(PAGE)
    names = [x["name"] for x in forms[0]["fields"]]
    assert names == ["rut", "aa", "mm"]
    assert forms[0]["fields"][1]["options"] == ["2026", "2025"]
    assert forms[0]["fields"][2]["n_options"] == 4


def test_find_links_keeps_row_context_and_absolute_url():
    links = find_links(PAGE, "https://www.cnmv.es/portal/x", r"verdocumento")
    assert len(links) == 2
    assert links[0]["href"].startswith("https://www.cnmv.es/webservices/verdocumento")
    assert "2024" in links[0]["row"]


def test_years_in_ignores_share_counts():
    assert years_in("2024 | IAGC 2015 790581560") == [2015, 2024]


def test_table_shapes():
    shapes = table_shapes(PAGE)
    assert shapes[0]["rows"] == 2
    assert "% de propiedad" in shapes[0]["cols"]


def test_pdf_markers_lists_pages():
    pages = ["A.2 Participaciones", "C.1.2 consejeros dominical", "nada"]
    mk = pdf_markers(pages)
    assert mk["A.2"] == [1]
    assert mk["C.1.2"] == [2]
    assert mk["A.6"] == []


def test_first_table_rows_picks_the_matching_table():
    from boards.probe import first_table_rows

    rows = first_table_rows(PAGE, "% de propiedad")
    assert rows[0][-1] == "% de propiedad"
    assert rows[1][0] == "ANTARCHILE S.A."
    assert first_table_rows(PAGE, "no such header") == []
