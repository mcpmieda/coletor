# Verificação do primeiro marco

## Executado localmente

- Python 3.12: parser, validação, calendário, ambiguidades, identidade e serviços
  locais, contraste da UI, assets e bandeja simulada: 80 testes passaram. As correções de volume vieram de revisão parcial.
- UI: 46 testes de labels, adaptador, erros, agenda e mascote passaram.
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
- Interface importa em memória; não há instalador, tray ativo, execução agendada ou failover. A agenda editável é uma prévia local.

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

Desvios intencionais: conteúdo e navegação próprios do coletor, com a raposa própria e sem
instalador, campos/alertas específicos da validação. A raposa foi escolhida pelo usuário; os componentes e a tipografia seguem o sistema de
design do Atualizador.
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

## Raposa animada e bandeja preparada

O painel possui oito poses reais num atlas único, treze ações/estados de animação
e preferências Mostrar/Animar. Testes cobrem limite de callbacks, pausa/redução de
movimento, cochilo/acordar, leitura/revisão/erro e preferência mínima. O smoke verifica
carinho, recuperação da preferência, nenhum novo fetch por quadro e imagens locais.
As capturas finais incluem prévia/validação, agenda e próximas etapas nos dois temas.

33 testes de bandeja usam controlador e doubles Win32 em Linux: não são validação
nativa no Windows. Módulo opt-in não é iniciado pelo launcher. Ícones locais são
checados como containers ICO multirresolução e também precisam de conferência real
na área de notificação antes de habilitar. Nenhuma tarefa ou instalação foi feita.

## Quantidade variável de usuários e computadores

Os textos e contratos preliminares não fixam quantidade de usuários ou PCs.
Permanece o escopo escolar autorizado, com um coletor ativo por vez e os demais
computadores autorizados como reservas. Teste de renderização e smoke de navegador
cobrem a mensagem compartilhada e o plano de coordenação. Não existe cadastro,
limite artificial de dispositivos ou mudança de permissões implementada neste marco.
