# Verificação do primeiro marco

## Executado localmente

- Python 3.12: parser, validação, calendário, ambiguidades, identidade e serviços
  locais: 40 testes passando após correções de volume identificadas em revisão parcial.
- UI: cinco testes de labels/adaptador/erros passaram.
- TypeScript estrito e build Vite: passaram.
- Fixtures: geradas, três alunos sintéticos; nenhuma exportação real versionada.
- Código do launcher Windows e contrato pywebview: inspecionados/compilados,
  mas não executados em Windows neste ambiente.

## Verificação visual e de interação

O navegador da nuvem não alcançou o loopback do executor (connection refused).
O Chromium no executor foi impedido de iniciar por restrição de socket do sandbox,
mesmo após tentativa suportada de execução com revisão. Nenhuma restrição foi
alterada. O script `scripts/check_ui.py` está preparado para o CI Linux com fixtures
sintéticas. Primeira execução remota confirmou carga, demo, filtros, paginação, tema escuro, navegação, limpeza e importação. Detectou overflow horizontal em viewport 390px; a correção de min-width/grid está em validação. Screenshots dessa execução foram baixados e inspecionados, sem dados reais.

Não afirmar fidelidade visual completa nem QA Windows até executar esses passos.
A referência visual é o código de UI do Atualizador 1.3.0, e não um novo conceito
raster: foram preservados HeroUI v3, tokens de accent claro/escuro, fonte Segoe UI,
barra lateral de 256px, marca em bloco verde, controles e navegação correspondentes.
A tela funcional foi adaptada ao diário; não contém estados de sincronização falsos.

## Limitações importantes

- Parser nativo usa contrato estrutural sanitizado observado na origem, mas não
  foi executado sobre dados reais no repositório. Piloto autorizado segue pendente.
- HTML isolado não prova `ct`, roster completo ou MAT; envio permanece bloqueado.
- Nenhuma coleta autenticada, credencial, dispositivo, API, banco ou portal conectado.
- Interface importa em memória; não há instalador, tray, agendamento ou failover.
