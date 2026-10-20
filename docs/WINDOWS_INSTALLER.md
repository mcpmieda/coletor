# Coletor Windows 0.4 — instalador interno candidato

A PR #7 passa a produzir dois formatos após os mesmos gates de segurança:

- `windows-portable-test`: pasta portátil em ZIP, para diagnóstico/reversão;
- `windows-installer-candidate`: `ColetorFrequencia-0.4.0-windows-x64-setup-candidato.exe` e seu arquivo SHA-256.

O instalador utiliza Inno Setup **6.7.3** obtido do lançamento oficial, e
o CI exige a assinatura Authenticode válida do fornecedor **Pyrsys B.V.**
antes de executar o compilador. Verifique a licença correspondente para uso
comercial. O launcher **ColetorFrequencia.exe** e o instalador têm assinatura
própria opcional, aplicada por `installer/sign-installer.ps1` com a configuração
existente `WINDOWS_SIGNING_BUNDLE_BASE64` (ou o par legado
`WINDOWS_SIGNING_PFX_BASE64`/`WINDOWS_SIGNING_PFX_PASSWORD`). O launcher é
assinado antes do MANIFEST, dos hashes e do ZIP. Sem certificado, sua política
é explicitamente **unsigned**; o manifesto registra `NotSigned`, sem editor
signatário. Não se cria certificado nem se modifica a confiança do Windows.
Certificados sem cadeia confiável são identificados como `signed-untrusted`;
isso não garante aprovação pelo SmartScreen ou por políticas corporativas.

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
Não fazer publicação produtiva antes da homologação em computador da escola,
configuração aprovada da PR #1293 e assinatura corporativa quando exigida.
