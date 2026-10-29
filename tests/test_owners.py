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
        ("FUNDACIÓN BANCARIA CAIXA D'ESTALVIS I PENSIONS DE BARCELONA", "foundation"),
        ("HOHN, CHRISTOPHER ANTHONY", "individual"),
        ("ANGELINI ROSSI ROBERTO", "individual"),
        ("INVERSIONES ANGELINI Y CIA LTDA", "corporate"),
        ("COMPAÑIA DE SEGUROS DE VIDA CONSORCIO NACIONAL DE SEGUROS S.A.", "institutional"),
    ],
)
def test_owner_type(name, expected):
    assert owner_type(name) == expected
