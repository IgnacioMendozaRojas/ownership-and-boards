import pytest

from boards.owners import owner_type


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ANTARCHILE S.A.", "corporate"),
        ("BANCO DE CHILE POR CUENTA DE TERCEROS CA", "custodian"),
        ("BANCHILE CORREDORES DE BOLSA S.A.", "broker"),
        ("BANCO SANTANDER - JP MORGAN", "custodian"),
        ("AFP HABITAT S.A. PARA FDO. PENSION C", "pension_fund"),
        ("FONDO DE PENSIONES PROVIDA C", "pension_fund"),
        ("CORFO", "state"),
        ("ENAIRE", "state"),
        ("NORGES BANK", "state_foreign"),
        ("BLACKROCK, INC.", "institutional"),
        ("THE CHILDREN'S INVESTMENT MASTER FUND", "institutional"),
        ("FUNDACIÓN BANCARIA CAIXA D'ESTALVIS I PENSIONS DE BARCELONA", "nonprofit"),
        ("CAMARA CHILENA DE LA CONSTRUCCION", "nonprofit"),
        ("CORPORACION DE FOMENTO DE LA PRODUCCION", "state"),
        ("FIP ALPHA II", "institutional"),
        ("BOLSA DE COMERCIO DE SANTIAGO BOLSA DE VALORES", "custodian"),
        ("THE BANK OF NEW YORK MELLON, ADRS", "custodian"),
        ("ENEL IBEROAMERICA SRL", "corporate"),
        ("HOHN, CHRISTOPHER ANTHONY", "individual"),
        ("ANGELINI ROSSI ROBERTO", "individual"),
        ("INVERSIONES ANGELINI Y CIA LTDA", "corporate"),
        ("COMPAÑIA DE SEGUROS DE VIDA CONSORCIO NACIONAL DE SEGUROS S.A.", "institutional"),
    ],
)
def test_owner_type(name, expected):
    assert owner_type(name) == expected


def test_banks_are_custody_only_in_chile():
    assert owner_type("BANCO SANTANDER CHILE") == "custodian"
    assert owner_type("BANCO SANTANDER, S.A.", country="es") == "corporate"
