"""Owner types from holder names, by ordered rules (the first rule that matches wins).

A rule-based first pass: transparent and easy to audit, and every name it cannot place falls to
'individual' only when it carries no company marker. The type list follows the literature on
owner identity (family or individual, corporate or group, institutional, state) plus the two
Chilean specifics: pension funds (AFP) and custodian or broker accounts.
"""

from __future__ import annotations

import re

from .cmf import norm

RULES: list[tuple[str, str]] = [
    (
        "pension_fund",
        r"\bAFP\b|ADMINISTRADORA DE FONDOS DE PENSIONES|FONDO DE PENSION|FDO\.? ?PENS",
    ),
    (
        "custodian",
        r"POR CUENTA DE|CTA\.? (DE )?TERCEROS|CUENTA DE TERCEROS|CUSTODI|EXTRANJEROS|"
        r"DEPOSITARY|\bADR\b|BANCO SANTANDER.*JP|CITIBANK|DEUTSCHE BANK|BNY|STATE STREET BANK",
    ),
    ("broker", r"CORREDOR(ES|A)? DE BOLSA|\bCORREDORA\b|VALORES S\.?A\b|LARRAIN VIAL|BTG PACTUAL"),
    (
        "state_foreign",
        r"NORGES BANK|QATAR INVESTMENT|\bGIC\b|MUBADALA|PUBLIC INVESTMENT FUND|"
        r"ABU DHABI INVESTMENT|KUWAIT INVESTMENT|TEMASEK",
    ),
    (
        "state",
        r"\bFISCO\b|\bCORFO\b|TESORERIA|ESTADO DE CHILE|\bCODELCO\b|\bENAP\b|\bSEPI\b|"
        r"\bENAIRE\b|SOCIEDAD ESTATAL|MINISTERIO|GOBIERNO DE|BANCO CENTRAL",
    ),
    (
        "institutional",
        r"BLACKROCK|VANGUARD|AMUNDI|FIDELITY|INVESCO|T\. ?ROWE|CAPITAL (GROUP|RESEARCH)|"
        r"WELLINGTON|DODGE|LAZARD|SCHRODER|ABERDEEN|FRANKLIN|NATIXIS|ALLIANZ GLOBAL|"
        r"GOLDMAN SACHS|MORGAN STANLEY|JP ?MORGAN|UBS|CREDIT SUISSE|"
        r"ASSET MANAGEMENT|INVESTMENT MANAGEMENT|CAPITAL MANAGEMENT|INVESTMENT MASTER|"
        r"\bFUND\b|\bFUNDS\b|FONDO (DE INVERSION|MUTUO)|FONDOS? MUTUOS|\bAGF\b|"
        r"ADMINISTRADORA GENERAL DE FONDOS|SEGUROS|INSURANCE|ASEGURADORA|CHILDREN.S INVESTMENT",
    ),
    ("foundation", r"\bFUNDACION\b|\bFOUNDATION\b|\bFUNDACIO\b"),
    (
        "corporate",
        r"\bS\.? ?A\.?\b|\bS\.?A\.?U\.?\b|\bSPA\b|\bLTDA\b|LIMITADA|\bS\.? ?L\.?\b|INVERSIONES|"
        r"SOCIEDAD|\bINC\b|\bLLC\b|\bL\.?P\.?\b|\bLTD\b|\bPLC\b|\bS\.?E\.?\b|\bAG\b|\bN\.?V\.?\b|"
        r"\bB\.?V\.?\b|GMBH|HOLDING|GROUP|\bCORP|COMPANY|COMPANIA|S\.?A\.?R\.?L|\bCIA\b|"
        r"\bSARL\b|\bS\.?C\.?A\b|INVERSORA|PARTICIPACIONES|CARTERA|\bLIMITED\b",
    ),
]
COMPILED = [(t, re.compile(p)) for t, p in RULES]
TYPES = [t for t, _ in RULES] + ["individual"]


def owner_type(name: str) -> str:
    n = norm(name)
    for t, rx in COMPILED:
        if rx.search(n):
            return t
    return "individual"
