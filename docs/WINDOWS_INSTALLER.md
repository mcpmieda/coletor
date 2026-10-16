# Coletor Windows 0.4 — instalador interno candidato

A PR #7 passa a produzir dois formatos após os mesmos gates de segurança:

- `windows-portable-test`: pasta portátil em ZIP, para diagnóstico/reversão;
- `windows-installer-candidate`: `ColetorFrequencia-0.4.0-windows-x64-setup-candidato.exe` e seu arquivo SHA-256.

O instalador utiliza Inno Setup **6.7.3** obtido do lançamento oficial, e
o CI exige a assinatura Authenticode válida do fornecedor **Pyrsys B.V.**
antes de executar o compilador. Verifique a licença correspondente para uso
comercial. O instalador é assinado por `installer/sign-installer.ps1` quando
os secrets `WINDOWS_SIGNING_PFX_BASE64` e `WINDOWS_SIGNING_PFX_PASSWORD`
existem (sem eles, sai sem assinatura e o CI avisa). Um certificado
autoassinado (`installer/new-signing-certificate.ps1`) identifica a escola e
prova integridade, mas não remove o SmartScreen; isso exige certificado de
autoridade reconhecida. O programa roda no `pythonw.exe` oficial, assinado
pela Python Software Foundation.

## Conteúdo e instalação

O instalador empacota exatamente o runtime Python oficial, a UI compilada,
ícones da raposa, módulos Python, instruções e manifestos já verificados
no pacote portátil. Não inclui sessões Smecel, tokens, diários ou contas.

Instala apenas no perfil atual em
`%LOCALAPPDATA%\Programs\ColetorFrequenciaSmecel`, sem UAC,
serviço Windows ou tarefa agendada. A opção **Abrir o Coletor ao entrar no
Windows** vem marcada e cria só um atalho em `{userstartup}` que abre o
programa ao lado do relógio (`--background`); desmarcada, o atalho é
removido. Reabrir com a coleta ativa retoma a coleta sozinho.
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

Um pacote só recebe o artefato `windows-installer-candidate` se
**essas duas fases** forem aprovadas. CI sintético nunca prova pareamento
real de Entra, chave permanente do PC ou login no Smecel.
Não fazer publicação produtiva antes da homologação em computador da escola,
configuração aprovada da PR #1293 e assinatura corporativa quando exigida.
