# Instaladores Windows — cinco últimas versões

Esta pasta mantém os **cinco instaladores .exe mais recentes aprovados pelos testes Windows** após novas integrações na branch main. O processo começa a funcionar quando o workflow da PR #7 for integrado. Os nomes contêm a versão da aplicação, o número do build e o identificador do commit, mesmo que a versão nominal (por exemplo, 0.4.0) não mude.

- **Baixar:** abra o arquivo .exe nesta pasta pelo GitHub, usando a opção de baixar o arquivo completo. Ele é armazenado no **Git LFS**, não como código de texto. Ao clonar o repositório, instale Git LFS e execute git lfs pull para obter os executáveis. Não tente executar um arquivo de ponteiro LFS.
- **Verificar:** cada .exe possui um arquivo .exe.sha256. O versoes.json registra nome, versão, hash SHA-256, commit original e execução de CI.
- **Retenção:** ao publicar a sexta versão validada, a mais antiga deixa de aparecer nesta pasta, mas seus dados históricos podem continuar contabilizados no Git LFS. A remoção da pasta **não equivale à eliminação do histórico de armazenamento LFS**.
- **Segurança:** somente o job Windows do workflow Preview checks aprovado na main autoriza a publicação. O empacotamento usa o instalador Inno Setup real e o teste de instalação/desinstalação no Windows. O publicador nunca executa o .exe recebido.
- **Compatibilidade:** instalador Windows x64, instalado por usuário, com Windows 10 ou superior e os pré-requisitos especificados em docs/WINDOWS_INSTALLER.md (WebView2, Edge e .NET Framework 4.8). A validação automatizada não substitui a homologação com a conta Microsoft, o Smecel e PCs físicos da escola.
- **Assinatura:** o script de compilação assina o .exe apenas se os segredos de assinatura estiverem configurados. Sem eles, o instalador continuará sendo um executável Windows válido, mas pode exibir avisos do SmartScreen; não declarar a assinatura como concluída nesses casos.

O publicador **não executa push direto na `main`**, nem pula checks. A atualização da pasta ocorre por PR de arquivo versionado em Git LFS e depende da proteção de branch. A aprovação automatizada em CI não dispensa as permissões necessárias para integrá-la.

Documentação complementar: docs/WINDOWS_INSTALLER.md.

## Branch protegida e cinco versões

**Esta pasta é o único lugar onde o instalador é publicado** (não há mais GitHub Releases). Após o CI Windows aprovado na `main`, o publicador grava o `.exe` e o `.sha256` aqui (Git LFS) numa PR da branch `automation/instalador-run-<id>`. No mesmo job, ele aprova a execução de checks dessa PR (a PR foi aberta pelo robô do Actions, por isso os checks ficam aguardando aprovação), espera `verify` e `windows-portable` passarem, confere que a PR só altera `instalador/` e a integra. A proteção da `main` continua valendo. Merges que alteram apenas `instalador/` não geram outro build.

**Permissão do GitHub Actions:** precisa estar ativo **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests**. Se algo impedir a atualização, o publicador **falha explicitamente**: `ARCHIVE_PR_NOT_CREATED` (não abriu a PR; o instalador fica na branch `automation/instalador-run-<id>`), `ARCHIVE_CHECKS_NOT_STARTED` ou `ARCHIVE_PR_NOT_MERGED` (a PR fica aberta). Não desative a proteção da `main` para contornar.

**Como recuperar a pasta:** um mantenedor pode integrar a PR `automation/instalador-run-<id>` pendente depois dos dois checks. Não execute um ponteiro LFS de 133 bytes como instalador.
