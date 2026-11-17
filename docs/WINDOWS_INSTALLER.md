# Coletor Windows 0.4 — instalador interno candidato

A PR #7 passa a produzir dois formatos após os mesmos gates de segurança:

- `windows-portable-test`: pasta portátil em ZIP, para diagnóstico/reversão;
- `windows-installer-candidate`: `ColetorFrequencia-0.4.0-windows-x64-setup-candidato.exe` e seu arquivo SHA-256.

O instalador utiliza Inno Setup **6.7.3** obtido do lançamento oficial, e
o CI exige a assinatura Authenticode válida do fornecedor **Pyrsys B.V.**
antes de executar o compilador. Verifique a licença correspondente para uso
comercial. O launcher **ColetorFrequencia.exe**, o instalador e o
`Instalar Coletor.exe` são assinados por `installer/sign-installer.ps1` em todo
build do CI: na `main`, com o certificado da escola (segredo
`WINDOWS_SIGNING_BUNDLE_BASE64` do ambiente `assinatura`, que só a `main` pode
usar); em qualquer outro build, com um certificado descartável criado na hora,
para que a assinatura e suas verificações rodem sempre. O launcher é assinado
antes do MANIFEST, dos hashes e do ZIP. Num build local sem certificado a
política é explicitamente **unsigned**; o manifesto registra `NotSigned`. Não se
modifica a confiança do Windows. Certificados sem cadeia confiável são
identificados como `signed-untrusted`; isso não garante aprovação pelo
SmartScreen ou por políticas corporativas.

O processo pai tem nome e ícone do Coletor; o filho **pythonw.exe** conserva
nome, ícone e assinatura PSF próprios. A assinatura do filho **não assina o
launcher**. O MANIFEST distingue produto, versão do arquivo, commit, assinatura
e SHA-256 de cada um. `app/coletor/__init__.py` fornece a versão do produto;
o build gera atributos do assembly e `dist/windows-portable/version.iss` para
o Inno, preservando os nomes publicados pelo workflow.

Antes de executar o compilador C#, o build consulta o diretório do Windows
pela API do sistema, rejeita `WINDIR` divergente e exige componentes Microsoft
com Authenticode válido em `Microsoft.NET/Framework64/v4.0.30319`. Registra
caminho relativo ao Windows, hash, editor e versão de `csc.exe`, `mscorlib.dll`,
`System.dll` e `System.Windows.Forms.dll`. As referências são explícitas;
compilador ausente, assinatura inválida ou erro C# interrompem o build sem
publicar um launcher parcial. Essa evidência de proveniência não significa que
os bytes C# sejam reproduzíveis entre versões diferentes do Windows/.NET.

## Conteúdo e instalação

O instalador empacota exatamente o runtime Python oficial, a UI compilada,
ícones da raposa, módulos Python, instruções e manifestos já verificados
no pacote portátil. Não inclui sessões Smecel, tokens, diários ou contas.

Instala apenas no perfil atual em
`%LOCALAPPDATA%\Programs\ColetorFrequenciaSmecel`, sem UAC,
serviço Windows. A opção **Abrir o Coletor ao entrar no Windows** vem
marcada e cria uma tarefa de logon do próprio usuário,
`\EcossistemaEscolar\ColetorFrequencia` (30 s após entrar, sem privilégios),
que abre o programa ao lado do relógio (`--background`), como o Atualizador.
O atalho antigo da pasta Inicializar ficava atrás de todos os itens de
inicialização e às vezes não abria; ele é removido. Desmarcada, a tarefa é
excluída, e desinstalar também a exclui. Reabrir com a coleta ativa retoma a coleta sozinho.
Cria entrada no menu Iniciar e pode criar atalho na área de trabalho.
A janela abre centralizada na área útil do monitor principal e utiliza
o mesmo ícone de raposa da bandeja.

A pasta `programa` acompanha o lançador. Não é necessário instalar
Python ou permitir execução remota de scripts.
O Windows precisa de WebView2, Edge e .NET Framework 4.8.
Não se tenta instalar essas dependências ou desabilitar bloqueios de segurança.

## Desinstalação consciente

A desinstalação via Aplicativos do Windows remove os arquivos do programa
e os atalhos. **Não revoga dispositivos nem elimina segredos, sessões DPAPI,
chaves CNG/TPM, filas ou configurações pessoais.** Isso impede que uma
desinstalação silenciosa destrua uma fila pendente sem conferência.

Antes de desinstalar, o operador deve usar o atalho
**Retirar acesso deste PC**, concluir a revogação no Ecossistema e verificar
o destino dos lotes não confirmados.
Esse fluxo continua explicitamente consentido e separado da desinstalação.

## Provas obrigatórias no GitHub Actions

O job Windows só monta o instalador após aprovação de:
janela WebView2 real, agenda e bandeja, Edge isolado, sessão manual,
CNG anônimo e proof backend, DPAPI, fila/recibos/fencing e ZIP.
Depois, instala o executável em pasta descartável usando modo atual
do usuário, verifica o commit do manifesto e todos os arquivos por SHA-256,
executa `python -m coletor --help`, desinstala e prova que um arquivo
sentinela externo não sofreu alterações.

O gate `check_windows_launcher.py` executa o EXE, o CMD e atalhos `.lnk` reais
do menu Iniciar e Inicializar em uma cópia descartável. Um módulo sintético,
somente nessa cópia, confere argumentos (inclusive aspas/espaços), diretório,
ausência de console no launcher/Python, códigos de saída, runtime ausente/inválido/acesso negado
e popup apenas interativo. Outra fase abre a janela e a bandeja reais, com
acesso institucional falso e preferências temporárias, nos mesmos quatro
caminhos. Um job Windows contém e verifica o fim dos processos próprios.
O pai e o Python devem encerrar; descendentes restantes do WebView2 são
contidos/limpos pelo job, com eventual encerramento forçado registrado na evidência.
O arquivo CMD usa o interpretador de comandos do Windows; quem desejar evitar
essa janela transitória deve abrir o EXE ou os atalhos nativos.
O instalador também verifica assinatura/versão do launcher instalado e o
contrato real do atalho Startup. Isso não certifica execução sob uma política
corporativa específica; se ela exigir assinatura confiável, deve-se usar o
certificado apropriado sem contornar o bloqueio.

Falhas do launcher registram somente horário UTC, categoria fixa e código em
`%LOCALAPPDATA%\EcossistemaEscolar\ColetorFrequencia\launcher.log` (limitado
a 64 KiB). Não incluem argumentos, caminhos privados, saída Python ou tokens.
Na abertura interativa aparece uma orientação de reinstalação/suporte; em
`--background` o erro mantém seu código de saída e é registrado sem popup.

Um pacote só recebe o artefato `windows-installer-candidate` se
**essas duas fases** forem aprovadas. CI sintético nunca prova pareamento
real de Entra, chave permanente do PC ou login no Smecel.
Cada build aprovado na `main` que muda o programa vira Release e é instalado sozinho nos
computadores da escola (seção seguinte): um merge na `main` é uma publicação produtiva.

## Publicação e atualização automática

Desde 15/11/2026 o instalador aprovado na `main` é publicado como GitHub Release (`v<versão>`,
com `COLETOR-v<versão>.exe`, `.sha256`, `atualizacao.json` e `Instalar-Coletor.exe`), não mais na
pasta `instalador/`. O Coletor instalado (`app/coletor/updater.py`) consulta só `github.com` e os hosts
de arquivos de Release, baixa e confere a versão nova e roda o instalador com `/VERYSILENT` quando
nenhuma coleta ou relatório está em andamento ou próximo na agenda. Antes disso registra uma entrada
`RunOnce` do usuário que refaz a instalação no próximo login se o computador desligar no meio; o
instalador apaga a entrada ao terminar; enquanto ela existe, a abertura com o Windows não inicia o
programa. Uma instalação que falha reabre o Coletor; cada versão é tentada no máximo 3 vezes, uma
por dia (`atualizacao/tentativas.json`; o último resultado fica em `estado.json` e o log do
instalador em `instalacao.log`). `SetupMutex` impede dois instaladores ao mesmo tempo. Só
mudanças em `app/`, `ui/`, `installer/`, `scripts/bootstrap/` e nos arquivos do build geram Release.
Na primeira abertura depois de atualizado, o Coletor apaga da pasta `programa\` o que a versão
anterior deixou e a nova não traz (`app/coletor/leftovers.py`, pelo inventário `MANIFEST.json`).
Pontos de uso:

- **Instalar num computador novo:** baixe o `Instalar Coletor.exe` de
  https://github.com/mcpmieda/coletor/releases/latest/download/Instalar-Coletor.exe (~20 KB, código em
  `scripts/bootstrap/`; o CI compila, assina e publica junto com cada Release, nunca um arquivo compilado
  à mão). Ele busca a última Release, só aceita uma criada, com instalador e `atualizacao.json` enviados,
  por `github-actions[bot]`, confere tamanho, SHA-256, cabeçalho PE e a assinatura da escola e abre o
  instalador normal. Precisa de internet. Pelo navegador, o instalador também está em
  https://github.com/mcpmieda/coletor/releases/latest.
- **Quem pode publicar:** o Coletor e o `Instalar Coletor.exe` só instalam um instalador com a assinatura
  da escola (o SHA-256 do certificado está em `SIGNERS`, em `app/coletor/updater.py`, e em `Signers`, em
  `scripts/bootstrap/InstalarColetor.cs`). A chave existe só como segredo do ambiente `assinatura` do
  GitHub, que aceita apenas a `main`: um workflow de outro ramo consegue criar uma Release como
  `github-actions[bot]`, mas não consegue assinar. Release feita ou alterada por pessoa ou outro app
  também é ignorada.
- **Trocar o certificado:** rode `installer/new-signing-certificate.ps1` e publique, ainda assinada pelo
  certificado antigo, uma versão que aceite os dois; só depois troque o segredo. Se a chave antiga se
  perder, os computadores precisam ser reinstalados à mão uma vez.
- **Computador formatado ou trocado:** o mesmo caminho do computador novo. Nada precisa ser guardado: o
  `Instalar Coletor.exe` e o instalador ficam sempre publicados na Release mais nova, no endereço acima.
  Depois de instalar, entre no Ecossistema e no Smecel de novo (o vínculo e o acesso salvo ficavam no
  Windows que foi apagado).
- **Verificar atualizações na hora:** Ajustes > Verificar atualizações consulta a Release mais nova. Havendo
  versão nova, ela é baixada, conferida e instalada pelo mesmo caminho da atualização automática, só que
  sem esperar a agenda ficar livre: espera apenas a coleta em andamento terminar.
- **Atualização:** confere ao abrir (2 min) e a cada 6 h; instala só fora de coleta, relatório e da janela
  da agenda, com espaço em disco e sem bateria abaixo de 40%. Configurações, fila cifrada e chave ficam em
  `%LOCALAPPDATA%\ColetorFrequenciaSmecel`; o instalador não mexe nelas.
- **Versão com defeito:** publique a correção ou a reversão na `main`; instalar à mão uma versão antiga
  não adianta, porque o Coletor volta para a mais nova.
- **Primeira vez:** versões até 0.4.329 não se atualizam sozinhas; instale uma vez com o `Instalar Coletor.exe`.
- **Aviso do Windows:** o certificado é da própria escola (autoassinado), não de uma autoridade paga; o
  SmartScreen pode avisar ao abrir o `Instalar Coletor.exe` baixado pelo navegador.
