# Smecel: regras observadas para frequência esparsa

Pesquisa somente leitura no navegador em nuvem. Leitura aprofundada em 10/10/2026, aproximadamente 00:06–00:22 UTC. Documento sanitizado: não contém nomes, matrículas, hashes pessoais, fotos, filiação, motivos médicos nem HTML real de alunos.

## Resultado

O modelo compatível com a origem é uma matriz de posições elegíveis da turma, exceções de falta, exceções justificadas, limites de vínculo e cobertura da captura. A presença pode ser derivada da convenção Smecel, mas não representa prova independente de chamada realizada.

O diário coletivo é a fonte principal para o calendário observado. O individual não pode ser usado para descobrir dias elegíveis: na mesma ficha ele mostrou seis pontos em 31/02/2026, sábado comum e feriado; o coletivo tratou essas células corretamente. A célula 31/02 foi confirmada por rótulo de linha, cabeçalho, alinhamento DOM, colspan 1 e imagem recortada da grade, sem erro de deslocamento do parser.

## Fontes nativas verificadas

- Pedagógico > Diários de Classe > Frequência: https://www.smecel.com.br/sistema/escola/diarios_preenchidos.php
- Diário coletivo de uma turma: https://www.smecel.com.br/sistema/escola/diario_frequencia.php?ct=13331&ano=2026
- Frequência consolidada: https://www.smecel.com.br/sistema/escola/vinculoAlunoFrequencia.php?ano=2026&ct=13331
- Turmas > Turmas Escolarização > Relatórios > Registro de frequência (por período): https://www.smecel.com.br/sistema/escola/print_frequencia_periodo.php?inicio=2026-01-01&fim=2026-12-31&ct=13331&ano=2026
- Administração > Calendário Escolar: https://www.smecel.com.br/sistema/escola/calendario_escolar.php
- Segundo coletivo, usado apenas para verificar um caso transferido: https://www.smecel.com.br/sistema/escola/diario_frequencia.php?ct=13334&ano=2026

Os parâmetros ct identificam turmas, não alunos. Links dependem da sessão e das permissões do usuário. URLs individuais não são incluídas por conterem identificadores pessoais.

## Estados nativos do coletivo

| Marca e estrutura do slot | Significado observado | Tratamento |
|---|---|---|
| Texto • em DIV direto da célula | Aula prevista/presença, conforme legenda | Posição elegível; presença derivada se não há falta |
| DIV > strong > span.ls-color-danger com X | Falta | Exceção de falta não justificada |
| DIV > strong > span.ls-color-warning.ls-ico-info | Falta justificada | Exceção separada, sem motivo clínico |
| DIV > span.ls-ico-calendar | Dia não letivo | Bloquear posição |
| DIV > span.ls-ico-minus | Fora do período de matrícula | Bloquear posição para o vínculo |
| DIV vazio ou espaço não separável | Vazio | Não converter em presença |
| TD sem filhos de posição | Sem posições disponíveis na apresentação | Não converter em presença; pode ser futuro ou após saída |

Não usar somente cor, classe calendar-day-disabled, rótulo de evento, intervalo de início/fim, dia da semana ou ausência de X para concluir elegibilidade. Validar datas reais antes de interpretar células. O número de posições deve vir da linha Aulas, não ser fixado em seis para toda escola.

## Conciliações concretas

1. Na turma principal, o coletivo tem 972 posições elegíveis no corte observado até 09/10/2026. O consolidado mostra 5 faltas em 972 aulas previstas e 99,5% na mesma amostra. O valor exato é 100 × (972 − 5) / 972. A apresentação do relatório por período exibe o percentual inteiro (99%).
2. Outra amostra tem 928 pontos + 36 X + 8 justificadas = 972 posições elegíveis. O total mensal somado e o total anual de faltas são 36, excluindo as oito justificadas. A legenda anual explicita exclusão das justificadas.
3. Outubro parcial: 42 aulas previstas, zero faltas, 100%. Novembro futuro: zero aulas, zero faltas, percentual vazio e estado Sem aulas. Não projetar o denominador de todo o ano na frequência acumulada atual.
4. O calendário selecionado Padrao 2026 (PADRÃO) tem 206 dias letivos no ano, dos quais 18 são sábados. Até o corte observado, são 162 dias elegíveis × 6 = 972 posições. O relatório anual por período pode mostrar 206 dias no rodapé enquanto a frequência usa cobertura já transcorrida.
5. Exemplos sem dados pessoais: 19/02 marcado não letivo/recesso; 23/02 primeiro dia de aula observado; 28/02 sábado letivo; 08/08 sábado comum vazio; 15/08 e 12/09 sábados letivos; 07/09 feriado bloqueado; 13/09 domingo vazio. Eventos de 14/08 e 04/09 continuam elegíveis. O cabeçalho geral que inicia em 19/02 não substitui a máscara diária.
6. A turma principal tem seis pontos em 05/10 (segunda), 07/10 (quarta) e 09/10 (sexta), inclusive sexta posição. A planilha de horário analisada por outro estudo indica cinco aulas nesses dias e seis às terças/quintas, com vigência ainda a reconciliar. Registrar divergência entre fontes; não reduzir a matriz Smecel nem excluir faltas automaticamente com base na planilha.
7. Um caso transferido aparece uma vez entre as 35 fichas do segundo coletivo. Todas as 136 datas válidas após a data de saída cadastrada estão vazias e sem posições; sete células de datas inexistentes foram excluídas da verificação. Antes/na saída há 673 pontos, 54 X, 5 justificadas, 192 posições não letivas, 6 fora do vínculo e 252 vazias. Posições elegíveis observadas: 732. Não foi feita nova consulta ao consolidado dessa amostra, portanto não se afirma conciliação do seu denominador oficial.

## Estrutura e cobertura do HTML coletivo

- Uma ficha por DIV direto em .container-fluid, com estilo page-break-inside: avoid, sem identificador pessoal estável no wrapper.
- Cabeçalho de dados pessoais em div.ls-box1: não persistir campos desnecessários. Texto de turma não é chave ct.
- Grade table.ls-sm-space.bordasimples. Cabeçalho usa TD: Meses, FEV/2026 etc. Linha Aulas define posições. Linhas 1–31 cruzam dia e mês. Última linha FALTAS resume cada mês.
- Fichas podem ter segunda tabela COMPONENTE / TOTAL DE FALTAS. Não presumir duas tabelas por aluno.
- Legenda junto à grade e total anual EXCETO AS JUSTIFICADAS.
- Não há ct, hash de vínculo, matrícula ou contagem esperada de fichas no HTML isolado que comprove proveniência/completude. A URL e um envelope de captura precisam registrar escola autorizada, ano, turma, instante, versão do parser, contagem observada e escopo. Conciliar com relação de turma quando houver fonte autorizada confiável.
- Captura observada da turma principal: 32 fichas, 6.593.663 caracteres e 6.653.368 bytes UTF-8. Um limite de 8 MiB deixa pouca margem; isso é tamanho de uma amostra, não máximo universal.
- Não prometer cobertura integral da escola. Foram identificadas 18 turmas na lista acessível, sem comando único de diário detalhado para todas. Não foi feito lote da escola inteira.
- Impressão nativa do navegador estava desabilitada na sessão. Verificado HTML pronto para impressão, não um PDF gerado.

## Regras recomendadas para preparação local

1. Guardar exceções X e justificadas; guardar calendário elegível por turma/posição, cortes de vínculo e evidência de cobertura. Evitar materializar presença por aluno/slot como registro primário.
2. Derivar presença somente quando data real, posição elegível, vínculo aplicável e captura cobrindo o escopo. Rotular como presença derivada da convenção da origem, sem alegar chamada confirmada.
3. Não transformar futuro, célula vazia, fora do vínculo ou não letivo em presença. Não tratar ausência de ficha como zero faltas.
4. Para correções futuras, reconciliar snapshots completos do mesmo escopo, preservando histórico/versionamento. A remoção de uma falta não foi testada por mutação e não deve ser assumida a partir de captura parcial.
5. Antes de envio ou publicação, validar identidade e completude externas ao HTML. Este estudo prepara regras; não autoriza envio ao PostgreSQL, POST, integração, compartilhamento com responsáveis ou alteração no Smecel.

## Limites de conclusão

Conciliação detalhada de uma turma principal e de um único caso transferido. Não auditados: todas as turmas, regras de todos os segmentos, ingresso tardio que reduza denominador durante período letivo, todas as modalidades de transferência, calendário histórico alterado, toda combinação de carga horária e correções de falta. A pesquisa não prova comportamento universal. A planilha externa e o calendário Smecel devem manter suas próprias fontes e vigências até reconciliação explícita.
