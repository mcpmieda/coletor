# coletor-frequencia-smecel

Coletor de frequência escolar para integração com o Ecossistema Escolar.

A versão 0.4 é candidata operacional para revisão junto do backend Ecossistema.
Implementa entrada Microsoft e vínculo revogável do PC, coleta manual/agendada,
computador ativo e reservas, agenda escolar compartilhada, fila e sessão Smecel
protegidas pelo Windows mediante consentimento nativo. Não cria autostart.

O operador entra no Smecel diretamente no Edge, carrega as turmas e marca nomes.
Cada captura revalida contexto/ano/turma e usa o worker isolado. O envio assinado
contém apenas observações X/J e referências locais de ficha; a identificação é
resolvida centralmente no Ecossistema, sem studentUid escolhido pelo PC.
Pontos, vazios e cobertura incompleta não viram presença ou percentual.

A prévia de HTML e os exemplos sintéticos continuam sem envio. A janela Windows
usa agenda do servidor com CAS, independentemente de rascunhos localStorage.
Coletar agora processa todas as turmas selecionadas, com uma lease por escola/ano,
heartbeat, cancelamento, retries limitados e confirmação por recibo servidor.

O pacote exige CI completo e provas nativas no SHA final. Implementação candidata
e validação real são estados separados: nenhum login, dado de aluno, chave real,
merge, deploy ou DDL produtivo é executado pelos testes. Consulte o
[estado operacional V2](docs/FREQUENCY_V2_CANDIDATE.md) e o
[roteiro de ativação](docs/TESTE_E_ATIVACAO.md).

## Raposa do coletor

Mascote escolhido pelo usuário, com quadros próprios e ações discretas: piscar,
orelhas, cauda, curiosidade, pulinho, passeio, descanso e carinho. Reage apenas ao
processamento local e aos avisos reais. Pode ser ocultado ou ficar estático; respeita
movimento reduzido e pausa com a aba oculta. A bandeja Windows mostra estados reais locais e controla mostrar/ocultar a mesma
janela e sair. Fechar pelo X também encerra o programa. Não cria autostart ou agente.

## Agenda pré-configurada e editável

No Windows, Horários de coleta carrega e salva a revisão compartilhada da escola no servidor. Alteração concorrente pede recarregar e comparar, sem sobrescrever. Fuso IANA America/Bahia, horários por dia/turno e fins de semana opcionais são editáveis. Sugestões não confirmam dias letivos nem aula ministrada. A prévia de desenvolvimento mantém seu rascunho local, que não ativa o runtime.

## Executar a prévia no desenvolvimento

### Instalador Windows 0.4 (candidato interno)

O CI também produz um instalador **.exe** para Windows 10/11 x64, por usuário,
sem exigir administrador ou criar inicialização automática. Cria atalho no
menu Iniciar (e opcionalmente na área de trabalho); conserva a raposa, a
bandeja, a interface e as operações do portátil. A janela abre centralizada
no monitor principal. O pacote `windows-installer-candidate` só é publicado
depois de testes Windows nativos e instalação/desinstalação reais em pasta
descartável. Ele ainda depende da homologação Microsoft/TPM/Smecel e do
backend da PR #1293 antes de uso produtivo. O executável do Coletor ainda
não tem assinatura digital própria; não contorne avisos de segurança.

Leia o [guia do instalador](docs/WINDOWS_INSTALLER.md) e as instruções
`installer/LEIA-ME-INSTALADOR.txt`. A remoção do vínculo do computador
é uma operação consentida **anterior** à desinstalação do aplicativo.

### Pacote portátil de teste

O CI privado agora prepara um ZIP para Windows x64 com Python oficial embutido,
dependências e interface compilada. O ZIP só é gerado se o teste da janela nativa
passar, junto dos gates de sessão manual e Edge externo. Extraia a pasta inteira e use `Abrir Coletor.cmd`; não é um instalador.
Microsoft Edge, WebView2 e .NET 4.8 continuam sendo requisitos e não é instalado automaticamente. Validação
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
está fixada para desenvolvimento; o CI já monta e testa o pacote portátil
com runtime embutido. Isso não autoriza instalação produtiva nem substitui QA no PC da escola.

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

- [Sessão manual isolada, limites e validação pendente](docs/MANUAL_SESSION_MILESTONE.md)
- [Agenda escolar editável, apenas local](docs/SCHEDULE_CONFIG.md)
- [Raposa e bandeja da prévia](docs/MASCOT_TRAY_PLAN.md)
- [Regras e fontes Smecel observadas](docs/SMECEL_SOURCE_RULES.md)
- [Arquitetura, fonte e próximos contratos](docs/ARCHITECTURE.md)
- [Segurança e privacidade](docs/SECURITY.md)
- [Estudo econômico PostgreSQL, ainda não implementado](docs/POSTGRESQL_PLAN.md)
- [DDL apenas ilustrativo, não executar](docs/POSTGRESQL_DDL_PROPOSAL.sql.txt)
- [Plano de PR e próximos marcos](docs/PR_PLAN.md)
- [Fixture sintética e cobertura](fixtures/README.md)
- [Verificação desta versão](docs/VERIFICATION.md)

Trabalho em PR aberta. Sem merge, deploy, publicação produtiva ou escrita em produção. O instalador candidato é artefato privado do CI, condicionado aos testes.


## Revalidação da auditoria #3

Consulte a [matriz, regressões, medições e pendências administrativas](docs/AUDIT_3_REMEDIATION.md).
O leitor suporta cabeçalho com **capacidade de seis posições por dia**. Isso
não significa seis aulas realizadas: dias podem usar menos posições ou não ter
marcações. Vazios ficam sem marcação; pontos ficam sem confirmação. Cabeçalhos
de capacidade 4/5/7 continuam rejeitados para conferência, sem cortar posições. Um contrato compartilhado limita HTML a 24 MiB,
pedido JSON a 48 MiB + 64 KiB, até 64 fichas e 130 mil registros. Esses são tetos
defensivos com regressão sintética, não garantia para qualquer captura real.
“Descartar resultado” mantém a leitura ativa e impede nova leitura até terminar.
Transmissão permanece bloqueada mesmo com metadados/recibo declarativos.
