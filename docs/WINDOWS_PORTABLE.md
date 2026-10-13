# Pacote portátil privado de teste

O usuário pediu o programa na raiz do OneDrive da secretaria. Esta etapa prepara
um ZIP executável de teste para essa entrega; não cria release pública, instalador,
serviço, tarefa de inicialização, credencial persistente ou integração de envio.
A entrada assistida e a leitura manual exigem confirmação do operador;
veja [limites e QA ainda pendente do login real](MANUAL_SESSION_MILESTONE.md).
O upload ao OneDrive é uma etapa separada. Um ZIP só de fontes não é o programa.

## Conteúdo e execução

`ColetorFrequencia-0.2.0-teste-windows-x64.zip` contém `Abrir Coletor.cmd`,
`LEIA-ME.txt`, `MANIFEST.json`, avisos de licença e a pasta `programa` com runtime,
bibliotecas, código necessário à execução e UI compilada. O usuário extrai toda
a pasta e abre o comando. O Python não é instalado globalmente; não há elevação.
O launcher usa `pythonw.exe -B -m coletor.portable` e perfil privado. A ponte
processa o diário em memória e salva somente agenda, tema e preferências da raposa
no arquivo próprio do usuário, separado do navegador e do Atualizador.
Não há instalação automática do WebView2.

Alvo: Windows 10/11 x64 com .NET Framework 4.8, WebView2 e Microsoft Edge. A janela de teste de
CI roda no Windows Server 2022 hospedado pelo GitHub: isso não certifica os PCs
da escola. Python 3.13 foi escolhido pela compatibilidade declarada do pythonnet
3.0.5; o runtime oficial 3.13.16 está fixado por URL e SHA-256. As dependências
Python estão fixadas em `requirements-windows-portable.txt`.

## Verificação e distribuição

O job Windows depende dos testes Linux. Confere o hash do runtime, as assinaturas
PSF dos executáveis e abre a janela real com o Python incluído. O smoke verifica
a UI, a ponte nativa e os dados sintéticos; fecha a janela e limita o tempo/processos.
Também abre quatro processos/janelas sucessivos para testar configurações locais:
salvar, reabrir, restaurar/reabrir e recuperar corrupção controlada. O teste usa
pasta temporária e confirma que o arquivo-sentinela de outro aplicativo continua
intacto. Os relatórios nativos (janela, persistência, bandeja e sessão manual) e o teste de
Edge separado precisam passar para criar o ZIP final. Todos usam fixtures sintéticas. O empacotamento
confere novamente os hashes e inclui apenas o inventário anterior ao teste.
Não empacota diretórios de captura, perfil, dados reais, segredo ou logs.

`MANIFEST.json` informa o commit, versões e SHA-256 de cada arquivo.
O SHA-256 externo cobre o ZIP completo. São evidências de integridade, não uma
assinatura própria do aplicativo. Se Windows/antivírus bloquear, o LEIA-ME orienta
parar e pedir ajuda; não desativar proteções. Nenhum bloqueio é contornado.

O pacote usa a estratégia de runtime oficial embutido do Atualizador, sem copiar
o instalador, as credenciais, os agentes nem scripts de segurança dele.
A bandeja WinForms controla mostrar/ocultar a mesma janela e sair; informa apenas leitura local, espera ou erro. O teste nativo separado é obrigatório antes do ZIP. Não há agente de coleta ou autostart.

## Fontes oficiais

- [Python 3.13.16 e checksum](https://www.python.org/downloads/release/python-31316/)
- [Python embutido no Windows](https://docs.python.org/3.13/using/windows.html#the-embeddable-package)
- [Dependências Windows do pywebview](https://pywebview.flowrl.com/guide/installation.html)
- [Compatibilidade pythonnet 3.0.5](https://pypi.org/project/pythonnet/3.0.5/)
- [Microsoft WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)

