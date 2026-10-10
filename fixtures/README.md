# Fixture exclusivamente sintética

`annual-synthetic.html` é gerado por `python scripts/generate_fixture.py`, sem rede e sem dados reais. Os nomes são literalmente `Aluno sintético 001`, `Aluno sintético 002` e `Aluno sintético 003`; a turma é `TESTE-A`, ano 2026. Não há MAT, credenciais, cookies ou identificadores da API. Os campos de nascimento, filiação e data de matrícula contêm apenas `[não coletado]` e não são preservados no snapshot.

## Estrutura e semântica

A fixture reproduz a estrutura descrita por inspeção sanitizada do diário anual Smecel: `.container-fluid`, uma `div` de ficha, cabeçalho `.ls-box1`, título anual, tabela `.bordasimples`, meses FEV–DEZ em colunas, dias 1–31 em linhas e seis `div`s por célula mensal. Os dois cabeçalhos usam `td`, não `th`. A posição da aula é validada no cabeçalho e não inferida de largura CSS. A tabela-resumo opcional não é usada para extrair frequência.

O marcador `data-report="synthetic-smecel-annual-v1"` e os atributos de turma/contagem são **apenas da demonstração**. O HTML real inspecionado não fornece ct, MAT ou contagem esperada de fichas. A leitura desse HTML real produz prévia `source_format="smecel-annual-v1"`, sempre bloqueada por `CLASS_ID_UNVERIFIED` e `ROSTER_COMPLETENESS_UNVERIFIED`. Uma futura captura autorizada precisará de envelope externo verificado com URL/turma e total esperado. Fechamento de tags e grade local íntegra não provam que toda a turma foi capturada.

Tokens são interpretados pela combinação de estrutura, símbolo, classe e legenda:

- `•`: `planned_unknown`, pois a legenda diz literalmente **Aula prevista/presença**. Não existe presença inequívoca nesse formato.
- `X` em `strong > span.ls-color-danger`: `absent`, falta não justificada.
- `strong > span.ls-color-warning.ls-ico-info`: `excused_absent`. A tradução desse estado para a API ainda precisa ser confirmada.
- `span.ls-ico-calendar`: `non_school_day`.
- `span.ls-ico-minus`: `outside_enrollment`.
- Células vazias, `&nbsp;` ou uma célula mensal totalmente vazia: `unmarked`. Não se infere o motivo ou uma falta.
- Qualquer outra marcação: `unknown`, preservada e bloqueada para envio. Ícones desconhecidos não desaparecem como células vazias.

A fixture inclui os estados acima, `?` desconhecido e marcação em 31/02 rejeitada por data inválida. Os testes geram em memória versões truncadas, duplicadas, adulteradas, com turma/ano divergentes e com calendário bissexto.

## Contrato Python

```python
from dataclasses import asdict
from coletor.parser import parse_annual_html
from coletor.validation import validate_for_transmission

snapshot = parse_annual_html(html, class_id="TESTE-A", year=2026)
json_ready = asdict(snapshot)
validation = validate_for_transmission(snapshot)  # Bloqueado sem vínculo validado pela API.
```

O snapshot contém `students`, `records`, `issues` e `summary`. `snapshot_id` é um SHA-256 determinístico do conteúdo normalizado; não contém timestamp. `source_student_ref` é uma referência à posição da ficha **nesta coleta**, não é durável, MAT ou studentUid. Nomes existem somente para visualização e nunca resolvem identidade. Dados de nascimento, responsáveis e matrícula são ignorados.

`MappingValidation` é um objeto de fronteira para um futuro adaptador autenticado. Não é verificação criptográfica e não pode ser aceito de JSON local ou de uma caixa de seleção da interface. O adaptador deverá verificar comprovante da API vinculado ao snapshot, turma, ano e todas as fichas. Não existe integração de rede neste módulo.

`build_safe_payload()` é uma função pura e não envia dados. Exige validação completa, falha com códigos sem nomes e retorna apenas upserts de estados explícitos suportados. Falta justificada tem um bloqueio adicional enquanto não há contrato de tradução da API. Não há exclusões, substituição de turma, faltas a partir de vazios ou deltas destrutivos. Uma captura parcial nunca autoriza remover registros existentes. O recibo falso utilizado por testes unitários não integra a aplicação.

## Verificação

```sh
PYTHONPATH=app python -m unittest discover -s tests -p test_parser.py -v
```

A implementação usa apenas a biblioteca padrão do Python. A validação foi feita com HTML sintético estruturalmente representativo; nenhum arquivo real de alunos foi baixado, persistido ou usado nos testes.

## Materialização

O HTML não é versionado. `python scripts/generate_fixture.py` o gera localmente
a partir de `app/coletor/demo.py`. A demonstração do aplicativo usa o mesmo
gerador em memória, sem gravar o HTML.
