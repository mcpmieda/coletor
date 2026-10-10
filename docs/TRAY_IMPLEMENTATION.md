# Raposa vermelha: contrato de bandeja e adaptador opcional

## O que está pronto, e o que ainda não está

Este marco contém a lógica de animação e um adaptador Windows **opt-in**. O
`desktop.py` não importa nem inicia o adaptador. Abrir a prévia atual continua
criando apenas a janela. Não há agente em segundo plano, tarefa de inicialização,
instalação, subprocesso, coleta Smecel, credencial, banco ou comunicação externa.

Os testes executados em Linux verificam a lógica e chamadas nativas simuladas.
**Isso não valida a bandeja no Windows.** Integração real com pywebview, experiência
visual, Explorer, DPI e acessibilidade permanecem pendentes de QA em Windows.
O menu preparado é nativo; o menu owner-draw do Atualizador foi somente estudado,
não copiado. Nenhuma arte de dragão, chama ou identificador do Atualizador é usada.

## Arquivos e responsabilidades

- `app/coletor/tray_animation.py`: estados, política de movimento, sequência de
  quadros, manifesto local e apresentação desacoplada do sistema operacional.
- `app/coletor/tray.py`: adaptador Windows opcional, com imports pywin32 tardios.
- `tests/test_tray.py`: testes portáveis de cadência, fallback e ciclo de vida.
- `app/assets/fox-icons/`: destino dos ICOs locais produzidos separadamente.

Importar os módulos ou construir o controlador não cria thread nem janela.
O adaptador exige `enabled=True` **e** uma chamada explícita a `start()`.
A dependência opcional `pywin32` deve existir num futuro ambiente Windows de
validação; este marco não instala nem altera dependências de desktop.

## Estados e efeitos

| Estado | Efeito | Selo obrigatório no ícone-base | Texto |
|---|---|---|---|
| `idle` | Olhos piscam, orelha e cauda se movem em gestos espaçados | Sem selo | Aguardando |
| `working` | Quatro quadros; selo de progresso mantém significado em todos | Progresso | Em andamento |
| `paused` | Estático | Símbolo de pausa | Pausado |
| `error` | Estático, sem alerta piscante | Exclamação | Requer atenção |

Todo tooltip começa com `Coletor de Frequência · Modo de teste · Coleta desligada`.
Nenhum estado significa conectado, coletado ou sincronizado. O controlador não
consulta o serviço nem infere sucesso. Uma futura integração deve separar a
prévia demonstrativa do estado operacional real antes de alterar esse contrato.
Detalhes de tooltip devem ser genéricos: nunca nomes de alunos, dados escolares,
credenciais, URLs de sessão ou mensagens brutas de exceção.

### Ritmo e acessibilidade

- Trocas animadas respeitam um intervalo mínimo de 600 ms. É possível aumentar
  o intervalo até 60 s; valores menores, infinitos ou inválidos são rejeitados.
- O ciclo idle dura 21,6 s na cadência padrão, com um piscar, uma orelha e uma
  curta sequência de cauda, intercalados por repouso.
- Erro e pausa não piscam. O selo e o texto continuam visíveis com movimento
  reduzido ou animações desligadas.
- `AnimationPolicy(enabled=False)` ou `AnimationPolicy(reduced_motion=True)`
  escolhem o quadro estático do estado. Reativar movimento começa suavemente.
- Eventos atrasados pulam quadros antigos, sem reproduzir uma rajada. Atualizar
  o tooltip ou repetir o mesmo estado não reinicia o ciclo.
- Mudanças semânticas de estado/preferência têm atualização imediata; o limite
  de 600 ms refere-se às animações, não a ocultar um erro recém-informado.
- Preferência de movimento reduzido é um parâmetro explícito. Não está ligada
  automaticamente às preferências do Windows ou ao `prefers-reduced-motion`
  do frontend; essa ligação pertence à futura integração desktop.
- Texto é limpo e limitado a 127 unidades UTF-16, preservando pares substitutos.

## Contrato dos arquivos de arte

Todos os arquivos ficam em `app/assets/fox-icons/`:

**Quatro bases obrigatórias**

- `fox-idle.ico`
- `fox-working-1.ico`
- `fox-paused.ico`
- `fox-error.ico`

**Sete quadros opcionais**

- `fox-blink.ico`
- `fox-ear.ico`
- `fox-tail-left.ico`
- `fox-tail-right.ico`
- `fox-working-2.ico`
- `fox-working-3.ico`
- `fox-working-4.ico`

Quadros idle ausentes usam `fox-idle.ico`; quadros working ausentes usam
`fox-working-1.ico`, preservando o selo. Ausência de uma base falha claramente
antes de criar a thread. Um arquivo presente, mas ilegível, falha no carregamento;
não é disfarçado como sucesso. Os selos devem estar desenhados no ICO; o adaptador
não gera overlays nem modifica a arte em runtime.

Cada ICO deve fornecer versões desenhadas/verificadas para 16, 20, 24, 32 e 48 px
(64/256 px são opcionais). Priorizar rosto/olhos legíveis em 16 px, contorno com
contraste em claro e escuro e símbolos de pausa/erro além da cor. Os nomes de
quadros são um contrato; não comprovam, sozinhos, a qualidade visual da arte.

## Assets presentes neste marco

Foram entregues nove ICOs: idle, blink, expressão atenta, quatro fases de trabalho,
pausa e erro. As posições de cauda do controlador usam fallback idle; não são
ICOs animados de cauda neste pacote. A expressão atenta se chama fox-ear no contrato.
A cauda em movimento existe no atlas do painel.

## Contrato de integração futura

A integração fornecerá três callbacks: `on_open`, `on_quit` e `dispatch`.
`dispatch(callback)` precisa enfileirar o callback na thread adequada da UI e
retornar imediatamente. Não deve bloquear esperando essa thread nem executar
coleta ou operações longas no loop da bandeja.

- Clique duplo e ativação por teclado encaminham `on_open`; o adaptador não
  lança outro processo e não tenta criar uma segunda janela.
- Menu nativo: estado, `Abrir programa` e `Sair`.
- Sair encaminha `on_quit` e solicita encerramento da bandeja. `on_quit` é
  responsável por fechar a janela e os recursos próprios da aplicação.
- `stop()` deve ser usado também no `finally` do ciclo de vida da aplicação.
  Ele aguarda a thread, é idempotente e evita `join()` sobre a própria thread.
- A instância é de uso único. Criar outra após parada confirmada. Isso não é
  garantia de instância única entre processos; mutex de aplicativo não foi
  implementado neste marco.

O controlador pode receber `set_state`/`set_policy` de outras threads. O adaptador
posta uma mensagem; ícones, menus e janela continuam pertencendo a uma única
thread nativa não daemon. Não há PID-filho nem thread separada de animação.
A classe da janela inclui o PID atual e um identificador único para evitar
colisão de classes; nada é escrito em disco ou no Registro por esse mecanismo.

O timer continua verificando disponibilidade do Explorer a cada 600 ms com
movimento desligado, mas só há `NIM_MODIFY` quando a apresentação muda.
`running` informa a existência da thread, não garante que o usuário esteja vendo
o ícone. Falha inicial do Explorer deixa o loop disponível para nova tentativa;
`last_error` expõe apenas um código genérico de diagnóstico.

## Recursos nativos e recuperação

- Janela invisível **top-level** recebe o broadcast `TaskbarCreated`.
- `NIM_ADD`, `NIM_MODIFY`, `NIM_DELETE` e protocolo versão 4 são preparados.
  O protocolo é reaplicado a cada adição, inclusive recuperação do Explorer.
- `TaskbarCreated` readiciona o estado atual e recarrega o tamanho de ícone.
  Arquivos são carregados com `SM_CXSMICON`; DPI por thread é solicitado quando
  o Windows oferece essa função.
- Falha de atualização invalida o registro e tenta adicionar novamente no
  próximo tick; falha de carregamento preserva os handles anteriores.
- Handles compartilhados por fallback são carregados uma vez e destruídos
  uma vez. Em falha parcial, os handles recém-criados são liberados.
- Encerrar mata o timer, remove a notificação antes de destruir a janela,
  libera os `HICON` e desregistra a classe. Erro numa limpeza não pula as demais.
- Menus são destruídos em `finally`; ponteiros de `SetTimer`/`KillTimer` têm
  tipos explícitos para 64 bits. Nenhum objeto GDI customizado é criado.
- Timeouts de início/parada são reportados. Se a thread não encerrar no prazo,
  isso é uma falha, nunca uma parada bem-sucedida ou permissão para duplicá-la.

## Validação

Teste específico, sem Windows nem pywin32:

```sh
PYTHONPATH=app python -m unittest discover -s tests -p test_tray.py -v
```

A cobertura inclui quatro estados, quatro quadros de trabalho, gestos idle,
limite de 600 ms, atraso/regressão de relógio, movimentos reduzidos, UTF-16,
fallbacks, não repetição de redraw, recuperação do Explorer simulada, falhas de
início e limpeza, callbacks enfileirados e ausência de ativação por padrão.
Os testes que simulam Win32 usam objetos Python, não uma bandeja de verdade.

Checklist necessário antes de habilitar na aplicação:

- Windows 10/11 e Python 3.12+, versão pywin32 fixada após validação.
- WebView2/pywebview: abrir/restaurar a mesma janela, fechar, abrir novamente e
  sair pelo menu sem janelas ou processos órfãos.
- ICO real em 16/20/24/32/48 px, claro/escuro e escalas 100/125/150/200%.
- Reinício real do Explorer, inicialização antes do Explorer e mudança de DPI.
- Teclado, Escape, clique fora do menu e leitor de tela.
- Desligar animações e propagar movimento reduzido da UI/sistema.
- Encerrar durante um menu aberto ou uma atualização; monitorar handles e threads.
- Confirmar que o ícone pode ficar inicialmente no overflow da área de
  notificação; a escolha de fixá-lo visível continua sendo do usuário.

## Referências consultadas

Os arquivos `pet/tray.py`, `pet/traymenu.py` e
`pet/references/integracao-windows.md` da referência fornecida foram lidos, não
executados. O padrão de bandeja foi reimplementado com identidade e contrato
próprios; não foram copiados segredos, perfis ou ações operacionais.

Referências primárias das APIs:

- [Microsoft: área de notificação](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area)
- [Microsoft: Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw)
- [Microsoft: TaskbarCreated](https://learn.microsoft.com/en-us/windows/win32/shell/taskbar#taskbar-creation-notification)
- [Microsoft: SetTimer](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-settimer)
- [pywin32: PyNOTIFYICONDATA](https://mhammond.github.io/pywin32/PyNOTIFYICONDATA.html)
