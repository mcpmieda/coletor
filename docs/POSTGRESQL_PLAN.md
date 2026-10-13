# Frequência Smecel no PostgreSQL: plano econômico

Status: estudo de viabilidade, sem API, POST, migration, conexão ou alteração de banco.
A instrução do responsável em 10/10/2026 é preparar a base e **não enviar nada
ao PostgreSQL** antes de definir como a frequência aparecerá para os pais.
Portanto, o formato final de envio, a consulta do Portal e o schema não estão
congelados. Os nomes/estruturas abaixo são opções de desenho, não um contrato
implementado. O esclarecimento funcional do responsável, confirmado pela
inspeção somente leitura, governa o estudo: Smecel considera frequente por
padrão; contar faltas e excluir células sem aula.

## 1. Decisão recomendada

**Guardar faltas explícitas, calendário e elegibilidade da matrícula; derivar a
frequência conforme a convenção do Smecel somente dentro da cobertura validada.**
Não guardar uma presença por aluno/aula nem repetir o diário anual a cada coleta.
A escolha é um modelo esparso, com estados de cobertura separados dos fatos.

Para uma célula `(studentUid, turma de origem, data, posição 1–6)`:

1. Data civil inválida: não é célula acadêmica; gerar diagnóstico, nunca um fato.
2. Fora do escopo efetivamente capturado: `nao_coletado`.
3. Calendário não resolvido/conflitante: `calendario_pendente`.
4. Aula não letiva: `sem_aula`, excluída do denominador.
5. Fora da matrícula/elegibilidade da fonte: `fora_matricula`, excluída.
6. Aula futura/fora do corte de cálculo da origem: `prevista`, sem entrar no
   denominador. No dia corrente, preservar o corte usado pela fonte; não
   substituir silenciosamente por uma regra própria de aula encerrada.
7. Falta explícita válida: `falta` ou `falta_justificada`, preservando a distinção.
8. Demais células elegíveis cobertas: `frequente_no_smecel`, derivado da regra
   da origem, **não uma declaração de chamada concluída pelo professor**.

A ausência de uma linha de falta somente tem o significado do item 8 depois
dessas guardas. Uma falha do coletor jamais vira presença. O símbolo `•` pode
continuar preservado pelo parser como `planned_unknown`: o adaptador de domínio
aplica a convenção acima; não precisa adulterar o significado bruto extraído.

A inspeção do consolidado confirmou: falta justificada é uma exceção que não
reduz a frequência nativa. Fórmula observada: `100 × (elegíveis − faltas não
justificadas) / elegíveis`. Com zero elegíveis, resultado é sem aulas, não 100%.
Aulas previstas no calendário anual inteiro não são o denominador transcorrido.
Precisam ser definidos com a tela dos pais: corte do dia atual, precisão de
arredondamento, total por dia ou por aula e necessidade de resumo por componente.
Não inventar regra de aprovação/reprovação por frequência nem alterar o motor
acadêmico existente.

## 2. O que foi confirmado no código real

Inspeção somente leitura de `mcpmieda/ecossistema-escola`, commit
`e9f5eb576b242fc9018881fd56bcc638ff1e91e5` (10/10/2026). A cópia local foi usada
para localizar código; contratos decisivos foram conferidos no conector GitHub.
Código e documentação não são uma inspeção do catálogo produtivo nesta tarefa.

- [Identidade compartilhada](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/docs/student-identity/README.md):
  `gradebook.student_identity(id uuid)` é a identidade durável, sem PII duplicada.
  `gradebook.aluno(id integer, ano smallint, student_uid uuid)` é o registro
  acadêmico anual. `student_portal.account.id` é a conta, não necessariamente
  igual a `studentUid`. Não alocar/reassociar UUIDs com este coletor.
- [Contrato](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/shared/student-identity/student-identity-v1.ts) e
  [leitor](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/server/student-identity/resolve-student-identity-v1.ts):
  usar `resolveStudentIdentitiesV1` depois de autorizar ano/alunos. Aceita até
  500 referências por chamada; UUID canônico em minúsculas, sem impor versão
  RFC. Um UID conhecido não autoriza consulta nem escrita.
- [Schema acadêmico](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/migrations/gradebook-simplified/0001_current_schema.sql):
  o vínculo real é `gradebook.vinculo(ano,turma_id,numero,aluno_id,situacao)`.
  `numero` é chamada. Não existe nesses contratos uma coluna de MAT que permita
  supor uma ligação automática com o HTML do Smecel.
- [Persistência oficial](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/docs/gradebook/STORAGE_RUNTIME_MAP.md):
  Pages/Worker → Hyperdrive `PROD_DB` → PostgreSQL/Supabase; aproveitar
  `withOfficialGradebookDatabaseV1` e as portas nativas existentes, com SQL
  parametrizado `$n`. Não criar SQL arbitrário enviado pelo PC nem reativar D1.
- [Portal](https://github.com/mcpmieda/ecossistema-escola/blob/e9f5eb576b242fc9018881fd56bcc638ff1e91e5/server/student-portal/composition/self-v1.ts):
  já possui sessão, `withAuthorized`, regras de acesso e publicação. Frequência
  deve entrar por um contrato estreito próprio, sem contornar essas guardas.

A inspeção do relatório de origem identificou grade anual FEV–DEZ, dias 1–31,
seis posições e 32 fichas na amostra. Isso não comprova 32 alunos por turma,
MAT, identidade estável, todas as turmas ou aulas realizadas. O cadastro
informado tem 18 turmas, 15 regulares e cerca de 353 ativos; ativos atuais não
são a população histórica exata do ano e podem ter vínculos simultâneos.

### Evidência adicional da frequência nativa (somente leitura)

O aprofundamento no navegador da origem em 10/10/2026, entre 00:07 e 00:12
UTC, verificou o corte de 09/10/2026 no
[calendário](https://www.smecel.com.br/sistema/escola/calendario_escolar.php),
[consolidado](https://www.smecel.com.br/sistema/escola/vinculoAlunoFrequencia.php?ano=2026&ct=13331) e
[diário](https://www.smecel.com.br/sistema/escola/diario_frequencia.php?ct=13331&ano=2026)
autenticados, sem modificar registros:

- Células elegíveis são a soma das marcas `•`, faltas `X` e justificadas. Uma
  conferência aritmética não identificada teve 928 + 36 + 8 = 972; o total de
  faltas exibido foi 36, excluindo as oito justificadas.
- Uma conferência de cinco faltas em 972 aulas resultou em 99,5% no consolidado.
  O relatório de período apresentou 99%, enquanto 36/972 apareceu como 96%.
  Há diferença de apresentação/arredondamento; não codificar precisão única
  antes de escolher o que a família verá.
- O calendário escolar padrão de 2026 mostrou 206 dias anuais, sendo 188
  normais e 18 sábados. No corte observado, 162 dias × seis posições = 972.
  O rodapé anual 206 não substitui o denominador de 972 aulas transcorridas.
- Outubro tinha 42 aulas previstas no corte (sete dias). Novembro futuro tinha
  zero/zero, “Sem aulas”. No HTML, futuro podia ser `td` vazio sem `div`; finais
  de semana e posições inválidas passadas tinham `div` vazios. Não colapsar
  essas estruturas em uma mesma presença padrão.
- Não letivo: ícone `ls-ico-calendar`; fora da matrícula: `ls-ico-minus`;
  falta: `X`/`ls-color-danger`; justificada: `ls-color-warning ls-ico-info`.
  Esses são sinais observados de versão da origem, não seletores eternos.

- Eventos não significam automaticamente dia sem aula: Show de Talentos e
  Jogos da Independência tinham seis posições elegíveis; sábados letivos também.
  Um sábado comum e domingo estavam vazios; feriado tinha seis ícones não
  letivos. O início geral em 19/02 incluía recesso; as aulas começavam em 23/02.
  Usar classificação nativa por data, não apenas segunda–sexta, intervalo do
  cabeçalho ou título de evento.
- Fora de matrícula foi observado visualmente, mas a amostra não permitiu
  comprovar o denominador em ingresso tardio/transferência. Esses dois casos
  continuam pendentes. Nunca promover um bloqueio individual de matrícula
  para uma regra de calendário da turma.

Essas verificações explicam a fórmula da fonte; não provam todos os alunos,
turnos, turmas ou o momento em que cada professor conclui lançamentos. O estudo
não testou remoções editando dados. A captura no fim da aula ainda precisa
registrar o corte e a atualidade, pois uma falta pode ser lançada depois.

## 3. Identidade, transferências e escopo

- O servidor mantém uma ligação verificada entre a chave durável da origem
  (no namespace escola/ano) e o `studentUid` já existente. Usar MAT somente se
  vier de uma fonte confiável com correspondência comprovada. Nunca nome,
  posição da ficha, número de chamada ou um hash de nome como identidade.
- O HTML atual sozinho não permite estabelecer essa ligação. `source_student_ref`
  local identifica apenas uma ficha daquele snapshot. Uma ligação assistida
  deve produzir recibo validado no servidor para aquele documento/escopo; não
  pode ser transportada para o próximo arquivo como se fosse chave durável.
- O DDL ilustrativo abaixo representa a via de chave durável. A via de recibo
  por snapshot, se necessária, precisa de contrato próprio antes da ativação.
- Referências ao aluno/turma anual são apenas atalhos atuais e podem ficar
  nulas após o reset. A FK durável aponta para `gradebook.student_identity`.
  Uma matrícula nova não pode reutilizar UID por decisão do coletor.
- A chave de uma falta contém também a turma de origem. Transferência preserva
  os fatos anteriores; nunca reatribui todo o histórico à turma atual.
  Sobreposição de duas turmas no mesmo horário não deve ser somada silenciosamente.
- Guardar intervalos de elegibilidade **evidenciados pela fonte**, inclusive
  limites de aula quando uma fronteira corta o dia. Não deduzir datas de entrada
  ou saída a partir da lista de alunos ativos hoje. Vínculo atual não prova
  elegibilidade histórica.
- Cobertura identifica turma, datas, seis posições, conjunto exato de alunos,
  revisão do roster, parser, legenda e calendário. Contagem igual sozinha não
  prova identidade/completude. As 15 turmas regulares não tornam as outras três
  implicitamente excluídas: o escopo operacional é decidido pelo responsável.

## 4. Comparação quantitativa

Hipóteses de dimensionamento, **não medição de produção nem preço**: 353 pessoas
com um vínculo cada; 200 dias letivos; seis aulas por dia; sem transferências.
Para o calendário civil do relatório de 2026, FEV–DEZ tem 334 dias válidos;
`11 × 31 = 341` posições visuais incluem sete datas inexistentes.

| Modelo | Linhas-base com 200 dias | Preservar os 334 dias válidos | Observação |
|---|---:|---:|---|
| Aluno/data/aula | 423.600 | 707.412 | Consultas simples, repete chaves/proveniência seis vezes |
| Aluno/data, seis `smallint` | 70.600 | 117.902 | Boa alternativa legível; seis colunas somam 12 bytes de estados |
| Esparso: somente faltas, taxa de 5% | 21.180 | Mesma conta se faltas só nos dias letivos | Mais calendário, matrícula e cobertura |
| Esparso: taxa de 10% | 42.360 | Idem | Candidato recomendado para a regra Smecel |
| Esparso: taxa de 20% | 84.720 | Idem | Pode ocupar mais que o modelo diário |

As taxas hipotéticas acima contam os dois tipos de exceção armazenada,
justificada e não justificada; só a não justificada penaliza a fórmula observada.

O limiar bruto entre faltas por aula e uma linha diária é perto de 16,7% de
faltas, antes dos metadados e da diferença de tamanho das linhas. Não assumir
que a taxa real está abaixo disso. O modelo esparso é escolhido pela semântica
e simplicidade das alterações; medir antes de alegar economia exata.

Estimativa grosseira de **160–240 bytes por linha de fato incluindo índices
mínimos** (não os bytes reais de um `smallint`):

- Por aula, 423.600 linhas: aproximadamente 67,8–101,7 MB.
- Por dia, 70.600 linhas: aproximadamente 11,3–16,9 MB.
- Por dia, 117.902 linhas: aproximadamente 18,9–28,3 MB.
- Só faltas a 5%: 3,4–5,1 MB; a 10%: 6,8–10,2 MB; a 20%: 13,6–20,3 MB.
- Calendário de 15 turmas × 334 dias: até 5.010 linhas compartilhadas, em vez
  de 117.902 calendários por aluno. Com 18 turmas, até 6.012 linhas.
- Um intervalo por aluno/turma seria cerca de 353 linhas; transferências,
  buracos e limites parciais aumentam esse número.
- Cobertura mensal estável: 165–198 cabeçalhos e aproximadamente 3.883 ligações
  aluno/mês (353 × 11), antes de alterações de roster. Estimar 1–3 MB adicionais
  para esse conjunto de metadados como ordem de grandeza, não capacidade garantida.

Valores em MB decimais. Excluem WAL, backups, réplicas, bloat, históricos e
cadastros já existentes. Headers, alinhamento e índices dominam; o PostgreSQL
não armazena uma linha de falta em apenas dois bytes. A medição futura é por
`pg_total_relation_size`, `pg_indexes_size` e planos reais de consulta.

Uma hipótese de 1.412 correções (2% de 70.600 aluno-dias), cada uma gerando
200–400 bytes de auditoria, acrescentaria 0,28–0,56 MB; uma correção com várias
células pode gerar mais eventos. Auditoria cresce com **alterações**, não com
a quantidade de coletas idênticas.

## 5. A maior economia está em não reenviar/regravar o ano

Assumindo seis encerramentos por dia e 200 dias: 18.000 coletas de turma/ano
para 15 turmas, ou 21.600 para 18. Com um HTML hipotético de 1 MB por turma,
o tráfego Smecel → líder seria 18–21,6 GB/ano. Se N computadores coletassem
independentemente, esse tráfego seria multiplicado por N. O desenho mantém um
coletor ativo por vez e os demais computadores autorizados como reservas,
sem fixar a quantidade de usuários ou dispositivos.

Uma medida real do HTML amostral foi **6.653.368 bytes UTF-8**, 32 fichas e 60
tabelas; conteúdo real não foi exportado para este repositório. Se todo relatório
tivesse esse tamanho, seriam aproximadamente 119,8–143,7 GB/ano para 15–18
turmas com um líder. É extrapolação da amostra, não medição da escola inteira;
tamanho HTTP comprimido pode ser bem menor que UTF-8 bruto.

O lease evita a multiplicação pelos computadores autorizados. Hash local **não evita baixar o
HTML de novo** quando a origem não oferece uma leitura incremental confiável.
Se o relatório anual já vem completo, compará-lo localmente detecta também
correções antigas, sem mais chamadas ao Smecel.

PC → API:

1. Parsear e normalizar no PC. Hash SHA-256 por turma/mês e conjunto exato de
   alunos; incluir calendário, elegibilidade, faltas e versões de interpretação.
   Excluir horário de captura, espaços HTML, CSS, nomes, scripts e ordem visual.
2. Enviar um manifesto pequeno com hashes, escopo e recibo de captura; somente
   diferenças confirmadas pela API precisam do corpo. O servidor recalcula o
   hash do corpo recebido; não confia em contadores/flags enviados pelo cliente.
3. Sem mudança, atualizar a atualidade do escopo em uma operação pequena, sem
   tocar em todas as faltas, alunos ou datas e sem incrementar revisão acadêmica.
4. Com mudança, enviar as faltas/calendário/intervalos alterados, incluindo
   remoções explícitas com revisão esperada. Nunca ausência por omissão.

Exemplo apenas aritmético: manifesto de 800 bytes com 11 hashes para cada uma
das 21.600 coletas = 17,28 MB/ano, antes de TLS/respostas/retries. Se cada alteração
normalizada custar 160 bytes, 42.360 faltas novas custariam 6,78 MB, além de
calendário, matrícula, remoções e baseline. Não é promessa de tráfego real.

Uma API por célula gastaria até 423.600 chamadas para a baseline letiva.
Usar lotes por turma/período e SQL set-based, nunca uma ida ao banco por célula.
Começar com limites de engenharia de 1 MiB descompactado e 5.000 mutações por
lote, medidos e ajustáveis; isso não é limite de população nem piloto. Divisão
por mês deve manter revisão/manifesto para não anunciar o ano completo antes
que todos os blocos necessários tenham sido aceitos.

## 6. Opção de fluxo futuro PC → API (não contratada nem implementada)

A decisão de formato aguarda a visão para os pais. Abaixo estão somente as
garantias que qualquer formato escolhido deve conservar. Reusar
autenticação/autorizações do Ecossistema. Registro persistente de
máquina, credenciais e permissões exigem sua aprovação própria. PC não recebe
connection string, credencial Supabase nem permissão para fornecer SQL.

- `POST /api/attendance/lease`: adquirir/renovar lease da escola/ano. Retorna
  dono, validade pelo relógio servidor e fencing token monotônico.
- `POST /api/attendance/captures`: abre captura autorizada para escopo e
  entrega ticket curto, sequência e revisão-base. Não pode ser inventado no PC.
- `POST /api/attendance/manifests`: recebe hashes/versões e informa blocos
  necessários ou confirma estado inalterado dentro da cobertura comprovada.
- `POST /api/attendance/batches`: comandos tipados, não SQL, com `requestId`,
  `deviceId`, ticket, fence, revisão-base, turma/ano, `capturedAt`, hash da fonte,
  `parserVersion`, `legendVersion`, revisão de roster e descritores de cobertura.
- Comandos: `setAbsence`, `removeAbsence`, `replaceCalendarDays`,
  `replaceEligibilityWithinScope`. Toda remoção/redução tem estado/revisão
  esperada e motivo técnico de reconciliação; não é um `DELETE` genérico.
- `GET /api/attendance/receipts/{requestId}`: reconcilia uma resposta incerta,
  autorizado para o dispositivo/escopo; não expõe outros alunos ou dispositivos.

`setAbsence` contém UID previamente resolvido, turma autorizada, data, posição
1–6, tipo (não justificada/justificada) e referência da evidência. Nenhum nome,
nascimento, filiação, cookie, senha, HTML completo ou URL com tokens no payload.
Uma correção de fonte normal é aplicável pelo contrato aprovado de sincronização;
uma reidentificação humana ou exceção de autorização é outro fluxo.

Resposta: `requestId`, resultado `committed/unchanged/conflict/rejected`, revisão
resultante, contagens, `receivedAt`, escopo aceito, lacunas e horário da próxima
coleta prevista. Erros de DB não se convertem em ausência de aluno/falta.

### Transação e concorrência

1. Validar identidade do dispositivo/operador, limites, schema estrito, escopo,
   autorização, associação UID e versões antes de trabalho caro.
2. Consultar recibo existente pela chave idempotente. Mesmo pedido/hash retorna
   o mesmo resultado; mesma chave com corpo diferente é conflito. Uma repetição
   já confirmada pode retornar recibo mesmo com lease agora vencido, sem escrever.
3. Para pedido novo: tomar lock do lease, conferir dono/fence/expiração usando
   relógio do banco; conferir ticket/ordem de captura e revisão-base. Lock é da
   transação curta, nunca mantido enquanto o PC baixa o Smecel.
4. Nova posse incrementa fence; renovação da mesma posse conserva fence. PC
   antigo, snapshot offline atrasado ou sequência anterior não sobrescreve novo
   estado, mesmo que seu relógio local diga que a captura é mais recente.
5. Comparar conjuntos do roster e blocos, calendário, matrículas e duplicatas.
   Não confiar em `complete:true`. Uma marca de não letivo em uma única ficha
   não altera o calendário da turma se outras fichas entram em conflito.
6. Aplicar SQL fixo parametrizado em lote e `ON CONFLICT ... DO UPDATE ... WHERE`
   somente quando valores diferirem. `DO NOTHING`/sem mudança não gera trilha
   repetida. Bloquear conflito com dado mais novo; a ordem de chegada não é
   automaticamente a ordem da origem.
7. Remover falta apenas por `removeAbsence` explícito, dentro de escopo completo
   revalidado e com a revisão anterior esperada. Preservar antes/depois na
   auditoria. Falha de captura ou aluno ausente do roster não autoriza remoção.
8. Persistir alterações, auditoria, revisão e recibo na mesma transação; commit
   vem antes do ACK. Retry reutiliza chave/corpo e primeiro reconcilia resultado.

Serializar a ingestão por turma e adquirir locks sempre na mesma ordem.
Respeitar o protocolo existente de reset/ano do Ecossistema quando resolver
referências acadêmicas; não criar uma segunda ordem de locks concorrente.
Não usar um relógio do Windows como fonte da validade do lease.

## 7. Cobertura, horários e correções

- Um bloco é um retângulo definido de alunos identificados × datas civis
  contíguas × seis posições. Um mês inteiro por turma é o caso simples.
  Lacunas ou alunos faltantes dividem o escopo aceito; jamais são preenchidos
  como frequentes. Um dia malformado não apaga fatos já armazenados.
- `last_attempt_at`: tentativa, inclusive com erro.
- `last_observed_at`: instante informado da leitura da origem, com origem de
  relógio explícita; não significa validação nem lançamento docente.
- `last_validated_at`: aceite técnico pelo servidor daquele exato escopo.
- `source_confirmed_at`: só se a origem oferecer confirmação acadêmica explícita
  confiável; fica nulo quando não oferece. Não preencher com o horário do scrape.
- Fatos apontam para o lote que os mudou. A atualidade de fatos inalterados é
  obtida pela cobertura validada do escopo, sem regravar todas as linhas.
- Intervalos de matrícula e calendário são reconstruídos só no escopo coberto;
  substituir um bloco parcial não remove intervalos fora dele.
- Correção de dia letivo para não letivo retira suas aulas do cálculo e preserva
  a alteração de calendário; faltas antigas ficam rastreáveis e não são apagadas
  automaticamente como consequência de uma classificação nova.
- Remoção de falta validada volta ao estado derivado pela convenção Smecel,
  mantendo a trilha. Diferenciar esse caso de `•` futuro, matrícula encerrada
  ou calendário ainda não conhecido.
- A agenda local pedida pelo responsável permite horários e dias da semana
  configuráveis, além de Coletar agora/Pausar. Na janela configurada, abrir a
  sessão, verificar login, coletar e fechar; retries sem concorrência. Dias da
  semana habilitados são apenas agenda operacional: sábado letivo/calendário
  continuam sendo a autoridade para a conta. Coleta no fim de cada aula usa
  fuso IANA da escola e os horários escolhidos; ainda não estão confirmados.
  Não substituir essa agenda por polling fixo a cada N minutos. PCs de reserva usam backoff/jitter e consultam o lease perto
  da janela de trabalho; os computadores de reserva não precisam repetir a captura.
- Se for adotado relatório de janela curta, reconciliar histórico em cadência
  definida por custo/atraso aceitável (por exemplo, ano completo semanal e ao
  fechamento). Se a mesma resposta já é anual, não acrescentar fetch histórico.
- Não mapear componente curricular pela posição de aula. O resumo opcional por
  componente é agregado da origem, em estrutura separada, com período/evidência;
  não serve para fabricar o componente de cada célula.

## 8. Leitura possível do Portal e índices mínimos

A apresentação para pais/responsáveis ainda não foi decidida. O Portal atual
é um ponto de integração a estudar; não supor que sua conta de aluno já
representa autorização de um responsável. Uma futura conta de responsável
precisa de vínculo autorizado com os filhos. O UID vem do contexto autorizado
no servidor, nunca somente da escolha do cliente. O aluno não escolhe um UID
livre por query string. Validar vigência da sessão, acesso, ano, escopo de
publicação e vínculos antes de consultar os fatos; preservar guardas atuais.
Conta encerrada ou posse do UUID não concede acesso histórico automaticamente.

Consulta por aluno/período: faltas do UID no intervalo, calendário das turmas
relevantes, intervalos de elegibilidade e blocos de cobertura que incluam esse
UID. Derivar estados e totais apenas na interseção. Para totais, operar sobre
os no máximo 6 × dias do período desse aluno, não sobre a escola inteira.
Resultado com lacunas deve distinguir total conhecido de total completo.

Índices iniciais:

- Falta: PK `(student_uid, school_date, source_class_id, lesson)` atende Portal
  e idempotência por célula. Um índice `(source_class_id, school_date)` atende
  reconciliação de turma/período. Não indexar tipo de falta isoladamente.
- Calendário: PK `(source_class_id, school_date)`; seis booleans anuláveis
  legíveis, sem bitmask opaca.
- Intervalos: B-tree `(student_uid, source_class_id, starts_on)` é suficiente
  na ordem de centenas/milhares de intervalos. Não exigir GiST/partições agora.
- Cobertura: membro `(student_uid, scope_id)` para localizar blocos; chave
  única de definição impede cabeçalhos duplicados. Um conjunto de membros é
  gravado só quando muda, não a cada coleta.
- Recibo: UNIQUE `(device_id, request_id)` e índice temporal para retenção
  apenas se necessário na implementação. Histórico: chave por lote/ordinal.

Sem índice GIN em JSON, índice em cada coluna, tabela de totais permanente,
particionamento mensal, Timescale ou novo serviço de fila por padrão.

A documentação atual do Hyperdrive informa que o cache de SELECT não é
invalidado por uma escrita. Lease, sessão, autorização, revisão-base e consulta
imediata de recibo precisam de leitura garantidamente fresca no caminho já
aprovado. Conferir a configuração efetiva antes de implementar; não alterar
infraestrutura aqui nem usar comentários SQL como controle de cache.
Respostas do Portal são privadas; não usar cache público/CDN compartilhado de
frequência de alunos. Reutilizar mecanismos oficiais de revisão/publicação
quando o contrato for aprovado, sem uma notificação por célula.

## 9. Decisões da visão para pais antes de congelar o envio

1. Mostrar apenas total/percentual, dias com falta, ou detalhe de cada aula?
2. Exibir justificadas separadamente? A recomendação é preservar a distinção
   da fonte, mesmo se a primeira tela não mostrar o detalhe.
3. Mostrar disciplina? O diário não atribui componente a cada posição; um
   resumo agregado da fonte não resolve esse vínculo automaticamente.
4. Qual corte/atualidade e qual arredondamento a família verá? Mostrar “última
   atualização” e lacunas evita tratar coleta técnica como chamada concluída.
5. Como autorizar cada responsável e tratar transferência/ano anterior?

Essas decisões podem justificar enviar somente agregados, faltas detalhadas
ou ambos. A base local pode preservar informação fiel para permitir a decisão;
não há autorização para iniciar envio ou persistência produtiva por antecipação.

## 10. Auditoria, retenção e verificação

Recomendação operacional, **não política legal aprovada nem job implementado**:

- HTML bruto: memória do PC por padrão. Não arquivar no PostgreSQL nem em Git.
  Se diagnóstico exigir arquivo, autorização, criptografia e prazo curto
  específico; nenhum dado real em fixtures, logs, issues ou screenshots.
- Recibos de tentativas inalteradas: janela candidata de 30 dias, suficiente
  somente se maior que a janela máxima permitida de retry offline. Após expirar,
  um ticket antigo não pode ser reenviado como novo para contornar idempotência.
- Lotes referidos por fatos, cobertura vigente ou auditoria: conservar; limpeza
  de recibos não pode quebrar proveniência. Logs técnicos sanitizados: 14–30 dias
  como proposta, agregados sem identificação por mais tempo se úteis.
- Faltas, calendário, matrícula e correções: manter conforme a política
  institucional aplicável; não inventar prazo legal nem apagar ao fechar o ano.
  Definir arquivamento e impacto de backup antes de qualquer expurgo.
- Métricas agregadas: bytes origem/API, duração de parse/Worker/SQL, nº de
  alterações, nº de lotes idênticos, cobertura e atraso por turma. Nunca nome,
  nascimento, matrícula, token ou payload de aluno em telemetria.

O arquivo `POSTGRESQL_DDL_PROPOSAL.sql.txt` é ilustrativo e intencionalmente
não é uma migration executável. Falta especificar os papéis/ACL do runtime,
a ligação Smecel confiável e as regras da origem antes de uma migration real.

Validação técnica futura, proporcional: testes focados para fim de mês/ano
bissexto; fonte parcial; transferido; falta justificada; remoção retroativa;
UID não autorizado; replay idempotente; dois líderes; fence antigo; relógio
adiantado; rollback e resposta perdida; calendário corrigido. Medir consultas
com dados sintéticos pequenos e os gates já existentes. Não exigir ensaio
amplo em produção nem criar turma piloto/bloqueio artificial para concluir
este desenho. A ativação e a validação real são decisões separadas.

## 11. Referências técnicas primárias

Consultadas em 10/10/2026; versão efetiva do PostgreSQL de produção não foi
consultada e deve ser conferida antes da migration.

- [PostgreSQL: layout de páginas e linhas](https://www.postgresql.org/docs/current/storage-page-layout.html)
- [PostgreSQL: tipos numéricos](https://www.postgresql.org/docs/current/datatype-numeric.html)
- [PostgreSQL: INSERT / ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- [PostgreSQL: locks explícitos](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL: tamanho de relações e índices](https://www.postgresql.org/docs/current/functions-admin.html)
- [PostgreSQL: Row-Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Supabase: proteger a Data API](https://supabase.com/docs/guides/api/securing-your-api)
- [Supabase: changelog](https://supabase.com/changelog) (a versão `.md` não foi
  legível pela ferramenta; conferida a página HTML)
- [Cloudflare Hyperdrive: cache e read-after-write](https://developers.cloudflare.com/hyperdrive/concepts/query-caching/)
