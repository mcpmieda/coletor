# coletor-frequencia-smecel

Coletor de frequência escolar para integração com o Ecossistema Escolar.

## Primeiro marco: prévia local, sem envio

Protótipo Windows com Python/pywebview e painel React + HeroUI v3, seguindo o
padrão de interface do Atualizador de Planilhas 1.3.0: HeroUI, Segoe UI e temas
claro, escuro e automático. A identidade do coletor usa vermelho/bordô, conforme
a escolha posterior do usuário.

Implementado:
- Abertura de HTML selecionado pelo operador, processado somente em memória.
- Parser de diário anual: fichas, FEV–DEZ, dias válidos e seis posições de aula.
- Prévia por aluno/mês, paginação e alertas de validação.
- Demonstração gerada com três alunos inteiramente sintéticos.
- Falha fechada para HTML desconhecido, login, truncamento e escopo divergente.
- Testes de parser, calendário, ambiguidades, identidade e adaptadores locais.
- Raposa animada no painel, com preferências de exibição e movimento reduzido.

A marca `•` é “aula prevista/presença” e continua **sem confirmação**. Não existe
presença presumida. O HTML anual não contém MAT/`studentUid`, `ct` ou total de
fichas verificável; importação isolada nunca autoriza envio. Nomes não são chaves.

Não implementado: login, coleta no Smecel, credenciais, API de produção, banco,
execução agendada, bandeja ativada/validada no Windows, coordenação dos computadores autorizados, portal ou instalador.
A interface mostra essas etapas como futuras. Não há endpoint de sincronização.
O usuário limitou este marco à base: a visão dos responsáveis e quais dados ela
exige serão definidos antes de qualquer envio ao PostgreSQL ou à API.

## Raposa do coletor

Mascote escolhido pelo usuário, com quadros próprios e ações discretas: piscar,
orelhas, cauda, curiosidade, pulinho, passeio, descanso e carinho. Reage apenas ao
processamento local e aos avisos reais. Pode ser ocultado ou ficar estático; respeita
movimento reduzido e pausa com a aba oculta. Ícones e adaptador Windows de bandeja
estão preparados separadamente, sem iniciar bandeja por padrão.

## Agenda pré-configurada e editável

A página Horários de coleta traz os horários sugeridos da planilha HORARIO 2026.xlsb
versão 75, separados por dia e turno, com fuso America/Bahia editável. Salva apenas
uma prévia neste navegador; nenhuma tarefa é executada. O escopo futuro é a escola:
a mesma configuração para os usuários e computadores autorizados, após login e sincronização ainda não
implementados. A quantidade é variável; o desenho prevê um coletor ativo por vez
e os demais computadores autorizados como reservas. Não guarda credenciais.
Consulte o [contrato da agenda](docs/SCHEDULE_CONFIG.md).

## Executar a prévia no desenvolvimento

### Pacote portátil de teste

O CI privado agora prepara um ZIP para Windows x64 com Python oficial embutido,
dependências e interface compilada. O ZIP só é gerado se o teste da janela nativa
passar. Extraia a pasta inteira e use `Abrir Coletor.cmd`; não é um instalador.
WebView2 continua sendo requisito e não é instalado automaticamente. Validação
nos computadores da escola é separada do CI. Veja [conteúdo e verificações](docs/WINDOWS_PORTABLE.md)
e [instruções simples do pacote](docs/PORTABLE_LEIA_ME.txt).

### Código-fonte

Requer Python 3.12+ e Node 22+. Na raiz:

```sh
python scripts/generate_fixture.py
npm ci --prefix ui
npm run build --prefix ui
PYTHONPATH=app python -m coletor --preview-server
```

Abra `http://127.0.0.1:8765`. O servidor só escuta o loopback. Para UI com hot
reload, use `--preview-server --dev` e, em outro terminal, `npm run dev --prefix ui`.

### Janela Windows a partir do código-fonte

Em PowerShell, depois do build da UI:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-desktop.txt
$env:PYTHONPATH = "app"
.venv\Scripts\python -m coletor
```

Requer WebView2 já disponível. O launcher não instala nada no sistema, não
registra tarefa de inicialização e usa perfil privado. A dependência desktop
está fixada para desenvolvimento; empacotamento e runtime embutido serão uma
etapa separada após validação em Windows.

## Verificações

```sh
python scripts/generate_fixture.py
PYTHONPATH=app python -m unittest discover -s tests -v
npm test --prefix ui
npm run build --prefix ui
python -m pip install -r requirements-test.txt
python -m playwright install chromium
PYTHONPATH=app python scripts/check_ui.py
```

`CHROMIUM_PATH` permite indicar um navegador de teste já instalado. Screenshots
sintéticos ficam em `/tmp/smecel-qa` por padrão (ou `QA_OUTPUT`). Nunca use relatórios
reais para gerar artefatos de CI. A fixture HTML é gerada e não versionada; o
conteúdo e casos são reprodutíveis a partir de `app/coletor/demo.py`.

## Arquitetura e revisão

- [Agenda escolar editável, apenas local](docs/SCHEDULE_CONFIG.md)
- [Direção futura de mascote e bandeja](docs/MASCOT_TRAY_PLAN.md)
- [Regras e fontes Smecel observadas](docs/SMECEL_SOURCE_RULES.md)
- [Arquitetura, fonte e próximos contratos](docs/ARCHITECTURE.md)
- [Segurança e privacidade](docs/SECURITY.md)
- [Estudo econômico PostgreSQL, ainda não implementado](docs/POSTGRESQL_PLAN.md)
- [DDL apenas ilustrativo, não executar](docs/POSTGRESQL_DDL_PROPOSAL.sql.txt)
- [Plano de PR e próximos marcos](docs/PR_PLAN.md)
- [Fixture sintética e cobertura](fixtures/README.md)
- [Verificação desta versão](docs/VERIFICATION.md)

Trabalho em draft PR. Sem merge, deploy, release, instalador ou escrita em produção.
