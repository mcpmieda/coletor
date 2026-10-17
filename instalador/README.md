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

Após CI Windows aprovado, o publicador guarda o `.exe` e seu `.sha256` em um GitHub Release permanente, mantendo até cinco releases desse tipo. Para atualizar os binários Git LFS desta pasta, ele abre uma PR da branch `automation/instalador-*`, dispara explicitamente `verify` e `windows-portable` com `workflow_dispatch`; um job separado tenta integrá-la **somente após os dois checks aprovarem**. A proteção de `main` permanece válida. Se a proteção não permitir o merge pelo bot, o release já está disponível e a PR aguarda revisão humana. Merges que alteram apenas `instalador/` não criam outro release.

**Permissão do GitHub Actions:** para abrir a PR sem intervenção humana, um administrador deve ativar **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests** (se a política da organização permitir). Sem essa permissão, o publicador mantém o Release verificável e a branch `automation/instalador-run-<id>` em Git LFS, mas **falha explicitamente** com `ARCHIVE_PR_NOT_CREATED`; não confunda o Release disponível com a atualização de `main/instalador`. A PR pode ser aberta por um mantenedor autorizado e deverá cumprir os dois checks exigidos. Se a PR passar, mas não puder ser integrada, a etapa de merge falha com `ARCHIVE_PR_NOT_MERGED`. Não desative a proteção da `main` para contornar essa limitação.

**Como recuperar a pasta:** o mantenedor pode abrir uma PR com os instaladores cujos ponteiros LFS já foram verificados nos releases e unir as cinco versões mais recentes no manifesto. Não execute um ponteiro LFS de 133 bytes como instalador e não marque a pasta como sincronizada até que a PR esteja integrada.
