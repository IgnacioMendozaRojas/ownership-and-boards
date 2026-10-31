import pandas as pd

from boards import chile, iagc

TEXT = """C.1.3 ...
Número total de consejeros ejecutivos 2
% sobre el total del consejo 13,33
Número total de consejeros dominicales 6
Número total de consejeros independientes 7
Número total de consejeros 15
% total de derechos de voto representados en el consejo de administración 51
"""


def words(rows):
    """Word boxes [x0, x1, top, text] from (top, [(x0, text), ...]) rows."""
    out = []
    for top, items in rows:
        for x0, text in items:
            out.append([x0, x0 + 6 * len(text), top, text])
    return out


A2 = [
    (100, [(40, "A.2"), (60, "Detalle"), (110, "los"), (130, "titulares")]),
    (120, [(40, "Nombre"), (90, "accionista"), (300, "Directo")]),
    (140, [(40, "ENAIRE"), (300, "51,00"), (360, "0,00"), (420, "51,00")]),
    (160, [(40, "HOHN,"), (90, "CHRISTOPHER")]),
    (170, [(300, "2,07"), (360, "0"), (420, "6,26")]),
    (180, [(40, "ANTHONY")]),
    (200, [(40, "BLACKROCK,"), (110, "INC."), (300, "4,18"), (360, "0,01"), (420, "4,19")]),
    (220, [(40, "Detalle"), (90, "de"), (110, "la"), (130, "participación"), (220, "indirecta")]),
]


def test_parse_report_counts_and_votes():
    rec = {
        "nif": "A1",
        "firm": "X",
        "year": 2025,
        "pages": [{"page": 1, "text": TEXT, "words": []}],
    }
    row = iagc.parse_report(rec)
    assert row["board_size"] == 15
    assert (row["n_exec"], row["n_dom"], row["n_ind"], row["n_other"]) == (2, 6, 7, 0)
    assert row["votes_on_board"] == 51.0


def test_parse_a2_assigns_wrapped_names_to_their_row():
    pages = [{"page": 1, "text": "", "words": words(A2)}]
    rows = iagc.parse_a2(pages)
    assert [(r["holder"], r["pct"]) for r in rows] == [
        ("ENAIRE", 51.0),
        ("TCI (Christopher Hohn)", 6.26),
        ("BlackRock", 4.19),
    ]
    assert rows[0]["type"] == "state"


def test_split_gaps_balances_name_lines_around_rows():
    # one line above the first row, two between the rows, one below the last: one each side
    assert iagc.split_gaps(1, [2], 1) == [1]
    # on a tie, a wrapped line stays with the name above it
    assert iagc.split_gaps(1, [2], 0) == [2]


def test_align_keeps_order():
    assert iagc.align([10, 20, 30], [(10, 0), (19, 1), (31, 2)]) == {0: 0, 1: 1, 2: 2}


def test_clean_top12_drops_share_counts_in_the_pct_column():
    top = pd.DataFrame(
        {
            "rut": ["1"] * 3,
            "period": ["2010-12"] * 3,
            "rank": [1, 2, 14],
            "holder": ["A S.A.", "AFP HABITAT S A FONDO TIPO A", "A S.A."],
            "pct": [50.1, 1.2, 3.0e9],
        }
    )
    t = chile.clean_top12(top)
    assert list(t["holder"]) == ["A S.A.", "AFP HABITAT S A FONDO TIPO A"]
    c = chile.constellations(t).iloc[0]
    assert c["top1_pct"] == 50.1 and c["pct_pension_fund"] == 1.2
    assert c["constellation"] == "corporate"


def test_pay_new_and_old_models():
    from boards import iagc

    new = (
        "C.1.13 Indique el importe de los siguientes conceptos relativos a la remuneración global\n"
        "del consejo de administración:\n"
        "Remuneración devengada en el ejercicio a favor del consejo de administración (miles de\n"
        "euros) 12.345\n"
        "C.1.14 ...\nRemuneración total alta dirección (en miles de euros) 7.890,5\n"
    )
    old = "Remuneración del consejo de administración (miles de euros) 4.100\n"
    rec = {"nif": "X", "firm": "F", "year": 2016, "pages": [{"text": old, "words": []}]}
    assert iagc.parse_report(rec)["board_pay"] == 4100
    rec = {"nif": "X", "firm": "F", "year": 2023, "pages": [{"text": new, "words": []}]}
    r = iagc.parse_report(rec)
    assert r["board_pay"] == 12345 and r["mgmt_pay"] == 7890.5


def test_cache_version(tmp_path):
    from boards import cnmv

    p = tmp_path / "x.json.gz"
    cnmv.save_cache(p, {"pages": []})
    assert not cnmv.is_current(p)
    cnmv.save_cache(p, {"pages": [], "v": cnmv.CACHE_VERSION})
    assert cnmv.is_current(p)
