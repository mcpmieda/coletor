# Instalador do Coletor

Os instaladores ficam nas **[Releases do GitHub](https://github.com/mcpmieda/coletor/releases/latest)**, não no repositório (decisão de 15/11/2026: o Git LFS guardava cada versão para sempre e ocupava a cota da conta).

- **Baixar:** abra `baixar-instalador.cmd` nesta pasta. Ele baixa a versão mais nova, confere o SHA-256 e abre o instalador. Pelo navegador, use o link acima e baixe `COLETOR-v<versão>.exe`.
- **Atualização automática:** um Coletor instalado confere as Releases ao abrir e a cada 6 horas. Quando há versão nova, ele baixa, confere tamanho, SHA-256 e cabeçalho do arquivo e instala em silêncio só quando nenhuma coleta ou relatório está em andamento ou próximo na agenda e o notebook não está com bateria abaixo de 40%. O instalador fecha o Coletor (terminando a coleta em andamento) e o reabre ao lado do relógio.
- **Computador desligado no meio:** antes de instalar, o Coletor pede ao Windows para rodar o mesmo instalador no próximo login (RunOnce). A instalação concluída apaga esse pedido; uma interrompida é refeita no próximo login e reabre o Coletor. As configurações, a fila cifrada e a chave do computador ficam em `%LOCALAPPDATA%\ColetorFrequenciaSmecel` e o instalador não mexe nelas.
- **Primeira vez:** versões até 0.4.329 não se atualizam sozinhas. Instale à mão uma vez a primeira versão com atualização automática; as seguintes chegam sozinhas.
- **Publicação:** só o instalador aprovado no job Windows do workflow Preview checks na `main` vira Release (`v<versão>`, com o `.exe`, o `.sha256` e o `atualizacao.json`). São mantidas as cinco Releases mais recentes. O publicador nunca executa o `.exe`.
- **Compatibilidade:** Windows 10 ou superior, x64, instalado por usuário, sem administrador; pré-requisitos em `docs/WINDOWS_INSTALLER.md` (WebView2, Edge e .NET Framework 4.8).
- **Assinatura:** o instalador não tem assinatura digital paga; o SmartScreen pode avisar quando ele é baixado pelo navegador.

Instaladores antigos continuam no histórico do Git LFS e não podem ser apagados um a um; só deixam de crescer.
