# Verificação do primeiro marco

## Executado localmente

- Python 3.12: parser, validação, calendário, ambiguidades, identidade e serviços
  locais e contraste da UI: 44 testes passando após correções de volume identificadas em revisão parcial.
- UI: 33 testes de labels, adaptador, erros e configuração de agenda passaram.
- TypeScript estrito e build Vite: passaram.
- Fixtures: geradas, três alunos sintéticos; nenhuma exportação real versionada.
- Código do launcher Windows e contrato pywebview: inspecionados/compilados,
  mas não executados em Windows neste ambiente.

## Verificação visual e de interação

O navegador da nuvem não alcançou o loopback do executor (connection refused).
O Chromium no executor foi impedido de iniciar por restrição de socket do sandbox,
mesmo após tentativa suportada de execução com revisão. Nenhuma restrição foi
alterada. O script `scripts/check_ui.py` está preparado para o CI Linux com fixtures
sintéticas. Primeira execução remota confirmou carga, demo, filtros, paginação, tema escuro, navegação, limpeza e importação. Detectou overflow horizontal em viewport 390px; a correção de min-width/grid passou na segunda execução. Screenshots dessa execução foram baixados e inspecionados, sem dados reais.

O CI completo passou em 05d9621132894f4483ff155f74047b3bc580d71c:
https://github.com/mcpmieda/coletor-frequencia-smecel/actions/runs/38007936337.

Não afirmar equivalência pixel a pixel ao Atualizador nem QA nativo Windows.
A referência visual é o código de UI do Atualizador 1.3.0, e não um novo conceito
raster: foram preservados HeroUI v3, fonte Segoe UI, barra lateral de 256px, controles e
navegação correspondentes. A marca mudou para vermelho/bordô por pedido explícito.
A tela funcional foi adaptada ao diário; não contém estados de sincronização falsos.

## Limitações importantes

- Parser nativo usa contrato estrutural sanitizado observado na origem, mas não
  foi executado sobre dados reais no repositório. Piloto autorizado segue pendente.
- HTML isolado não prova `ct`, roster completo ou MAT; envio permanece bloqueado.
- Nenhuma coleta autenticada, credencial, dispositivo, API, banco ou portal conectado.
- Interface importa em memória; não há instalador, tray, execução agendada ou failover. A agenda editável é uma prévia local.

## Inspeção visual da UI renderizada

Screenshots sintéticos do CI inspecionados: estado vazio claro, prévia clara,
prévia escura e viewport móvel. O script verifica 1440×1000, 1240×820 (tamanho inicial previsto para a janela)
e 390×844. Consulte a execução do commit na PR para o resultado mais recente.

Comparação com os fontes de identidade do Atualizador:
1. Paleta: vermelho/bordô próprio do coletor; contrastes de texto e botões testados nos dois temas.
2. Tipografia: família Segoe UI Variable Text/Segoe UI declarada; CI Linux usa fallback,
   portanto a aparência exata da fonte precisa de QA no Windows.
3. Navegação: barra lateral 256px, marca em quadrado da cor principal e ícones Lucide lineares.
4. Controles: Button/Chip/TextField/Select reais do HeroUI 3.2.6, sem simulação raster.
5. Estados: claro/escuro/automático, vazio, erro, carga, prévia, filtros e paginação funcionais.
6. Responsividade: overflow de página corrigido; a tabela conserva rolagem própria.

Desvios intencionais: conteúdo e navegação próprios do coletor, sem mascote nem
instalador, campos/alertas específicos da validação. Não foi criado conceito gráfico
novo, pois a referência solicitada é o sistema de design existente do Atualizador.
O texto acima da dobra identifica protótipo local e envio desativado; nenhuma
mensagem afirma conexão ou sincronização fictícia.

## Agenda editável

Padrões comparados com as dez combinações de dia/turno da fonte v75: 54 coletas e
10 rechecagens. Os quatro pares de fim de semana iniciam desmarcados. Testes unitários
conferem todos os horários, fuso confirmado, schema, validação, persistência mínima,
limites e recuperação visível de armazenamento inválido. O smoke de UI cobre edição,
erro, salvamento/reabertura, navegação sem perder rascunho, descarte e restauração,
além de capturas claras/escuras e mobile. Resultado remoto vinculado ao commit da PR.

## Mudança de paleta solicitada

Após a agenda passar o CI completo f41c81ff19caa811a8068d894256dfcc7ddd6b7b
(run 38009482329), a marca mudou para vermelho/bordô a pedido do usuário. Testes
medem contraste de texto/controles (mínimo 4,5:1) e foco (3:1), preservando verde
semântico para presença explícita. Erros também têm texto, role alert e borda;
nunca dependem apenas da cor da marca. QA visual deve conferir o novo SHA da PR.
