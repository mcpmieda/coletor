# Raposa na bandeja Windows

A janela desktop agora inicia `tray_winforms.py` na mesma thread WinForms do
pywebview. Reutiliza `tray_animation.py` e os ICOs locais. Não exige pywin32,
instalador, serviço, subprocesso, tarefa de inicialização ou acesso externo.
O adaptador antigo `tray.py` continua isolado e não é iniciado pelo launcher.

## Controles reais

- “Ocultar na bandeja” oculta a janela existente. O menu oferece Mostrar janela,
  Ocultar janela e Sair. Clique esquerdo simples/duplo restaura a mesma janela.
- Fechar pelo X encerra o programa; não transforma o fechamento em persistência.
- Sair remove ícone, timer, handlers e recursos nativos antes de fechar a janela.
- Se a criação da bandeja falhar, a janela continua aberta, mostra aviso e não
  oferece ocultar. Não instala dependência nem altera proteção do Windows.
- O ícone pode aparecer no overflow do Windows; fixá-lo é uma escolha do usuário.

## Estado e movimento

`desktop_state.py` recebe apenas idle/reading/error e movimento reduzido, sem
texto livre. Contabiliza operações reais no parser. Uma operação nativa ainda
ativa mantém reading mesmo se a UI cancelar a exibição. O estado volta a espera
após o término e usa erro genérico quando o arquivo não pode ser lido.
A UI informa também leitura do File local e erros de seleção/validação.

Tooltips e menu sempre dizem Coleta desligada. Espera não significa um agente
agendado; leitura significa somente processamento de arquivo local ou exemplo.
Não há login, coleta automática, sincronização, compartilhamento ou envio.

A bandeja fica estática em espera/erro, sem timer. Durante leitura, os quatro
quadros existentes mudam no máximo a cada 600 ms. Animar raposa desmarcado ou
`prefers-reduced-motion: reduce` desliga o timer imediatamente; a preferência
é carregada do JSON próprio antes da criação da bandeja. Mostrar raposa desmarcado
troca o ícone por um ícone neutro do aplicativo e interrompe animação, preservando
os controles da janela. Preferências já salvas continuam válidas.
O painel mantém seu repertório atual e para animação quando oculto.

NotifyIcon administra o registro Shell_NotifyIcon e recuperação TaskbarCreated.
Nenhuma configuração do Explorer ou de outros aplicativos é modificada.
Os eventos .NET próprios são removidos explicitamente no encerramento.

## QA e empacotamento

`scripts/check_windows_tray.py` executa dois processos sucessivos com o Python
embutido e configurações temporárias. Verifica registro real do ícone, menu
WinForms visível, mostrar/ocultar repetidamente, mesma janela, eventos de clique
simples/duplo, leitura local bloqueada controladamente, erro real de validação,
cancelamento, animação limitada, movimento reduzido emulado no WebView2,
preferências salvas e saída por Sair e FormClosing (mesmo caminho do X).

São interações programáticas em controles e eventos nativos, não cliques físicos.
Capturas PrintWindow incluem apenas janela/menu deste teste com dados sintéticos.
O teste é contido por Windows Job Object, verifica zero processos remanescentes
e falha se o worker não sair ou qualquer controle obrigatório não for confirmado.
Não reinicia Explorer nem muda DPI, política, segurança ou inicialização.
Teclado/leitor de tela, múltiplos DPIs e reinício real do Explorer não são
certificados por esse roteiro.

O CI exige os três relatórios: janela básica, persistência local e bandeja.
Só então reconfere o inventário/hash e gera o ZIP privado. Não empacota estado
temporário, perfil, captura ou log. O manifesto marca a bandeja ativa somente
para controle da janela/prévia local, sem agente de coleta.

Referências: [Microsoft NotifyIcon](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon),
[área de notificação](https://learn.microsoft.com/en-us/windows/win32/shell/notification-area).
