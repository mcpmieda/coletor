#!/usr/bin/env python3
"""Generate synthetic HTML shaped like the inspected annual Smecel grid.

No network, copied source HTML, real students, dates of birth or family data.
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

MONTHS = ("FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
SLOT_STYLE = "width:16.666666666667%;float:left;border-left:#999 solid 1px;border-right:#999 solid 1px;"
LEGEND = ('• = Aula prevista/presença; X = falta não justificada; '
          '<span class="ls-color-warning ls-ico-info"></span> = falta justificada; '
          '<span class="ls-ico-calendar"></span> = dia não letivo (calendário); '
          '<span class="ls-ico-minus"></span> = fora do período de matrícula; '
          'em branco = data fora do calendário da matriz/padrão.')


def build_fixture(year: int = 2026, class_id: str = "TESTE-A", students: int = 3,
                  include_edge_cases: bool = True) -> str:
    if not 1 <= students <= 3:
        raise ValueError("Use one to three explicitly synthetic students.")
    out = ["<!doctype html>", '<html lang="pt-BR"><head><meta charset="utf-8">',
           '<title>Diário anual SINTÉTICO — sem dados reais</title></head><body>',
           '<h1>DEMONSTRAÇÃO SINTÉTICA — não é uma exportação real do Smecel</h1>',
           f'<div class="container-fluid" data-report="synthetic-smecel-annual-v1" '
           f'data-class-id="{escape(class_id, quote=True)}" data-year="{year}" data-student-count="{students}">']
    for student in range(1, students + 1):
        out += [f'<div style="page-break-inside: avoid;" data-student-row="{student}">',
                '<p></p><div class="ls-box1"><span class="ls-float-right"></span><small>',
                f'Aluno(a): <strong>Aluno sintético {student:03d}</strong><br>',
                'Nascimento: <strong>[não coletado]</strong><br>',
                'Filiação: <strong>[não coletado]</strong><br>',
                f'Turma: <strong>{escape(class_id)}</strong><br>',
                'Data da matrícula: <strong>[não coletado]</strong>',
                '</small></div><p></p>',
                f'<p class="ls-ico-text ls-txt-center">FREQUENCIA ESCOLAR {year}</p>',
                '<table class="ls-sm-space bordasimples"><tbody>',
                '<tr class="ls-txt-center"><td>Meses</td>' + ''.join(f'<td>{month}/{year}</td>' for month in MONTHS) + '</tr>',
                '<tr><td>Aulas</td>' + ''.join('<td><div style="width:100%">' + ''.join(f'<div>{lesson}</div>' for lesson in range(1, 7)) + '</div></td>' for _ in MONTHS) + '</tr>']
        for day in range(1, 32):
            out.append(f'<tr><td>{day}</td>')
            for month in MONTHS:
                out.append('<td>')
                for lesson in range(1, 7):
                    symbol = ""
                    if student == 1 and month == "FEV" and day == 2 and lesson == 2:
                        symbol = '<strong><span class="ls-color-danger">X</span></strong>'
                    if student == 2 and month == "MAR" and day == 3 and lesson == 6:
                        symbol = '<strong><span class="ls-color-danger">X</span></strong>'
                    if include_edge_cases and student == 1 and month == "FEV" and day == 2:
                        symbol = {1: '<strong><span class="ls-color-danger">X</span></strong>',
                                  2: '<strong><span class="ls-color-warning ls-ico-info"></span></strong>',
                                  3: '•', 4: '<span class="ls-ico-calendar"></span>',
                                  5: '<span class="ls-ico-minus"></span>', 6: '?'}[lesson]
                    if include_edge_cases and student == 1 and month == "FEV" and day == 31 and lesson == 1:
                        symbol = '<strong><span class="ls-color-danger">X</span></strong>'
                    out.append(f'<div style="{SLOT_STYLE}" data-day="{day}" data-lesson="{lesson}">{symbol}</div>')
                out.append('</td>')
            out.append('</tr>')
        out += ['<tr><td>FALTAS</td>' + ''.join('<td>Faltas: 0</td>' for _ in MONTHS) + '</tr>',
                '</tbody></table>', f'<p style="margin:8px 0 0 0;"><small><i>{LEGEND}</i></small></p>']
        if student == 2:
            out.append('<br><table><tbody><tr><td>COMPONENTE</td><td>TOTAL DE FALTAS</td></tr></tbody></table>')
        out.append('</div>')
    out += ['<footer data-report-end="complete">Fim da demonstração sintética.</footer>', '</div></body></html>', '']
    return '\n'.join(out)


